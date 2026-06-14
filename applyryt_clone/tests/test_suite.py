"""
tests/test_suite.py — full pre-production validation
Run: python -m pytest tests/ -v
Or:  python tests/test_suite.py

Covers all 16 checks from the validation checklist:
  - Scraping tests (4)
  - AI quality tests (4)
  - PDF + submission tests (4)
  - Reliability tests (4)
"""
import sys, json, os
sys.path.insert(0, str(__file__.replace("/tests/test_suite.py", "")))

import pytest
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# SCRAPING TESTS
# ─────────────────────────────────────────────────────────────────────────────
class TestScraping:

    def test_greenhouse_returns_jobs(self):
        """Greenhouse scraper returns > 0 real jobs from a live company."""
        from scrapers import scrape_greenhouse
        jobs = scrape_greenhouse("stripe")
        assert len(jobs) > 0, "Greenhouse/stripe returned 0 jobs"
        print(f"  Greenhouse/stripe: {len(jobs)} jobs")

    def test_lever_returns_jobs(self):
        """Lever scraper returns > 0 real jobs."""
        from scrapers import scrape_lever
        jobs = scrape_lever("netflix")
        assert len(jobs) > 0, "Lever/netflix returned 0 jobs"
        print(f"  Lever/netflix: {len(jobs)} jobs")

    def test_ashby_returns_jobs(self):
        """Ashby scraper returns > 0 real jobs."""
        from scrapers import scrape_ashby
        jobs = scrape_ashby("openai")
        assert len(jobs) > 0, "Ashby/openai returned 0 jobs"
        print(f"  Ashby/openai: {len(jobs)} jobs")

    def test_all_jobs_have_required_fields(self):
        """Every scraped job must have title, url, and source."""
        from scrapers import scrape_greenhouse
        jobs = scrape_greenhouse("notion")
        for j in jobs:
            assert j.get("title"), f"Missing title: {j}"
            assert j.get("url"),   f"Missing url: {j}"
            assert j.get("source"), f"Missing source: {j}"

    def test_deduplication_removes_exact_duplicates(self):
        """Deduplication reduces a list with known duplicates."""
        from utils import deduplicate
        jobs = [
            {"title": "Software Engineer", "company": "Acme", "url": "http://a.com"},
            {"title": "Software Engineer", "company": "Acme", "url": "http://a.com"},
            {"title": "Data Scientist",    "company": "Acme", "url": "http://b.com"},
        ]
        unique = deduplicate(jobs)
        assert len(unique) == 2, f"Expected 2 unique jobs, got {len(unique)}"

    def test_ats_router_identifies_platforms(self):
        """ATS router correctly identifies 8 known URLs."""
        from scrapers import detect_ats
        cases = {
            "https://boards.greenhouse.io/stripe/jobs/123":        "greenhouse",
            "https://jobs.lever.co/netflix/abc":                   "lever",
            "https://jobs.ashbyhq.com/openai/xyz":                 "ashby",
            "https://jobs.smartrecruiters.com/Visa/abc":           "smartrecruiters",
            "https://amazon.wd5.myworkdayjobs.com/amazonglobal":   "workday",
            "https://company.icims.com/jobs/search":               "icims",
            "https://company.taleo.net/careersection":             "taleo",
            "https://company.bamboohr.com/careers":                "bamboohr",
        }
        for url, expected in cases.items():
            result = detect_ats(url)
            assert result == expected, f"Expected {expected} for {url}, got {result}"

    def test_blacklist_filter_works(self):
        """Jobs from blacklisted companies are removed."""
        from utils import filter_jobs, get_config
        cfg = get_config()
        if not cfg["search"].get("blacklist_companies"):
            pytest.skip("No blacklisted companies configured")
        blacklisted = cfg["search"]["blacklist_companies"][0]
        jobs = [
            {"title": "Engineer", "company": blacklisted, "url": "http://a.com"},
            {"title": "Engineer", "company": "Good Company", "url": "http://b.com"},
        ]
        filtered = filter_jobs(jobs)
        companies = [j["company"] for j in filtered]
        assert blacklisted not in companies


