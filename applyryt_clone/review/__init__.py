"""
review/__init__.py — Approve-before-send review queue

Like Tsenta's "04 · you approve before send" — shows you every tailored
resume change and cover letter before anything is submitted.

HOW IT WORKS:
  1. AI tailors resume → stored in review queue (logs/review_queue.json)
  2. FastAPI server serves a simple web UI at localhost:8080
  3. You see: original bullet vs rewritten bullet (diff view)
  4. You click Approve → job gets submitted
  5. You click Skip → job skipped
  6. auto_approve: true in config → bypasses review (fully hands-off)

UI runs on: http://localhost:8080
"""
import json, time
from pathlib import Path
from utils import log, get_config

ROOT         = Path(__file__).parent.parent
QUEUE_FILE   = ROOT / "logs" / "review_queue.json"

def _load_queue() -> list[dict]:
    QUEUE_FILE.parent.mkdir(parents=True, exist_ok=True)
    if QUEUE_FILE.exists():
        try:
            return json.loads(QUEUE_FILE.read_text())
        except Exception:
            pass
    return []

def _save_queue(queue: list[dict]):
    QUEUE_FILE.write_text(json.dumps(queue, indent=2))

def add_to_queue(job: dict):
    """Add a tailored job to the review queue before submission."""
    queue = _load_queue()
    queue.append({
        **job,
        "status": "pending",
        "queued_at": time.time(),
    })
    _save_queue(queue)
    log.info(f"  [REVIEW] Queued for approval: {job['title']} @ {job['company']}")

def get_pending() -> list[dict]:
    return [j for j in _load_queue() if j.get("status") == "pending"]

def approve(job_id: str):
    queue = _load_queue()
    for j in queue:
        if j.get("id") == job_id:
            j["status"] = "approved"
    _save_queue(queue)

def skip(job_id: str):
    queue = _load_queue()
    for j in queue:
        if j.get("id") == job_id:
            j["status"] = "skipped"
    _save_queue(queue)

def get_approved_and_clear() -> list[dict]:
    """Returns approved jobs and removes them from the queue."""
    queue = _load_queue()
    approved = [j for j in queue if j.get("status") == "approved"]
    remaining = [j for j in queue if j.get("status") != "approved"]
    _save_queue(remaining)
    return approved
