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
    # Universities & colleges (full names)
    "university", "college", "polytechnic", "institute of technology",
    "community college", "school of medicine", "graduate school",
    "state university", "city university", "school of business",
    "school of engineering", "school of public health",
    # University abbreviations & nicknames
    "m.i.t", "nyu", "ucla", "ucsf", "uc davis", "uc berkeley",
    "uc irvine", "uc santa", "uc san diego", "uc riverside",
    "caltech", "georgia tech", "virginia tech", "penn state",
    "ohio state", "michigan state", "arizona state", "florida state",
    "texas a&m", "nc state", "iowa state", "oregon state",
    "washington state", "colorado state", "utah state",
    "suny", "cuny", "cal state", "uc system",
    # Hospitals & health systems
    "hospital", "medical center", "health system", "healthcare system",
    "children's", "johns hopkins", "mayo clinic", "cleveland clinic",
    "kaiser permanente", "memorial sloan", "mount sinai", "cedars-sinai",
    "mass general", "brigham and women", "new york presbyterian",
    "stanford health", "ucla health", "ucsf health", "wake forest baptist",
    "vanderbilt health", "duke health", "penn medicine",
    # National labs & govt research
    # Health systems & integrated care networks (nonprofit)
    "health system", "health network", "health plan", "healthpartners",
    "health partners", "allina", "fairview", "hennepin healthcare",
    "park nicollet", "regions hospital", "ucare", "sanford health",
    "essentia health", "adventhealth", "dignity health", "providence health",
    "intermountain health", "banner health", "ascension health",
    "sutter health", "geisinger", "ochsner", "medstar",
    "christus health", "northwell", "ohio state wexner",
    "uc san diego health", "uw medicine", "vanderbilt health",
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
    # Cancer centers (nonprofit)
    "cancer center", "cancer institute", "cancer research",
    "moffitt", "sloan kettering", "md anderson", "dana-farber",
    "fred hutchinson", "huntsman cancer", "roswell park",
    "city of hope", "fox chase cancer",
    # Major nonprofits
    "american red cross", "red cross", "united way",
    "salvation army", "ymca", "ywca", "habitat for humanity",
    "brookings", "urban institute", "pew research",
    "kaiser family foundation", "commonwealth fund",
    "robert wood johnson", "gates foundation", "ford foundation",
    "macarthur foundation", "rockefeller foundation",
    "american heart association", "american cancer society",
    "american lung association", "american diabetes association",
    # Government agencies & labs
    "nih ", "n.i.h", "national institutes of health",
    "cdc ", "centers for disease control",
    "nasa ", "n.a.s.a",
    "noaa ", "n.o.a.a",
    "usda ", "department of agriculture",
    "department of energy", "dept of energy",
    "department of defense", "dept of defense",
    "department of health", "dept of health",
    "national science foundation", "nsf ",
    "national endowment",
    # Research institutions
    "sri international", "sri research",
    "rtinternational", "rti international",
    "urban institute", "mathematica",
    "abt associates", "westat",
    "american institutes for research",
    "educational testing service", "ets ",
    "institute for defense analyses", "ida ",
]

# Exact-match abbreviations that would cause false positives as substrings
EXEMPT_EXACT = {
    "mit", "nih", "cdc", "nasa", "noaa", "nsf", "usda", "ets", "ida",
}

# University names that appear as standalone words (not substrings)
EXEMPT_UNIVERSITIES = {
    "stanford", "caltech", "harvard", "yale", "princeton",
    "cornell", "columbia", "dartmouth", "brown", "duke",
    "emory", "vanderbilt", "georgetown", "tufts", "tulane",
    "northeastern", "drexel", "villanova", "marquette",
}

def is_h1b_exempt(company: str) -> bool:
    import re
    c = company.lower().strip()
    # 1. Exact full-name match (MIT, NIH, CDC, NASA)
    if c in EXEMPT_EXACT:
        return True
    # 2. University name as a word (Stanford, Harvard, etc.)
    for uni in EXEMPT_UNIVERSITIES:
        if re.search(r'\b' + uni + r'\b', c):
            return True
    # 3. Substring signals (university, hospital, foundation, etc.)
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
    """Returns one of three H1B categories.
    ORDER MATTERS: always check Cap-Exempt FIRST before sponsor list.
    A university that also files H1B is still Cap-Exempt (better for you).
    """
    if not company or company.lower() in ("nan","none",""):
        return "❓ No H1B Record"

    # Cap-Exempt check FIRST — university/hospital/nonprofit beats everything
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
H1B STATUS LEGEND — YOUR PRIORITY ORDER (F1 STEM OPT):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🎓 Cap-Exempt = University / Nonprofit Research / Govt Lab
   → NO H1B lottery — file any time of year
   → IMPORTANT: Cap-Exempt does NOT mean they hire on OPT/STEM OPT
     Some (Mayo Clinic, NIH) do NOT accept STEM OPT for most roles
     Universities (USF, UT, UMN) often DO hire BAs on OPT
   → BEST strategy: apply, then ask in interview about OPT + H1B policy
   → If they hire you → guaranteed H1B approval, no lottery risk

✅ H1B Sponsor = Proven USCIS H1B filer (Amazon, JPMorgan, etc.)
   → Most actively hire F1 OPT workers — your most reliable path NOW
   → Subject to April lottery (~40% chance per year)
   → Your past employers (Amex, HSBC, Verifone) are in this category
   → Best bet: large tech + large finance companies

❓ No Record = Not in USCIS data (startups, smaller companies)
   → We still apply — don't miss opportunities
   → Ask during interview: "Do you sponsor H1B?"
   → Many will sponsor if they want you badly enough

WHAT ACTUALLY WORKS FOR YOUR SITUATION:
  🥇 Universities (IT/Ops BA roles) → Cap-Exempt + hire STEM OPT
     USF, UF, UCF, FIU — your home state targets
     Michigan, Stanford, Johns Hopkins, NYU — national
     These file H1B cap-exempt year-round, no lottery ever

  🥈 Nonprofit Hospitals (IT BA, Revenue Cycle BA, EHR Analyst)
     AdventHealth, BayCare, TGH — Tampa area
     Cleveland Clinic, Penn Medicine, NYU Langone — national
     Affiliated with universities = cap-exempt status

  🥉 Think Tanks & Research Nonprofits (data/policy analyst)
     RAND, MITRE, Battelle, RTI International
     Hire analysts, not just researchers

  4️⃣  Large Tech H1B Sponsors (lottery risk but most likely to hire)
     Google, Amazon, Microsoft, Salesforce — familiar with OPT
     Your past companies: Amex, HSBC, Verifone — excellent refs

  💡 2025/2026 KEY FACT:
     New $100K H1B fee applies to OVERSEAS hires only.
     You are already in the US on OPT → employers PREFER you.
     This is YOUR advantage right now.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


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
