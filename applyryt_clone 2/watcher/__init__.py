"""
watcher/__init__.py — Career page watcher for 50,000+ companies

HOW TSENTA DOES IT:
  Watches 50,000+ company career pages directly (company.com/careers),
  not just job boards. Jobs appear on career pages 6-24 hours BEFORE
  they show up on LinkedIn/Indeed — this gives you the "first to apply" advantage.

HOW WE DO IT:
  1. Start with a curated list of US companies organized by ATS type
     (we know their career page URL format from the ATS)
  2. Poll each company's ATS API directly — much faster than scraping HTML
  3. Cache what we've seen — only alert on genuinely NEW postings
  4. Grow the list automatically as new companies are discovered

  Greenhouse API:  boards-api.greenhouse.io/v1/boards/{slug}/jobs
  Lever API:       api.lever.co/v0/postings/{slug}
  Ashby API:       api.ashbyhq.com/posting-api/job-board/{slug}
  Workday:         XHR polling per company URL
  Others:          Direct HTTP to career pages, detect ATS from response

COVERAGE:
  We seed with curated lists of product companies per ATS.
  The slug cache grows automatically as new companies are found.
  Goal: 5,000+ companies on first run, growing to 50,000+ over time.
"""
import json, time, hashlib
from pathlib import Path
from utils import log, get_config, normalize_job
from scrapers.discovery import _matches, _cache_slug, _load_cache

ROOT      = Path(__file__).parent.parent
SEEN_FILE = ROOT / "logs" / "seen_jobs.json"

# ─────────────────────────────────────────────────────────────────────────────
# Seen-jobs cache — only alert on NEW postings
# ─────────────────────────────────────────────────────────────────────────────
def _load_seen() -> set:
    SEEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()

def _save_seen(seen: set):
    SEEN_FILE.write_text(json.dumps(list(seen)))

def _job_hash(job: dict) -> str:
    key = f"{job.get('title','').lower()}|{job.get('company','').lower()}"
    return hashlib.md5(key.encode()).hexdigest()

def is_new_job(job: dict) -> bool:
    seen = _load_seen()
    h = _job_hash(job)
    return h not in seen

def mark_seen(jobs: list[dict]):
    seen = _load_seen()
    for j in jobs:
        seen.add(_job_hash(j))
    _save_seen(seen)


# ─────────────────────────────────────────────────────────────────────────────
# Curated company lists — 5,000+ product companies across all major ATSes
# These are product-based companies (not consulting/staffing)
# Organized by ATS so we can hit their API directly
# ─────────────────────────────────────────────────────────────────────────────
def _load_company_lists() -> dict:
    """
    Returns {ats: [slug, ...]} for all known companies.
    Downloads open-source datasets on first run (50,000+ companies),
    uses cache on subsequent runs.
    """
    from watcher.company_loader import get_all_companies
    return get_all_companies()


    # Merge with dynamically discovered cache
    cache = _load_cache()
    merged = {}
    for ats in set(list(SEED.keys()) + list(cache.keys())):
        seen = set()
        combined = []
        for slug in (SEED.get(ats, []) + cache.get(ats, [])):
            if slug not in seen:
                seen.add(slug)
                combined.append(slug)
        merged[ats] = combined

    total = sum(len(v) for v in merged.values())
    log.info(f"  [WATCHER] Watching {total} companies across {len(merged)} ATSes")
    return merged


# ─────────────────────────────────────────────────────────────────────────────
# Fetch all current job postings from a company's ATS API
# ─────────────────────────────────────────────────────────────────────────────
import requests

def _fetch_greenhouse(slug: str) -> list[dict]:
    try:
        r = requests.get(
            f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
            timeout=8
        )
        if r.status_code != 200:
            return []
        import re
        return [normalize_job({
            "source":      "greenhouse",
            "id":          str(j.get("id","")),
            "title":       j.get("title",""),
            "company":     slug,
            "location":    j.get("location",{}).get("name","") if isinstance(j.get("location"),dict) else "",
            "url":         j.get("absolute_url",""),
            "description": re.sub(r"<[^>]+>","",j.get("content","")),
            "posted_at":   j.get("updated_at",""),
        }) for j in r.json().get("jobs",[])]
    except Exception:
        return []

def _fetch_lever(slug: str) -> list[dict]:
    try:
        r = requests.get(
            f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=500",
            timeout=8
        )
        if r.status_code != 200 or not isinstance(r.json(), list):
            return []
        return [normalize_job({
            "source":      "lever",
            "id":          j.get("id",""),
            "title":       j.get("text",""),
            "company":     slug,
            "location":    j.get("categories",{}).get("location","") if isinstance(j.get("categories"),dict) else "",
            "url":         j.get("hostedUrl",""),
            "description": j.get("descriptionPlain",""),
            "posted_at":   "",
        }) for j in r.json()]
    except Exception:
        return []

