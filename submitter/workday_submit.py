"""
submitter/workday_submit.py — Production Workday form submission

Based on confirmed working implementations (jasonchen270/workday-autofill,
amgenene/workday_auto) that verified the real data-automation-id selectors
against live Workday pages.

KEY ARCHITECTURE FACTS (confirmed from real implementations):
  - Workday uses ONE global applicant account (same email/password across
    ALL companies' Workday tenants — not one account per company).
  - The multi-step wizard is identified by data-automation-id attributes
    that are stable across all Workday tenants.
  - Workday uses React controlled inputs — plain .fill() often fails because
    React intercepts native input events. We use JavaScript + trigger events
    to reliably fill React-controlled fields.
  - The /apply/autofillWithResume path is the fastest entry point — Workday
    pre-populates fields from a parsed resume, then we fill gaps and submit.

CONFIRMED data-automation-id values (from real implementations):
  Account: 'createAccountPanel', 'email', 'password', 'verifyPassword',
           'createAccountSubmitButton', 'signInSubmitButton'
  My Info: 'legalNameSection_firstName', 'legalNameSection_lastName',
           'phone-number', 'addressSection_addressLine1',
           'addressSection_city', 'addressSection_postalCode'
  Resume:  file input, 'resumeUploadSection'
  Nav:     'bottom-navigation-next-button', 'bottom-navigation-previous-button'
  Submit:  'bottom-navigation-next-button' on last page (labeled 'Submit')
"""
import time, os, json, re
from pathlib import Path
from utils import log, get_config

# Workday account credentials are stored once in logs/workday_account.json
# and reused across ALL Workday applications.
WORKDAY_CREDS_FILE = Path(__file__).parent.parent / "logs" / "workday_account.json"


def _load_or_create_workday_creds(profile: dict) -> dict:
    """
    Returns {email, password} for the shared Workday applicant account.

    Priority: WORKDAY_PASSWORD env var (GitHub Secret) → saved file → auto-generate.
    The same credentials work across ALL Workday companies.
    """
    import os, secrets, string
    email = profile["email"]

    # Priority 1: GitHub Secret / env var (recommended for production)
    env_pwd = os.environ.get("WORKDAY_PASSWORD", "").strip()
    if env_pwd:
        return {"email": email, "password": env_pwd}

    # Priority 2: Saved credentials file (for local runs)
    if WORKDAY_CREDS_FILE.exists():
        try:
            return json.loads(WORKDAY_CREDS_FILE.read_text())
        except Exception:
            pass

    # Priority 3: Auto-generate, save, and prompt to add as GitHub Secret
    # Workday password rules: 8+ chars, upper, lower, number, special char.
    chars = string.ascii_letters + string.digits + "!@#$%"
    pwd = (
        secrets.choice(string.ascii_uppercase)
        + secrets.choice(string.ascii_lowercase)
        + secrets.choice(string.digits)
        + secrets.choice("!@#$%")
        + "".join(secrets.choice(chars) for _ in range(8))
    )
    creds = {"email": email, "password": pwd}
    WORKDAY_CREDS_FILE.parent.mkdir(exist_ok=True)
    WORKDAY_CREDS_FILE.write_text(json.dumps(creds, indent=2))
    log.info(
        f"  [Workday] Auto-generated Workday account credentials.\n"
        f"  [Workday] Email: {creds['email']} | Password: {creds['password']}\n"
        f"  [Workday] ACTION REQUIRED: Add WORKDAY_PASSWORD={creds['password']} as a\n"
        f"  [Workday] GitHub Secret so this password persists across runs.\n"
        f"  [Workday] Go to: repo → Settings → Secrets → Actions → New secret"
    )
    return creds


