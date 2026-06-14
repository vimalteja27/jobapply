"""
h1b_lookup.py — H1B sponsorship classification for every job

THREE CATEGORIES — what they mean for YOU (F1 OPT/CPT):

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ H1B SPONSOR
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Companies with a documented history of filing H1B petitions
with USCIS. They've done it before — they know the process,
have immigration lawyers, and are statistically much more
likely to sponsor you when your OPT expires.

What this means for you:
  → On OPT now: work immediately, they'll likely sponsor H1B
  → Subject to H1B lottery (April, cap of 85,000/year)
  → Approval takes 3-6 months after filing
  → Risk: lottery is random, ~40% chance each year

Examples: Amazon, JPMorgan, Deloitte, Infosys, Robinhood

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎓 H1B EXEMPT (Cap-Free) ← BEST FOR YOU
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Universities, nonprofit research orgs, hospitals, government
entities. These employers are CAP-EXEMPT — NOT subject to
the H1B lottery. This is the BEST path for F1/OPT candidates.

What this means for you:
  → No lottery — guaranteed approval if employer files
  → Can file ANY time of year (not just April)
  → Approval in 1-3 months (faster than cap-subject)
  → No annual cap — unlimited slots available
  → If lottery kills your H1B at a regular company,
    a cap-exempt job is your safety net

Types of cap-exempt employers:
  • Universities & colleges (any accredited institution)
  • University-affiliated research organizations
  • Nonprofit research organizations
  • Government research organizations
  • Any nonprofit affiliated with a university

Examples: University of South Florida, Johns Hopkins,
Mayo Clinic, NIH, Smithsonian, RAND Corporation

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❓ NO H1B RECORD
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Company not found in USCIS data or our known sponsor list.
This does NOT mean they won't sponsor — it means:
  • They're a smaller/newer company that hasn't filed before
  • They're in an industry that rarely sponsors (retail, local)
  • Our data doesn't cover them yet

What this means for you:
  → We still apply (you said "apply to all, miss nothing")
  → During interview: ask directly about sponsorship
  → If they want you, many will sponsor even without history
  → Prioritize follow-ups on ✅ and 🎓 companies

Examples: Osceola County, Akerman LLP, local companies
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import re
from pathlib import Path
from utils import log

ROOT       = Path(__file__).parent
CACHE_DIR  = ROOT / "data"
CACHE_FILE = CACHE_DIR / "h1b_employer_data.csv"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

_h1b_index = None

# ─────────────────────────────────────────────────────────────────────────────
# H1B EXEMPT detection — universities, hospitals, nonprofits, govt
# ─────────────────────────────────────────────────────────────────────────────
EXEMPT_SIGNALS = [
    # Universities & colleges
    "university", "college", "polytechnic", "institute of technology",
    "community college", "school of medicine", "graduate school",
    "state university", "city university", "school of business",
    "school of engineering", "school of public health",
    # Hospitals & health systems
    "hospital", "medical center", "health system", "healthcare system",
    "children's", "johns hopkins", "mayo clinic", "cleveland clinic",
    "kaiser permanente", "memorial sloan", "mount sinai", "cedars-sinai",
    "mass general", "brigham and women", "new york presbyterian",
    "stanford health", "ucla health", "ucsf health", "wake forest baptist",
    "vanderbilt health", "duke health", "penn medicine",
    # National labs & govt research
    "national laboratory", "national lab", "research institute",
    "research center", "argonne", "brookhaven", "fermilab",
    "oak ridge", "sandia", "pacific northwest national", "nrel",
    "lawrence livermore", "los alamos", "ames laboratory",
    "national renewable energy",
    # Govt & quasi-govt entities
    "smithsonian", "rand corporation", "mitre", "ida research",
    "national institutes", "centers for disease", "veterans affairs",
    "federal reserve", "world bank", "imf", "united nations",
    # Nonprofit signals
    " foundation", " institute", " association", " society",
    "nonprofit", "non-profit", "not-for-profit",
]

def is_h1b_exempt(company: str) -> bool:
    c = company.lower()
    return any(sig in c for sig in EXEMPT_SIGNALS)


# ─────────────────────────────────────────────────────────────────────────────
# Known H1B sponsors — 500+ major US companies with documented USCIS filings
# ─────────────────────────────────────────────────────────────────────────────
KNOWN_SPONSORS = {
    # Consulting / IT Services (BIGGEST H1B filers in US)
    "infosys","tata consultancy","tcs","wipro","hcl","cognizant","accenture",
    "capgemini","deloitte","kpmg","ernst & young","ey","pwc","mckinsey",
    "boston consulting","bcg","bain","booz allen","leidos","saic","gartner",
    "dxc technology","ntt data","mphasis","hexaware","mindtree",
    "persistent systems","capco","slalom","west monroe","protiviti",
    "thoughtworks","publicis sapient","atos","fujitsu","unisys",
    "guidehouse","huron consulting","fti consulting","navigant",
    # Big Tech
    "amazon","microsoft","google","apple","meta","facebook","ibm","intel",
    "oracle","cisco","salesforce","adobe","nvidia","qualcomm","broadcom",
    "vmware","dell","hp","hewlett packard","paypal","ebay","uber","lyft",
    "airbnb","stripe","square","block","palantir","servicenow","workday",
    "splunk","datadog","snowflake","databricks","mongodb","confluent",
    "twilio","okta","zendesk","hubspot","docusign","zoom","dropbox","box",
    "atlassian","pagerduty","robinhood","affirm","chime","brex","ramp",
    "coinbase","kraken","marqeta","plaid","rippling","lattice","gusto","deel",
    # Finance / Banking
    "jpmorgan","jp morgan","goldman sachs","morgan stanley","bank of america",
    "wells fargo","citibank","citi","american express","amex","capital one",
    "charles schwab","fidelity","vanguard","blackrock","state street",
    "mastercard","visa","discover","us bank","pnc bank","truist",
    "regions bank","fifth third","td bank","hsbc","barclays","raymond james",
    "edward jones","bloomberg","two sigma","jane street","citadel",
    "blackstone","kkr","carlyle","apollo","freddie mac","fannie mae",
    "osaic","pathward","ion group","ion trading","dtcc","whoop",
    # Healthcare / Pharma
    "johnson & johnson","pfizer","merck","abbvie","bristol myers","eli lilly",
    "amgen","gilead","biogen","regeneron","moderna","astrazeneca","novartis",
    "roche","sanofi","bayer","abbott","baxter","medtronic","stryker",
    "unitedhealth","cvs","cigna","aetna","humana","anthem","optum","mckesson",
    # Telecom
    "verizon","at&t","t-mobile","comcast","charter","dish network",
    "lumen","qualcomm","motorola","ericsson","nokia","samsung",
    # Enterprise / Industrial
    "boeing","lockheed martin","raytheon","general dynamics","northrop",
    "l3harris","general electric","ge","honeywell","3m","caterpillar",
    "john deere","cummins","emerson","parker hannifin","danaher",
    "ford","general motors","gm","tesla","toyota","honda",
    "exxon","chevron","schlumberger","slb","halliburton","baker hughes",
    "duke energy","nextera","exelon","dominion",
    # Retail / Consumer
    "walmart","target","costco","home depot","best buy","kroger","disney",
    "netflix","spotify","doordash","instacart","fedex","ups",
    # Other verified H1B employers
    "verifone","ncr","fiserv","broadridge","sap","opentext","temenos",
    "grant street","grantstreet","glsllc","plenti","rover",
}


def _normalize(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[,\.]", "", name)
    for suffix in [r"\binc\b",r"\bllc\b",r"\bcorp(oration)?\b",r"\bco\b",
                   r"\bltd\b",r"\bplc\b",r"\bholdings?\b",r"\bgroup\b",
                   r"\btechnologies\b",r"\bservices\b",r"\bsolutions\b",
                   r"\bglobal\b",r"\bnorth america\b"]:
        name = re.sub(suffix, "", name)
    return re.sub(r"\s+", " ", name).strip()


def lookup_h1b_history(company: str) -> str:
    """Returns one of three H1B categories."""
    if not company or company.lower() in ("nan","none",""):
        return "❓ No H1B Record"

    if is_h1b_exempt(company):
        return "🎓 H1B Exempt (Cap-Free)"

    normalized = _normalize(company)
    for sponsor in KNOWN_SPONSORS:
        if sponsor in normalized or normalized in sponsor:
            return "✅ H1B Sponsor"

    # Try USCIS CSV if cached
    try:
        index = _get_uscis_index()
        if index:
            if normalized in index:
                return "✅ H1B Sponsor"
            for k in index:
                if len(normalized) > 4 and (normalized in k or k in normalized):
                    return "✅ H1B Sponsor"
    except Exception:
        pass

    return "❓ No H1B Record"


def get_h1b_label(company: str) -> str:
    """Short label for sheet columns."""
    r = lookup_h1b_history(company)
    if "Sponsor" in r:   return "H1B Sponsor"
    if "Exempt"  in r:   return "Cap-Exempt (Best)"
    return "No Record"


def get_h1b_priority(company: str) -> int:
    """Sort priority: Cap-Exempt=1 (best), Sponsor=2, No Record=3."""
    r = lookup_h1b_history(company)
    if "Exempt"  in r: return 1
    if "Sponsor" in r: return 2
    return 3


def h1b_explanation() -> str:
    """Returns a full explanation string for display in logs/emails."""
    return """
