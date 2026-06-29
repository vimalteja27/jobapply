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
from h1b_lookup import lookup_h1b_history, h1b_explanation
from h1b_cap_exempt_targets import get_cap_exempt_tier

# Platforms we can auto-submit to directly
_SUBMITTABLE_SOURCES = {"greenhouse", "lever", "ashby", "workday"}


def _h1b_priority_rank(job: dict) -> tuple:
    """
    Sort key for priority ordering. Lower rank = applied to first.
    Primary: H1B tier. Secondary: submittable source. Tertiary: date.
    This ensures Greenhouse/Lever/Ashby/Workday jobs get processed
    before Indeed jobs that may point to unresolvable custom portals.
    """
    tier   = job.get("h1b_tier", 0)
    h1b    = job.get("h1b_history", "")
    source = job.get("source", "")

    if tier == 1:
        rank = 0
    elif tier in (2, 3, 4):
        rank = 1
    elif "Exempt" in h1b:
        rank = 2
    elif "Sponsor" in h1b:
        rank = 3
    else:
        rank = 4

    # Within same H1B tier: auto-submittable sources first (0), others second (1)
    submittable = 0 if source in _SUBMITTABLE_SOURCES else 1

    posted   = job.get("posted_at", "") or ""
    has_date = 0 if posted else 1
    return (rank, submittable, has_date, _DateDesc(posted))


class _DateDesc:
    """Wraps a date string so that sorting ascending gives newest-first order."""
    __slots__ = ("value",)
    def __init__(self, value: str):
        self.value = value
    def __lt__(self, other):
        return self.value > other.value  # inverted: bigger date = "less" = sorts first
    def __eq__(self, other):
        return self.value == other.value


def collect_all_jobs(role: str) -> list[dict]:
    cfg      = get_config()
    location = cfg["search"]["location"]
    hours    = cfg["search"]["hours_old"]

    log.info(f"\n{'═'*60}\n  Role: {role}\n{'═'*60}")

    all_jobs = []

    # STEP 1: Job boards (LinkedIn + Indeed — searches ALL US companies)
    log.info("\n[1] Job boards: Indeed + Google Jobs...")
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

    # NOTE: Career page watcher is NOT run here. It already accepts a list
    # of roles and filters against all of them in a single pass over the
    # company sample — see watch_and_find_new() below. Running it once per
    # role (as before) re-scanned the same ~2,000 sampled companies once
    # per configured role for zero benefit, multiplying the slowest step
    # in the whole pipeline by len(roles). It now runs ONCE in run(),
    # outside this per-role loop.

    log.info(f"\n  Raw total for '{role}': {len(all_jobs)} jobs")
    for j in all_jobs:
        j["searched_role"] = role
    return all_jobs


def _tag_watcher_jobs_with_role(jobs: list[dict], roles: list[str]) -> None:
    """
    Watcher jobs are matched against ALL roles at once, so unlike
    collect_all_jobs() we can't assume a single role. Tag each job with
    whichever configured role its title actually matches (first match wins;
    titles are checked in the same order roles are configured).
    """
    for j in jobs:
        title = j.get("title", "")
        matched = next((r for r in roles if role_matches(title, r)), roles[0] if roles else "")
        j["searched_role"] = matched


