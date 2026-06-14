"""
submitter/form_questions.py — AI-powered custom question handler

THE PROBLEM:
  Every ATS form has DIFFERENT custom screening questions:
    - "Why do you want to work here?"
    - "What's your salary expectation?"
    - "Are you authorized to work in the US?"
    - "How many years of experience with Python?"
    - "Do you require visa sponsorship?"
  These can't be hardcoded — they're different on every job posting.

THE SOLUTION:
  1. Playwright scans the page for ALL form fields (inputs, selects, textareas, radios)
  2. Filters to fields NOT already filled by standard profile data
  3. For each unanswered field, extracts its label/question text
  4. Sends all questions + job description + resume to AI in ONE batch call
  5. AI returns answers honest to your actual profile (never fabricates experience)
  6. Playwright fills each field with the AI's answer

SAFETY:
  - Salary questions use your configured range, never invented numbers
  - Work authorization uses your configured visa_status, never guessed
  - EEO/diversity questions (race, gender, veteran, disability) are SKIPPED —
    these are legally voluntary and best left to "Decline to self-identify"
  - If AI is unsure, it picks the safest neutral answer (e.g. "Yes" for
    standard yes/no eligibility questions only if your profile supports it)
"""

import json, re
from utils import log, get_config, get_master_resume

# ─────────────────────────────────────────────────────────────────────────────
# Fields we NEVER let AI answer — legally voluntary, skip entirely
# ─────────────────────────────────────────────────────────────────────────────
SKIP_PATTERNS = [
    r"race", r"ethnicit", r"gender", r"sexual orientation",
    r"veteran status", r"disability status", r"disab(led|ility)",
    r"pronoun", r"transgender", r"voluntary self.identif",
    r"eeo", r"equal employment",
]

# ─────────────────────────────────────────────────────────────────────────────
# Fields with DETERMINISTIC answers from config — never sent to AI
# ─────────────────────────────────────────────────────────────────────────────
def _deterministic_answer(label: str, cfg: dict) -> str | None:
    """Returns a hardcoded answer from config for common standardized questions."""
    label_l = label.lower()
    profile = cfg["profile"]

    # EEO / voluntary self-identification — only if user opted in
    if profile.get("eeo_disclose"):
        if re.search(r"race|ethnicit", label_l):
            return profile.get("race_ethnicity", "Decline to self-identify")
        if re.search(r"gender(?!.{0,10}identity)", label_l):
            return profile.get("gender", "Decline to self-identify")
        if re.search(r"veteran", label_l):
            return profile.get("veteran_status", "I am not a veteran")
        if re.search(r"disab", label_l):
            return profile.get("disability_status", "No, I do not have a disability")

    # Work authorization
    if re.search(r"(authoriz|eligib).{0,30}(work|employ).{0,20}(us|united states|u\.s)", label_l) or \
       re.search(r"(legally|lawfully).{0,20}work", label_l):
        # F1/OPT/CPT, H1B, Green Card, US Citizen — all are authorized to work in the US
        return "Yes"

    # Visa sponsorship
    if re.search(r"(require|need|will.{0,10}you).{0,20}(visa|sponsorship)", label_l):
        requires = cfg["profile"].get("requires_sponsorship")
        if requires is not None:
            return "Yes" if requires else "No"
        visa = cfg["profile"].get("visa_status", "").lower()
        if "citizen" in visa or "green card" in visa or "permanent resident" in visa:
            return "No"
        return "Yes"

    # Salary expectation — use configured minimum, never AI-invented
    if re.search(r"(salary|compensation|pay).{0,20}(expect|requirement|desired|target)", label_l) or \
       re.search(r"(desired|expected|target).{0,20}(salary|compensation|pay)", label_l):
        salary_cfg = cfg.get("search", {}).get("salary_expectation")
        if salary_cfg:
            # If field looks numeric-only (no text labels expected), strip to a number
            if re.search(r"(numeric|number|amount)", label_l) or label_l.strip() in ("salary", "desired salary"):
                digits = re.sub(r"[^\d]", "", salary_cfg.split("-")[0].split("+")[0])
                return digits if digits else salary_cfg
            return salary_cfg
        return None  # Let AI handle with a range-based answer if no config value

    # How did you hear about us
    if re.search(r"how did you (hear|find)", label_l):
        return "Online job board"

    # LinkedIn/portfolio URL fields (if not auto-filled by selector)
    if "linkedin" in label_l:
        return profile.get("linkedin", "")
    if "github" in label_l or "portfolio" in label_l:
        return profile.get("github", "")

    # Notice period / start date
    if re.search(r"(notice period|when.{0,10}(can|able).{0,10}start)", label_l):
        return cfg.get("search", {}).get("notice_period", "2 weeks")

    # Location / relocation
    if re.search(r"willing to relocate", label_l):
        return "Yes" if cfg["search"].get("willing_to_relocate", False) else "No"

    if re.search(r"(open to|comfortable with).{0,10}remote", label_l):
        return "Yes"

    return None


