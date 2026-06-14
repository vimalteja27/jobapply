"""
tracker/__init__.py — logs every application to Google Sheets + sends daily digest email
"""
import os
from datetime import datetime
from utils import log, get_config

SHEET_HEADERS = [
    "Date", "Company", "Role", "Location", "Source",
    "Fit Score", "H1B Status", "H1B Category",
    "ATS Keywords", "URL", "PDF Path", "Status", "Notes"
]


def _get_sheet():
    import gspread
    from google.oauth2.service_account import Credentials
    import json

    creds_json = os.environ.get("GSHEET_CREDENTIALS_JSON")
    if creds_json:
        creds_dict = json.loads(creds_json)
        creds = Credentials.from_service_account_info(
            creds_dict,
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"]
        )
    else:
        creds = Credentials.from_service_account_file(
            "credentials.json",
            scopes=["https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive"]
        )

    gc = gspread.authorize(creds)
    cfg = get_config()
    sheet_name = cfg["tracking"]["sheet_name"]
    try:
        sh = gc.open(sheet_name).sheet1
    except Exception:
        sh = gc.create(sheet_name).sheet1
        sh.append_row(SHEET_HEADERS)
    return sh


def log_application(job: dict, pdf_path: str | None, submitted: bool):
    """Appends one row to Google Sheets for a processed job."""
    try:
        from h1b_lookup import lookup_h1b_history, get_h1b_label
        sheet = _get_sheet()
        status       = "Applied" if submitted else "Dry Run"
        h1b_full     = job.get("h1b_history") or lookup_h1b_history(job.get("company",""))
        h1b_category = get_h1b_label(job.get("company",""))  # "H1B Sponsor" / "Cap-Exempt" / "No Record"
        row = [
            datetime.now().strftime("%Y-%m-%d %H:%M"),
            job.get("company", ""),
            job.get("title", ""),
            job.get("location", ""),
            job.get("source", ""),
            job.get("fit_score", ""),
            h1b_full,        # Full status with emoji
            h1b_category,    # Short category for filtering in Sheets
            ", ".join(job.get("ats_keywords", [])),
            job.get("url", ""),
            pdf_path or "",
            status,
            job.get("fit_reasoning", "")
        ]
        sheet.append_row(row)
        log.info(f"  Logged: {job['title']} @ {job['company']} | {h1b_full}")
    except Exception as e:
        if "credentials.json" in str(e) or "No such file" in str(e):
            log.warning(
                "Sheets logging skipped: credentials.json not found. "
                "This is expected until Google Sheets is set up — see README "
                "Step 3. Applications are still processed; only the Sheet log is skipped."
            )
        else:
            log.warning(f"Sheets logging failed: {e}")


def send_run_notification(results: list[dict]):
    """
    Sends a concise email after each run using Gmail App Password (SMTP).

    Setup — 2 minutes, no Google Cloud needed:
      1. Go to myaccount.google.com/security
      2. Enable 2-Step Verification (if not already on)
      3. Go to myaccount.google.com/apppasswords
      4. App name: "ApplyRyt" → Create
      5. Copy the 16-character password shown
      6. Add as GitHub secret: GMAIL_APP_PASSWORD

    That's it. One secret, works immediately.
    """
    import smtplib
    from email.mime.text import MIMEText

    cfg     = get_config()
    dry_run = cfg.get("dry_run", True)
    applied = [r for r in results if r.get("submitted")]
    skipped = [r for r in results if not r.get("submitted")]

    if not applied:
        log.info("  No applications this run — skipping email notification")
        return

    # Get credentials — App Password only (no OAuth complexity)
    app_password = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not app_password:
        log.warning(
            "Email skipped: GMAIL_APP_PASSWORD not set. "
            "Get one at myaccount.google.com/apppasswords → add as GitHub secret."
        )
        return

    sender = cfg["profile"]["email"]
    recipient = cfg["tracking"]["notify_email"]
    now_str = datetime.now().strftime("%b %d, %Y %I:%M %p UTC")
    action  = "Dry-run logged" if dry_run else "Applied"

    # H1B breakdown
    from collections import Counter
    h1b_counts = Counter(j.get("h1b_history","❓ No H1B Record") for j in applied)

    # Build email body
    lines = [
        f"{'[DRY RUN] ' if dry_run else ''}ApplyRyt Run Summary — {now_str}",
        "=" * 55,
        "",
        f"{action}: {len(applied)} jobs  |  Skipped: {len(skipped)}",
        "",
        "H1B SPONSORSHIP BREAKDOWN:",
        f"  ✅ H1B Sponsor       {h1b_counts.get('✅ H1B Sponsor', 0)} jobs",
        f"  🎓 Cap-Exempt        {h1b_counts.get('🎓 H1B Exempt (Cap-Free)', 0)} jobs",
        f"  ❓ No Record         {h1b_counts.get('❓ No H1B Record', 0)} jobs",
        "",
        "JOBS APPLIED (sorted by fit score):",
        "-" * 55,
    ]
    top_jobs = sorted(applied, key=lambda x: x.get("fit_score", 0), reverse=True)
    for j in top_jobs:
        h1b = j.get("h1b_history", "❓ No H1B Record")
        tag = "✅" if "Sponsor" in h1b else ("🎓" if "Exempt" in h1b else "❓")
        lines.append(
            f"{tag} {j.get('fit_score','?')}/10  {j['title']} @ {j['company']}"
        )
        lines.append(f"   Source: {j.get('source','')}  |  {h1b}")
        lines.append(f"   {j.get('url', '')}")
        lines.append("")
    lines += [
        "-" * 55,
        "View all: Google Sheets → ApplyRyt Applications",
        "",
        "Legend:",
        "  ✅ H1B Sponsor  = proven H1B filer, likely to sponsor",
        "  🎓 Cap-Exempt   = university/hospital/nonprofit (NO LOTTERY, best path)",
        "  ❓ No Record    = not in USCIS data, may still sponsor",
        "",
        "To pause: set dry_run: true in config.yaml → push to GitHub",
    ]

    subject = (
        f"{'[DRY RUN] ' if dry_run else ''}ApplyRyt: {len(applied)} jobs "
        f"{'logged' if dry_run else 'applied'} — {datetime.now().strftime('%b %d %I:%M%p')}"
    )

    try:
        msg = MIMEText("\n".join(lines), "plain")
        msg["From"]    = sender
        msg["To"]      = recipient
        msg["Subject"] = subject

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender, app_password)
            server.sendmail(sender, recipient, msg.as_string())

        log.info(f"Run notification sent to {recipient}")

    except smtplib.SMTPAuthenticationError:
        log.warning(
            "Email failed: Gmail authentication error. "
            "Make sure GMAIL_APP_PASSWORD is correct and 2-Step Verification is enabled. "
            "Get a new App Password at myaccount.google.com/apppasswords"
        )
    except Exception as e:
        log.warning(f"Email notification failed: {e}")


# Alias for backward compatibility
send_daily_digest = send_run_notification
