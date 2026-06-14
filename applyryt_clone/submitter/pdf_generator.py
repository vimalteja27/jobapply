"""
submitter/pdf_generator.py — generates a tailored PDF resume per job
Uses weasyprint (free). HTML template is filled with AI-tailored content.
"""
from pathlib import Path
from datetime import datetime
from utils import log, get_config, get_master_resume

OUTPUT_DIR = Path(__file__).parent.parent / "resumes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

RESUME_HTML = """
<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 10.5pt; color: #1a1a1a; padding: 28px 36px; line-height: 1.4; }}
  h1 {{ font-size: 20pt; font-weight: 700; letter-spacing: -0.3px; }}
  .contact {{ font-size: 9pt; color: #444; margin-top: 3px; }}
  .contact a {{ color: #1a56db; text-decoration: none; }}
  hr {{ border: none; border-top: 1.5px solid #1a1a1a; margin: 8px 0 6px; }}
  .section-title {{ font-size: 10pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.8px; margin: 10px 0 4px; border-bottom: 0.5px solid #ccc; padding-bottom: 2px; }}
  .summary {{ font-size: 10pt; color: #333; margin-bottom: 6px; }}
  .job {{ margin-bottom: 8px; }}
  .job-header {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .job-title {{ font-weight: 700; font-size: 10.5pt; }}
  .job-company {{ font-size: 10pt; color: #333; }}
  .job-date {{ font-size: 9pt; color: #666; white-space: nowrap; }}
  ul {{ margin: 3px 0 0 14px; }}
  li {{ font-size: 10pt; margin-bottom: 2px; }}
  .skills-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2px 20px; }}
  .skill-row {{ font-size: 9.5pt; }}
  .skill-cat {{ font-weight: 600; }}
  .edu {{ display: flex; justify-content: space-between; }}
  .edu-left .deg {{ font-weight: 700; }}
  .project {{ margin-bottom: 5px; }}
  .proj-name {{ font-weight: 700; font-size: 10pt; }}
  .proj-desc {{ font-size: 9.5pt; color: #333; }}
  .certs {{ font-size: 9.5pt; }}
  @page {{ margin: 0; }}
</style>
</head>
<body>

<h1>{name}</h1>
<div class="contact">
  {email} &nbsp;|&nbsp; {phone} &nbsp;|&nbsp;
  <a href="{linkedin}">{linkedin_short}</a> &nbsp;|&nbsp;
  <a href="{github}">{github_short}</a> &nbsp;|&nbsp;
  {location}
</div>
<hr>

<div class="section-title">Summary</div>
<div class="summary">{tailored_summary}</div>

<div class="section-title">Skills</div>
<div class="skills-grid">
  <div class="skill-row"><span class="skill-cat">Languages:</span> {languages}</div>
  <div class="skill-row"><span class="skill-cat">Frameworks:</span> {frameworks}</div>
  <div class="skill-row"><span class="skill-cat">Databases:</span> {databases}</div>
  <div class="skill-row"><span class="skill-cat">Cloud / Tools:</span> {cloud}</div>
</div>

<div class="section-title">Experience</div>
{experience_html}

<div class="section-title">Projects</div>
{projects_html}

<div class="section-title">Education</div>
{education_html}

{certs_html}

</body>
</html>
"""

def _build_experience_html(master: dict, tailored_bullets: list[str]) -> str:
    html = ""
    for i, exp in enumerate(master.get("experience", [])):
        bullets = tailored_bullets if i == 0 else exp.get("bullets", [])
        bullet_html = "\n".join(f"<li>{b}</li>" for b in bullets)
        html += f"""
        <div class="job">
          <div class="job-header">
            <div><span class="job-title">{exp['role']}</span> &nbsp;·&nbsp; <span class="job-company">{exp['company']}</span></div>
            <div class="job-date">{exp['start']} – {exp['end']}</div>
          </div>
          <ul>{bullet_html}</ul>
        </div>"""
    return html

def _build_projects_html(master: dict) -> str:
    html = ""
    for p in master.get("projects", []):
        tech = ", ".join(p.get("tech", []))
        html += f"""
        <div class="project">
          <span class="proj-name">{p['name']}</span> &nbsp;·&nbsp; <span style="font-size:9pt;color:#666">{tech}</span><br>
          <span class="proj-desc">{p['description']}</span>
        </div>"""
    return html

def _build_education_html(master: dict) -> str:
    html = ""
    for e in master.get("education", []):
        html += f"""
        <div class="edu">
          <div class="edu-left">
            <div class="deg">{e['degree']} — {e['institution']}</div>
            <div style="font-size:9pt;color:#555">GPA: {e.get('gpa','')} &nbsp;|&nbsp; {', '.join(e.get('relevant_courses',[])[:4])}</div>
          </div>
          <div class="job-date">{e['graduation']}</div>
        </div>"""
    return html

def _build_certs_html(master: dict) -> str:
    certs = master.get("certifications", [])
    if not certs:
        return ""
    items = " &nbsp;·&nbsp; ".join(certs)
    return f'<div class="section-title">Certifications</div><div class="certs">{items}</div>'


def generate_pdf(job: dict) -> str | None:
    """
    Generates a tailored PDF resume for a given job.
    Returns the output file path, or None if generation fails.
    """
    try:
        from weasyprint import HTML
        cfg = get_config()
        master = get_master_resume()
        basics = master["basics"]
        skills = master.get("skills", {})

        filename = f"{job['company'].replace(' ','_')}_{job['title'].replace(' ','_')}_{datetime.now().strftime('%Y%m%d')}.pdf"
        filename = "".join(c for c in filename if c.isalnum() or c in "_-.")
        out_path = OUTPUT_DIR / filename

        html_content = RESUME_HTML.format(
            name=basics["name"],
            email=basics["email"],
            phone=basics["phone"],
            linkedin=basics.get("linkedin", ""),
            linkedin_short=basics.get("linkedin", "").replace("https://", ""),
            github=basics.get("github", ""),
            github_short=basics.get("github", "").replace("https://", ""),
            location=basics.get("location", ""),
            tailored_summary=job.get("tailored_summary", basics.get("summary", "")),
            languages=", ".join(skills.get("languages", [])),
            frameworks=", ".join(skills.get("frameworks", [])),
            databases=", ".join(skills.get("databases", [])),
            cloud=", ".join(skills.get("cloud", []) + skills.get("tools", []))[:80],
            experience_html=_build_experience_html(master, job.get("tailored_bullets", [])),
            projects_html=_build_projects_html(master),
            education_html=_build_education_html(master),
            certs_html=_build_certs_html(master),
        )

        HTML(string=html_content).write_pdf(str(out_path))
        log.info(f"  PDF generated: {out_path.name}")
        return str(out_path)

    except Exception as e:
        err_str = str(e)
        if "libpango" in err_str or "libgobject" in err_str or "cannot load library" in err_str:
            log.warning(
                f"PDF generation failed for {job['title']} @ {job['company']}: "
                f"weasyprint is missing system libraries (Pango/Cairo). "
                f"Fix with: brew install pango  (then restart your terminal). "
                f"Continuing without PDF — application will proceed with cover letter only."
            )
        else:
            log.warning(f"PDF generation failed for {job['title']} @ {job['company']}: {e}")
        return None
