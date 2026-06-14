"""
scrapers/platforms.py — CONSOLIDATED, high-confidence sources only

After live testing (June 2026), the following sources were CUT because they
returned 0 results, errored, or required paid/registered API keys:
  RemoteOK, TheMuse, YCombinator, USAJobs, We Work Remotely,
  Wellfound, Dice, Otta, BuiltIn, Remotive, Jobicy, Arbeitnow

What remains and is PROVEN to work:
  - JobSpy (LinkedIn, Indeed, Google Jobs) → scrapers/discovery.py::search_jobboards
  - Direct ATS APIs (Greenhouse, Lever, Ashby, Workday, SmartRecruiters)
    → scrapers/discovery.py::find_jobs_for_role

This file is now a thin pass-through kept only so existing imports in main.py
don't break. scrape_all_platforms() returns an empty list — all real work
happens in scrapers/discovery.py.
"""
from utils import log


def scrape_all_platforms(role: str) -> list[dict]:
    """
    No-op. All job collection now happens via:
      - scrapers.discovery.search_jobboards()  (LinkedIn/Indeed/Google via JobSpy)
      - scrapers.discovery.find_jobs_for_role() (Greenhouse/Lever/Ashby/Workday/SmartRecruiters)
    Kept for backward compatibility with main.py imports.
    """
    log.debug("scrape_all_platforms: skipped (consolidated into discovery.py)")
    return []
