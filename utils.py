"""
utils.py — shared utilities used across all modules
"""
import yaml, json, logging, hashlib, os
from pathlib import Path
from datetime import datetime, timedelta

ROOT = Path(__file__).parent
(ROOT / "logs").mkdir(parents=True, exist_ok=True)
(ROOT / "resumes").mkdir(parents=True, exist_ok=True)

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(ROOT / "logs" / f"run_{datetime.now().strftime('%Y%m%d')}.log")
    ]
)
log = logging.getLogger("applyryt")

# ── Config loader ─────────────────────────────────────────────────────────────
_config = None

def get_config() -> dict:
    global _config
    if _config is None:
        with open(ROOT / "config.yaml") as f:
            _config = yaml.safe_load(f)
    return _config

def get_master_resume() -> dict:
    with open(ROOT / "master_resume.json") as f:
        return json.load(f)

# ── Job schema ────────────────────────────────────────────────────────────────
def normalize_job(raw: dict) -> dict:
    """Ensure every job dict has the same keys regardless of source."""
    return {
        "id":          raw.get("id", ""),
        "source":      raw.get("source", "unknown"),
        "company":     raw.get("company", ""),
        "title":       raw.get("title", "").strip(),
        "location":    raw.get("location", "").strip(),
        "url":         raw.get("url", "").strip(),
        "description": raw.get("description", "").strip(),
        "posted_at":   raw.get("posted_at", ""),
        "salary_min":  raw.get("salary_min"),
        "salary_max":  raw.get("salary_max"),
    }

# ── Deduplication ─────────────────────────────────────────────────────────────
def deduplicate(jobs: list[dict]) -> list[dict]:
    """Remove duplicates by hashing (title + company). Case-insensitive."""
    seen = set()
    unique = []
    for j in jobs:
        key = hashlib.md5(
            f"{j['title'].lower().strip()}|{j['company'].lower().strip()}".encode()
        ).hexdigest()
        if key not in seen and j["title"]:
            seen.add(key)
            unique.append(j)
    log.info(f"Deduplicated: {len(jobs)} → {len(unique)} unique jobs")
    return unique

# ── Filtering ─────────────────────────────────────────────────────────────────
def _parse_posted_date(posted_at: str) -> datetime | None:
    """Try to parse posted_at string into a datetime. Returns None if unparseable."""
    if not posted_at:
        return None
    from datetime import timezone
    # Try common formats
    for fmt in [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%B %d, %Y",
        "%b %d, %Y",
    ]:
        try:
            return datetime.strptime(posted_at.strip(), fmt)
        except ValueError:
            continue
    # Try ISO format (handles timezone offsets)
    try:
        return datetime.fromisoformat(posted_at.strip().rstrip("Z"))
    except Exception:
        return None


def filter_jobs(jobs: list[dict]) -> list[dict]:
    cfg = get_config()
    blacklist_co  = [c.lower() for c in cfg["search"].get("blacklist_companies", [])]
    blacklist_kw  = [k.lower() for k in cfg["search"].get("blacklist_keywords", [])]
    hours_old     = int(cfg["search"].get("hours_old", 360))
    max_age_days  = hours_old / 24  # convert to days for display

    # Always-exclude title keywords for "full-time only" strictness
    NON_FULLTIME = [
        "intern", "internship", "contract", "contractor", "c2c", "c2h",
        "part-time", "part time", "temporary", "temp ", "freelance",
        "1099", "co-op", "coop", "apprenticeship",
    ]

    # Non-US location signals — excludes if location clearly outside US
    NON_US_SIGNALS = [
        "india", "canada", "uk", "united kingdom", "philippines", "mexico",
        "brazil", "germany", "france", "poland", "ukraine", "pakistan",
        "bangladesh", "nigeria", "argentina", "remote - emea", "remote - apac",
        "remote, eu", "europe", "latam", "apac",
    ]

    cutoff = datetime.now() - timedelta(hours=hours_old)

    filtered  = []
    skipped_old = 0
    skipped_ats_exempted = 0  # ATS jobs that would have been filtered but were kept
    for j in jobs:
        co       = j["company"].lower()
        title    = j["title"].lower()
        location = (j.get("location") or "").lower()

        if any(b in co for b in blacklist_co):
            log.debug(f"Skipped (blacklisted company): {j['company']}")
            continue

        # Skip consulting/staffing/outsourcing firms — product companies only
        if cfg["search"].get("company_type", "product") == "product":
            if is_consulting_company(j.get("company", "")):
                log.debug(f"Skipped (consulting/staffing): {j['company']}")
                continue
        if any(k in title for k in blacklist_kw):
            log.debug(f"Skipped (blacklisted keyword): {j['title']}")
            continue

        # Strict full-time filter
        if any(k in title for k in NON_FULLTIME):
            log.debug(f"Skipped (not full-time): {j['title']}")
            continue

        # Strict US-only filter — exclude jobs with clear non-US location signals
        if location and any(s in location for s in NON_US_SIGNALS):
            log.debug(f"Skipped (non-US location): {j['title']} - {j.get('location')}")
            continue

        # Date filter — skip for ATS sources (Greenhouse/Lever/Ashby/etc)
        # because their posted_at = last_modified date, not actual posting date
        ATS_SOURCES = {"greenhouse","lever","ashby","workday","smartrecruiters",
                       "workable","bamboohr","jobvite","breezy","rippling","icims"}
        if j.get("source") not in ATS_SOURCES:
            posted = _parse_posted_date(j.get("posted_at", ""))
            if posted:
                posted_naive = posted.replace(tzinfo=None)
                if posted_naive < cutoff:
                    skipped_old += 1
                    log.debug(f"Skipped (too old): {j['title']} @ {j['company']}")
                    continue
        else:
            # ATS source — check if it would have been filtered, log for visibility
            posted = _parse_posted_date(j.get("posted_at", ""))
            if posted:
                posted_naive = posted.replace(tzinfo=None)
                if posted_naive < cutoff:
                    skipped_ats_exempted += 1

        filtered.append(j)

    log.info(f"After filtering: {len(filtered)} jobs remain "
             f"(removed {skipped_old} job-board results older than {int(max_age_days)} days"
             f"{f', kept {skipped_ats_exempted} ATS jobs regardless of date' if skipped_ats_exempted else ''})")
    return filtered

