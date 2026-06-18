"""
scrapers/discovery.py — Dynamic discovery across all 12 ATS platforms

THE FUNDAMENTAL TRUTH about all these ATS platforms:
  Workday, Greenhouse, Lever, Ashby, Rippling, iCIMS, BambooHR,
  Workable, JazzHR, Jobvite, Breezy, Oracle — NONE have a cross-company
  search API. You cannot say "search all Greenhouse companies for Business
  Analyst". They are per-company-only APIs.

THE SOLUTION — dynamic slug extraction:
  1. Indeed + Google Jobs search by ROLE KEYWORD across ALL companies
     → returns job URLs like:
       https://boards.greenhouse.io/stripe/jobs/123
       https://jobs.lever.co/netflix/abc
       https://company.bamboohr.com/careers/...
       https://company.wd5.myworkdayjobs.com/...
  2. We extract the company slug from each URL → cache it
  3. We then hit that company's ATS API directly for the full JD
  4. Cache grows every run — more companies discovered automatically

PLATFORMS COVERED:
  Tier 1 (search by role, all companies): Indeed, Google Jobs, Glassdoor
  Tier 2 (dynamic slug extraction):
    Greenhouse, Lever, Ashby, Rippling, iCIMS, BambooHR,
    Workable, JazzHR, Jobvite, Breezy, SmartRecruiters, Oracle/Taleo
  Tier 3 (workday — URL extraction from job boards):
    Workday (myworkdayjobs.com)
"""

import re, time, json, requests
from pathlib import Path
from urllib.parse import quote_plus
from utils import log, get_config, normalize_job

ROOT       = Path(__file__).parent.parent


def _safe_str(value, default: str = "") -> str:
    """
    Safely converts a pandas row value to a string, handling NaN correctly.

    BUG THIS FIXES: pandas NaN is truthy in Python, so `row.get(x, "") or ""`
    does NOT fall back to "" when the cell is empty — it returns the NaN
    float, and str(nan) produces the literal string "nan". This silently
    corrupted company/title/location fields with the text "nan" whenever
    Indeed/JobSpy returned a blank cell (observed in production: several
    jobs showed company name "nan" in --list output).
    """
    if value is None:
        return default
    # Covers pandas/numpy NaN without requiring a pandas import here —
    # NaN is the only float that is never equal to itself.
    if isinstance(value, float) and value != value:
        return default
    s = str(value).strip()
    if s.lower() == "nan":
        return default
    return s
CACHE_FILE = ROOT / "logs" / "slug_cache.json"

# ─────────────────────────────────────────────────────────────────────────────
# ATS URL patterns — extract company slug from ANY career page URL
# ─────────────────────────────────────────────────────────────────────────────
# ATS_PATTERNS now in scrapers/ats_scrapers.py
ATS_PATTERNS = [
    ("greenhouse",      r"boards\.greenhouse\.io/([a-z0-9_-]+)"),
    ("greenhouse",      r"job-boards\.greenhouse\.io/([a-z0-9_-]+)"),
    ("lever",           r"jobs\.lever\.co/([a-z0-9_-]+)"),
    ("ashby",           r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)"),
    ("rippling",        r"ats\.rippling\.com/([a-zA-Z0-9_-]+)"),
    ("smartrecruiters", r"jobs\.smartrecruiters\.com/([a-zA-Z0-9_-]+)"),
    ("workable",        r"apply\.workable\.com/([a-z0-9_-]+)"),
    ("bamboohr",        r"([a-z0-9-]+)\.bamboohr\.com"),
    ("icims",           r"([a-z0-9-]+)\.icims\.com"),
    ("jazzhr",          r"([a-z0-9-]+)\.applytojob\.com"),
    ("jobvite",         r"jobs\.jobvite\.com/([a-zA-Z0-9_-]+)"),
    ("breezy",          r"([a-z0-9-]+)\.breezy\.hr"),
    ("oracle",          r"([a-z0-9-]+)\.fa\.([a-z0-9]+)\.oraclecloud\.com"),
    ("taleo",           r"([a-z0-9-]+)\.taleo\.net"),
    ("workday",         r"(https?://[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com[^\s\"'<>]*)"),
    ("teamtailor",      r"jobs\.([a-z0-9-]+)\.com.*teamtailor"),
    ("personio",        r"([a-z0-9-]+)\.jobs\.personio\.(de|com)"),
]