def run():
    run_start_time = time.time()

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

    # Career page watcher — runs ONCE across all configured roles
    # (it already accepts a role list and matches against all of them
    # in a single pass), instead of once per role inside the loop above.
    log.info(f"\n{'═'*60}\n  Career page watcher (all roles: {', '.join(roles)})\n{'═'*60}")
    t0 = time.time()
    try:
        watcher_jobs = watch_and_find_new(roles)
        _tag_watcher_jobs_with_role(watcher_jobs, roles)
        log.info(f"  {len(watcher_jobs)} NEW jobs from career pages ({time.time()-t0:.1f}s)")
        raw.extend(watcher_jobs)
    except Exception as e:
        log.warning(f"  Watcher: {e}")

    jobs = deduplicate(raw)
    jobs = filter_jobs(jobs)
    jobs = [j for j in jobs if not already_applied(j)]

    for job in jobs:
        job["h1b_history"] = lookup_h1b_history(job.get("company",""))
        job["h1b_tier"]    = get_cap_exempt_tier(job.get("company",""))

    jobs.sort(key=_h1b_priority_rank)

    src_counts = Counter(j["source"] for j in jobs)
    h1b_counts = Counter(j.get("h1b_history","❓ No H1B Record") for j in jobs)

    log.info(f"\n{'─'*60}")
    log.info(f"Ready: {len(jobs)} unique jobs across {len(src_counts)} platforms")
    log.info(f"{'─'*60}")

    # Source breakdown
    log.info("By source:")
    for src, cnt in src_counts.most_common():
        log.info(f"  {src:25s} {cnt:4d} jobs")

    # H1B breakdown — prominent
    log.info("")
    log.info("H1B breakdown (for your F1/OPT planning):")
    log.info(f"  🎓 Cap-Exempt (No lottery, BEST) {h1b_counts.get('🎓 H1B Exempt (Cap-Free)', 0):4d} jobs")
    log.info(f"  ✅ H1B Sponsor (April lottery)   {h1b_counts.get('✅ H1B Sponsor', 0):4d} jobs")
    log.info(f"  ❓ No Record (still applying)    {h1b_counts.get('❓ No H1B Record', 0):4d} jobs")
    log.info(f"{'─'*60}")

    applied_count = get_today_applied_count()
    start_count   = applied_count
    results       = []

    # PER-RUN CAP — critical for GitHub Actions production use.
    # GitHub Actions has a 60-minute job timeout. The cron fires every
    # 20 minutes. If a single run tried to chase the full daily_cap (150),
    # it would apply ~50-60 jobs before timing out, get killed mid-application
    # (risking a half-submitted form), and repeat the ~6-minute discovery
    # phase from scratch on the next run without ever finishing the batch.
    #
    # Instead: spread daily_cap across the number of runs/day the cron
    # schedule provides, with headroom for discovery time + a safety margin.
    cron_runs_per_day = cfg.get("search", {}).get("cron_runs_per_day", 72)  # */20min = 72
    per_run_cap = max(1, daily_cap // max(cron_runs_per_day // 3, 1))
    # //3 above means: assume ~1 in 3 scheduled runs actually gets to apply
    # (others may be skipped/overlap-prevented), giving each active run
    # room to fully complete well inside the 60-minute timeout.
    per_run_cap = min(per_run_cap, 20)  # hard ceiling: ~20 jobs * 50s = ~17 min, safe margin
    log.info(f"Per-run cap: {per_run_cap} jobs (daily cap {daily_cap}, ~{cron_runs_per_day} scheduled runs/day)")

    applied_this_run = 0

    # TIME-BUDGET SAFETY GUARD — critical for GitHub Actions.
    # Discovery time is NOT constant: e.g. one observed run had Lever
    # watcher scraping take 5x longer than Greenhouse for the identical
    # 500-company workload (316s vs 59s), likely due to upstream API
    # slowness. The per_run_cap above assumes a typical discovery time,
    # but on a slow day it can leave too little real time before
    # GitHub Actions' 30-minute hard timeout — and the WORST place for
    # that timeout to land is mid-way through submitting a real form to
    # an actual employer's website.
    #
    # This guard checks elapsed wall-clock time before each application
    # and stops cleanly (committing whatever was already done) instead
    # of risking a hard kill mid-submission. Any unapplied jobs simply
    # carry over to the next scheduled run, same as hitting per_run_cap.
    max_runtime_minutes = cfg.get("search", {}).get("max_runtime_minutes", 20)
    max_runtime_seconds = max_runtime_minutes * 60

    for job in jobs:
        if applied_count >= daily_cap:
            log.info(f"\nDaily cap ({daily_cap}) reached.")
            break
        if applied_this_run >= per_run_cap:
            log.info(f"\nPer-run cap ({per_run_cap}) reached — remaining jobs carry over to next scheduled run.")
            break

        elapsed = time.time() - run_start_time
        if elapsed >= max_runtime_seconds:
            log.warning(
                f"\nTime budget ({max_runtime_minutes} min) reached after {elapsed/60:.1f} min elapsed "
                f"(discovery took longer than usual this run). Stopping cleanly here — "
                f"remaining jobs carry over to the next scheduled run rather than risking "
                f"a mid-submission timeout kill."
            )
            break

        log.info(f"\n→ [{job['source']}] {job['title']} @ {job['company']}")

        applied_this_run += 1
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
        roles_cfg = cfg["search"]["roles"]
        raw  = []
        for role in roles_cfg:
            raw.extend(collect_all_jobs(role))

        # Watcher runs once for all roles, same as in run() — see comment there.
        print(f"\n[Watcher] Checking career pages once for all roles: {', '.join(roles_cfg)}...")
        try:
            watcher_jobs = watch_and_find_new(roles_cfg)
            _tag_watcher_jobs_with_role(watcher_jobs, roles_cfg)
            raw.extend(watcher_jobs)
        except Exception as e:
            log.warning(f"  Watcher: {e}")

        jobs = deduplicate(raw)
        jobs = filter_jobs(jobs)
        jobs = [j for j in jobs if not already_applied(j)]

        for job in jobs:
            job["h1b_history"] = lookup_h1b_history(job.get("company",""))
            job["h1b_tier"]    = get_cap_exempt_tier(job.get("company",""))

        jobs.sort(key=_h1b_priority_rank)

        src = Counter(j["source"] for j in jobs)
        university = [j for j in jobs if j["h1b_tier"] == 1]
        hospital_npo_govt = [j for j in jobs if j["h1b_tier"] in (2, 3, 4)]
        other_exempt = [j for j in jobs if j["h1b_tier"] == 0 and "Exempt" in j["h1b_history"]]
        sponsor = [j for j in jobs if j["h1b_tier"] == 0 and "Sponsor" in j["h1b_history"]]
        norecord = [j for j in jobs if j["h1b_tier"] == 0
                    and "Exempt" not in j["h1b_history"] and "Sponsor" not in j["h1b_history"]]

        print(f"\n{'═'*65}")
        print(f"  JOB PREVIEW — {len(jobs)} jobs across {len(src)} platforms")
        print(f"{'═'*65}")
        print(h1b_explanation())
        print(f"\n  APPLY ORDER (all are applied to — this is just the priority):")
        print(f"  1. 🎓 University (verified, hires STEM OPT)  {len(university):4d} jobs")
        print(f"  2. 🏥 Hospital/Nonprofit/Govt (verified)     {len(hospital_npo_govt):4d} jobs")
        print(f"  3. 🎓 Other Cap-Exempt (unverified)          {len(other_exempt):4d} jobs")
        print(f"  4. ✅ H1B Sponsor (April lottery)            {len(sponsor):4d} jobs")
        print(f"  5. ❓ No H1B Record                          {len(norecord):4d} jobs")
        print(f"\n{'─'*65}")

        by_src = defaultdict(list)
        for j in jobs:
            by_src[j["source"]].append(j)
        for source, sjobs in sorted(by_src.items()):
            print(f"\n  [{source.upper()}] — {len(sjobs)} jobs")
            print(f"  {'─'*63}")
            for j in sjobs:
                if j["h1b_tier"] == 1:
                    tag = "🎓1"
                elif j["h1b_tier"] in (2, 3, 4):
                    tag = "🏥2"
                elif "Exempt" in j["h1b_history"]:
                    tag = "🎓?"
                elif "Sponsor" in j["h1b_history"]:
                    tag = "✅ "
                else:
                    tag = "❓ "
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
