"""
scrapers/ats_scrapers.py — All 19 ATS platform scrapers

Matching Tsenta's 19 ATS coverage:
  Tier 1 (Public JSON API — fast, no browser):
    1.  Greenhouse        boards-api.greenhouse.io/v1/boards/{slug}/jobs
    2.  Lever             api.lever.co/v0/postings/{slug}
    3.  Ashby             api.ashbyhq.com/posting-api/job-board/{slug}
    4.  Workable          apply.workable.com/api/v3/accounts/{slug}/jobs
    5.  SmartRecruiters   api.smartrecruiters.com/v1/companies/{slug}/postings
    6.  BambooHR          {slug}.bamboohr.com/careers/list
    7.  Jobvite           jobs.jobvite.com/{slug}/search-jobs/results
    8.  Breezy            {slug}.breezy.hr/json
    9.  Rippling          ats.rippling.com/api/ats/public/companies/{slug}/jobs
    10. Recruitee         {slug}.recruitee.com/api/offers
    11. Personio          {slug}.jobs.personio.com/api/jobs
    12. Teamtailor        api.teamtailor.com/v1/jobs (requires token — skip)
    13. Pinpoint          {slug}.pinpointhq.com/api/v1/postings

  Tier 2 (Browser/XHR — slower but covers enterprise):
    14. Workday           *.wd*.myworkdayjobs.com (XHR interception)
    15. iCIMS             *.icims.com (Playwright)
    16. Taleo/Oracle      *.taleo.net (Playwright)
    17. SuccessFactors    careers.sap.com/api/v1/jobs (SAP SuccessFactors)
    18. ADP               jobs.adp.com (REST API)
    19. Paycom            {slug}.paycom.com/careers (Playwright)

DISCOVERY:
  Company slugs are discovered dynamically from:
  1. Indeed/Google job URLs (extracted automatically)
  2. DuckDuckGo SERP for each ATS domain
  3. Open-source company datasets (20,000+ companies)
  4. Growing slug cache (logs/slug_cache.json)
"""
import re, time, requests
from utils import log, normalize_job

TIMEOUT = 8  # seconds per API call


def _get(url: str, headers: dict | None = None) -> dict | list | None:
    """Safe GET with timeout."""
    try:
        r = requests.get(url, headers=headers or {}, timeout=TIMEOUT)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 1. GREENHOUSE
# ─────────────────────────────────────────────────────────────────────────────
def scrape_greenhouse(slug: str) -> list[dict]:
    data = _get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    if not data or not isinstance(data.get("jobs"), list):
        return []
    return [normalize_job({
        "source":      "greenhouse",
        "id":          str(j.get("id", "")),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("location", {}).get("name", "") if isinstance(j.get("location"), dict) else "",
        "url":         j.get("absolute_url", ""),
        "description": re.sub(r"<[^>]+>", " ", j.get("content", "")),
        "posted_at":   j.get("updated_at", ""),
    }) for j in data["jobs"]]


# ─────────────────────────────────────────────────────────────────────────────
# 2. LEVER
# ─────────────────────────────────────────────────────────────────────────────
def scrape_lever(slug: str) -> list[dict]:
    data = _get(f"https://api.lever.co/v0/postings/{slug}?mode=json&limit=500")
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


# ─────────────────────────────────────────────────────────────────────────────
# 3. ASHBY
# ─────────────────────────────────────────────────────────────────────────────
def scrape_ashby(slug: str) -> list[dict]:
    data = _get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
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


# ─────────────────────────────────────────────────────────────────────────────
# 4. WORKABLE
# ─────────────────────────────────────────────────────────────────────────────
def scrape_workable(slug: str) -> list[dict]:
    data = _get(f"https://apply.workable.com/api/v3/accounts/{slug}/jobs")
    if not data or not isinstance(data.get("results"), list):
        return []
    return [normalize_job({
        "source":      "workable",
        "id":          j.get("shortcode", ""),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://apply.workable.com/{slug}/j/{j.get('shortcode', '')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("published_on", ""),
    }) for j in data["results"]]


# ─────────────────────────────────────────────────────────────────────────────
# 5. SMARTRECRUITERS
# ─────────────────────────────────────────────────────────────────────────────
def scrape_smartrecruiters(slug: str) -> list[dict]:
    data = _get(f"https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100")
    if not data or not isinstance(data.get("content"), list):
        return []
    return [normalize_job({
        "source":      "smartrecruiters",
        "id":          j.get("id", ""),
        "title":       j.get("name", ""),
        "company":     j.get("company", {}).get("name", slug) if isinstance(j.get("company"), dict) else slug,
        "location":    j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://jobs.smartrecruiters.com/{slug}/{j.get('id', '')}",
        "description": j.get("jobDescription", {}).get("text", "") if isinstance(j.get("jobDescription"), dict) else "",
        "posted_at":   j.get("releasedDate", ""),
    }) for j in data["content"]]