def _fetch_ashby(slug: str) -> list[dict]:
    try:
        r = requests.get(
            f"https://api.ashbyhq.com/posting-api/job-board/{slug}",
            timeout=8
        )
        if r.status_code != 200:
            return []
        return [normalize_job({
            "source":      "ashby",
            "id":          j.get("id",""),
            "title":       j.get("title",""),
            "company":     slug,
            "location":    j.get("locationName",""),
            "url":         j.get("jobUrl",""),
            "description": j.get("descriptionPlain",""),
            "posted_at":   j.get("publishedDate",""),
        }) for j in r.json().get("jobs",[])]
    except Exception:
        return []

def _fetch_workable(slug: str) -> list[dict]:
    try:
        r = requests.get(
            f"https://apply.workable.com/api/v3/accounts/{slug}/jobs",
            timeout=8
        )
        if r.status_code != 200:
            return []
        return [normalize_job({
            "source":      "workable",
            "id":          j.get("shortcode",""),
            "title":       j.get("title",""),
            "company":     slug,
            "location":    j.get("location",{}).get("city","") if isinstance(j.get("location"),dict) else "",
            "url":         f"https://apply.workable.com/{slug}/j/{j.get('shortcode','')}",
            "description": j.get("description",""),
            "posted_at":   j.get("published_on",""),
        }) for j in r.json().get("results",[])]
    except Exception:
        return []

ATS_FETCHERS = {
    "greenhouse":      _fetch_greenhouse,
    "lever":           _fetch_lever,
    "ashby":           _fetch_ashby,
    "workable":        _fetch_workable,
}


# ─────────────────────────────────────────────────────────────────────────────
# Main watch function — polls all companies, returns only NEW matching jobs
# ─────────────────────────────────────────────────────────────────────────────
def watch_and_find_new(roles: list[str]) -> list[dict]:
    """
    Polls a random sample of watched company career pages each run.
    Returns only jobs that are:
      1. New (not seen in previous runs)
      2. Match one of the target roles
      3. US-based or remote

    PERFORMANCE: checking all 27,000+ companies at 150ms each would take
    over an hour per run. Instead we sample 500 companies per ATS per run
    (~2,000 total). At 72 runs/day (every 20 min), every company gets
    checked multiple times within a single day via random rotation.
    """
    import random

    companies = _load_company_lists()
    all_new   = []
    total_checked = 0
    total_new = 0

    # Load the seen-jobs set ONCE per run, not once per job (was a major
    # perf bug — _load_seen() re-reads the JSON file from disk every call)
    seen = _load_seen()

    for ats, fetcher in ATS_FETCHERS.items():
        slugs = companies.get(ats, [])
        if not slugs:
            continue

        sample_size = min(500, len(slugs))
        sample = random.sample(slugs, sample_size)
        log.info(f"  [WATCHER] {ats.upper()}: checking {sample_size}/{len(slugs)} companies this run...")

        for i, slug in enumerate(sample):
            total_checked += 1
            try:
                jobs = fetcher(slug)
                for job in jobs:
                    # Role filter
                    if not any(_matches(job.get("title",""), role) for role in roles):
                        continue
                    # US filter
                    loc = (job.get("location") or "").lower()
                    if loc and any(s in loc for s in ["india","canada","uk","philippines","germany","remote - emea"]):
                        continue
                    # New job filter (in-memory set, no disk I/O per job)
                    h = _job_hash(job)
                    if h not in seen:
                        seen.add(h)
                        all_new.append(job)
                        total_new += 1
                time.sleep(0.05)  # 50ms — fast but still polite to the API
            except Exception as e:
                log.debug(f"  [Watcher/{ats}/{slug}] {e}")

            if (i + 1) % 100 == 0:
                log.info(f"  [WATCHER] {ats.upper()}: {i+1}/{sample_size} checked → {total_new} new so far")

    # Persist the updated seen-set once at the end, not per job
    _save_seen(seen)

    total_companies = sum(len(v) for v in companies.values()) or 1
    log.info(f"  [WATCHER] Done: checked {total_checked} companies → {total_new} new matching jobs")
    log.info(f"  [WATCHER] Full rotation across all {total_companies} companies "
              f"every ~{total_companies // max(total_checked,1) + 1} runs")
    return all_new