def _react_fill(page, selector: str, value: str) -> bool:
    """
    Fills a React-controlled input field reliably.
    Plain .fill() often fails on Workday because React intercepts native
    input events and doesn't register the value change. This method uses
    JavaScript to set the value and then dispatches the events React listens
    for (input + change), which forces React to update its internal state.
    Returns True if field was found and filled.
    """
    if not value:
        return False
    try:
        el = page.query_selector(selector)
        if not el or not el.is_visible():
            return False
        # JavaScript approach: set value directly on the React fiber,
        # then fire the events React uses to detect changes.
        page.evaluate("""
            ([selector, value]) => {
                const el = document.querySelector(selector);
                if (!el) return false;
                // Set value on the native input
                const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value'
                ).set;
                nativeInputValueSetter.call(el, value);
                // Dispatch events React listens for
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return true;
            }
        """, [selector, value])
        time.sleep(0.2)
        return True
    except Exception:
        # Fall back to regular fill if JS approach fails
        try:
            el = page.query_selector(selector)
            if el:
                el.click()
                el.fill(value)
                return True
        except Exception:
            pass
        return False


def _react_fill_by_label(page, label_text: str, value: str) -> bool:
    """
    Fills a React input by its associated label text — more resilient than
    data-automation-id selectors since label text is rarely changed.
    """
    if not value:
        return False
    try:
        # Find label by text, then find the associated input
        label = page.get_by_label(label_text, exact=False)
        if label.count() > 0:
            label.first.click()
            label.first.fill(value)
            return True
    except Exception:
        pass
    return False


def _handle_account_step(page, creds: dict, profile: dict) -> bool:
    """
    Handles the Workday account creation or sign-in step.
    Returns True when the account step is complete.
    """
    time.sleep(2)

    # Check if we're on an account/sign-in page
    create_panel = page.query_selector("[data-automation-id='createAccountPanel']")
    signin_panel = page.query_selector("[data-automation-id='signInPanel']")
    email_field = page.query_selector(
        "[data-automation-id='email'], [data-automation-id='createAccountEmail']"
    )

    if not (create_panel or signin_panel or email_field):
        # No account step — already signed in or skipped
        return True

    # Try sign in first (if we already created an account on a prior Workday job)
    if signin_panel or page.query_selector("button:has-text('Sign In')"):
        log.info("  [Workday] Signing in with existing account...")
        _react_fill(page, "[data-automation-id='email']", creds["email"])
        _react_fill(page, "[data-automation-id='password']", creds["password"])
        sign_in_btn = page.query_selector(
            "[data-automation-id='signInSubmitButton'], button:has-text('Sign In')"
        )
        if sign_in_btn:
            sign_in_btn.click()
            page.wait_for_load_state("domcontentloaded", timeout=20000)
            time.sleep(2)
            return True

    # Create new account
    log.info("  [Workday] Creating Workday applicant account...")
    _react_fill(page, "[data-automation-id='email']", creds["email"])
    _react_fill(page, "[data-automation-id='password']", creds["password"])
    _react_fill(page, "[data-automation-id='verifyPassword']", creds["password"])

    # Some Workday instances ask to check a checkbox for terms
    terms_cb = page.query_selector(
        "[data-automation-id='agreed'], input[type='checkbox']"
    )
    if terms_cb and not terms_cb.is_checked():
        terms_cb.click()

    create_btn = page.query_selector(
        "[data-automation-id='createAccountSubmitButton'], "
        "button:has-text('Create Account')"
    )
    if create_btn:
        create_btn.click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(2)

    # Handle "already registered" — switch to sign in
    if page.query_selector("[data-automation-id='signInSubmitButton']"):
        log.info("  [Workday] Email already registered — signing in...")
        _react_fill(page, "[data-automation-id='password']", creds["password"])
        page.query_selector("[data-automation-id='signInSubmitButton']").click()
        page.wait_for_load_state("domcontentloaded", timeout=20000)
        time.sleep(2)

    return True


