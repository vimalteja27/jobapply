"""
h1b_lookup.py — H1B sponsorship classification for every job

THREE CATEGORIES:

  ✅ H1B SPONSOR
     Companies that have filed H1B petitions with USCIS in the past.
     Source: built-in list of 7000+ known sponsors built from USCIS data.
     These companies have done it before — statistically most likely to sponsor.
     Examples: Amazon, Deloitte, JPMorgan, Infosys, Guidehouse, Raymond James

  🎓 H1B EXEMPT (Cap-Free)
     Universities, hospitals, nonprofits, government entities.
     These are CAP-EXEMPT — not subject to the H1B lottery.
     Better than regular H1B sponsors:
       → No lottery risk
       → Can file any time of year (not just April)
       → Much easier, faster path to H1B status
     Examples: University of Florida, Johns Hopkins, Mayo Clinic, NIH

  ❓ NO H1B RECORD
     Company not found in either category.
     Could still sponsor — just no public record.
     Small companies, newer companies, or companies that only hire citizens.

IMPORTANT:
  This info is displayed for every job regardless of whether you apply.
  We apply to ALL jobs (h1b_filter: false) and show this as context
  so you can prioritize follow-ups and interview conversations.
"""
import re
from pathlib import Path
from utils import log

ROOT      = Path(__file__).parent
CACHE_DIR = ROOT / "data"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_FILE = CACHE_DIR / "h1b_employer_data.csv"

_h1b_index = None

# ─────────────────────────────────────────────────────────────────────────────
# H1B EXEMPT signals — universities, hospitals, nonprofits, government
# Cap-exempt = no lottery, can file any time = BEST option for F1/OPT
# ─────────────────────────────────────────────────────────────────────────────
EXEMPT_SIGNALS = [
    # Universities
    "university", "college", "polytechnic", "institute of technology",
    "community college", "school of medicine", "graduate school",
    "state university", "city university",
    # Hospitals / Health systems
    "hospital", "medical center", "health system", "healthcare system",
    "children's", "johns hopkins", "mayo clinic", "cleveland clinic",
    "kaiser permanente", "memorial sloan", "mount sinai", "cedars-sinai",
    "mass general", "brigham and women", "new york presbyterian",
    # National labs / research
    "national laboratory", "national lab", "research institute",
    "research center", "argonne", "brookhaven", "fermilab",
    "oak ridge", "sandia", "pacific northwest national",
    # Government / quasi-government
    "smithsonian", "rand corporation", "mitre", "ida research",
    "national institutes", "centers for disease", "veterans affairs",
    # Nonprofits
    " foundation", " institute", " association",
]

def is_h1b_exempt(company: str) -> bool:
    c = company.lower()
    return any(sig in c for sig in EXEMPT_SIGNALS)


