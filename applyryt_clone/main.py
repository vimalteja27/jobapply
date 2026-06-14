"""
main.py — ApplyRyt (Tsenta-equivalent) orchestrator

FEATURES:
  ✅ 50,000+ company career page watcher (watcher/)
  ✅ Real-time monitoring every 5 minutes (GitHub Actions every 20 min minimum)
  ✅ Production form filling — Greenhouse, Lever, Ashby, Workday + 8 more ATSes
  ✅ Resume tailored per job (AI rewrites bullets to mirror JD language)
  ✅ Approve-before-send review queue (review/server.py at localhost:8080)
  ✅ Reply tracking / inbox routing (inbox/)
  ✅ Google Sheets tracker + email notifications

USAGE:
  python main.py              # Full run — scrape, score, queue/apply
  python main.py --list       # Preview jobs without applying
  python main.py --review     # Start the approve-before-send UI at localhost:8080
  python main.py --inbox      # Check inbox for recruiter replies
"""
import os, sys, time
from collections import Counter, defaultdict
from pathlib import Path

from utils import (log, get_config, deduplicate, filter_jobs,
                   already_applied, mark_applied, is_dry_run,
                   get_today_applied_count, increment_today_count)
from scrapers.discovery import search_jobboards, find_jobs_for_role, _matches as role_matches
from scrapers.glassdoor import scrape_glassdoor
from watcher import watch_and_find_new
from ai import analyze_job
from submitter import submit
from submitter.workday_submit import submit_workday
from submitter.pdf_generator import generate_pdf
from tracker import log_application, send_daily_digest
from h1b_lookup import lookup_h1b_history


def collect_all_jobs(role: str) -> list[dict]:
    cfg      = get_config()
    location = cfg["search"]["location"]
    hours    = cfg["search"]["hours_old"]

    log.info(f"\n{'═'*60}\n  Role: {role}\n{'═'*60}")

    all_jobs = []

    # STEP 1: Job boards (LinkedIn + Indeed — searches ALL US companies)
    log.info("\n[1] Job boards: LinkedIn + Indeed...")
    t0 = time.time()
    board_jobs = search_jobboards(role, location, hours)
    board_jobs = [j for j in board_jobs if role_matches(j.get("title",""), role)]
    log.info(f"  {len(board_jobs)} relevant ({time.time()-t0:.1f}s)")
    all_jobs.extend(board_jobs)

    # STEP 2: Glassdoor
    log.info("\n[2] Glassdoor...")
    t0 = time.time()
    try:
        gd = [j for j in scrape_glassdoor(role) if role_matches(j.get("title",""), role)]
        log.info(f"  {len(gd)} relevant ({time.time()-t0:.1f}s)")
        all_jobs.extend(gd)
    except Exception as e:
        log.warning(f"  Glassdoor: {e}")

    # STEP 3: ATS platforms from cache (Greenhouse, Lever, Ashby, Workday + more)
    log.info("\n[3] ATS platforms (all dynamically discovered companies)...")
    t0 = time.time()
    ats_jobs = find_jobs_for_role(role)
    log.info(f"  {len(ats_jobs)} ATS jobs ({time.time()-t0:.1f}s)")
    all_jobs.extend(ats_jobs)

    # STEP 4: Career page watcher (50,000+ companies, new jobs only)
    log.info("\n[4] Career page watcher (5,000+ product companies)...")
    t0 = time.time()
    try:
        new_jobs = watch_and_find_new([role])
        log.info(f"  {len(new_jobs)} NEW jobs from career pages ({time.time()-t0:.1f}s)")
        all_jobs.extend(new_jobs)
    except Exception as e:
        log.warning(f"  Watcher: {e}")

    log.info(f"\n  Raw total for '{role}': {len(all_jobs)} jobs")
    return all_jobs


