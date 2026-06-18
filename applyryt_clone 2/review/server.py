"""
review/server.py — Approve-before-send web UI

Run: python -m review.server
Opens at: http://localhost:8080

Shows each pending application with:
  - Job title, company, source, H1B status
  - Side-by-side: original resume bullets vs AI-tailored bullets
  - AI-generated cover letter
  - Fit score and reasoning
  - [Approve] [Skip] buttons

Requires: pip install fastapi uvicorn
"""
import sys, json
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
from review import _load_queue, approve, skip

app = FastAPI()

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<title>ApplyRyt — Review Queue</title>
<meta charset="utf-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
          background: #f5f5f5; color: #1a1a1a; }}
  .header {{ background: #1a1a1a; color: white; padding: 16px 24px;
             display: flex; align-items: center; gap: 12px; }}
  .header h1 {{ font-size: 18px; font-weight: 600; }}
  .stats {{ font-size: 13px; color: #888; margin-left: auto; }}
  .container {{ max-width: 900px; margin: 24px auto; padding: 0 16px; }}
  .empty {{ text-align: center; padding: 80px; color: #888; font-size: 15px; }}
  .job-card {{ background: white; border-radius: 12px; margin-bottom: 20px;
               box-shadow: 0 1px 3px rgba(0,0,0,0.1); overflow: hidden; }}
  .job-header {{ padding: 16px 20px; border-bottom: 1px solid #f0f0f0;
                 display: flex; align-items: center; gap: 12px; }}
  .score {{ width: 44px; height: 44px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center; font-weight: 700;
            font-size: 15px; flex-shrink: 0; }}
  .score-high {{ background: #d1fae5; color: #065f46; }}
  .score-med  {{ background: #fef3c7; color: #92400e; }}
  .score-low  {{ background: #fee2e2; color: #991b1b; }}
  .job-info h2 {{ font-size: 16px; font-weight: 600; margin-bottom: 2px; }}
  .job-meta {{ font-size: 12px; color: #666; }}
  .h1b-tag {{ font-size: 11px; padding: 2px 8px; border-radius: 10px;
              font-weight: 500; margin-left: 8px; }}
  .h1b-sponsor {{ background: #d1fae5; color: #065f46; }}
  .h1b-exempt  {{ background: #dbeafe; color: #1e40af; }}
  .h1b-none    {{ background: #f3f4f6; color: #6b7280; }}
  .section {{ padding: 16px 20px; border-bottom: 1px solid #f0f0f0; }}
  .section-title {{ font-size: 12px; font-weight: 600; color: #888;
                    text-transform: uppercase; letter-spacing: 0.5px;
                    margin-bottom: 10px; }}
  .diff-row {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px;
               margin-bottom: 8px; }}
  .original {{ background: #fff5f5; border-left: 3px solid #fca5a5;
               padding: 8px 12px; border-radius: 4px; font-size: 13px;
               color: #7f1d1d; text-decoration: line-through; opacity: 0.7; }}
  .tailored {{ background: #f0fdf4; border-left: 3px solid #86efac;
               padding: 8px 12px; border-radius: 4px; font-size: 13px;
               color: #14532d; }}
  .cover-letter {{ background: #f8fafc; padding: 12px; border-radius: 8px;
                   font-size: 13px; line-height: 1.6; color: #374151; }}
  .reasoning {{ font-size: 13px; color: #666; font-style: italic; }}
  .actions {{ padding: 16px 20px; display: flex; gap: 10px; }}
  .btn {{ padding: 10px 24px; border-radius: 8px; font-size: 14px;
          font-weight: 500; cursor: pointer; border: none; transition: all 0.1s; }}
  .btn-approve {{ background: #10b981; color: white; }}
  .btn-approve:hover {{ background: #059669; }}
  .btn-skip {{ background: #f3f4f6; color: #6b7280; }}
  .btn-skip:hover {{ background: #e5e7eb; }}
  .btn-view {{ background: #3b82f6; color: white; font-size: 12px;
               padding: 6px 14px; }}
  .all-approve {{ background: #1a1a1a; color: white; padding: 12px 24px;
                  border-radius: 8px; font-size: 14px; font-weight: 500;
                  cursor: pointer; border: none; margin-bottom: 20px; }}
  .keywords {{ display: flex; flex-wrap: wrap; gap: 6px; }}
  .kw-tag {{ background: #eff6ff; color: #1d4ed8; font-size: 11px;
             padding: 2px 8px; border-radius: 10px; }}
</style>
</head>
<body>
<div class="header">
  <h1>ApplyRyt Review Queue</h1>
  <div class="stats">{pending_count} pending &nbsp;·&nbsp; {approved_count} approved today</div>
</div>
<div class="container">
{content}
</div>
<script>
async function approveJob(id) {{
  await fetch('/approve/' + id, {{method:'POST'}});
  document.getElementById('card-' + id).style.opacity = '0.3';
  document.getElementById('card-' + id).style.pointerEvents = 'none';
  document.getElementById('status-' + id).textContent = '✅ Approved — will be submitted next run';
}}
async function skipJob(id) {{
  await fetch('/skip/' + id, {{method:'POST'}});
  document.getElementById('card-' + id).style.display = 'none';
}}
async function approveAll() {{
  const pending = document.querySelectorAll('[data-pending]');
  for (const el of pending) {{
    await approveJob(el.dataset.id);
    await new Promise(r => setTimeout(r, 200));
  }}
}}
</script>
</body>
</html>"""

def _score_class(score):
    if score >= 8: return "score-high"
    if score >= 6: return "score-med"
    return "score-low"

def _h1b_class(h1b):
    if "Sponsor" in h1b: return "h1b-sponsor"
    if "Exempt" in h1b:  return "h1b-exempt"
    return "h1b-none"

def _render_queue():
    queue  = _load_queue()
    pending  = [j for j in queue if j.get("status") == "pending"]
    approved = [j for j in queue if j.get("status") == "approved"]

    if not pending:
        content = '<div class="empty">🎉 No pending applications.<br>The bot will add new matches here automatically.</div>'
    else:
        cards = [f'<button class="all-approve" onclick="approveAll()">Approve All {len(pending)} Applications</button>']
        for job in pending:
            jid   = job.get("id", job.get("title","")[:20].replace(" ","_"))
            score = job.get("fit_score", 0)
            h1b   = job.get("h1b_history","❓ No H1B Record")
            orig_bullets  = job.get("original_bullets", [])
            tail_bullets  = job.get("tailored_bullets", [])
            cover = job.get("cover_letter","")
            keywords = job.get("ats_keywords",[])[:8]

            diff_rows = ""
            for orig, tail in zip(orig_bullets[:4], tail_bullets[:4]):
                diff_rows += f'''
                <div class="diff-row">
                  <div class="original">− {orig}</div>
                  <div class="tailored">+ {tail}</div>
                </div>'''

            kw_html = " ".join(f'<span class="kw-tag">{k}</span>' for k in keywords)

            cards.append(f'''
            <div class="job-card" id="card-{jid}" data-pending data-id="{jid}">
              <div class="job-header">
                <div class="score {_score_class(score)}">{score}/10</div>
                <div class="job-info">
                  <h2>{job.get("title","")} <span style="color:#888;font-weight:400">@</span> {job.get("company","")}</h2>
                  <div class="job-meta">
                    {job.get("source","").upper()} · {job.get("location","")}
                    <span class="h1b-tag {_h1b_class(h1b)}">{h1b}</span>
                  </div>
                </div>
                <a href="{job.get("url","#")}" target="_blank">
                  <button class="btn btn-view">View Job →</button>
                </a>
              </div>
              <div class="section">
                <div class="section-title">Resume Changes (AI-tailored for this role)</div>
                {diff_rows if diff_rows else '<p style="color:#888;font-size:13px">No bullet changes — original bullets are already a strong match.</p>'}
              </div>
              <div class="section">
                <div class="section-title">Cover Letter</div>
                <div class="cover-letter">{cover or "No cover letter generated."}</div>
              </div>
              <div class="section">
                <div class="section-title">ATS Keywords Matched</div>
                <div class="keywords">{kw_html}</div>
              </div>
              <div class="section">
                <div class="section-title">Fit Reasoning</div>
                <div class="reasoning">{job.get("fit_reasoning","")}</div>
              </div>
              <div class="actions">
                <button class="btn btn-approve" onclick="approveJob('{jid}')">✅ Approve & Submit</button>
                <button class="btn btn-skip" onclick="skipJob('{jid}')">Skip</button>
                <span id="status-{jid}" style="font-size:13px;color:#666;margin-left:auto;align-self:center;"></span>
              </div>
            </div>''')
        content = "\n".join(cards)

    return HTML_TEMPLATE.format(
        pending_count=len(pending),
        approved_count=len(approved),
        content=content,
    )

@app.get("/", response_class=HTMLResponse)
def index():
    return _render_queue()

@app.post("/approve/{job_id}")
def approve_job(job_id: str):
    approve(job_id)
    return {"status": "approved"}

@app.post("/skip/{job_id}")
def skip_job(job_id: str):
    skip(job_id)
    return {"status": "skipped"}

@app.get("/api/pending")
def api_pending():
    return get_pending()

if __name__ == "__main__":
    print("\n  ApplyRyt Review Queue")
    print("  Open in browser: http://localhost:8080")
    print("  Approve or skip each application before it's submitted\n")
    uvicorn.run(app, host="0.0.0.0", port=8080, log_level="error")