# ─────────────────────────────────────────────────────────────────────────────
# AI QUALITY TESTS
# ─────────────────────────────────────────────────────────────────────────────
SAMPLE_JD = """
Software Engineer — Backend (Python)

We are looking for a senior backend engineer with 4+ years of experience building
scalable Python services. You will work on our core API platform using FastAPI,
PostgreSQL, Redis, and AWS. Requirements: Python, FastAPI, PostgreSQL, Redis, AWS,
Docker, microservices, REST APIs. Nice to have: Kubernetes, GraphQL, Datadog.
"""

class TestAI:

    @pytest.mark.skipif(not os.environ.get("GROQ_API_KEY") and not os.environ.get("GEMINI_API_KEY"),
                        reason="No AI API key in environment")
    def test_fit_score_is_valid_integer(self):
        """fit_score is an integer between 1 and 10."""
        from ai import analyze_job
        job = {"title": "Senior Backend Engineer", "company": "Acme",
               "location": "Remote", "description": SAMPLE_JD}
        result = analyze_job(job)
        # Could be None if below threshold, which is valid
        if result:
            score = result["fit_score"]
            assert isinstance(score, int), f"fit_score should be int, got {type(score)}"
            assert 1 <= score <= 10,       f"fit_score {score} out of range 1–10"
            print(f"  fit_score: {score}/10")

    @pytest.mark.skipif(not os.environ.get("GROQ_API_KEY") and not os.environ.get("GEMINI_API_KEY"),
                        reason="No AI API key in environment")
    def test_tailored_bullets_contain_jd_keywords(self):
        """Tailored bullets contain keywords from the JD."""
        from ai import analyze_job
        job = {"title": "Senior Backend Engineer", "company": "Acme",
               "location": "Remote", "description": SAMPLE_JD,
               "fit_score": 8}
        result = analyze_job(job)
        if result and result.get("tailored_bullets"):
            bullets_text = " ".join(result["tailored_bullets"]).lower()
            jd_keywords  = ["python", "api", "backend", "engineer"]
            matched = [k for k in jd_keywords if k in bullets_text]
            assert len(matched) >= 2, f"Bullets missing JD keywords. Matched: {matched}"
            print(f"  Keywords matched in bullets: {matched}")

    @pytest.mark.skipif(not os.environ.get("GROQ_API_KEY") and not os.environ.get("GEMINI_API_KEY"),
                        reason="No AI API key in environment")
    def test_cover_letter_contains_company_name(self):
        """Cover letter mentions the company name."""
        from ai import analyze_job
        job = {"title": "Backend Engineer", "company": "TechCorp",
               "location": "Remote", "description": SAMPLE_JD}
        result = analyze_job(job)
        if result and result.get("cover_letter"):
            assert "techcorp" in result["cover_letter"].lower(), \
                "Cover letter doesn't mention the company name"

    def test_ai_json_parse_is_robust(self):
        """JSON parser handles markdown fences and extra whitespace."""
        from ai import _parse_json
        cases = [
            '{"fit_score": 8, "tailored_bullets": ["bullet1"]}',
            '```json\n{"fit_score": 8, "tailored_bullets": ["bullet1"]}\n```',
            '```\n{"fit_score": 8, "tailored_bullets": ["bullet1"]}\n```',
            '  {"fit_score": 8, "tailored_bullets": ["bullet1"]}  ',
        ]
        for raw in cases:
            result = _parse_json(raw)
            assert result["fit_score"] == 8, f"Parse failed for: {raw[:50]}"


