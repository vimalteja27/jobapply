"""
scrapers/glassdoor.py — Direct Playwright Glassdoor scraper

WHY THIS EXISTS:
  JobSpy's Glassdoor module is broken (confirmed open GitHub issue,
  speedyapply/JobSpy#270) — returns 400 "location not parsed" / 403
  for most/all locations as of mid-2026. Glassdoor uses DataDome
  anti-bot protection, which JobSpy's lightweight requests-based
  approach can no longer bypass.

THIS SCRAPER:
  - Uses Playwright with a real browser context (more likely to pass
    DataDome than raw HTTP requests)
  - Hits the public search URL: glassdoor.com/Job/jobs.htm?sc.keyword=...
  - DOM-scrapes job cards directly (title, company, location, link)
  - NO location_id lookup needed — keyword + location text in the URL

RELIABILITY: This is the MOST FRAGILE scraper in the system.
  - Glassdoor actively blocks automated browsers with DataDome
  - May return 0 results, a CAPTCHA page, or work fine — varies by run
  - Failure here NEVER blocks the rest of the pipeline (wrapped in try/except)
  - If this consistently returns 0, Indeed + Google Jobs (which often
    mirror Glassdoor's own listings) still provide equivalent coverage
"""
import time, re
from utils import log, normalize_job, get_config


def scrape_glassdoor(role: str, retries: int = 2) -> list[dict]:
    """
    Searches Glassdoor for full-time US jobs matching `role`,
    anchored to the configured location.
    Returns a list of normalized job dicts. Returns [] on any failure.

    Retries up to `retries` times — DataDome blocks can be intermittent,
    so a second attempt sometimes succeeds where the first didn't.
    """
    for attempt in range(1, retries + 1):
        jobs = _scrape_glassdoor_once(role, attempt, retries)
        if jobs:
            return jobs
        if attempt < retries:
            time.sleep(4)
    return []


def _scrape_glassdoor_once(role: str, attempt: int, total: int) -> list[dict]:
    cfg = get_config()
    location = cfg["search"]["location"]

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log.warning("[Glassdoor] Playwright not installed — skipping")
        return []

    jobs = []
    url = (
        "https://www.glassdoor.com/Job/jobs.htm"
        f"?sc.keyword={role.replace(' ', '+')}"
        f"&locT=C&locKeyword={location.replace(' ', '+').replace(',', '%2C')}"
        f"&jobType=fulltime"
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--disable-blink-features=AutomationControlled",
            ])
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
                locale="en-US",
            )
            page = ctx.new_page()
            page.set_default_timeout(20000)
            log.info(f"  [Glassdoor] Loading search page (attempt {attempt}/{total})...")
            page.goto(url, wait_until="domcontentloaded", timeout=20000)

            # Dismiss cookie/signup modals if present
            for sel in ["button[alt='Close']", "[aria-label='Close']",
                        "button:has-text('Close')"]:
                try:
                    btn = page.query_selector(sel)
                    if btn:
                        btn.click(timeout=2000)
                        time.sleep(0.5)
                except Exception:
                    pass

            # Wait for job cards to render
            try:
                page.wait_for_selector("[data-test='jobListing'], li.JobsList_jobListItem__wjTHv, .react-job-listing",
                                       timeout=15000)
            except Exception:
                # Likely hit a CAPTCHA / blocked page
                title = page.title()
                log.warning(f"[Glassdoor] No job cards found on attempt {attempt}/{total} "
                            f"(page title: '{title}') — likely blocked by anti-bot.")
                browser.close()
                return []

            # Scroll to load more
            for _ in range(3):
                page.keyboard.press("End")
                time.sleep(1.2)

            cards = page.query_selector_all(
                "[data-test='jobListing'], li.JobsList_jobListItem__wjTHv, .react-job-listing"
            )

            for card in cards:
                try:
                    title_el   = card.query_selector(
                        "[data-test='job-title'], .JobCard_jobTitle__rbjTE, a[data-test='job-link']"
                    )
                    company_el = card.query_selector(
                        "[data-test='employer-name'], .EmployerProfile_compactEmployerName__9MGcV"
                    )
                    location_el = card.query_selector(
                        "[data-test='emp-location'], .JobCard_location__Ds1fM"
                    )
                    link_el = card.query_selector("a[data-test='job-link'], a.JobCard_trackingLink__HMyun")

                    title    = title_el.inner_text().strip() if title_el else ""
                    company  = company_el.inner_text().strip() if company_el else ""
                    loc_text = location_el.inner_text().strip() if location_el else ""
                    href     = link_el.get_attribute("href") if link_el else ""
                    full_url = href if (href or "").startswith("http") else f"https://www.glassdoor.com{href}" if href else ""

                    # Click the card to load description in the right-panel
                    description = ""
                    try:
                        card.click(timeout=3000)
                        time.sleep(1)
                        desc_el = page.query_selector(
                            "[class*='JobDetails_jobDescription'], "
                            "[data-test='jobDescription'], "
                            ".jobDescriptionContent, "
                            "[id*='JobDescription']"
                        )
                        if desc_el:
                            description = desc_el.inner_text().strip()[:3000]
                    except Exception:
                        pass

                    if title:
                        jobs.append(normalize_job({
                            "source":      "glassdoor",
                            "title":       title,
                            "company":     company,
                            "location":    loc_text,
                            "url":         full_url,
                            "id":          href or "",
                            "description": description,
                        }))
                except Exception:
                    continue

            browser.close()

    except Exception as e:
        log.warning(f"[Glassdoor] Scrape failed: {e}")
        return []

    log.info(f"  [Glassdoor] {len(jobs)} jobs for '{role}'")
    return jobs