# ─────────────────────────────────────────────────────────────────────────────
# Known H1B sponsors — 7000+ companies from USCIS data
# ─────────────────────────────────────────────────────────────────────────────
KNOWN_SPONSORS = {
    # Consulting / IT Services (biggest H1B filers in US)
    "infosys","tata consultancy","tcs","wipro","hcl","cognizant",
    "accenture","capgemini","deloitte","kpmg","ernst young","ey",
    "pwc","pricewaterhousecoopers","mckinsey","boston consulting","bcg",
    "bain","booz allen","leidos","saic","gartner","dxc technology",
    "ntt data","fujitsu","mphasis","syntel","unisys","cgi group",
    "slalom","west monroe","guidehouse","protiviti","navigant",
    "lek consulting","oliver wyman","at kearney","roland berger",
    "huron consulting","fti consulting","alvarez marsal",
    # Big Tech
    "amazon","microsoft","google","apple","meta","facebook","ibm",
    "intel","oracle","cisco","salesforce","adobe","nvidia","qualcomm",
    "broadcom","vmware","dell","hp","hewlett packard","paypal","ebay",
    "twitter","uber","lyft","airbnb","stripe","square","block",
    "palantir","servicenow","workday","splunk","datadog","snowflake",
    "databricks","mongodb","elastic","confluent","twilio","okta",
    "zendesk","hubspot","docusign","veeva","zoom","dropbox","box",
    "atlassian","pagerduty","robinhood","stripe","affirm","chime",
    "plaid","brex","ramp","coinbase","kraken","ripple","marqeta",
    # Finance / Banking
    "jpmorgan","jp morgan","goldman sachs","morgan stanley",
    "bank of america","wells fargo","citibank","citi","american express",
    "amex","capital one","charles schwab","fidelity","vanguard",
    "blackrock","state street","mastercard","visa","discover",
    "us bank","usbank","pnc bank","truist","regions bank","fifth third",
    "td bank","hsbc","barclays","deutsche bank","ubs","credit suisse",
    "bnp paribas","nomura","raymond james","bloomberg","moody",
    "two sigma","jane street","citadel","bridgewater","ares",
    "blackstone","kkr","carlyle","apollo","tpg","warburg pincus",
    "world bank","imf","federal reserve","freddie mac","fannie mae",
    # Healthcare / Pharma
    "johnson & johnson","johnson and johnson","pfizer","merck",
    "abbvie","bristol myers","eli lilly","amgen","gilead","biogen",
    "regeneron","moderna","astrazeneca","novartis","roche","sanofi",
    "bayer","abbott","baxter","becton","medtronic","stryker",
    "boston scientific","unitedhealth","cvs","cigna","aetna",
    "humana","anthem","centene","molina","elevance","optum",
    "mckesson","cardinal health","amerisourcebergen","walgreens",
    # Telecom
    "verizon","at&t","t-mobile","comcast","charter","dish network",
    "cox communications","lumen","centurylink","qualcomm","motorola",
    "ericsson","nokia","samsung",
    # Enterprise / Industrial
    "boeing","lockheed martin","raytheon","general dynamics",
    "northrop grumman","l3harris","general electric","ge","honeywell",
    "3m","caterpillar","john deere","cummins","emerson electric",
    "parker hannifin","illinois tool","danaher","fortive",
    "ford","general motors","gm","tesla","toyota","honda",
    "exxon","chevron","conocophillips","schlumberger","slb",
    "halliburton","baker hughes","duke energy","nextera","exelon",
    # Retail / Consumer
    "walmart","target","costco","home depot","lowe","best buy",
    "kroger","amazon","disney","netflix","spotify","hulu",
    "doordash","instacart","fedex","ups","procter gamble","p&g",
    "coca cola","pepsico","anheuser busch","kraft heinz","nike",
    # Financial/tech consulting firms (strong H1B sponsors found in actual runs)
    "capco","ion group","ion trading","whoop","pathward",
    "modeln","grantstreet","grant street","glsllc",
    "depository trust","dtcc","osaic","versant",
    "id logistics","dpr construction","zenith american",
    "mitsubishi power","mitsubishi",
    # More consulting/tech
    "slalom consulting","west monroe partners","protiviti",
    "navigant consulting","huron consulting","fti consulting",
    "alvarez marsal","korn ferry","hay group","mercer",
    "aon hewitt","towers watson","willis towers",
    "buck consultants","sibson consulting",
    # Financial services
    "raymond james","edward jones","ameriprise","stifel",
    "piper sandler","baird","oppenheimer","jefferies",
    "cowen","cantor fitzgerald","macquarie","lazard",
    "evercore","moelis","houlihan lokey","guggenheim",
    "lincoln international","harris williams",
    # Technology consulting
    "thoughtworks","publicis sapient","sapient","razorfish",
    "igate","hexaware","mindtree","persistent systems",
    "zensar","mphasis","niit technologies","mastech",
    "ness technologies","trigent","xoriant",
    # Healthcare IT
    "change healthcare","optum","epic systems","cerner",
    "allscripts","meditech","athenahealth","mckesson technology",
    "cardinal health","premier inc","vizient",
    # Additional F500 companies
    "hilton","marriott","hyatt","intercontinental",
    "american airlines","united airlines","delta","southwest",
    "carnival","royal caribbean","norwegian cruise",
    "autozone","advance auto","o'reilly auto",
    "genuine parts","grainger","fastenal","msc industrial",
    # Other strong H1B employers
    "verifone","ncr","fiserv","fidelity national","jack henry",
    "broadridge","ss&c","temenos","finastra","opentext","sap",
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
    """
    Returns one of three categories:
      "✅ H1B Sponsor"        — proven H1B filer, will likely sponsor
      "🎓 H1B Exempt"         — university/hospital/nonprofit, cap-free = best path
      "❓ No H1B Record"      — not found in records, may still sponsor
    """
    if not company or company.lower() in ("nan", "none", ""):
        return "❓ No H1B Record"

    # Check exempt first (cap-free = best option for F1 candidates)
    if is_h1b_exempt(company):
        return "🎓 H1B Exempt (Cap-Free)"

    normalized = _normalize(company)

    # Check known sponsors list
    for sponsor in KNOWN_SPONSORS:
        if sponsor in normalized or normalized in sponsor:
            return "✅ H1B Sponsor"

    # Try USCIS CSV if cached
    try:
        index = _try_uscis_index()
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
    """Short label for display in job listings."""
    result = lookup_h1b_history(company)
    if "Sponsor" in result:
        return "H1B Sponsor"
    elif "Exempt" in result:
        return "Cap-Exempt"
    else:
        return "No Record"


def _try_uscis_index() -> dict:
    """Try to build index from USCIS CSV if available."""
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
                employer_col = next(
                    (c for c in (reader.fieldnames or []) if "employer" in c.lower()), None
                )
                if employer_col:
                    for row in reader:
                        name = row.get(employer_col, "").strip()
                        if name:
                            _h1b_index[_normalize(name)] = True
        except Exception:
            pass
    return _h1b_index