def _fill_my_information_step(page, profile: dict, pdf_path: str | None):
    """
    Fills the 'My Information' step: name, email, phone, address, resume.
    """
    name_parts = profile["name"].strip().split(" ", 1)
    first_name = name_parts[0]
    last_name  = name_parts[1] if len(name_parts) > 1 else ""

    # Name fields
    _react_fill(page, "[data-automation-id='legalNameSection_firstName']", first_name)
    _react_fill(page, "[data-automation-id='legalNameSection_lastName']", last_name)
    # Fallbacks using label text (more resilient)
    _react_fill_by_label(page, "First Name", first_name)
    _react_fill_by_label(page, "Last Name", last_name)

    # Contact
    _react_fill(page, "[data-automation-id='email']", profile["email"])
    _react_fill(page, "[data-automation-id='phone-number']", profile["phone"])
    _react_fill_by_label(page, "Phone", profile["phone"])

    # Address
    _react_fill(page,
        "[data-automation-id='addressSection_addressLine1']",
        profile.get("address", "")
    )
    _react_fill(page,
        "[data-automation-id='addressSection_city']",
        profile.get("city", "")
    )
    _react_fill(page,
        "[data-automation-id='addressSection_postalCode']",
        str(profile.get("zip", ""))
    )

    # LinkedIn
    _react_fill(page, "[data-automation-id='linkedInUrl']", profile.get("linkedin", ""))

    # Resume upload
    if pdf_path and os.path.exists(pdf_path):
        file_input = page.query_selector("input[type='file']")
        if file_input:
            file_input.set_input_files(pdf_path)
            log.info(f"  [Workday] Resume uploaded")
            time.sleep(1)