def extract_ats(url: str) -> tuple[str, str] | None:
    """Given any job URL, return (ats_platform, company_slug) or None."""
    if not url:
        return None
    for ats, pat in ATS_PATTERNS:
        m = re.search(pat, url, re.IGNORECASE)
        if m:
            try:
                val = m.group(1).strip("/")
                if ats == "workday":
                    return ("workday", url)   # workday needs full URL
                return (ats, val.lower())
            except (IndexError, AttributeError):
                continue
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Slug cache — persists across runs, grows automatically every run
# ─────────────────────────────────────────────────────────────────────────────
def _load_cache() -> dict:
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_cache(cache: dict):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def _cache_slug(ats: str, slug: str) -> bool:
    """Add a discovered company to cache. Returns True if it was new."""
    cache = _load_cache()
    lst   = cache.setdefault(ats, [])
    if slug not in lst:
        lst.append(slug)
        _save_cache(cache)
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Role matching — flexible keyword matching with common variants
# ─────────────────────────────────────────────────────────────────────────────
ROLE_VARIANTS = {
    "business analyst": [
        # Must contain "business" + "analyst" concept together
        "business systems analyst","business process analyst","business data analyst",
        "business intelligence analyst","business operations analyst",
        "it business analyst","sr. business analyst","sr business analyst",
        "senior business analyst","lead business analyst","principal business analyst",
        "associate business analyst","junior business analyst",
        "enterprise analyst","functional analyst","requirements analyst",
        "management analyst",
    ],
    "business transformation analyst": [
        "transformation analyst","business transformation",
        "process improvement analyst","change management analyst",
        "operational excellence analyst","continuous improvement analyst",
        "lean six sigma analyst","enterprise transformation",
    ],
    "product owner": [
        "product owner","scrum product owner","technical product owner",
        "agile product owner","digital product owner",
    ],
    "process improvement analyst": [
        "process improvement analyst","continuous improvement analyst",
        "operational excellence analyst","lean analyst",
        "six sigma analyst","process optimization analyst",
    ],
}

def _matches(title: str, role: str) -> bool:
    t, r = title.lower(), role.lower()
    if r in t: return True
    words = [w for w in r.split() if len(w) > 2 and w not in ("and","the","for","with")]
    if words and all(w in t for w in words): return True
    for canon, variants in ROLE_VARIANTS.items():
        if canon in r and any(v in t for v in variants): return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 1+2: JobSpy → Indeed + Google