# ── Applied-jobs ledger ───────────────────────────────────────────────────────
APPLIED_FILE = ROOT / "logs" / "applied.json"

def load_applied() -> set:
    if APPLIED_FILE.exists():
        return set(json.loads(APPLIED_FILE.read_text()))
    return set()

def mark_applied(job: dict):
    key = f"{job['title'].lower()}|{job['company'].lower()}"
    applied = load_applied()
    applied.add(key)
    APPLIED_FILE.write_text(json.dumps(list(applied)))

def already_applied(job: dict) -> bool:
    key = f"{job['title'].lower()}|{job['company'].lower()}"
    return key in load_applied()

# ── Daily cap tracking (resets each calendar day, UTC) ───────────────────────
DAILY_COUNT_FILE = ROOT / "logs" / "daily_count.json"

def get_today_applied_count() -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    if DAILY_COUNT_FILE.exists():
        data = json.loads(DAILY_COUNT_FILE.read_text())
        if data.get("date") == today:
            return data.get("count", 0)
    return 0

def increment_today_count():
    today = datetime.now().strftime("%Y-%m-%d")
    count = get_today_applied_count() + 1
    DAILY_COUNT_FILE.write_text(json.dumps({"date": today, "count": count}))

# ── Dry-run guard ─────────────────────────────────────────────────────────────
def is_dry_run() -> bool:
    return get_config().get("dry_run", True)

# ── Consulting/Staffing company blacklist ─────────────────────────────────────
CONSULTING_SIGNALS = [
    # Pure consulting firms
    "consulting", "consultancy", "consultants",
    "advisory", "advisors",
    # Staffing / IT services
    "staffing", "recruiting", "recruitment", "talent solutions",
    "manpower", "workforce solutions",
    # Known IT outsourcing firms by name
    "infosys", "tcs", "tata consultancy", "wipro", "hcl technologies",
    "cognizant", "capgemini", "accenture", "mphasis", "hexaware",
    "mindtree", "persistent systems", "zensar", "mastech",
    "niit technologies", "ness technologies", "syntel",
    "igate", "patni", "kforce", "modis", "apex systems",
    "insight global", "robert half", "randstad", "adecco",
    "manpowergroup", "kelly services", "spherion", "volt",
    # Management consulting
    "deloitte", "pwc", "pricewaterhousecoopers", "ernst & young", "kpmg",
    "mckinsey", "boston consulting group", "bcg", "bain & company",
    "capco", "slalom", "protiviti", "navigant", "huron consulting",
    "fti consulting", "alvarez marsal", "west monroe", "publicis sapient",
    "thoughtworks", "sapient", "razorfish", "atos", "dxc technology",
    "ntt data", "fujitsu", "unisys", "leidos", "saic", "booz allen",
    # Temp/contract agencies
    "contract staffing", "temp agency", "job placement",
]

def is_consulting_company(company: str) -> bool:
    """Returns True if company appears to be a consulting/staffing/outsourcing firm."""
    c = company.lower()
    return any(signal in c for signal in CONSULTING_SIGNALS)
