"""
get_gmail_token.py — Run this ONCE on your Mac to get your Gmail refresh token.

Steps:
  1. Download your OAuth credentials JSON from Google Cloud Console
     (APIs & Services → Credentials → download icon next to your OAuth client)
  2. Save it as oauth_client.json in this folder
  3. Run: python get_gmail_token.py
  4. A browser opens — sign in with vimalteja.m@gmail.com and click Allow
  5. Copy the printed GMAIL_REFRESH_TOKEN and add it as a GitHub secret

You only need to do this once. The refresh token doesn't expire.
"""
import json
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]
CLIENT_FILE = Path("oauth_client.json")

if not CLIENT_FILE.exists():
    print("ERROR: oauth_client.json not found.")
    print()
    print("To get it:")
    print("  1. Go to https://console.cloud.google.com")
    print("  2. APIs & Services → Credentials")
    print("  3. Click the download icon next to your OAuth 2.0 Client ID")
    print("  4. Save the file as oauth_client.json in this folder")
    print("  5. Re-run this script")
    exit(1)

print("Opening browser for Gmail authorization...")
print("Sign in with vimalteja.m@gmail.com and click Allow.")
print()

flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_FILE), SCOPES)
creds = flow.run_local_server(port=0)

print()
print("=" * 60)
print("SUCCESS — Add these as GitHub Secrets:")
print("=" * 60)
print()

client_info = json.loads(CLIENT_FILE.read_text())
web_or_installed = client_info.get("web") or client_info.get("installed", {})

print(f"GMAIL_CLIENT_ID     = {web_or_installed.get('client_id', '(see oauth_client.json)')}")
print(f"GMAIL_CLIENT_SECRET = {web_or_installed.get('client_secret', '(see oauth_client.json)')}")
print(f"GMAIL_REFRESH_TOKEN = {creds.refresh_token}")
print()
print("GitHub → Your repo → Settings → Secrets and variables → Actions")
print("→ New repository secret → paste each value above")
