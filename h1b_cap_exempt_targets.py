"""
h1b_cap_exempt_targets.py

Curated list of Cap-Exempt employers that:
  1. Are legally cap-exempt (university/nonprofit/govt research)
  2. Actually hire STEM OPT holders
  3. Have Business Analyst / Data Analyst / Product / Process roles
  4. Have a track record of filing H1B cap-exempt petitions

Sources: USCIS LCA data, H1BMetrics, H1BGrader, scale.jobs research

KEY DISTINCTION (from research):
  - Cap-Exempt = no H1B lottery, file any time of year
  - But employer must ALSO be willing to hire STEM OPT holders
  - Universities/affiliated nonprofits are your best bet for BA roles
  - Pure research labs (NIH, Mayo clinical) mostly hire researchers/clinicians
  - University IT/operations/analytics departments hire BAs on OPT regularly

IMPORTANT NEW 2025 RULE:
  - $100K supplemental H1B fee for overseas hires — BUT
  - F1 OPT holders already in the US are EXEMPT from this fee
  - This actually makes you MORE attractive to employers in 2025/2026
  - Companies now PREFER to hire OPT holders over overseas candidates
"""

# ─────────────────────────────────────────────────────────────────────────────
# TIER 1: Universities — hire BAs for IT, operations, analytics, admin
# These departments actively hire STEM OPT for non-research roles:
# IT Department, Finance, Operations, Data Analytics, Business Intelligence
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSITY_TARGETS = [
    # Florida (your home state — Tampa)
    "University of South Florida",
    "University of Florida",
    "Florida State University",
    "University of Central Florida",
    "Florida International University",
    "University of Miami",
    "Moffitt Cancer Center",          # USF-affiliated, hires analysts
    "Tampa General Hospital",          # USF Health-affiliated

    # Top university systems known to hire OPT BAs
    "University of Michigan",          # 488 cap-exempt H1B filings, 0% denial
    "Stanford University",             # 434 cap-exempt filings
    "University of California",        # UC system — huge employer
    "University of Texas",
    "University of Minnesota",
    "Ohio State University",
    "University of Washington",
    "University of Pennsylvania",
    "Carnegie Mellon University",
    "Johns Hopkins University",
    "Duke University",
    "Vanderbilt University",
    "Georgetown University",
    "Boston University",
    "Northeastern University",
    "New York University",
    "Columbia University",
    "Cornell University",
    "University of Chicago",
    "Northwestern University",
    "Indiana University",
    "Purdue University",
    "Penn State University",
    "Michigan State University",
    "Arizona State University",
    "University of Arizona",
    "University of Maryland",
    "Virginia Tech",
    "Georgia Tech",
    "Texas A&M University",
    "University of Illinois",
    "University of Wisconsin",
    "University of Colorado",
    "University of Pittsburgh",
    "Case Western Reserve University",

    # Community colleges & smaller schools also cap-exempt
    "Hillsborough Community College",
    "Valencia College",
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 2: University-affiliated health systems & hospitals
# These ARE cap-exempt (affiliated with universities)
# They DO hire Business Analysts for IT, operations, revenue cycle, EHR
# ─────────────────────────────────────────────────────────────────────────────
UNIVERSITY_HOSPITAL_TARGETS = [
    # Confirmed cap-exempt + hire analysts
    "UCSF Medical Center",
    "Johns Hopkins Hospital",
    "Massachusetts General Hospital",
    "Brigham and Women's Hospital",
    "Cleveland Clinic",               # hires IT/ops BAs, accepts OPT
    "Penn Medicine",
    "Duke University Health System",
    "Vanderbilt University Medical Center",
    "University of Michigan Health",
    "UW Medicine",
    "Mayo Clinic",                    # cap-exempt BUT limited STEM OPT for non-research
    "Ohio State Wexner Medical Center",
    "Indiana University Health",      # avg $299K H1B — large employer
    "University of Pittsburgh Medical Center",
    "UT Southwestern Medical Center",
    "Emory Healthcare",
    "Rush University Medical Center",
    "Northwestern Memorial Hospital",
    "Barnes-Jewish Hospital",
    "Cedars-Sinai Medical Center",
    "NYU Langone Health",
    "Montefiore Medical Center",
    "NewYork-Presbyterian Hospital",
    "Mount Sinai Health System",
    "Stanford Health Care",
    "UC San Diego Health",
    "Tampa General Hospital",
    "AdventHealth",                   # large nonprofit health system
    "BayCare Health System",          # Tampa-based nonprofit
    "HealthPartners",
    "Allina Health",
    "Fairview Health Services",
    "Hennepin Healthcare",
    "Park Nicollet Health Services",
    "Sanford Health",
    "Essentia Health",
    "Ochsner Health",
    "Geisinger Health System",
    "Intermountain Health",
    "Banner Health",
    "Providence Health & Services",
    "Ascension Health",
    "Dignity Health",
    "Sutter Health",
    "MedStar Health",
    "Northwell Health",
    "Christus Health",
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 3: Nonprofit research orgs & think tanks
# Cap-exempt, hire analysts for research support, data, policy, operations
# ─────────────────────────────────────────────────────────────────────────────
NONPROFIT_RESEARCH_TARGETS = [
    "RAND Corporation",
    "MITRE Corporation",
    "Battelle Memorial Institute",    # 115 H1B filings 2025, avg $99K
    "SRI International",
    "RTI International",
    "Urban Institute",
    "Brookings Institution",
    "Mathematica",
    "Abt Associates",
    "Westat",
    "American Institutes for Research",
    "Educational Testing Service",
    "Howard Hughes Medical Institute",
    "Fred Hutchinson Cancer Center",
    "Dana-Farber Cancer Institute",
    "St. Jude Children's Research Hospital",  # 269 H1B filings, 264 approvals
    "Salk Institute",
    "Cold Spring Harbor Laboratory",
    "Jackson Laboratory",
    "Roswell Park Cancer Institute",
    "City of Hope",
    "MD Anderson Cancer Center",
    "Moffitt Cancer Center",
    "Memorial Sloan Kettering",
]

# ─────────────────────────────────────────────────────────────────────────────
# TIER 4: Government research organizations
# Cap-exempt, hire analysts for data, policy, operations
# ─────────────────────────────────────────────────────────────────────────────
GOVERNMENT_RESEARCH_TARGETS = [
    "National Institutes of Health",
    "NIH",
    "Centers for Disease Control",
    "CDC",
    "National Science Foundation",
    "Federal Reserve Bank",
    "Federal Reserve Board",
    "World Bank",
    "International Monetary Fund",
    "Smithsonian Institution",
    "Library of Congress",
    "National Academies of Sciences",
]

# Combined flat list — used by the bot to boost scoring
ALL_CAP_EXEMPT_TARGETS = (
    UNIVERSITY_TARGETS
    + UNIVERSITY_HOSPITAL_TARGETS
    + NONPROFIT_RESEARCH_TARGETS
    + GOVERNMENT_RESEARCH_TARGETS
)

def is_priority_cap_exempt(company: str) -> bool:
    """
    Returns True if company is in our verified cap-exempt target list
    (these are confirmed to hire STEM OPT holders for analyst roles).
    """
    c = company.lower().strip()
    for target in ALL_CAP_EXEMPT_TARGETS:
        if target.lower() in c or c in target.lower():
            return True
    return False

def get_cap_exempt_tier(company: str) -> int:
    """Returns tier (1=best) for cap-exempt companies, 0 if not in list."""
    c = company.lower().strip()
    for t in UNIVERSITY_TARGETS:
        if t.lower() in c or c in t.lower():
            return 1
    for t in UNIVERSITY_HOSPITAL_TARGETS:
        if t.lower() in c or c in t.lower():
            return 2
    for t in NONPROFIT_RESEARCH_TARGETS:
        if t.lower() in c or c in t.lower():
            return 3
    for t in GOVERNMENT_RESEARCH_TARGETS:
        if t.lower() in c or c in t.lower():
            return 4
    return 0