# Searches ALL US companies by role keyword
# Extracts ATS slugs from job URLs as side-effect → populates the cache
# ─────────────────────────────────────────────────────────────────────────────
def search_jobboards(role: str, location: str, hours_old: int) -> list[dict]:
    """
    Searches LinkedIn + Indeed across multiple US cities to maximize coverage.
    LinkedIn/Indeed limit results to ~50-100 per search regardless of results_wanted.
    Running multiple city-anchored searches gets us 5-10x more total results.
    """
    all_jobs = []
    try:
        from jobspy import scrape_jobs
    except ImportError:
        log.warning("[JobSpy] Not installed")
        return []

    hours_label = "since last month" if hours_old > 168 else                   "since last week" if hours_old > 72 else "since yesterday"
    google_query = f"{role} jobs United States {hours_label}"

    # Multiple US metro anchors — each returns a different geo-ranked set of results
    US_ANCHORS = [
        location,           # Tampa, FL (user's location)
        "New York, NY",
        "Chicago, IL",
        "Dallas, TX",
        "Atlanta, GA",
        "Washington, DC",
        "Houston, TX",
        "Los Angeles, CA",
        "San Francisco, CA",
        "Seattle, WA",
        "Boston, MA",
        "Austin, TX",
    ]

    seen_ids: set = set()  # dedup across all anchor searches
    seen_lock = __import__("threading").Lock()

    def _search(site: str, label: str, anchor: str) -> list[dict]:
        try:
            df = scrape_jobs(
                site_name=[site],
                search_term=role,
                google_search_term=google_query,
                location=anchor,
                distance=75,
                results_wanted=500,
                hours_old=hours_old,
                country_indeed="USA",
                # Removed job_type="fulltime" — LinkedIn returns fewer results with it
                # Full-time filtering handled by title keyword filter downstream
                linkedin_fetch_description=True,
            )
            jobs, new = [], 0
            for _, row in df.iterrows():
                url    = _safe_str(row.get("job_url", ""))
                job_id = _safe_str(row.get("id", "")) or url

                # seen_ids and the ATS slug cache are shared across threads —
                # guard both with the lock to avoid races / duplicate writes
                with seen_lock:
                    if job_id in seen_ids:
                        continue
                    seen_ids.add(job_id)
                    result = extract_ats(url)
                    if result:
                        ats, slug = result
                        if _cache_slug(ats, slug):
                            new += 1

                company = _safe_str(row.get("company", ""))
                if not company:
                    # Skip jobs with no usable company name entirely —
                    # these can't be meaningfully scored, deduped, or
                    # applied to, and previously leaked through as the
                    # literal string "nan" in job listings.
                    continue

                jobs.append(normalize_job({
                    "source":      row.get("site", label.lower()),
                    "title":       _safe_str(row.get("title", "")),
                    "company":     company,
                    "location":    _safe_str(row.get("location", "")),
                    "url":         url,
                    "description": _safe_str(row.get("description", "")),
                    "id":          job_id,
                    "salary_min":  row.get("min_amount"),
                    "salary_max":  row.get("max_amount"),
                }))
            if jobs:
                log.info(f"  [{label}/{anchor.split(',')[0]}] {len(jobs)} jobs | {new} new ATS")
            return jobs
        except Exception as e:
            log.debug(f"  [{label}/{anchor}] {e}")
            return []

    # Indeed — across all US regions, run concurrently for speed.
    # JobSpy/Indeed calls are I/O-bound (network), so a thread pool gives a
    # real wall-clock speedup without hitting Python's GIL limitations.
    # Capped at 6 concurrent workers to stay polite to Indeed and avoid
    # the "blocked for too many requests" failure mode JobSpy warns about.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    log.info(f"  [Indeed] '{role}' across {len(US_ANCHORS)} US regions (parallel)...")
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_search, "indeed", "indeed", anchor): anchor for anchor in US_ANCHORS}
        for future in as_completed(futures):
            all_jobs.extend(future.result())

    # Google Jobs — catches company career pages not on Indeed
    log.info(f"  [Google Jobs] '{role}'...")
    all_jobs.extend(_search("google", "google", location))
    all_jobs.extend(_search("google", "google", "United States"))

    log.info(f"  [Job boards total] {len(all_jobs)} unique jobs for '{role}'")
    return all_jobs


# ─────────────────────────────────────────────────────────────────────────────
# SOURCE 3: SERP discovery (DuckDuckGo)
# Finds ATS company slugs by searching role + site:boards.greenhouse.io etc.
# Supplements URL extraction with roles that don't appear on Indeed/Google
# ─────────────────────────────────────────────────────────────────────────────
# Tsenta covers 19 ATSes — SERP discovers companies on each
SERP_TARGETS = {
    "greenhouse":      "site:boards.greenhouse.io",
    "lever":           "site:jobs.lever.co",
    "ashby":           "site:jobs.ashbyhq.com",
    "workable":        "site:apply.workable.com",
    "smartrecruiters": "site:jobs.smartrecruiters.com",
    "bamboohr":        "site:bamboohr.com",
    "breezy":          "site:breezy.hr",
    "jobvite":         "site:jobs.jobvite.com",
    "rippling":        "site:ats.rippling.com",
    "recruitee":       "site:recruitee.com",
    "personio":        "site:jobs.personio.com",
    "pinpoint":        "site:pinpointhq.com",
}

