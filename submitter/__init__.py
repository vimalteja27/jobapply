"""
submitter/__init__.py — submits applications via web form (Playwright) or email
Supports: Greenhouse, Lever, Ashby, Workday form auto-fill.
Indeed/Glassdoor jobs are redirect-resolved at submit time and routed to
whichever of the above ATS platforms they actually land on.
BambooHR does NOT have a verified form-fill implementation yet
(see _submit_unsupported below) — jobs from those sources are logged
clearly as skipped rather than silently failing through email.
"""
import os, re, time
from utils import log, get_config, get_master_resume, is_dry_run

# Reuse the existing ATS URL-pattern detector so Indeed/Glassdoor jobs
# (which link to an intermediate URL, not the employer's real application
# page) can be redirect-resolved and routed to the correct submitter below.
from scrapers.discovery import extract_ats

def submit(job: dict, pdf_path: str) -> bool:
    """
    Routes to the correct submission method based on ATS source.
    Returns True if submitted (or dry-run), False if failed.
    """
    source = job.get("source", "unknown")

    if is_dry_run():
        log.info(f"  [DRY RUN] Would submit: {job['title']} @ {job['company']} via {source}")
        return True

    submitters = {
        "greenhouse": _submit_greenhouse,
        "lever":      _submit_lever,
        "ashby":      _submit_ashby,
        "workday":    _submit_workday,
    }

    # Indeed/Glassdoor jobs link to an intermediate URL, not the employer's
    # real application page. Resolve the redirect first, then route to
    # whichever ATS the final destination actually is.
    if source in ("indeed", "glassdoor"):
        resolved = _resolve_redirect_source(job)
        if resolved:
            resolved_source, resolved_url = resolved
            log.info(f"  [{source}->resolved] {job['title']} @ {job['company']} -> {resolved_source}")
            job = {**job, "source": resolved_source, "url": resolved_url}
            source = resolved_source
        else:
            log.warning(
                f"  Could not resolve real application URL for {job['title']} @ "
                f"{job.get('company','')} (source: {source}). This is expected for "
                f"jobs hosted on a fully custom company career site that doesn't "
                f"match any known ATS pattern — those can't be auto-filled generically. "
                f"Job not submitted."
            )
            return False

    if source in ("bamboohr",):
        return _submit_unsupported(job)

    fn = submitters.get(source, _submit_email)
    return fn(job, pdf_path)