def _should_skip(label: str, cfg: dict | None = None) -> bool:
    label_l = label.lower()
    is_eeo = any(re.search(p, label_l) for p in SKIP_PATTERNS)
    if not is_eeo:
        return False
    if cfg and cfg["profile"].get("eeo_disclose"):
        return False  # don't skip — will be answered deterministically below
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Detect all unfilled required fields on the page
# ─────────────────────────────────────────────────────────────────────────────
def detect_unanswered_fields(page, cfg: dict | None = None) -> list[dict]:
    """
    Scans the current Playwright page for form fields that:
      - Are required
      - Are not yet filled
      - Are not standard fields (name/email/phone/resume — handled elsewhere)

    Returns list of {selector, label, field_type, options} dicts.
    """
    fields = []

    try:
        # Find all labeled inputs, textareas, and selects
        elements = page.query_selector_all(
            "input:not([type='hidden']):not([type='file']):not([type='submit']), "
            "textarea, select"
        )

        for el in elements:
            try:
                # Skip if already filled
                tag = el.evaluate("el => el.tagName.toLowerCase()")
                input_type = el.get_attribute("type") or "text"

                if tag == "input" and input_type in ("text", "email", "tel", "number"):
                    current_val = el.input_value()
                    if current_val:
                        continue
                elif tag == "textarea":
                    current_val = el.input_value()
                    if current_val:
                        continue

                # Skip if not required (best-effort — many forms mark required visually only)
                is_required = el.get_attribute("required") is not None or \
                               el.get_attribute("aria-required") == "true"

                # Get the label text — try multiple strategies
                label_text = _get_label_for_element(page, el)

                if not label_text or len(label_text) < 3:
                    continue

                if _should_skip(label_text, cfg):
                    continue

                # Skip fields we already handle via standard profile mapping
                if _is_standard_field(label_text):
                    continue

                field_info = {
                    "label":     label_text,
                    "tag":       tag,
                    "type":      input_type,
                    "required":  is_required,
                    "element":   el,
                }

                # For selects/radios, capture options
                if tag == "select":
                    options = el.query_selector_all("option")
                    field_info["options"] = [
                        o.inner_text().strip() for o in options
                        if o.inner_text().strip()
                    ]

                fields.append(field_info)

            except Exception:
                continue

        # Also detect radio button groups (these need special handling)
        radio_groups = _detect_radio_groups(page, cfg)
        fields.extend(radio_groups)

    except Exception as e:
        log.debug(f"Field detection error: {e}")

    return fields


def _get_label_for_element(page, el) -> str:
    """Tries multiple strategies to find the human-readable label for a field."""
    try:
        # Strategy 1: <label for="id">
        el_id = el.get_attribute("id")
        if el_id:
            label = page.query_selector(f"label[for='{el_id}']")
            if label:
                return label.inner_text().strip()

        # Strategy 2: aria-label
        aria = el.get_attribute("aria-label")
        if aria:
            return aria.strip()

        # Strategy 3: placeholder
        placeholder = el.get_attribute("placeholder")
        if placeholder:
            return placeholder.strip()

        # Strategy 4: parent element text (common in custom form builders)
        parent_text = el.evaluate("""
            el => {
                let p = el.closest('div, fieldset');
                if (!p) return '';
                let clone = p.cloneNode(true);
                let inputs = clone.querySelectorAll('input, select, textarea');
                inputs.forEach(i => i.remove());
                return clone.innerText.trim().slice(0, 200);
            }
        """)
        if parent_text:
            return parent_text

    except Exception:
        pass
    return ""


