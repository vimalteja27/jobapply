"""
ai/__init__.py — Resume tailoring and job scoring via Groq (free)

For every job:
  1. Reads the full job description
  2. Reads your master_resume.json (all your experience, skills, bullets)
  3. Scores fit 1-10
  4. Rewrites your resume bullets to mirror the JD's exact language/keywords
  5. Writes a custom cover letter specific to that job
  6. Returns the enriched job dict with tailored_bullets, cover_letter, fit_score
"""
import os, json, re, time
from utils import log, get_config, get_master_resume

MODEL   = "openai/gpt-oss-20b"
API_URL = "https://api.groq.com/openai/v1/chat/completions"

TAILOR_PROMPT = """You are an expert resume writer. Tailor this candidate's resume for the specific job below.

=== JOB POSTING ===
Title: {title}
Company: {company}
Description:
{description}

=== CANDIDATE MASTER RESUME ===
{master_resume}

=== YOUR TASK ===
1. Score the fit 1-10 (10 = perfect match)
2. Select the 4-6 most relevant experience bullets from the candidate's history
3. REWRITE each selected bullet to mirror the job description's exact language,
   keywords, and requirements — while staying factually accurate to what the
   candidate actually did. Do not fabricate experience.
4. Reorder skills to put the most relevant ones first
5. Write a 3-sentence cover letter opening specific to THIS job and company

Return ONLY valid JSON, no markdown fences:
{{
  "fit_score": <1-10>,
  "fit_reasoning": "<one sentence why this is a good/bad fit>",
  "tailored_bullets": [
    "<rewritten bullet 1 mirroring JD language>",
    "<rewritten bullet 2>",
    "<rewritten bullet 3>",
    "<rewritten bullet 4>"
  ],
  "relevant_skills": ["<skill1>", "<skill2>", ...],
  "cover_letter": "<3 sentences specific to this job and company>",
  "ats_keywords": ["<keyword from JD>", "<keyword2>", ...]
}}"""


def _call_groq(prompt: str, retries: int = 3) -> str:
    api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise KeyError("GROQ_API_KEY")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "User-Agent":    "Mozilla/5.0",
    }
    payload = {
        "model":       MODEL,
        "max_tokens":  1500,
        "temperature": 0.3,
        "messages":    [{"role": "user", "content": prompt}],
    }

    import urllib.request
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(
                API_URL, method="POST",
                data=json.dumps(payload).encode(),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            time.sleep(2)  # respect Groq's 30 RPM rate limit (max 1 req/2s)
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            if attempt < retries:
                time.sleep(2 ** attempt)
            else:
                raise e


def _parse_json(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    clean = re.sub(r"```(?:json)?", "", raw).strip()
    m = re.search(r"\{.*\}", clean, re.DOTALL)
    if m:
        return json.loads(m.group(0))
    return json.loads(clean)


def analyze_job(job: dict) -> dict | None:
    """
    Scores the job and generates tailored resume content.
    Returns the job dict enriched with tailoring data, or None if below threshold.
    """
    cfg         = get_config()
    threshold   = cfg["search"]["min_fit_score"]
    master      = get_master_resume()
    description = (job.get("description") or "").strip()

    if not description:
        log.warning(f"  No description for {job['title']} @ {job['company']} "
                    f"— skipping AI analysis")
        return None

    resume_summary = _compact_resume(master)

    prompt = TAILOR_PROMPT.format(
        title=job.get("title", ""),
        company=job.get("company", ""),
        description=description[:3000],
        master_resume=resume_summary,
    )

    try:
        raw    = _call_groq(prompt)
        result = _parse_json(raw)

        fit_score = int(result.get("fit_score", 0))
        log.info(f"  Score {fit_score}/10 — {job['title']} @ {job['company']}  "
                 f"({result.get('fit_reasoning','')[:80]})")

        if fit_score < threshold:
            log.debug(f"  Skipped (score {fit_score} < {threshold})")
            return None

        return {
            **job,
            "fit_score":        fit_score,
            "fit_reasoning":    result.get("fit_reasoning", ""),
            "tailored_bullets": result.get("tailored_bullets", []),
            "relevant_skills":  result.get("relevant_skills", []),
            "cover_letter":     result.get("cover_letter", ""),
            "ats_keywords":     result.get("ats_keywords", []),
        }

    except KeyError:
        log.warning(f"  AI analysis failed for {job['title']} @ {job['company']}: "
                    f"GROQ_API_KEY not set. Run: export GROQ_API_KEY=gsk_...")
        return None
    except Exception as e:
        log.warning(f"  AI analysis failed for {job['title']} @ {job['company']}: {e}")
        return None


def _compact_resume(master: dict) -> str:
    """Compact master_resume.json into a token-efficient string for the prompt."""
    lines = []

    basics = master.get("basics", {})
    lines.append(f"Name: {basics.get('name','')}")
    lines.append(f"Summary: {basics.get('summary','')}")

    skills = master.get("skills", {})
    all_skills = []
    for v in skills.values():
        if isinstance(v, list):
            all_skills.extend(v)
    lines.append(f"Skills: {', '.join(all_skills[:30])}")

    lines.append("\nExperience:")
    for exp in master.get("experience", []):
        lines.append(f"\n{exp.get('role','')} at {exp.get('company','')} "
                     f"({exp.get('start','')} - {exp.get('end','')})")
        for bullet in exp.get("bullets", []):
            lines.append(f"  • {bullet}")

    lines.append("\nEducation:")
    for edu in master.get("education", []):
        lines.append(f"  {edu.get('degree','')} — {edu.get('institution','')}")

    certs = master.get("certifications", [])
    if certs:
        lines.append(f"\nCertifications: {', '.join(certs)}")

    return "\n".join(lines)


# Expose for other modules (form_questions.py)
def _call_ai(prompt: str) -> str:
    return _call_groq(prompt)