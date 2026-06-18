"""
submitter/workday_submit.py — Production Workday form submission

Workday is the most common enterprise ATS (Amazon, Microsoft, Walmart, etc.)
Every Workday instance has the same structure — once we map the form fields,
it works across ALL Workday employers.

Workday form fields (standard across all instances):
  - Full name (split into first/last)
  - Email, phone, address
  - Resume upload (file input)
  - LinkedIn URL, website
  - Work authorization (Yes/No dropdown)
  - Sponsorship required (Yes/No)
  - How did you hear about us
  - Open-ended questions (vary per job)
  - EEO fields (race, gender, veteran, disability)

Workday uses React-rendered forms with specific selectors that are
consistent across all Workday deployments.
"""
import time, os
from utils import log, get_config, get_master_resume
from submitter.form_questions import fill_custom_questions


def submit_workday(job: dict, pdf_path: str | None) -> bool:
    """
    Submits an application to a Workday career page.
    Opens the job's apply URL, fills all fields, uploads resume, submits.
    Returns True if successfully submitted.
    """
    cfg    = get_config()
    resume = get_master_resume()
    profile = cfg["profile"]
    dry_run = cfg.get("dry_run", True)

    apply_url = job.get("url", "")
    if not apply_url or "myworkdayjobs.com" not in apply_url:
        log.debug(f"  [Workday] Not a Workday URL: {apply_url}")
        return False

    if dry_run:
        log.info(f"  [DRY RUN] Would submit to Workday: {job['title']} @ {job['company']}")
        return True

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = ctx.new_page()
            page.set_default_timeout(25000)

            log.info(f"  [Workday] Opening application page...")
            page.goto(apply_url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(2)

            # Click "Apply" button if on job description page
            for apply_sel in ["button[data-automation-id='applyButton']",
                              "a[data-automation-id='applyButton']",
                              "button:has-text('Apply')",
                              "a:has-text('Apply Now')"]:
                try:
                    btn = page.query_selector(apply_sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=15000)
                        time.sleep(2)
                        break
                except Exception:
                    pass

            # ── Fill standard Workday fields ─────────────────────────────────
            name_parts = profile["name"].split(" ", 1)
            first_name = name_parts[0]
            last_name  = name_parts[1] if len(name_parts) > 1 else ""

            _fill(page, "input[data-automation-id='legalNameSection_firstName']", first_name)
            _fill(page, "input[data-automation-id='legalNameSection_lastName']", last_name)
            _fill(page, "input[data-automation-id='email']", profile["email"])
            _fill(page, "input[data-automation-id='phone-number']", profile["phone"])

            # LinkedIn URL
            _fill(page, "input[data-automation-id='linkedInUrl']", profile.get("linkedin",""))

            # Resume upload
            if pdf_path and os.path.exists(pdf_path):
                file_input = page.query_selector("input[type='file']")
                if file_input:
                    file_input.set_input_files(pdf_path)
                    time.sleep(1)
                    log.info(f"  [Workday] Resume uploaded: {pdf_path}")

            # Work authorization
            _select_option(page,
                "select[data-automation-id='countryDropdown']",
                "United States of America"
            )
            _answer_yes_no(page,
                "authorizedToWork",
                "Yes"  # F1/OPT authorized to work in US
            )
            _answer_yes_no(page,
                "requireSponsorship",
                "No" if not profile.get("requires_sponsorship", False) else "Yes"
            )

            # Cover letter if there's a text field for it
            cover = job.get("cover_letter", "")
            if cover:
                _fill(page, "textarea[data-automation-id='coverLetterSection']", cover)

            # AI-powered custom questions (varies per employer)
            fill_custom_questions(page, job)

            # Navigate through multi-page Workday form
            for _ in range(5):  # max 5 "Next" clicks
                next_btn = _find_next_button(page)
                if not next_btn:
                    break
                next_btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=15000)
                time.sleep(2)
                fill_custom_questions(page, job)  # fill any new questions on each page

            # Final submit
            submit_btn = page.query_selector(
                "button[data-automation-id='bottom-navigation-next-button'],"
                "button[data-automation-id='submit'],"
                "button:has-text('Submit')"
            )
            if submit_btn and submit_btn.is_visible():
                submit_btn.click()
                page.wait_for_load_state("domcontentloaded", timeout=20000)
                time.sleep(2)
                log.info(f"  [Workday] ✅ Submitted: {job['title']} @ {job['company']}")
                browser.close()
                return True
            else:
                log.warning(f"  [Workday] Could not find submit button for {job['title']}")
                browser.close()
                return False

    except Exception as e:
        log.warning(f"  [Workday] Submit failed for {job['title']}: {e}")
        return False


def _fill(page, selector: str, value: str):
    if not value:
        return
    try:
        el = page.query_selector(selector)
        if el and el.is_visible():
            el.fill(value)
    except Exception:
        pass


def _select_option(page, selector: str, value: str):
    try:
        el = page.query_selector(selector)
        if el:
            el.select_option(label=value)
    except Exception:
        pass


def _answer_yes_no(page, field_id: str, answer: str):
    """Clicks Yes or No radio button for Workday binary questions."""
    try:
        # Workday uses data-automation-id patterns for radio groups
        options = page.query_selector_all(f"[data-automation-id*='{field_id}']")
        for opt in options:
            label = opt.inner_text().strip() if opt else ""
            if answer.lower() in label.lower():
                opt.click()
                return
    except Exception:
        pass


def _find_next_button(page):
    """Finds the 'Next' / 'Continue' button on a multi-page Workday form."""
    selectors = [
        "button[data-automation-id='bottom-navigation-next-button']",
        "button[data-automation-id='nextButton']",
        "button:has-text('Next')",
        "button:has-text('Continue')",
        "button:has-text('Save and Continue')",
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                label = btn.inner_text().strip().lower()
                if "submit" not in label:  # don't click submit prematurely
                    return btn
        except Exception:
            pass
    return None