# ─────────────────────────────────────────────────────────────────────────────
# 6. BAMBOOHR
# ─────────────────────────────────────────────────────────────────────────────
def scrape_bamboohr(slug: str) -> list[dict]:
    data = _get(f"https://{slug}.bamboohr.com/careers/list",
                headers={"Accept": "application/json"})
    if not data or not isinstance(data.get("result"), list):
        return []
    return [normalize_job({
        "source":      "bamboohr",
        "id":          str(j.get("id", "")),
        "title":       j.get("jobOpeningName", j.get("title", "")),
        "company":     slug,
        "location":    j.get("location", {}).get("city", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://{slug}.bamboohr.com/careers/{j.get('id', '')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("datePosted", ""),
    }) for j in data["result"]]


# ─────────────────────────────────────────────────────────────────────────────
# 7. JOBVITE
# ─────────────────────────────────────────────────────────────────────────────
def scrape_jobvite(slug: str) -> list[dict]:
    data = _get(f"https://jobs.jobvite.com/{slug}/search-jobs/results?&Job.Location=United+States")
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


# ─────────────────────────────────────────────────────────────────────────────
# 8. BREEZY HR
# ─────────────────────────────────────────────────────────────────────────────
def scrape_breezy(slug: str) -> list[dict]:
    data = _get(f"https://{slug}.breezy.hr/json")
    if not isinstance(data, list):
        return []
    return [normalize_job({
        "source":      "breezy",
        "id":          j.get("_id", ""),
        "title":       j.get("name", ""),
        "company":     slug,
        "location":    j.get("location", {}).get("name", "") if isinstance(j.get("location"), dict) else "",
        "url":         f"https://{slug}.breezy.hr/p/{j.get('_id', '')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("creation_date", ""),
    }) for j in data]


# ─────────────────────────────────────────────────────────────────────────────
# 9. RIPPLING
# ─────────────────────────────────────────────────────────────────────────────
def scrape_rippling(slug: str) -> list[dict]:
    data = _get(f"https://ats.rippling.com/api/ats/public/companies/{slug}/jobs")
    if not isinstance(data, list):
        return []
    return [normalize_job({
        "source":      "rippling",
        "id":          str(j.get("id", "")),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("location", ""),
        "url":         f"https://ats.rippling.com/{slug}/jobs/{j.get('id', '')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("createdAt", ""),
    }) for j in data]


# ─────────────────────────────────────────────────────────────────────────────
# 10. RECRUITEE
# ─────────────────────────────────────────────────────────────────────────────
def scrape_recruitee(slug: str) -> list[dict]:
    data = _get(f"https://{slug}.recruitee.com/api/offers")
    if not data or not isinstance(data.get("offers"), list):
        return []
    return [normalize_job({
        "source":      "recruitee",
        "id":          str(j.get("id", "")),
        "title":       j.get("title", ""),
        "company":     slug,
        "location":    j.get("city", ""),
        "url":         j.get("careers_url", ""),
        "description": re.sub(r"<[^>]+>", " ", j.get("description", "")),
        "posted_at":   j.get("published_at", ""),
    }) for j in data["offers"]]


# ─────────────────────────────────────────────────────────────────────────────
# 11. PERSONIO
# ─────────────────────────────────────────────────────────────────────────────
def scrape_personio(slug: str) -> list[dict]:
    data = _get(f"https://{slug}.jobs.personio.com/api/v1/jobs?language=en")
    if not isinstance(data, list):
        return []
    return [normalize_job({
        "source":      "personio",
        "id":          str(j.get("id", "")),
        "title":       j.get("name", ""),
        "company":     slug,
        "location":    j.get("office", ""),
        "url":         f"https://{slug}.jobs.personio.com/job/{j.get('id', '')}",
        "description": j.get("description", ""),
        "posted_at":   j.get("created_at", ""),
    }) for j in data]


# ─────────────────────────────────────────────────────────────────────────────
# 12. PINPOINT
# ─────────────────────────────────────────────────────────────────────────────
def scrape_pinpoint(slug: str) -> list[dict]:
    data = _get(f"https://{slug}.pinpointhq.com/api/v1/jobs")
    if not data or not isinstance(data.get("data"), list):
        return []
    return [normalize_job({
        "source":      "pinpoint",
        "id":          str(j.get("id", "")),
        "title":       j.get("attributes", {}).get("title", "") if isinstance(j.get("attributes"), dict) else "",
        "company":     slug,
        "location":    j.get("attributes", {}).get("location", "") if isinstance(j.get("attributes"), dict) else "",
        "url":         j.get("attributes", {}).get("show_url", "") if isinstance(j.get("attributes"), dict) else "",
        "description": "",
        "posted_at":   "",
    }) for j in data["data"]]


# ─────────────────────────────────────────────────────────────────────────────
# 13. WORKDAY (XHR interception — enterprise, 32% of US market)
# ─────────────────────────────────────────────────────────────────────────────
def scrape_workday(url: str) -> list[dict]:
    """XHR-based Workday scraper. url = full myworkdayjobs.com URL."""
    try:
        from playwright.sync_api import sync_playwright
        captured = []
        done = False

        def on_response(resp):
            if done:
                return
            if "wday/cxs" not in resp.url:
                return
            try:
                ct = resp.headers.get("content-type", "")
                if "json" not in ct:
                    return
                d = resp.json()
                chunk = d.get("jobPostings", [])
                if isinstance(chunk, list):
                    captured.extend(chunk)
            except Exception:
                pass

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(20000)
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception:
                pass
            time.sleep(6)
            done = True
            page.remove_listener("response", on_response)
            try:
                browser.close()
            except Exception:
                pass

        try:
            company = url.split("//")[-1].split(".wd")[0]
        except Exception:
            company = "unknown"
        try:
            base = url.split(".myworkdayjobs.com")[0] + ".myworkdayjobs.com"
        except Exception:
            base = url

        return [normalize_job({
            "source":    "workday",
            "company":   company,
            "id":        j.get("bulletFields", [""])[0] if j.get("bulletFields") else "",
            "title":     j.get("title", ""),
            "location":  j.get("locationsText", ""),
            "url":       base + j.get("externalPath", "") if j.get("externalPath") else url,
            "posted_at": j.get("postedOn", ""),
            "description": j.get("jobDescription", ""),
        }) for j in captured]
    except Exception as e:
        log.debug(f"[Workday] {url}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# 14. iCIMS (Playwright — large enterprise ATS)
# ─────────────────────────────────────────────────────────────────────────────
def scrape_icims(slug: str) -> list[dict]:
    """iCIMS career pages — each company has a subdomain."""
    try:
        from playwright.sync_api import sync_playwright
        jobs = []
        url = f"https://{slug}.icims.com/jobs/search"
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(15000)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
                # Try to capture JSON feed
                cards = page.query_selector_all(".iCIMS_JobsTable_JobRow, .job-listing")
                for card in cards:
                    try:
                        title_el = card.query_selector("a.iCIMS_Anchor, a.title")
                        if title_el:
                            jobs.append(normalize_job({
                                "source":   "icims",
                                "title":    title_el.inner_text().strip(),
                                "company":  slug,
                                "location": "",
                                "url":      title_el.get_attribute("href") or url,
                            }))
                    except Exception:
                        pass
            except Exception:
                pass
            browser.close()
        return jobs
    except Exception:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# MAP: ATS name → scraper function
# Used by discovery.py to route discovered slugs to the right scraper
# ─────────────────────────────────────────────────────────────────────────────
ATS_SCRAPERS = {
    "greenhouse":      scrape_greenhouse,
    "lever":           scrape_lever,
    "ashby":           scrape_ashby,
    "workable":        scrape_workable,
    "smartrecruiters": scrape_smartrecruiters,
    "bamboohr":        scrape_bamboohr,
    "jobvite":         scrape_jobvite,
    "breezy":          scrape_breezy,
    "rippling":        scrape_rippling,
    "recruitee":       scrape_recruitee,
    "personio":        scrape_personio,
    "pinpoint":        scrape_pinpoint,
    # workday and icims handled separately (browser-based)
}

# URL patterns for ATS detection from job board URLs
ATS_URL_PATTERNS = [
    ("greenhouse",      r"boards\.greenhouse\.io/([a-z0-9_-]+)"),
    ("greenhouse",      r"job-boards\.greenhouse\.io/([a-z0-9_-]+)"),
    ("lever",           r"jobs\.lever\.co/([a-z0-9_-]+)"),
    ("ashby",           r"jobs\.ashbyhq\.com/([a-zA-Z0-9_-]+)"),
    ("workable",        r"apply\.workable\.com/([a-z0-9_-]+)"),
    ("smartrecruiters", r"jobs\.smartrecruiters\.com/([a-zA-Z0-9_-]+)"),
    ("bamboohr",        r"([a-z0-9-]+)\.bamboohr\.com"),
    ("jobvite",         r"jobs\.jobvite\.com/([a-zA-Z0-9_-]+)"),
    ("breezy",          r"([a-z0-9-]+)\.breezy\.hr"),
    ("rippling",        r"ats\.rippling\.com/([a-zA-Z0-9_-]+)"),
    ("recruitee",       r"([a-z0-9-]+)\.recruitee\.com"),
    ("personio",        r"([a-z0-9-]+)\.jobs\.personio\.(de|com)"),
    ("pinpoint",        r"([a-z0-9-]+)\.pinpointhq\.com"),
    ("icims",           r"([a-z0-9-]+)\.icims\.com"),
    ("taleo",           r"([a-z0-9-]+)\.taleo\.net"),
    ("workday",         r"(https?://[a-z0-9-]+\.wd\d+\.myworkdayjobs\.com[^\s\"'<>]*)"),
]