# ─────────────────────────────────────────────────────────────────────────────
# Redirect resolution for Indeed/Glassdoor — these link to an intermediate
# URL (e.g. indeed.com/viewjob?jk=...), not the employer's real application
# page. We open the page, click through to the real destination, and check
# if that final URL matches a known ATS pattern.
# ─────────────────────────────────────────────────────────────────────────────
def _resolve_redirect_source(job: dict) -> tuple[str, str] | None:
    """
    Returns (ats_name, real_url) if the job's true application page can be
    found and matches a known ATS, else None.
    """
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(15000)
            try:
                page.goto(job["url"], wait_until="domcontentloaded", timeout=15000)
            except Exception as e:
                log.warning(f"  Redirect resolution goto failed for {job['url']}: {e}")
                browser.close()
                return None

            # Indeed: "Apply on company site" button redirects out.
            # Glassdoor: similarly has an external-apply link for non-Easy-Apply jobs.
            # Selectors below are best-effort — Indeed/Glassdoor change DOM
            # structure periodically, so this is not guaranteed to find the
            # button on every job. If it can't be found, we correctly fall
            # through to returning None rather than guessing.
            external_btn = page.query_selector(
                "a[href*='greenhouse.io'], a[href*='lever.co'], "
                "a[href*='ashbyhq.com'], a[href*='myworkdayjobs.com'], "
                "a[href*='bamboohr.com'], "
                "button:has-text('Apply on company site'), "
                "a:has-text('Apply on company site')"
            )
            real_url = None
            if external_btn:
                href = external_btn.get_attribute("href")
                if href:
                    real_url = href
                else:
                    # It's a button, not a direct link — click and capture
                    # whatever URL the browser lands on afterward.
                    try:
                        with page.expect_navigation(timeout=10000):
                            external_btn.click()
                        real_url = page.url
                    except Exception:
                        real_url = page.url  # best-effort fallback

            browser.close()

            if not real_url:
                return None

            result = extract_ats(real_url)
            if result:
                ats_name, _slug = result
                return (ats_name, real_url)
            return None
    except Exception as e:
        log.warning(f"  Redirect resolution error for {job.get('title','')}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Workday form submission — delegates to workday_submit.py
# ─────────────────────────────────────────────────────────────────────────────
def _submit_workday(job: dict, pdf_path: str) -> bool:
    from submitter.workday_submit import submit_workday
    return submit_workday(job, pdf_path)


# ─────────────────────────────────────────────────────────────────────────────
# Explicitly unsupported platforms — fail LOUDLY and clearly, not silently
# through a broken email fallback. BambooHR has no confirmed public applicant-
# facing selector set verified yet — needs a live posting URL to inspect first.
# Workday is now supported above.
# ─────────────────────────────────────────────────────────────────────────────
def _submit_unsupported(job: dict) -> bool:
    log.warning(
        f"  Skipped (no verified form-fill yet): {job['title']} @ {job.get('company','')} "
        f"via {job.get('source','')}. BambooHR auto-fill is not yet built — "
        f"this job was found but NOT submitted. (Workday is now supported.)"
    )
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Greenhouse form auto-fill
# ─────────────────────────────────────────────────────────────────────────────
def _submit_greenhouse(job: dict, pdf_path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
        cfg = get_config()
        p_cfg = cfg["profile"]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(20000)
            try:
                page.goto(job["url"], wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                log.warning(f"  goto timeout for {job['url']}: {e}")
            time.sleep(2)

            # Standard Greenhouse field selectors
            _fill_if_exists(page, "#first_name",         p_cfg["name"].split()[0])
            _fill_if_exists(page, "#last_name",          " ".join(p_cfg["name"].split()[1:]))
            _fill_if_exists(page, "#email",              p_cfg["email"])
            _fill_if_exists(page, "#phone",              p_cfg["phone"])
            _fill_if_exists(page, "#resume_text",        job.get("cover_letter", ""))

            # Upload resume PDF
            resume_input = page.query_selector("input[type='file'][name*='resume'], #resume")
            if resume_input and pdf_path:
                resume_input.set_input_files(pdf_path)
                time.sleep(1)

            # Cover letter text area
            _fill_if_exists(page, "#cover_letter_text", job.get("cover_letter", ""))

            # AI-powered custom screening questions
            from submitter.form_questions import fill_custom_questions
            fill_custom_questions(page, job)

            # Submit
            submit_btn = page.query_selector("input[type='submit'], button[type='submit']")
            if submit_btn:
                submit_btn.click()
                page.wait_for_load_state("load", timeout=15000)
                log.info(f"  Submitted (Greenhouse): {job['title']} @ {job['company']}")
            browser.close()
        return True
    except Exception as e:
        log.warning(f"Greenhouse submit failed for {job['title']}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Lever form auto-fill
# ─────────────────────────────────────────────────────────────────────────────
def _submit_lever(job: dict, pdf_path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
        cfg = get_config()
        p_cfg = cfg["profile"]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(20000)
            try:
                page.goto(job["url"], wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                log.warning(f"  goto timeout for {job['url']}: {e}")
            time.sleep(2)

            _fill_if_exists(page, "input[name='name']",  p_cfg["name"])
            _fill_if_exists(page, "input[name='email']", p_cfg["email"])
            _fill_if_exists(page, "input[name='phone']", p_cfg["phone"])
            _fill_if_exists(page, "input[name='org']",   "")  # current company

            # Resume file upload
            file_input = page.query_selector("input[type='file']")
            if file_input and pdf_path:
                file_input.set_input_files(pdf_path)
                time.sleep(1)

            # Cover letter
            _fill_if_exists(page, "textarea[name='comments']", job.get("cover_letter", ""))

            # AI-powered custom screening questions
            from submitter.form_questions import fill_custom_questions
            fill_custom_questions(page, job)

            submit_btn = page.query_selector("button[type='submit'], .lever-button-primary")
            if submit_btn:
                submit_btn.click()
                page.wait_for_load_state("load", timeout=15000)
                log.info(f"  Submitted (Lever): {job['title']} @ {job['company']}")
            browser.close()
        return True
    except Exception as e:
        log.warning(f"Lever submit failed for {job['title']}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Ashby form auto-fill
#
# CONFIDENCE NOTE: Ashby's underlying field schema (confirmed from their
# public API docs) uses path names _systemfield_name, _systemfield_email,
# _systemfield_resume — these are stable across every company on Ashby.
# However, the RENDERED HTML on the live application page may use different
# attribute names (data-* attributes, generated IDs, etc.) than the schema
# path. The selectors below use multiple fallback strategies (name, id,
# placeholder, aria-label) to maximize the chance of matching the real DOM,
# but unlike Greenhouse/Lever this has not been confirmed against a live
# Ashby job posting. Watch the logs after the first few real Ashby
# submissions to confirm fields are actually being filled correctly.
# ─────────────────────────────────────────────────────────────────────────────
def _submit_ashby(job: dict, pdf_path: str) -> bool:
    try:
        from playwright.sync_api import sync_playwright
        cfg = get_config()
        p_cfg = cfg["profile"]

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(20000)
            try:
                page.goto(job["url"], wait_until="domcontentloaded", timeout=20000)
            except Exception as e:
                log.warning(f"  goto timeout for {job['url']}: {e}")
            time.sleep(2)

            # Multiple fallback selectors per field, since the exact rendered
            # attribute name is not independently confirmed (see note above).
            _fill_first_match(page, [
                "input[name='_systemfield_name']", "input[id*='name']",
                "input[placeholder='Full Name']", "input[aria-label*='Name']",
            ], p_cfg["name"])
            _fill_first_match(page, [
                "input[name='_systemfield_email']", "input[type='email']",
                "input[id*='email']", "input[aria-label*='Email']",
            ], p_cfg["email"])
            _fill_first_match(page, [
                "input[name='_systemfield_phone']", "input[type='tel']",
                "input[id*='phone']", "input[aria-label*='Phone']",
            ], p_cfg["phone"])

            # Resume file upload
            file_input = page.query_selector("input[type='file']")
            if file_input and pdf_path:
                file_input.set_input_files(pdf_path)
                time.sleep(1)

            # AI-powered custom screening questions
            from submitter.form_questions import fill_custom_questions
            fill_custom_questions(page, job)

            submit_btn = page.query_selector(
                "button[type='submit'], button:has-text('Submit Application'), "
                "button:has-text('Submit')"
            )
            if submit_btn:
                submit_btn.click()
                page.wait_for_load_state("load", timeout=15000)
                log.info(f"  Submitted (Ashby): {job['title']} @ {job['company']}")
            else:
                log.warning(
                    f"  Ashby submit button not found for {job['title']} @ "
                    f"{job.get('company','')} — form may not have been submitted "
                    f"even though fields were filled. Verify manually if this "
                    f"happens repeatedly."
                )
                browser.close()
                return False
            browser.close()
        return True
    except Exception as e:
        log.warning(f"Ashby submit failed for {job['title']}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Email fallback — for platforms without form auto-fill

# ─────────────────────────────────────────────────────────────────────────────
def _submit_email(job: dict, pdf_path: str) -> bool:
    # Check required Gmail OAuth env vars up front with a clear message —
    # this fallback path is not wired up by default in the GitHub Actions
    # workflow (only GROQ_API_KEY, GMAIL_APP_PASSWORD, GSHEET_CREDENTIALS_JSON
    # are passed), so missing-credential failures here are expected unless
    # email-fallback submission has been explicitly set up.
    missing = [v for v in ("GMAIL_CLIENT_ID", "GMAIL_CLIENT_SECRET", "GMAIL_REFRESH_TOKEN")
               if not os.environ.get(v)]
    if missing:
        log.warning(
            f"Email submit skipped for {job['title']} @ {job.get('company','')}: "
            f"missing {', '.join(missing)}. Email-fallback submission requires "
            f"Gmail OAuth secrets (separate from GMAIL_APP_PASSWORD used for "
            f"notifications) — not configured. This job was not submitted."
        )
        return False

    try:
        import base64
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        from email.mime.application import MIMEApplication
        from googleapiclient.discovery import build
        from google.oauth2.credentials import Credentials

        cfg = get_config()
        creds = Credentials.from_authorized_user_info({
            "client_id":     os.environ["GMAIL_CLIENT_ID"],
            "client_secret": os.environ["GMAIL_CLIENT_SECRET"],
            "refresh_token": os.environ["GMAIL_REFRESH_TOKEN"],
        }, scopes=["https://www.googleapis.com/auth/gmail.send"])

        service = build("gmail", "v1", credentials=creds)

        msg = MIMEMultipart()
        msg["From"]    = cfg["profile"]["email"]
        msg["To"]      = f"careers@{job.get('company','').lower().replace(' ','')}.com"
        msg["Subject"] = f"Application — {job['title']} | {cfg['profile']['name']}"

        body = f"Dear Hiring Team,\n\n{job.get('cover_letter', '')}\n\nBest regards,\n{cfg['profile']['name']}\n{cfg['profile']['phone']}\n{cfg['profile']['linkedin']}"
        msg.attach(MIMEText(body, "plain"))

        if pdf_path:
            with open(pdf_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=f"Resume_{cfg['profile']['name'].replace(' ','_')}.pdf")
            part["Content-Disposition"] = f'attachment; filename="Resume_{cfg["profile"]["name"].replace(" ","_")}.pdf"'
            msg.attach(part)

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()
        log.info(f"  Submitted (email): {job['title']} @ {job['company']}")
        return True
    except Exception as e:
        log.warning(f"Email submit failed for {job['title']}: {e}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────────────────────────────────────
def _fill_if_exists(page, selector: str, value: str):
    try:
        el = page.query_selector(selector)
        if el:
            el.fill(value)
    except Exception:
        pass


def _fill_first_match(page, selectors: list[str], value: str) -> bool:
    """
    Tries each selector in order, fills the first one found, then stops.
    Used where the exact rendered DOM attribute name isn't independently
    confirmed (e.g. Ashby) and several plausible selectors need to be tried.
    Returns True if a field was actually filled, False if none matched.
    """
    for selector in selectors:
        try:
            el = page.query_selector(selector)
            if el:
                el.fill(value)
                return True
        except Exception:
            continue
    return False