def _serp_discover(role: str):
    """DuckDuckGo search for role on each ATS domain → caches new slugs."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0",
        "Accept-Language": "en-US,en;q=0.9",
    }
    total_new = 0
    for ats, site_filter in SERP_TARGETS.items():
        try:
            q   = f"{role} {site_filter}"
            url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
            r   = requests.get(url, headers=headers, timeout=12)
            # Find all ATS URLs in the HTML response
            for ats2, pat in ATS_PATTERNS:
                if ats2 != ats:
                    continue
                for slug in re.findall(pat, r.text, re.IGNORECASE):
                    slug = slug.lower().strip("/")
                    if slug and len(slug) > 1 and _cache_slug(ats, slug):
                        total_new += 1
            time.sleep(1)
        except Exception as e:
            log.debug(f"[SERP/{ats}] {e}")
    if total_new:
        log.info(f"  [SERP] {total_new} new company slugs discovered")


# ─────────────────────────────────────────────────────────────────────────────
# ATS scraper functions — one per platform, all free public APIs
# ─────────────────────────────────────────────────────────────────────────────
def _scrape_ats_api(url: str, headers: dict | None = None,
                    timeout: int = 10) -> dict | list | None:
    try:
        r = requests.get(url, headers=headers or {}, timeout=timeout)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


def _scrape_greenhouse(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    )
    if not data or not isinstance(data.get("jobs"), list):
        return []
    return [normalize_job({
        "source":      "greenhouse",
        "id":          str(j.get("id", "")),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("location", {}).get("name", "") if isinstance(j.get("location"), dict) else "",
        "url":         j.get("absolute_url", ""),
        "description": re.sub(r"<[^>]+>", "", j.get("content", "")),
        "posted_at":   j.get("updated_at", ""),
    }) for j in data["jobs"]]


def _scrape_lever(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=500"
    )
    if not isinstance(data, list):
        return []
    return [normalize_job({
        "source":      "lever",
        "id":          j.get("id", ""),
        "title":       j.get("text", ""),
        "company":     slug,
        "location":    j.get("categories", {}).get("location", "") if isinstance(j.get("categories"), dict) else "",
        "url":         j.get("hostedUrl", ""),
        "description": j.get("descriptionPlain", ""),
        "posted_at":   "",
    }) for j in data]


def _scrape_ashby(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    )
    if not data or not isinstance(data.get("jobs"), list):
        return []
    return [normalize_job({
        "source":      "ashby",
        "id":          j.get("id", ""),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("locationName", ""),
        "url":         j.get("jobUrl", ""),
        "description": j.get("descriptionPlain", ""),
        "posted_at":   j.get("publishedDate", ""),
    }) for j in data["jobs"]]


def _scrape_smartrecruiters(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100"
    )
    if not data or not isinstance(data.get("content"), list):
        return []
    return [normalize_job({
        "source":      "smartrecruiters",
        "id":          j.get("id", ""),
        "title":       j.get("name", ""),
        "company":     j.get("company", {}).get("name", slug) if isinstance(j.get("company"), dict) else slug,
        "location":    j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://jobs.smartrecruiters.com/{slug}/{j.get('id','')}",
        "description": j.get("jobDescription", {}).get("text", "") if isinstance(j.get("jobDescription"), dict) else "",
        "posted_at":   j.get("releasedDate", ""),
    }) for j in data["content"]]


def _scrape_workable(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://apply.workable.com/api/v3/accounts/{slug}/jobs",
        headers={"Content-Type": "application/json"},
    )
    if not data or not isinstance(data.get("results"), list):
        return []
    return [normalize_job({
        "source":      "workable",
        "id":          j.get("shortcode", ""),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://apply.workable.com/{slug}/j/{j.get('shortcode','')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("published_on", ""),
    }) for j in data["results"]]


def _scrape_bamboohr(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://{slug}.bamboohr.com/careers/list",
        headers={"Accept": "application/json"},
    )
    if not data or not isinstance(data.get("result"), list):
        return []
    return [normalize_job({
        "source":      "bamboohr",
        "id":          str(j.get("id", "")),
        "title":       j.get("jobOpeningName", j.get("title", "")),
        "company":     slug,
        "location":    j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://{slug}.bamboohr.com/careers/{j.get('id','')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("datePosted", ""),
    }) for j in data["result"]]


def _scrape_jazzhr(slug: str) -> list[dict]:
    data = _scrape_ats_api(f"https://{slug}.applytojob.com/apply")
    # JazzHR returns HTML, needs parsing — skip for now, URL extraction still works
    return []


def _scrape_jobvite(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://jobs.jobvite.com/{slug}/search-jobs/results?&Job.Location=United+States"
    )
    if not isinstance(data, list):
        return []
    return [normalize_job({
        "source":      "jobvite",
        "id":          j.get("id", ""),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("location", ""),
        "url":         j.get("applyLink", j.get("shareLink", "")),
        "description": j.get("description", ""),
        "posted_at":   j.get("date", ""),
    }) for j in data]


def _scrape_breezy(slug: str) -> list[dict]:
    data = _scrape_ats_api(f"https://{slug}.breezy.hr/json")
    if not isinstance(data, list):
        return []
    return [normalize_job({
        "source":      "breezy",
        "id":          j.get("_id", ""),
        "title":       j.get("name", ""),
        "company":     slug,
        "location":    j.get("location", {}).get("name", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://{slug}.breezy.hr/p/{j.get('_id','')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("creation_date", ""),
    }) for j in data]


def _scrape_rippling(slug: str) -> list[dict]:
    data = _scrape_ats_api(
        f"https://ats.rippling.com/api/ats/public/companies/{slug}/jobs"
    )
    if not isinstance(data, list):
        return []
    return [normalize_job({
        "source":      "rippling",
        "id":          str(j.get("id", "")),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("location", ""),
        "url":         f"https://ats.rippling.com/{slug}/jobs/{j.get('id','')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("createdAt", ""),
    }) for j in data]


def _scrape_icims(slug: str) -> list[dict]:
    # iCIMS API varies by client — use their search endpoint
    data = _scrape_ats_api(
        f"https://{slug}.icims.com/jobs/search?ss=1&searchCategory=&searchLocation=&pr=1&in_iframe=1",
        headers={"Accept": "application/json"},
    )
    # iCIMS returns HTML — ATS URL extraction from job boards is more reliable
    return []


# Map ATS name → scraper function
ATS_SCRAPERS = {
    "greenhouse":      _scrape_greenhouse,
    "lever":           _scrape_lever,
    "ashby":           _scrape_ashby,
    "smartrecruiters": _scrape_smartrecruiters,
    "workable":        _scrape_workable,
    "bamboohr":        _scrape_bamboohr,
    "jobvite":         _scrape_jobvite,
    "breezy":          _scrape_breezy,
    "rippling":        _scrape_rippling,
    # jazzhr, icims, oracle/taleo: URL extraction works but JSON API needs auth
    # Jobs from these still get found via Indeed/Google URL extraction
}


# ─────────────────────────────────────────────────────────────────────────────
# Workday — XHR-based scraping from cached URLs
# ─────────────────────────────────────────────────────────────────────────────
def _scrape_workday_cached(role: str) -> list[dict]:
    from scrapers import scrape_workday
    cache = _load_cache()
    urls  = cache.get("workday", [])
    if not urls:
        return []
    log.info(f"  [WORKDAY] Scraping {len(urls)} discovered enterprise sites...")
    results = []
    for url in urls:
        try:
            jobs = scrape_workday(url)
            hits = [j for j in jobs if _matches(j.get("title",""), role)]
            results.extend(hits)
            time.sleep(2)
        except Exception as e:
            log.debug(f"  [Workday/{url[:40]}] {e}")
    log.info(f"  [WORKDAY] {len(results)} matching jobs found")
    return results


# ─────────────────────────────────────────────────────────────────────────────
# MASTER function — called from main.py
# ─────────────────────────────────────────────────────────────────────────────
def find_jobs_for_role(role: str) -> list[dict]:
    """
    Full ATS discovery pipeline.
    All companies discovered dynamically — zero hardcoded slugs.
    Cache grows every run as new companies are found from job board URLs.
    """
    # Step 1: SERP discovery (finds slugs on Greenhouse/Lever/Ashby/etc)
    log.info("\n[2/4] SERP discovery (DuckDuckGo → ATS companies)...")
    _serp_discover(role)

    # Step 2: Load all dynamically discovered company slugs from cache
    log.info("\n[3/4] Scraping all discovered companies from their ATS APIs...")
    cache   = _load_cache()
    results = []

    # Scrape each ATS platform for which we have cached slugs
    for ats, scraper_fn in ATS_SCRAPERS.items():
        slugs = cache.get(ats, [])
        if not slugs:
            continue
        log.info(f"  [{ats.upper()}] {len(slugs)} companies discovered...")
        matched = 0
        for slug in slugs:
            try:
                jobs = scraper_fn(slug)
                hits = [j for j in jobs if _matches(j.get("title",""), role)]
                matched += len(hits)
                results.extend(hits)
                time.sleep(0.2)
            except Exception as e:
                log.debug(f"  [{ats}/{slug}] {e}")
        if matched:
            log.info(f"  [{ats.upper()}] {matched} matching '{role}' jobs")

    # Step 3: Workday — from cached URLs
    log.info("\n[4/4] Workday enterprise scraping...")
    results.extend(_scrape_workday_cached(role))

    return results