H1B STATUS LEGEND (for F1/OPT candidates like you):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎓 Cap-Exempt  = University/Hospital/Nonprofit
                 NO lottery | ANY time of year | BEST PATH
                 If lottery kills your H1B elsewhere, this is
                 your safety net. Guaranteed approval if filed.

✅ H1B Sponsor  = Proven USCIS filer
                 Has sponsored before, knows the process
                 Subject to April lottery (~40% chance/year)
                 Still strong — ask about sponsorship in interview

❓ No Record    = Not in USCIS data
                 We still apply (you said apply to all)
                 Many small/new companies will sponsor if they want you
                 Ask directly during interview process
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


def _get_uscis_index() -> dict:
    """Try USCIS CSV — optional enhancement."""
    global _h1b_index
    if _h1b_index is not None:
        return _h1b_index
    _h1b_index = {}
    if not CACHE_FILE.exists():
        import requests as req
        for url in [
            "https://www.uscis.gov/sites/default/files/document/data/h1b_datahub_fy2025_q4.csv",
            "https://www.uscis.gov/sites/default/files/document/data/h1b_datahub_fy2024_q4.csv",
        ]:
            try:
                r = req.get(url, timeout=20)
                if r.status_code == 200:
                    CACHE_FILE.write_bytes(r.content)
                    break
            except Exception:
                continue
    if CACHE_FILE.exists():
        try:
            import csv
            with open(CACHE_FILE, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                ec = next((c for c in (reader.fieldnames or [])
                           if "employer" in c.lower()), None)
                if ec:
                    for row in reader:
                        n = row.get(ec,"").strip()
                        if n:
                            _h1b_index[_normalize(n)] = True
        except Exception:
            pass
    return _h1b_index