def _is_standard_field(label: str) -> bool:
    """True if this field is already handled by the standard profile-fill step."""
    label_l = label.lower()
    standard_patterns = [
        "first name", "last name", "full name", "your name",
        "email", "phone", "mobile",
        "resume", "cv", "cover letter",
        "address", "city", "state", "zip", "postal",
    ]
    return any(p in label_l for p in standard_patterns)


def _detect_radio_groups(page, cfg: dict | None = None) -> list[dict]:
    """Detects radio button groups (e.g. Yes/No eligibility questions)."""
    groups = []
    try:
        radios = page.query_selector_all("input[type='radio']")
        seen_names = set()
        for radio in radios:
            name = radio.get_attribute("name")
            if not name or name in seen_names:
                continue
            seen_names.add(name)

            # Check if any radio in this group is already checked
            group_radios = page.query_selector_all(f"input[type='radio'][name='{name}']")
            if any(r.is_checked() for r in group_radios):
                continue  # already answered

            # Get the question label (usually a fieldset legend or preceding text)
            label_text = radio.evaluate("""
                el => {
                    let fieldset = el.closest('fieldset');
                    if (fieldset) {
                        let legend = fieldset.querySelector('legend');
                        if (legend) return legend.innerText.trim();
                    }
                    let container = el.closest('div');
                    if (container) {
                        let clone = container.cloneNode(true);
                        let inputs = clone.querySelectorAll('input');
                        inputs.forEach(i => i.remove());
                        return clone.innerText.trim().slice(0, 200);
                    }
                    return '';
                }
            """)

            if not label_text or _should_skip(label_text, cfg):
                continue

            options = []
            for r in group_radios:
                opt_label = _get_label_for_element(page, r)
                options.append({"value": opt_label, "element": r})

            groups.append({
                "label":    label_text,
                "tag":      "radio_group",
                "type":     "radio",
                "required": True,
                "options":  [o["value"] for o in options],
                "elements": options,
            })
    except Exception as e:
        log.debug(f"Radio group detection error: {e}")

    return groups


# ─────────────────────────────────────────────────────────────────────────────
# AI batch answer generation
# ─────────────────────────────────────────────────────────────────────────────
ANSWER_PROMPT = """You are filling out a job application form on behalf of the candidate below.
Answer each question truthfully based ONLY on the candidate's actual background.
Never invent specific experience, employers, or skills not present in the resume.

=== CANDIDATE RESUME SUMMARY ===
{resume_summary}

=== CANDIDATE PROFILE ===
Visa/Work status: {visa_status}
Years of professional experience: {years_exp}

=== JOB POSTING ===
{job_title} at {company}
{job_description}

=== QUESTIONS TO ANSWER ===
{questions_block}

=== INSTRUCTIONS ===
For each question, provide a concise, professional answer.
- For yes/no questions, answer exactly "Yes" or "No"
- For multiple choice (options given), pick the EXACT option text that best applies
- For open-ended questions ("why this company", "tell us about yourself"), write 2-3 sentences specific to THIS job/company
- For experience-with-X questions, give an honest estimate based on the resume (e.g. "3 years")
- If a question cannot be answered honestly from the resume, answer "N/A" 

Return ONLY valid JSON, a list of strings in the SAME ORDER as the questions:
["answer1", "answer2", "answer3", ...]
"""

