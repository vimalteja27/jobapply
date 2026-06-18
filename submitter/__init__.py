"""
submitter/__init__.py — submits applications via web form (Playwright) or email
Supports: Greenhouse, Lever form auto-fill + generic email apply
"""
import os, time
from utils import log, get_config, get_master_resume, is_dry_run

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
    }

    fn = submitters.get(source, _submit_email)
    return fn(job, pdf_path)


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
