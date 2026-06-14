"""
scrapers/__init__.py — all ATS scrapers + router
Tier 1: Pure HTTP JSON APIs  (Greenhouse, Lever, Ashby, SmartRecruiters, Workable)
Tier 2: XHR interception     (Workday, iCIMS, Taleo, SuccessFactors)
Tier 3: Playwright DOM       (BambooHR, Jobvite, JazzHR, BreezyHR, Teamtailor, Rippling + fallback)
Tier 4: JobSpy library       (LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter)
"""
import time, requests
from utils import log, normalize_job, get_config

# ─────────────────────────────────────────────────────────────────────────────
# ATS URL detector
# ─────────────────────────────────────────────────────────────────────────────
ATS_PATTERNS = {
    "greenhouse":      ["boards.greenhouse.io", "greenhouse.io/jobs"],
    "lever":           ["jobs.lever.co", "lever.co/"],
    "ashby":           ["jobs.ashbyhq.com", "ashbyhq.com"],
    "smartrecruiters": ["smartrecruiters.com"],
    "workable":        ["apply.workable.com", "jobs.workable.com"],
    "workday":         ["myworkdayjobs.com", "workday.com"],
    "icims":           ["icims.com"],
    "taleo":           ["taleo.net"],
    "successfactors":  ["successfactors.com", "sapsf.com"],
    "bamboohr":        ["bamboohr.com"],
    "jobvite":         ["jobs.jobvite.com"],
    "jazzhr":          ["app.jazz.co"],
    "breezyhr":        ["breezy.hr"],
    "teamtailor":      ["teamtailor.com"],
    "rippling":        ["ats.rippling.com"],
    "personio":        ["jobs.personio.com"],
    "pinpoint":        ["pinpointhq.com"],
}

def detect_ats(url: str) -> str:
    url_lower = url.lower()
    for ats, patterns in ATS_PATTERNS.items():
        if any(p in url_lower for p in patterns):
            return ats
    return "unknown"

# ─────────────────────────────────────────────────────────────────────────────
# TIER 1 — Pure HTTP JSON APIs
# ─────────────────────────────────────────────────────────────────────────────
def scrape_greenhouse(token: str) -> list[dict]:
    try:
        url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        jobs = r.json().get("jobs", [])
        return [normalize_job({
            "source": "greenhouse", "company": token,
            "id": str(j["id"]), "title": j["title"],
            "location": j.get("location", {}).get("name", ""),
            "url": j["absolute_url"],
            "description": j.get("content", ""),
            "posted_at": j.get("updated_at", "")
        }) for j in jobs]
    except Exception as e:
        log.warning(f"[Greenhouse] {token}: {e}")
        return []


def scrape_lever(company: str) -> list[dict]:
    try:
        url = f"https://api.lever.co/v0/postings/{company}?mode=json&limit=500"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        jobs = r.json() if isinstance(r.json(), list) else []
        return [normalize_job({
            "source": "lever", "company": company,
            "id": j["id"], "title": j["text"],
            "location": j.get("categories", {}).get("location", ""),
            "url": j["hostedUrl"],
            "description": j.get("descriptionPlain", ""),
            "posted_at": str(j.get("createdAt", ""))
        }) for j in jobs]
    except Exception as e:
        log.warning(f"[Lever] {company}: {e}")
        return []


def scrape_ashby(company: str) -> list[dict]:
    try:
        payload = {
            "operationName": "ApiJobBoardWithTeams",
            "variables": {"organizationHostedJobsPageName": company},
            "query": """query ApiJobBoardWithTeams($organizationHostedJobsPageName: String!) {
                jobBoard: jobBoardWithTeams(organizationHostedJobsPageName: $organizationHostedJobsPageName) {
                    jobPostings { id title locationName employmentType isRemote externalLink publishedDate }
                }
            }"""
        }
        r = requests.post("https://jobs.ashbyhq.com/api/non-user-graphql", json=payload, timeout=15)
        postings = r.json().get("data", {}).get("jobBoard", {}).get("jobPostings", [])
        return [normalize_job({
            "source": "ashby", "company": company,
            "id": j["id"], "title": j["title"],
            "location": j.get("locationName", ""),
            "url": j.get("externalLink") or f"https://jobs.ashbyhq.com/{company}/{j['id']}",
            "posted_at": j.get("publishedDate", "")
        }) for j in postings]
    except Exception as e:
        log.warning(f"[Ashby] {company}: {e}")
        return []


def scrape_smartrecruiters(company: str) -> list[dict]:
    try:
        url = f"https://api.smartrecruiters.com/v1/companies/{company}/postings?limit=100"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        jobs = r.json().get("content", [])
        return [normalize_job({
            "source": "smartrecruiters", "company": company,
            "id": j["id"], "title": j["name"],
            "location": j.get("location", {}).get("city", ""),
            "url": f"https://jobs.smartrecruiters.com/{company}/{j['id']}",
            "posted_at": j.get("releasedDate", "")
        }) for j in jobs]
    except Exception as e:
        log.warning(f"[SmartRecruiters] {company}: {e}")
        return []