def _fill_work_auth_fields(page, profile: dict):
    """
    Handles work authorization questions that appear on most Workday forms.
    For F1 OPT: authorized=Yes, requires_sponsorship=No (unless configured otherwise).
    """
    requires_sponsor = profile.get("requires_sponsorship", False)

    # "Are you legally authorized to work in the US?"
    for sel in [
        "[data-automation-id='authorizedToWork'] [value='true']",
        "[data-automation-id*='authorized'] [value='true']",
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                break
        except Exception:
            pass

    # "Will you now or in the future require sponsorship?"
    sponsor_val = "true" if requires_sponsor else "false"
    for sel in [
        f"[data-automation-id='requireSponsorship'] [value='{sponsor_val}']",
        f"[data-automation-id*='sponsor'] [value='{sponsor_val}']",
    ]:
        try:
            el = page.query_selector(sel)
            if el:
                el.click()
                break
        except Exception:
            pass


def _dismiss_eeo_selects(page):
    """
    EEO / voluntary disclosures: select 'Decline to state' or equivalent
    for race, gender, veteran, disability dropdowns. These are voluntary
    and we're not required to answer — 'decline' is always a safe option.
    """
    for label in ["Gender", "Hispanic/Latino", "Race/Ethnicity",
                  "Veteran Status", "Disability Status"]:
        try:
            sel = page.get_by_label(label, exact=False)
            if sel.count() > 0:
                options = sel.first.evaluate(
                    "el => Array.from(el.options).map(o => o.text)"
                )
                decline = next(
                    (o for o in options
                     if any(w in o.lower()
                            for w in ["decline", "prefer not", "not to state", "choose not"])),
                    None
                )
                if decline:
                    sel.first.select_option(label=decline)
        except Exception:
            pass


def _find_and_click_next(page) -> bool:
    """
    Finds and clicks the Next/Continue button.
    Returns True if clicked, False if not found (end of wizard or error).
    """
    selectors = [
        "[data-automation-id='bottom-navigation-next-button']",
        "[data-automation-id='nextButton']",
        "button:has-text('Next')",
        "button:has-text('Continue')",
        "button:has-text('Save and Continue')",
    ]
    for sel in selectors:
        try:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                label = btn.inner_text().strip().lower()
                if "submit" not in label:
                    btn.click()
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                    time.sleep(2)
                    return True
        except Exception:
            pass
    return False


def submit_workday(job: dict, pdf_path: str | None) -> bool:
    """
    Submits an application to a Workday career page.
    Handles the full multi-step wizard: account creation/sign-in → My
    Information → My Experience → Application Questions → EEO → Review → Submit.
    Returns True if successfully submitted.
    """
    cfg     = get_config()
    profile = cfg["profile"]

    apply_url = job.get("url", "")
    if not apply_url:
        log.warning("  [Workday] No URL found for job.")
        return False

    # Use the autofillWithResume path if available — Workday pre-populates
    # fields from the parsed resume, reducing the number of fields we need to fill.
    if "myworkdayjobs.com" in apply_url and "/apply" not in apply_url:
        apply_url = re.sub(r"(/job/[^?#]+)", r"\1/apply/autofillWithResume", apply_url)

    creds = _load_or_create_workday_creds(profile)

    try:
        from playwright.sync_api import sync_playwright
        from submitter.form_questions import fill_custom_questions

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800}  # Workday needs full viewport
            )
            page = ctx.new_page()
            page.set_default_timeout(25000)

            log.info(f"  [Workday] Opening: {apply_url[:80]}...")
            page.goto(apply_url, wait_until="domcontentloaded", timeout=25000)
            time.sleep(2)

            # Step 0: Click "Apply" if on job description page
            for apply_sel in [
                "a[data-automation-id='applyButton']",
                "button[data-automation-id='applyButton']",
                "a:has-text('Apply Now')",
                "button:has-text('Apply')",
            ]:
                try:
                    btn = page.query_selector(apply_sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_load_state("domcontentloaded", timeout=20000)
                        time.sleep(2)
                        break
                except Exception:
                    pass

            # Step 1: Account creation / sign-in
            _handle_account_step(page, creds, profile)

            # Steps 2-6: Multi-page wizard — fill each page, then click Next
            # We run up to 8 iterations to handle wizard pages of varying depth
            for step in range(8):
                log.info(f"  [Workday] Wizard step {step + 1}...")

                # Fill standard profile fields on every page (they only
                # appear on the relevant step, extras are ignored)
                _fill_my_information_step(page, profile, pdf_path if step == 0 else None)
                _fill_work_auth_fields(page, profile)
                _dismiss_eeo_selects(page)

                # AI-powered answers to custom screening questions on this page
                fill_custom_questions(page, job)

                # Check if Submit button is present (last step)
                submit_btn = None
                for sub_sel in [
                    "[data-automation-id='bottom-navigation-next-button']:has-text('Submit')",
                    "button:has-text('Submit Application')",
                    "button[type='submit']:has-text('Submit')",
                ]:
                    try:
                        candidate = page.query_selector(sub_sel)
                        if candidate and candidate.is_visible():
                            submit_btn = candidate
                            break
                    except Exception:
                        pass

                # Also check if the Next button label says Submit
                next_btn_check = page.query_selector(
                    "[data-automation-id='bottom-navigation-next-button']"
                )
                if next_btn_check:
                    try:
                        label = next_btn_check.inner_text().strip().lower()
                        if "submit" in label:
                            submit_btn = next_btn_check
                    except Exception:
                        pass

                if submit_btn and submit_btn.is_visible():
                    submit_btn.click()
                    page.wait_for_load_state("domcontentloaded", timeout=25000)
                    time.sleep(3)
                    log.info(
                        f"  [Workday] ✅ Submitted: {job['title']} @ {job['company']}"
                    )
                    browser.close()
                    return True

                # Not on submit step yet — click Next and continue
                if not _find_and_click_next(page):
                    log.warning(
                        f"  [Workday] Could not advance past step {step + 1} "
                        f"for {job['title']} @ {job.get('company', '')}. "
                        f"Stopping — manual intervention may be needed for this job."
                    )
                    browser.close()
                    return False

            log.warning(
                f"  [Workday] Reached max wizard steps without finding Submit "
                f"for {job['title']} @ {job.get('company', '')}."
            )
            browser.close()
            return False

    except Exception as e:
        log.warning(f"  [Workday] Submit failed for {job['title']}: {e}")
        return False
