"""
inbox/__init__.py — Reply tracking and inbox routing

Like Tsenta's "04 · track" — monitors your Gmail inbox for recruiter emails,
matches them to applications in the tracker, and updates status automatically.

HOW IT WORKS:
  1. Poll Gmail inbox for new emails from recruiters
  2. Match email to application by company name / job title
  3. Classify email: viewed / replied / interview / rejected / offer
  4. Update Google Sheets status column
  5. Send you a notification for each status change

SETUP:
  Requires GMAIL_APP_PASSWORD set as environment variable.
  Reads emails via IMAP (gmail, outlook, any email provider).
"""
import os, re, imaplib, email, time
from datetime import datetime, timedelta
from email.header import decode_header
from pathlib import Path
from utils import log, get_config

def _decode_str(s) -> str:
    if not s:
        return ""
    parts = decode_header(s)
    result = []
    for part, enc in parts:
        if isinstance(part, bytes):
            result.append(part.decode(enc or "utf-8", errors="replace"))
        else:
            result.append(str(part))
    return " ".join(result)


def _classify_email(subject: str, body: str) -> str:
    """Classify a recruiter email into a status."""
    text = (subject + " " + body).lower()
    if any(w in text for w in ["offer","congratulations","pleased to offer","extend an offer","compensation package"]):
        return "OFFER"
    if any(w in text for w in ["interview","schedule","availability","book a time","calendar","meet","call","zoom","teams"]):
        return "INTERVIEW"
    if any(w in text for w in ["regret","unfortunately","moved forward","other candidates","not a fit","not selected","won't be moving"]):
        return "REJECTED"
    if any(w in text for w in ["received your application","thank you for applying","we've received","application is under review"]):
        return "VIEWED"
    if any(w in text for w in ["reply","response","following up","wanted to reach out","quick question"]):
        return "REPLIED"
    return "REPLIED"  # any recruiter email that doesn't match above = they replied


def _match_to_application(subject: str, sender: str, applications: list[dict]) -> dict | None:
    """Try to match an email to a specific application."""
    text = (subject + " " + sender).lower()
    for app in applications:
        company = app.get("company","").lower()
        if company and len(company) > 2 and company in text:
            return app
        domain = sender.split("@")[-1].split(".")[0].lower() if "@" in sender else ""
        if domain and len(domain) > 2 and (domain in company or company in domain):
            return app
    return None


def check_inbox_for_replies(applications: list[dict]) -> list[dict]:
    """
    Checks Gmail inbox for recruiter replies to our applications.
    Returns list of {application, status, subject, sender} for each match.

    Requires: GMAIL_APP_PASSWORD env var
    """
    app_password = os.environ.get("GMAIL_APP_PASSWORD","")
    cfg = get_config()
    email_addr = cfg["profile"]["email"]

    if not app_password:
        log.debug("[INBOX] GMAIL_APP_PASSWORD not set — skipping inbox check")
        return []

    updates = []
    try:
        # Connect via IMAP
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(email_addr, app_password)
        mail.select("INBOX")

        # Search for emails from last 7 days
        since = (datetime.now() - timedelta(days=7)).strftime("%d-%b-%Y")
        _, data = mail.search(None, f'SINCE {since}')
        email_ids = data[0].split()

        log.info(f"  [INBOX] Checking {len(email_ids)} recent emails for recruiter replies...")

        for eid in email_ids[-50:]:  # check last 50 emails max
            try:
                _, msg_data = mail.fetch(eid, "(RFC822)")
                msg = email.message_from_bytes(msg_data[0][1])

                subject = _decode_str(msg.get("Subject",""))
                sender  = _decode_str(msg.get("From",""))

                # Skip emails we sent
                if email_addr in sender:
                    continue

                # Get body text
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                            break
                else:
                    body = msg.get_payload(decode=True).decode("utf-8", errors="replace") if msg.get_payload(decode=True) else ""

                # Try to match to an application
                matched_app = _match_to_application(subject, sender, applications)
                if matched_app:
                    status = _classify_email(subject, body)
                    updates.append({
                        "application": matched_app,
                        "status":      status,
                        "subject":     subject,
                        "sender":      sender,
                        "preview":     body[:200],
                    })
                    log.info(f"  [INBOX] {status}: '{subject}' from {sender.split('<')[0]}")

            except Exception as e:
                log.debug(f"  [INBOX] Error reading email: {e}")

        mail.logout()

    except imaplib.IMAP4.error as e:
        log.warning(f"[INBOX] Gmail IMAP error: {e}. Make sure IMAP is enabled in Gmail settings.")
    except Exception as e:
        log.warning(f"[INBOX] Inbox check failed: {e}")

    log.info(f"  [INBOX] Found {len(updates)} recruiter replies")
    return updates