def scrape_workable(company: str) -> list[dict]:
    try:
        url = f"https://apply.workable.com/api/v3/accounts/{company}/jobs"
        r = requests.post(url, json={"query": "", "location": [], "department": []}, timeout=15)
        jobs = r.json().get("results", [])
        return [normalize_job({
            "source": "workable", "company": company,
            "id": j["shortcode"], "title": j["title"],
            "location": j.get("location", {}).get("location_str", ""),
            "url": f"https://apply.workable.com/{company}/j/{j['shortcode']}/",
            "posted_at": j.get("published_on", "")
        }) for j in jobs]
    except Exception as e:
        log.warning(f"[Workable] {company}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# TIER 2 — XHR Interception via Playwright
# ─────────────────────────────────────────────────────────────────────────────
def _xhr_scrape(url: str, pattern: str, data_key: str, source: str) -> list:
    """
    Loads a page and captures XHR responses matching `pattern`.

    Fixes applied:
    - resp.json() guarded: Workday returns HTML error pages on some endpoints;
      calling .json() on non-JSON content raises an exception in the callback
      thread (asyncio.CancelledError chain seen in traceback). Now checks
      Content-Type before calling .json().
    - Browser closed AFTER off-loading callback: previously browser.close()
      could fire while a pending XHR callback was still awaiting resp.body(),
      causing TargetClosedError. Now we remove the listener before closing.
    - goto errors are caught and logged; scrape still proceeds with whatever
      XHR responses were captured before the timeout.
    """
    try:
        from playwright.sync_api import sync_playwright
        captured = []
        done = False  # guard: ignore callbacks after we start closing

        def on_response(resp):
            if done:
                return
            if pattern not in resp.url:
                return
            try:
                # Only attempt JSON parse if content-type looks like JSON
                ct = resp.headers.get("content-type", "")
                if "json" not in ct and "javascript" not in ct:
                    return
                d = resp.json()
                chunk = d.get(data_key, [])
                if isinstance(chunk, list):
                    captured.extend(chunk)
            except Exception:
                pass  # silently ignore parse errors, HTML pages, closed connections

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(20000)
            page.on("response", on_response)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                # Timeout is common on Workday — still wait for XHRs that fired
                log.debug(f"[{source}] goto timeout for {url}: {type(e).__name__}")
            # Wait for XHR responses to complete
            time.sleep(6)
            # Signal callback to stop, then close cleanly
            done = True
            page.remove_listener("response", on_response)
            try:
                browser.close()
            except Exception:
                pass
        return captured
    except Exception as e:
        log.warning(f"[{source}] XHR scrape failed for {url}: {e}")
        return []


def scrape_workday(url: str) -> list[dict]:
    raw = _xhr_scrape(url, "wday/cxs", "jobPostings", "Workday")
    if not raw:
        return []
    # Extract company name from URL: https://amazon.wd5.myworkdayjobs.com/...
    try:
        company = url.split("//")[-1].split(".wd")[0]
    except Exception:
        company = "Unknown"
    # Base URL for building full job links
    try:
        base = url.split(".myworkdayjobs.com")[0] + ".myworkdayjobs.com"
    except Exception:
        base = url
    jobs = []
    for j in raw:
        try:
            jobs.append(normalize_job({
                "source":    "workday",
                "company":   company,
                "id":        j.get("bulletFields", [""])[0] if j.get("bulletFields") else "",
                "title":     j.get("title", ""),
                "location":  j.get("locationsText", ""),
                "url":       base + j.get("externalPath", "") if j.get("externalPath") else url,
                "posted_at": j.get("postedOn", ""),
                "description": j.get("jobDescription", ""),
            }))
        except Exception:
            continue
    return jobs


def scrape_icims(url: str) -> list[dict]:
    raw = _xhr_scrape(url, "/sites/", "items", "iCIMS")
    return [normalize_job({
        "source": "icims",
        "title": j.get("jobtitle", j.get("title", "")),
        "location": j.get("joblocation", {}).get("value", "") if isinstance(j.get("joblocation"), dict) else "",
        "url": j.get("url", ""),
        "description": j.get("jobdescription", ""),
        "id": str(j.get("id", ""))
    }) for j in raw]


def scrape_taleo(url: str) -> list[dict]:
    raw = _xhr_scrape(url, "cf?caller", "requisitionList", "Taleo")
    return [normalize_job({
        "source": "taleo",
        "title": j.get("jobTitle", ""),
        "location": f"{j.get('city', '')}, {j.get('stateProvince', '')}",
        "url": url + f"?job={j.get('contestNumber', '')}",
        "description": j.get("externalJobDescription", ""),
        "id": str(j.get("contestNumber", ""))
    }) for j in raw]


# ─────────────────────────────────────────────────────────────────────────────
# TIER 3 — Playwright DOM scraping (JS-rendered career pages)
# ─────────────────────────────────────────────────────────────────────────────
DOM_SELECTORS = {
    "bamboohr":   {"card": ".BambooHR-ATS-Jobs-Item",  "title": "a",   "location": ".BambooHR-ATS-Department-Item"},
    "jobvite":    {"card": ".jv-job-list-name",         "title": "a",   "location": ".jv-job-list-data"},
    "jazzhr":     {"card": ".job",                       "title": "h3 a","location": ".location"},
    "breezyhr":   {"card": "li.position",                "title": "h2",  "location": ".location"},
    "teamtailor": {"card": "[data-job-id]",              "title": "h2",  "location": ".job-location"},
    "rippling":   {"card": "[data-testid='job-posting']","title": "h3",  "location": "[data-testid='job-location']"},
    "personio":   {"card": ".job-box",                   "title": "h3",  "location": ".job-box__location"},
}

GENERIC_SELECTORS = {
    "card":     "[class*='job-card'], [class*='job-item'], [class*='JobCard'], [data-job-id], [data-testid*='job']",
    "title":    "h2, h3, [class*='title'], a[href*='job']",
    "location": "[class*='location'], [class*='Location'], [class*='city']"
}

def scrape_dom(url: str, ats_hint: str = "unknown") -> list[dict]:
    try:
        from playwright.sync_api import sync_playwright
        sel = DOM_SELECTORS.get(ats_hint, GENERIC_SELECTORS)
        jobs = []
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ))
            page = ctx.new_page()
            page.set_default_timeout(20000)
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                log.warning(f"[DOM:{ats_hint}] goto timeout for {url}: {e}")
            time.sleep(3)

            # Scroll to trigger lazy load
            for _ in range(5):
                page.keyboard.press("End")
                time.sleep(1.2)

            # Click "load more" if present
            for phrase in ["Load more", "Show more", "View all jobs", "See all"]:
                try:
                    btn = page.get_by_text(phrase, exact=False)
                    if btn.count() > 0:
                        btn.first.click()
                        page.wait_for_load_state("load", timeout=8000)
                except Exception:
                    pass

            cards = page.query_selector_all(sel["card"])
            for card in cards:
                try:
                    t = card.query_selector(sel["title"])
                    l = card.query_selector(sel["location"])
                    a = card.query_selector("a")
                    href = a.get_attribute("href") if a else ""
                    full_url = href if (href or "").startswith("http") else url.rstrip("/") + "/" + (href or "").lstrip("/")
                    jobs.append(normalize_job({
                        "source": ats_hint, "title": t.inner_text().strip() if t else "",
                        "location": l.inner_text().strip() if l else "",
                        "url": full_url, "id": href or ""
                    }))
                except Exception:
                    continue
            browser.close()
        return jobs
    except Exception as e:
        log.warning(f"[DOM:{ats_hint}] {url}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# TIER 4 — JobSpy (LinkedIn, Indeed, Glassdoor, Google Jobs, ZipRecruiter)
# ─────────────────────────────────────────────────────────────────────────────
def scrape_jobboards(role: str, location: str = "United States", hours_old: int = 48) -> list[dict]:
    try:
        from jobspy import scrape_jobs
        cfg = get_config()
        sites = cfg["ats_targets"]["jobboards"]["sites"]
        df = scrape_jobs(
            site_name=sites,
            search_term=role,
            google_search_term=f"{role} jobs in {location} since 2 days ago",
            location=location,
            results_wanted=100,
            hours_old=hours_old,
            country_indeed="USA",
            linkedin_fetch_description=True,
        )
        return [normalize_job({
            "source": row.get("site", ""),
            "title": row.get("title", ""),
            "company": row.get("company", ""),
            "location": row.get("location", ""),
            "url": row.get("job_url", ""),
            "description": row.get("description", "") or "",
            "id": str(row.get("id", "")),
            "salary_min": row.get("min_amount"),
            "salary_max": row.get("max_amount"),
        }) for _, row in df.iterrows()]
    except Exception as e:
        log.warning(f"[JobSpy] {role}: {e}")
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Master router — call this to scrape any URL
# ─────────────────────────────────────────────────────────────────────────────
def scrape_any(url: str) -> list[dict]:
    ats = detect_ats(url)
    log.info(f"  [{ats.upper()}] {url}")
    dispatch = {
        "greenhouse":      lambda: scrape_greenhouse(url.split("greenhouse.io/")[-1].split("/")[0]),
        "lever":           lambda: scrape_lever(url.split("lever.co/")[-1].split("/")[0]),
        "ashby":           lambda: scrape_ashby(url.split("ashbyhq.com/")[-1].split("/")[0]),
        "smartrecruiters": lambda: scrape_smartrecruiters(url.split("smartrecruiters.com/")[-1].split("/")[0]),
        "workable":        lambda: scrape_workable(url.split("workable.com/")[-1].split("/")[0]),
        "workday":         lambda: scrape_workday(url),
        "icims":           lambda: scrape_icims(url),
        "taleo":           lambda: scrape_taleo(url),
    }
    fn = dispatch.get(ats, lambda: scrape_dom(url, ats))
    return fn()
