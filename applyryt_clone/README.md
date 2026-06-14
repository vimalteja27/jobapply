# ApplyRyt Clone — Setup Guide

## What this does
Automatically scrapes 20+ ATS platforms daily, scores each job with AI (fit 1-10),
tailors your resume + cover letter per job, submits applications, and logs everything
to Google Sheets. Runs free on GitHub Actions, Mon–Fri 9am.

---

## Setup in 8 steps

### Step 1 — Clone & fill your profile
```bash
git clone https://github.com/YOUR_USERNAME/applyryt-clone
cd applyryt-clone
```
Edit `config.yaml`:
- Fill in your name, email, phone, LinkedIn, GitHub
- Set your target roles and company lists
- Keep `dry_run: true` until all tests pass

Edit `master_resume.json`:
- Replace ALL placeholder content with your real experience
- Be thorough — the AI picks from this

### Step 2 — Get your free Groq API key
1. Go to https://console.groq.com
2. Sign up (free) → API Keys → Create key
3. Copy the key — you'll add it as a GitHub Secret

### Step 3 — Set up Google Sheets logging
1. Go to https://console.cloud.google.com
2. Create a project → Enable "Google Sheets API" + "Google Drive API"
3. Create a Service Account → download credentials JSON
4. Create a Google Sheet named "Job Applications" and share it with the service account email

### Step 4 — Set up Gmail sending (optional but recommended)
1. In the same Google Cloud project, enable "Gmail API"
2. Create OAuth2 credentials (Desktop app)
3. Run the auth flow once to get your refresh token:
```bash
pip install google-auth-oauthlib
python -c "
from google_auth_oauthlib.flow import InstalledAppFlow
flow = InstalledAppFlow.from_client_secrets_file('oauth_client.json',
    scopes=['https://www.googleapis.com/auth/gmail.send'])
creds = flow.run_local_server(port=0)
print('refresh_token:', creds.refresh_token)
"
```

### Step 5 — Add GitHub Secrets
Go to your repo → Settings → Secrets → Actions → New repository secret

| Secret name               | Value |
|---------------------------|-------|
| `GROQ_API_KEY`            | Your Groq API key |
| `GMAIL_CLIENT_ID`         | OAuth client ID |
| `GMAIL_CLIENT_SECRET`     | OAuth client secret |
| `GMAIL_REFRESH_TOKEN`     | Refresh token from Step 4 |
| `GSHEET_CREDENTIALS_JSON` | Full contents of service account credentials JSON |

### Step 6 — Install and run tests locally
```bash
pip install -r requirements.txt
playwright install chromium

# Run reliability + config tests (no API key needed)
python -m pytest tests/test_suite.py::TestReliability tests/test_suite.py::TestScraping -v

# Run with AI tests (needs GROQ_API_KEY in env)
export GROQ_API_KEY=your_key_here
python -m pytest tests/ -v
```
All 16 tests must pass before going live.

### Step 7 — Dry run locally
```bash
export GROQ_API_KEY=your_key_here
python main.py
```
Check the logs/ folder and Google Sheets. No applications are submitted (dry_run: true).

### Step 8 — Go live
Once all tests pass and dry run looks correct:
1. Set `dry_run: false` in config.yaml
2. Push to GitHub
3. The pipeline runs automatically Mon–Fri 9am UTC

---

## Project structure
```
applyryt-clone/
├── config.yaml              ← your settings (edit this)
├── master_resume.json        ← your full resume data (edit this)
├── main.py                  ← daily orchestrator
├── utils.py                 ← shared utilities
├── requirements.txt
├── scrapers/
│   └── __init__.py          ← all ATS scrapers + router
├── ai/
│   └── __init__.py          ← scoring, tailoring, cover letter
├── submitter/
│   ├── __init__.py          ← form auto-fill + email submit
│   └── pdf_generator.py     ← tailored PDF per job
├── tracker/
│   └── __init__.py          ← Google Sheets + digest email
├── tests/
│   └── test_suite.py        ← 16 pre-production validation tests
├── resumes/                 ← generated PDFs (gitignored)
├── logs/                    ← daily run logs (gitignored)
└── .github/
    └── workflows/
        └── daily_pipeline.yml ← GitHub Actions cron
```

---

## Adding more companies
In `config.yaml`, add tokens/slugs to any ATS list:
```yaml
ats_targets:
  greenhouse:
    - "newcompany"        # boards.greenhouse.io/newcompany
  lever:
    - "anotherco"         # jobs.lever.co/anotherco
  workday:
    - "https://company.wd5.myworkdayjobs.com/careers"
```

## Adjusting the AI threshold
In `config.yaml`:
```yaml
search:
  min_fit_score: 7   # lower to 6 for more applications, raise to 8 for stricter
```

## Troubleshooting
- **0 jobs from a scraper**: the company slug might be wrong. Visit boards.greenhouse.io/SLUG to verify.
- **AI returns None**: check your GROQ_API_KEY is set and the job has a description.
- **PDF not generating**: run `pip install weasyprint` and ensure system fonts are installed.
- **GitHub Actions timeout**: reduce the number of Workday URLs (they're slowest).