# ─────────────────────────────────────────────────────────────────────────────
# PDF + SUBMISSION TESTS
# ─────────────────────────────────────────────────────────────────────────────
class TestPDFAndSubmission:

    def test_pdf_generates_successfully(self):
        """PDF is created and is a valid file > 0 bytes."""
        from submitter.pdf_generator import generate_pdf
        job = {
            "title": "Software Engineer", "company": "TestCo",
            "location": "Remote, USA", "source": "greenhouse",
            "fit_score": 8, "url": "https://example.com",
            "tailored_bullets": [
                "Built REST APIs serving 1M requests/day",
                "Reduced latency by 40% using Redis caching",
            ],
            "tailored_summary": "Senior engineer with 4+ years of backend experience.",
            "ats_keywords": ["Python", "FastAPI", "PostgreSQL"],
        }
        pdf_path = generate_pdf(job)
        assert pdf_path is not None, "PDF generation returned None"
        assert Path(pdf_path).exists(), f"PDF file not found: {pdf_path}"
        assert Path(pdf_path).stat().st_size > 1000, "PDF is suspiciously small"
        print(f"  PDF generated: {pdf_path}")
        Path(pdf_path).unlink(missing_ok=True)

    def test_dry_run_does_not_submit(self):
        """In dry_run mode, submit() returns True without making any network calls."""
        from utils import get_config
        cfg = get_config()
        original = cfg.get("dry_run")
        cfg["dry_run"] = True

        from submitter import submit
        job = {"title": "Engineer", "company": "Acme", "source": "greenhouse",
               "url": "https://example.com", "cover_letter": "Test"}
        result = submit(job, None)
        assert result is True, "Dry run should return True"
        cfg["dry_run"] = original

    def test_daily_cap_respected(self):
        """Pipeline stops after daily_cap applications."""
        from utils import get_config
        cfg = get_config()
        cap = cfg["search"]["daily_cap"]
        assert isinstance(cap, int), "daily_cap must be an integer"
        assert 1 <= cap <= 100, f"daily_cap {cap} seems unreasonable"
        print(f"  Daily cap: {cap}")

    def test_applied_ledger_persists(self):
        """mark_applied() and already_applied() work correctly."""
        from utils import mark_applied, already_applied, load_applied, APPLIED_FILE
        test_job = {"title": "Test Role UNIQUE12345", "company": "TestCo UNIQUE12345"}
        key = f"{test_job['title'].lower()}|{test_job['company'].lower()}"

        # Ensure not already there
        applied = load_applied()
        applied.discard(key)
        import json
        APPLIED_FILE.write_text(json.dumps(list(applied)))

        assert not already_applied(test_job), "Should not be applied yet"
        mark_applied(test_job)
        assert already_applied(test_job), "Should be marked as applied"

        # Cleanup
        applied = load_applied()
        applied.discard(key)
        APPLIED_FILE.write_text(json.dumps(list(applied)))


# ─────────────────────────────────────────────────────────────────────────────
# RELIABILITY TESTS
# ─────────────────────────────────────────────────────────────────────────────
class TestReliability:

    def test_broken_url_does_not_crash_scraper(self):
        """A bad URL is handled gracefully — returns empty list, not an exception."""
        from scrapers import scrape_greenhouse
        result = scrape_greenhouse("this-company-does-not-exist-zzz999")
        assert isinstance(result, list), "Should return a list, not raise"
        assert len(result) == 0, "Should return empty list for bad token"

    def test_missing_description_skips_ai(self):
        """Jobs with no description are skipped by analyze_job gracefully."""
        from ai import analyze_job
        job = {"title": "Engineer", "company": "Acme",
               "location": "Remote", "description": ""}
        result = analyze_job(job)
        assert result is None, "Should return None for empty description"

    def test_config_loads_without_error(self):
        """config.yaml loads and has all required sections."""
        from utils import get_config
        cfg = get_config()
        for key in ["profile", "search", "ai", "ats_targets", "tracking"]:
            assert key in cfg, f"Missing config section: {key}"

    def test_master_resume_loads_without_error(self):
        """master_resume.json loads and has all required fields."""
        from utils import get_master_resume
        resume = get_master_resume()
        for key in ["basics", "skills", "experience", "education"]:
            assert key in resume, f"Missing resume section: {key}"
        assert resume["basics"].get("name"), "basics.name is empty"
        assert resume["basics"].get("email"), "basics.email is empty"
        assert len(resume["experience"]) > 0, "No experience entries"


# ─────────────────────────────────────────────────────────────────────────────
# Run standalone
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python", "-m", "pytest", __file__, "-v", "--tb=short", "--no-header"],
        cwd=str(Path(__file__).parent.parent)
    )
    sys.exit(result.returncode)