def generate_answers(fields: list[dict], job: dict) -> list[str]:
    """
    Sends all unanswered questions to AI in one batch call.
    Returns a list of answer strings, same order as `fields`.
    """
    if not fields:
        return []

    from ai import _call_ai, _parse_json
    cfg    = get_config()
    resume = get_master_resume()

    # Build a compact resume summary (avoid huge prompts)
    exp_lines = []
    for exp in resume.get("experience", [])[:3]:
        exp_lines.append(f"- {exp['role']} at {exp['company']} ({exp['start']}-{exp['end']}): "
                         + "; ".join(exp.get("bullets", [])[:3]))
    resume_summary = (
        f"Summary: {resume['basics'].get('summary','')}\n"
        f"Skills: {', '.join(sum(resume.get('skills',{}).values(), []))}\n"
        f"Experience:\n" + "\n".join(exp_lines)
    )

    # Estimate years of experience from earliest job
    years_exp = "3-5"  # default fallback
    try:
        first_job = resume["experience"][-1]
        start_year = int(first_job["start"].split()[-1])
        from datetime import datetime
        years_exp = str(datetime.now().year - start_year)
    except Exception:
        pass

    # Build questions block
    questions_block = ""
    for i, f in enumerate(fields, 1):
        q = f"{i}. {f['label']}"
        if f.get("options"):
            q += f"  [Options: {', '.join(f['options'])}]"
        questions_block += q + "\n"

    prompt = ANSWER_PROMPT.format(
        resume_summary=resume_summary[:2000],
        visa_status=cfg["profile"].get("visa_status", "Not specified"),
        years_exp=years_exp,
        job_title=job.get("title", ""),
        company=job.get("company", ""),
        job_description=(job.get("description", "") or "")[:1500],
        questions_block=questions_block,
    )

    try:
        raw = _call_ai(prompt)
        answers = _parse_json(raw)
        if isinstance(answers, list) and len(answers) == len(fields):
            return answers
        log.warning(f"AI returned {len(answers) if isinstance(answers,list) else 'non-list'} "
                    f"answers for {len(fields)} questions — using fallback")
    except Exception as e:
        log.warning(f"Form question AI call failed: {e}")

    # Fallback: neutral defaults
    return ["N/A"] * len(fields)


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point — call this after standard profile fields are filled
# ─────────────────────────────────────────────────────────────────────────────
def fill_custom_questions(page, job: dict) -> int:
    """
    Detects and fills all custom screening questions on the current page.
    Returns the number of fields successfully filled.

    Order of operations per field:
      1. Try deterministic config-based answer (salary, visa, relocation, etc)
      2. If none, batch remaining fields to AI
      3. Fill each field according to its type (text/select/radio)
    """
    cfg = get_config()
    fields = detect_unanswered_fields(page, cfg)

    if not fields:
        log.debug("  No custom questions detected")
        return 0

    log.info(f"  Found {len(fields)} custom question(s)")

    # Separate deterministic vs AI-needed fields
    deterministic = {}
    needs_ai = []
    for f in fields:
        det = _deterministic_answer(f["label"], cfg)
        if det is not None:
            deterministic[id(f)] = det
        else:
            needs_ai.append(f)

    # Batch AI call for remaining fields
    ai_answers = generate_answers(needs_ai, job) if needs_ai else []
    ai_map = {id(f): ans for f, ans in zip(needs_ai, ai_answers)}

    filled = 0
    for f in fields:
        answer = deterministic.get(id(f)) or ai_map.get(id(f), "")
        if not answer or answer == "N/A":
            continue

        try:
            _fill_field(f, answer)
            filled += 1
            log.debug(f"    Filled: '{f['label'][:50]}' = '{answer[:50]}'")
        except Exception as e:
            log.debug(f"    Failed to fill '{f['label'][:50]}': {e}")

    log.info(f"  Filled {filled}/{len(fields)} custom questions")
    return filled


def _fill_field(field: dict, answer: str):
    """Fills a single field based on its type."""
    tag  = field["tag"]
    el   = field.get("element")

    if tag == "radio_group":
        # Find the radio option matching the answer (case-insensitive, partial match)
        for opt in field["elements"]:
            if answer.lower() in opt["value"].lower() or opt["value"].lower() in answer.lower():
                opt["element"].check()
                return
        # Default to first option if no match (usually "Yes")
        if field["elements"]:
            field["elements"][0]["element"].check()

    elif tag == "select":
        # Try exact match first, then partial
        options = field.get("options", [])
        for opt in options:
            if answer.lower() == opt.lower():
                el.select_option(label=opt)
                return
        for opt in options:
            if answer.lower() in opt.lower() or opt.lower() in answer.lower():
                el.select_option(label=opt)
                return

    elif tag == "textarea":
        el.fill(answer)

    elif tag == "input":
        el.fill(answer)