def run():
    cfg       = get_config()
    roles     = cfg["search"]["roles"]
    daily_cap = cfg["search"]["daily_cap"]
    auto_approve = cfg.get("auto_approve", True)

    # Pre-flight check
    if not os.environ.get("GROQ_API_KEY"):
        print("\n" + "═"*55)
        print("  ERROR: GROQ_API_KEY not set")
        print("  Fix: export GROQ_API_KEY=gsk_your_key")
        print("  Free key: console.groq.com/keys")
        print("═"*55 + "\n")
        return -1

    log.info("═"*60)
    log.info(f"ApplyRyt  {'[DRY RUN]' if is_dry_run() else '[LIVE]'}")
    log.info(f"Roles: {', '.join(roles)}")
    log.info(f"Cap: {daily_cap}/day | auto_approve: {auto_approve}")
    log.info("═"*60)

    # Collect from all sources
    raw = []
    for role in roles:
        raw.extend(collect_all_jobs(role))

    jobs = deduplicate(raw)
    jobs = filter_jobs(jobs)
    jobs = [j for j in jobs if not already_applied(j)]
    jobs.sort(key=lambda j: j.get("posted_at",""), reverse=True)

    for job in jobs:
        job["h1b_history"] = lookup_h1b_history(job.get("company",""))

    src_counts = Counter(j["source"] for j in jobs)
    log.info(f"\n{'─'*60}")
    log.info(f"Ready: {len(jobs)} unique jobs")
    for src, cnt in src_counts.most_common():
        log.info(f"  {src:25s} {cnt:4d}")
    log.info(f"{'─'*60}")

    applied_count = get_today_applied_count()
    start_count   = applied_count
    results       = []

    for job in jobs:
        if applied_count >= daily_cap:
            log.info(f"\nDaily cap ({daily_cap}) reached.")
            break

        log.info(f"\n→ [{job['source']}] {job['title']} @ {job['company']}")

        # AI: score + tailor resume per JD
        enriched = analyze_job(job)
        if enriched is None:
            results.append({**job, "submitted": False})
            continue

        # Store original bullets for review UI diff
        master = __import__('utils').get_master_resume()
        orig_bullets = []
        for exp in master.get("experience",[])[:2]:
            orig_bullets.extend(exp.get("bullets",[])[:2])
        enriched["original_bullets"] = orig_bullets[:4]

        # Review queue (if auto_approve: false, hold for human review)
        if not auto_approve and not is_dry_run():
            from review import add_to_queue
            add_to_queue(enriched)
            log.info(f"  → Queued for review at localhost:8080")
            results.append({**enriched, "submitted": False, "status": "pending_review"})
            continue

        # Generate tailored PDF
        pdf_path = generate_pdf(enriched)

        # Submit — route to the right ATS submitter
        url = enriched.get("url","")
        if "myworkdayjobs.com" in url:
            submitted = submit_workday(enriched, pdf_path)
        else:
            submitted = submit(enriched, pdf_path)

        log_application(enriched, pdf_path, submitted)

        if submitted:
            mark_applied(enriched)
            applied_count += 1
            increment_today_count()

        results.append({**enriched, "submitted": submitted})
        time.sleep(2)

    # Check inbox for recruiter replies
    log.info("\n[INBOX] Checking for recruiter replies...")
    try:
        from inbox import check_inbox_for_replies
        from tracker import update_application_status
        updates = check_inbox_for_replies(results)
        for u in updates:
            log.info(f"  📬 {u['status']}: {u['application'].get('title','')} @ "
                     f"{u['application'].get('company','')} — \"{u['subject'][:50]}\"")
    except Exception as e:
        log.debug(f"[INBOX] {e}")

    new_this_run = applied_count - start_count
    log.info(f"\n{'═'*60}")
    log.info(f"Done: {new_this_run} {'logged (dry run)' if is_dry_run() else 'submitted'} "
             f"({applied_count}/{daily_cap} today)")
    if not auto_approve and not is_dry_run():
        log.info(f"  Review pending applications: python -m review.server")
    log.info("═"*60)

    send_daily_digest(results)
    return new_this_run


if __name__ == "__main__":
    if "--review" in sys.argv:
        print("Starting review UI at http://localhost:8080")
        import subprocess
        subprocess.run([sys.executable, "-m", "review.server"])

    elif "--inbox" in sys.argv:
        from inbox import check_inbox_for_replies
        updates = check_inbox_for_replies([])
        print(f"\n{len(updates)} recruiter replies found")
        for u in updates:
            print(f"  {u['status']}: {u['subject']} from {u['sender']}")

    elif "--list" in sys.argv:
        cfg  = get_config()
        raw  = []
        for role in cfg["search"]["roles"]:
            raw.extend(collect_all_jobs(role))
        jobs = deduplicate(raw)
        jobs = filter_jobs(jobs)
        jobs = [j for j in jobs if not already_applied(j)]
        src  = Counter(j["source"] for j in jobs)

        print(f"\n{'═'*65}")
        print(f"  JOB PREVIEW — {len(jobs)} jobs across {len(src)} platforms")
        h1b_cnt = Counter(lookup_h1b_history(j.get("company","")) for j in jobs)
        print(f"\n  H1B BREAKDOWN:")
        print(f"    ✅ H1B Sponsor       {h1b_cnt.get('✅ H1B Sponsor',0):4d} jobs")
        print(f"    🎓 Cap-Exempt        {h1b_cnt.get('🎓 H1B Exempt (Cap-Free)',0):4d} jobs")
        print(f"    ❓ No Record         {h1b_cnt.get('❓ No H1B Record',0):4d} jobs")
        print(f"\n{'─'*65}")

        by_src = defaultdict(list)
        for j in jobs: by_src[j["source"]].append(j)
        for source, sjobs in sorted(by_src.items()):
            print(f"\n  [{source.upper()}] — {len(sjobs)} jobs")
            print(f"  {'─'*63}")
            for j in sjobs:
                h1b = lookup_h1b_history(j.get("company",""))
                tag = "✅" if "Sponsor" in h1b else ("🎓" if "Exempt" in h1b else "❓")
                print(f"  {tag} {j['title'][:44]:44s}  {j['company'][:22]:22s}")

        print(f"\n{'═'*65}")
        print(f"  TOTAL: {len(jobs)} jobs")
        print(f"\n  Commands:")
        print(f"    python main.py                # apply to all jobs")
        print(f"    python main.py --review       # approve-before-send UI")
        print(f"    python main.py --inbox        # check recruiter replies")
        print(f"{'═'*65}\n")
        sys.exit(0)

    else:
        sys.exit(0 if run() >= 0 else 1)
