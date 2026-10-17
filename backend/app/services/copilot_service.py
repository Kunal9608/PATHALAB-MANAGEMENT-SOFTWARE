"""
Copilot Service — Context Builder & Intent Router.
Integrates deterministic backend retrieval, RBAC enforcement,
Redis-first cache-aside, and zero hallucination guarantees.
"""
import re
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any
from sqlalchemy.orm import Session

from backend.app.models.user import User, RoleEnum, ViewScopeEnum
from backend.app.services.copilot_retriever import (
    LookupStatus,
    BackendLookupResult,
    PATIENT_ID_SCAN_REGEX,
    MALFORMED_PATIENT_SCAN_REGEX,
    PHONE_SCAN_REGEX,
    TEST_CODE_SCAN_REGEX,
    RESERVED_WORDS,
    retrieve_patient,
    retrieve_by_phone,
    retrieve_test,
    retrieve_finance,
    retrieve_pending_reports,
    retrieve_latest_reports,
    retrieve_latest_patient,
    STAFF_ID_SCAN_REGEX,
    retrieve_staff,
    retrieve_staff_by_phone,
    retrieve_staff_by_name,
    retrieve_all_staff,
    retrieve_all_tests,
    retrieve_by_patient_name,
    retrieve_doctors,
)
from backend.app.models.audit_log import AuditLog
from backend.app.models.patient import Patient
from backend.app.models.test import Test

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _get_base_system_prompt(current_user: User) -> str:
    now_ist = datetime.now(timezone.utc).astimezone(IST)
    current_time_str = now_ist.strftime("%A, %d %B %Y, %I:%M %p")
    time_12h = now_ist.strftime("%I:%M %p")
    date_str = now_ist.strftime("%d %B %Y (%A)")
    u_created = getattr(current_user, 'created_at', None)
    if u_created:
        if u_created.tzinfo is None:
            u_created = u_created.replace(tzinfo=timezone.utc)
        user_created = u_created.astimezone(IST).strftime('%Y-%m-%d')
    else:
        user_created = 'Unknown'
    v_scope = current_user.view_scope.value if hasattr(current_user.view_scope, 'value') else str(current_user.view_scope)
    role_val = current_user.role.value if hasattr(current_user.role, 'value') else str(current_user.role)

    return f"""You are Akriti Diagnostic AI Assistant.
You are the official AI assistant integrated inside the PathLab Management System.

REAL-TIME INDIAN STANDARD TIME (IST):
- Current Time: {time_12h} (12-hour format with AM/PM)
- Today's Date: {date_str}
- Timestamp: {current_time_str}

TIME & DATE HANDLING RULES:
- When the user asks for the current time or date, answer politely with the real-time IST time in 12-hour AM/PM format (e.g. "{time_12h} IST").
- NEVER say "Current System Time" or output server timestamps.
- NEVER append the time or date at the bottom of unrelated responses (e.g., patient lookup, billing, test results) unless the user specifically asked for the time.

[Logged-In User Profile]:
Name: {current_user.name}, Email: {getattr(current_user, 'email', 'N/A')}, Role: {role_val}, Staff Code: {getattr(current_user, 'staff_code', 'N/A')}, View Scope: {v_scope}, Registered On: {user_created}.

ROLE BASED ACCESS RULES:
- Admin can access everything (patients, tests, reports, and financial revenue/analytics).
- Staff can ONLY access records they are authorized to view.
- If user lacks permission for patient or financial data, reply: "You do not have permission to access this information."

EXPERT PATHLAB & CLINICAL DIAGNOSTIC SCOPE:
You are an expert PathLab AI Assistant for Akriti Diagnostics Center. You expertly handle:
1. LAB MANAGEMENT & OPERATIONS:
   - Patient lookups, booked tests, sample collection status, test reports, billing, doctor referrals, pending reports, recent registrations, and admin financial reports.
2. CLINICAL PATHOLOGY & DIAGNOSTIC TESTS:
   - Provide accurate, medically-sound clinical pathology knowledge for ALL diagnostic lab tests (e.g., CBC, HbA1c, Blood Sugar, LFT, KFT/RFT, Lipid Profile, Thyroid T3/T4/TSH, Urine Routine & Microscopy, Widal, Dengue, Vitamin D, Vitamin B12, Electrolytes, Cardiac/Troponin, etc.).
   - Explain biological reference ranges, units (mg/dL, g/dL, µIU/mL, etc.), and clinical significance of high or low abnormal values.
   - Pre-test patient preparation (e.g. fasting duration of 8-12 hours for fasting sugar/lipids, morning sample, sample tube colors like EDTA purple, Fluoride grey, Plain red, Citrate blue).
   - Turnaround times and sample collection procedures.
3. LANGUAGE & COMMUNICATION:
   - Understand Hindi, Hinglish, and English naturally. If the user asks in Hindi or Hinglish, answer in polite, clear Hinglish/Hindi. If the user asks in English, answer in English.
   - Use clean, well-formatted Markdown with bullet points, bold headers, and tables where appropriate.
   - For general medical interpretations, provide clear educational guidance with a standard clinical disclaimer that lab findings must be correlated by a qualified consulting physician.
4. UNRELATED TOPICS:
   - If a question is completely unrelated to medical, health, pathology, biology, or the lab system (e.g. movies, programming code, cricket scores), politely redirect: "I specialize in Akriti Diagnostics Lab Management and Clinical Pathology. How can I help you with our lab tests or patient records?"

STRICT ANTI-HALLUCINATION POLICY:
- Backend database is always the ONLY source of truth for all patients, staff, doctors, and financial data.
- NEVER invent, assume, or fabricate staff profiles, doctor names, departments (e.g. Hematology, Pathology), attendance, verified report counts, or credentials.
- If a staff member, doctor, patient, test, or revenue record is NOT explicitly provided in verified backend data, reply firmly: "No record found for this identifier in Akriti Diagnostics database."
- When CRITICAL LIVE DATA is provided below, ALWAYS use that exact data.
- NEVER output <think> or </think> tags.

PRESENTATION & CLEAN FORMATTING GUIDELINES (STRICT):
- ABSOLUTELY NEVER USE ANY EMOJIS (no medical icons, no calendars, no money bags, no warning signs, etc.). The frontend UI renders crisp SVG icons instead.
- NEVER use markdown hashes (e.g. NEVER output '###' or '##' or '#').
- NEVER use asterisk bullets (e.g. NEVER output '* item' or '*').
- Keep answers SHORT, NEAT, COMPACT, and CRISP. Avoid unnecessary fluff or conversational padding ("Hello! Here is the complete summary...").
- For section headers, use clean bold labels without emojis, for example:
  **Patient Information**
  **Status & Timeline**
  **Doctor & Staff Details**
  **Booked Tests**
  **Billing & Accounts**
  **Diagnostic Reports**
  **Test Results**
GROQ TOKEN OPTIMIZATION & CONCISENESS RULES:
- Groq daily API quota is strictly limited (1,000 requests/day, 200,000 tokens/day).
- Keep all responses highly concise, factual, and strictly relevant to what the user asked.
- Strictly avoid repetitive conversational greetings, introductory fluff ("Sure, let me check that..."), or repeating the user's question.
- When the user asks to analyze a patient's report or test findings:
  1. Highlight ABNORMAL or out-of-range parameters first (Observed value, Unit, Normal Reference Interval).
  2. Provide a crisp 2-3 sentence clinical observation of what these values may indicate.
  3. Suggest standard next clinical steps or doctor correlation.
- Target response length: 50 to 150 words to conserve daily quota.
- If the user asks a specific question (e.g. "what is the bill" or "is report ready"), answer that directly in 1-3 lines.
"""


def extract_recent_patient_from_history(history: Optional[list]) -> Optional[str]:
    """
    Scans the last 5 messages in conversation history in reverse order
    to identify the most recently discussed patient code (e.g. PAT260055).
    """
    if not history:
        return None
    import json
    for item in reversed(history):
        content = item.get("content", "")
        if not content:
            continue
        # Check for JSON patient card
        if '"__card": "patient"' in content or '"__card":"patient"' in content:
            try:
                card = json.loads(content)
                code = card.get("code")
                if code:
                    return str(code).upper()
            except Exception:
                pass
        # Check regex
        matches = PATIENT_ID_SCAN_REGEX.findall(content)
        if matches:
            return matches[0].upper()
        m = re.search(r'\b(PAT\d{4,8}|AKR\d{4,8})\b', content, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return None


def is_patient_followup_query(message: str) -> bool:
    """
    Determines if the message is referring back to a previously mentioned patient
    (e.g., 'report analyse kro uska', 'uska bill kitna hai', 'what are the abnormal findings?').
    """
    msg = message.lower().strip()
    switch_words = ["all staff", "staff list", "doctor list", "all doctors", "all tests", "rate list", "audit log", "today revenue", "yesterday revenue"]
    if any(k in msg for k in switch_words):
        return False

    patient_context_words = [
        "report", "reports", "analyse", "analyze", "analysis", "test", "tests",
        "result", "results", "abnormal", "findings", "finding", "parameter",
        "uska", "iska", "unka", "inhe", "patient", "mareez", "bill", "billing",
        "due", "paid", "amount", "rupaye", "rupees", "kitna", "status", "ready",
        "sample", "doctor", "kaisa", "kya hua", "dikkat", "problem", "condition",
        "detail", "details", "check", "batao", "explain", "him", "her", "his",
        "he", "she", "this", "that"
    ]
    if any(k in msg for k in patient_context_words):
        return True

    words = msg.split()
    if len(words) <= 6 and any(w in msg for w in ["kya", "kaise", "kab", "kyu", "why", "what", "is", "how", "normal"]):
        return True

    return False


async def build_copilot_context_async(
    message: str,
    current_user: User,
    db: Session,
    history: Optional[list] = None
) -> Tuple[str, Optional[str], Optional[BackendLookupResult]]:
    """
    Asynchronous deterministic context builder with conversation memory support.
    Returns:
        (system_prompt, direct_authoritative_response, lookup_result)
        If direct_authoritative_response is not None, the router streams this
        exact message directly, bypassing the LLM to guarantee 100% factual accuracy.
    """
    msg_trimmed = message.strip()
    msg_lower = msg_trimmed.lower()
    system_prompt = _get_base_system_prompt(current_user)

    # 0. STAFF IDENTIFIER LOOKUP (e.g. STAFF26003, STAFF26001, etc.)
    staff_matches = STAFF_ID_SCAN_REGEX.findall(message)
    if staff_matches:
        target_staff = staff_matches[0]
        result = await retrieve_staff(db, target_staff, current_user)
        if result.status == LookupStatus.not_found:
            return system_prompt, result.message, result
        if result.status != LookupStatus.success or not result.data:
            return system_prompt, result.message or f"Unable to retrieve staff record for '{target_staff}'.", result

        d = result.data
        direct_response = (
            f"**Staff Profile**\n\n"
            f"• Name: {d['name']}\n"
            f"• Staff Code: {d['staff_code']}\n"
            f"• Role: {d['role']}\n"
            f"• Status: {d['status']}\n"
            f"• Mobile: {d['mobile']}\n"
            f"• Email: {d['email']}\n"
            f"• View Scope: {d['view_scope']}\n"
            f"• Registered On: {d['registered_on']}"
        )
        return system_prompt, direct_response, result

    # 0.2 STAFF BY MOBILE NUMBER (when query mentions staff/employee/worker)
    phone_candidates = PHONE_SCAN_REGEX.findall(message)
    is_staff_intent = any(k in msg_lower for k in ["staff", "employee", "worker", "karmachari", "member"])
    if phone_candidates and is_staff_intent:
        target_phone = phone_candidates[0]
        result = await retrieve_staff_by_phone(db, target_phone, current_user)
        if result.status == LookupStatus.not_found:
            return system_prompt, result.message, result
        if result.status != LookupStatus.success or not result.data:
            return system_prompt, result.message or f"Unable to retrieve staff record for '{target_phone}'.", result

        d = result.data
        direct_response = (
            f"**Staff Profile**\n\n"
            f"• Name: {d['name']}\n"
            f"• Staff Code: {d['staff_code']}\n"
            f"• Role: {d['role']}\n"
            f"• Status: {d['status']}\n"
            f"• Mobile: {d['mobile']}\n"
            f"• Email: {d['email']}\n"
            f"• View Scope: {d['view_scope']}\n"
            f"• Registered On: {d['registered_on']}"
        )
        return system_prompt, direct_response, result

    # 0.3 STAFF NAME LOOKUP (e.g. "search staff Om Raj", "find staff Om Raj", "staff Om Raj")
    staff_name_match = re.search(r'\b(?:find staff|search staff|staff named|staff member)\s+([A-Za-z\s]{2,40})', message, re.IGNORECASE)
    if not staff_name_match:
        strict_s = re.match(r'^(?:staff)\s+([A-Za-z]{2,20}(?:\s+[A-Za-z]{2,20}){0,2})$', msg_trimmed, re.IGNORECASE)
        if strict_s and not any(k in msg_lower for k in ["list", "all", "members", "directory"]):
            staff_name_match = strict_s

    if staff_name_match:
        s_cand = staff_name_match.group(1).strip()
        if s_cand.lower() not in ["list", "all", "members", "directory", "details", "info"]:
            result = await retrieve_staff_by_name(db, s_cand, current_user)
            if result.status == LookupStatus.success and result.data:
                if isinstance(result.data, dict):
                    d = result.data
                    direct_response = (
                        f"**Staff Profile**\n\n"
                        f"• Name: {d['name']}\n"
                        f"• Staff Code: {d['staff_code']}\n"
                        f"• Role: {d['role']}\n"
                        f"• Status: {d['status']}\n"
                        f"• Mobile: {d['mobile']}\n"
                        f"• Email: {d['email']}\n"
                        f"• View Scope: {d['view_scope']}\n"
                        f"• Registered On: {d['registered_on']}"
                    )
                    return system_prompt, direct_response, result
                elif isinstance(result.data, list):
                    items = [f"• {s['name']} — Staff Code: {s['staff_code']} | Mobile: {s['mobile']} | Status: {s['status']}" for s in result.data]
                    direct_response = f"**Found {len(items)} staff member(s) matching '{s_cand}':**\n\n" + "\n".join(items)
                    return system_prompt, direct_response, result
            elif result.status == LookupStatus.not_found:
                return system_prompt, result.message, result

    # 0.5. ALL STAFF DIRECTORY
    staff_list_keywords = ["staff list", "all staff", "list of staff", "staff members", "lab staff", "show staff"]
    if any(k in msg_lower for k in staff_list_keywords):
        result = await retrieve_all_staff(db, current_user)
        if result.status == LookupStatus.success and result.data is not None:
            if not result.data:
                return system_prompt, "No staff members found in the system.", result
            items = [f"• {s['name']} — Staff Code: {s['staff_code']} | Status: {s['status']} | Email: {s['email']}" for s in result.data]
            direct_response = f"**Akriti Diagnostics Staff Directory ({len(items)} members)**\n\n" + "\n".join(items)
            return system_prompt, direct_response, result

    # 1. EXACT PATIENT IDENTIFIER LOOKUP
    exact_patient_matches = PATIENT_ID_SCAN_REGEX.findall(message)
    malformed_candidates = MALFORMED_PATIENT_SCAN_REGEX.findall(message)

    target_candidate = None
    if exact_patient_matches:
        target_candidate = exact_patient_matches[0]
    elif malformed_candidates:
        cand = malformed_candidates[0]
        if cand.upper() not in RESERVED_WORDS and any(c.isdigit() for c in cand):
            target_candidate = cand
    elif history:
        # Check if user is asking a follow-up query referring to the last patient
        recent_patient = extract_recent_patient_from_history(history)
        if recent_patient and is_patient_followup_query(message):
            target_candidate = recent_patient

    if target_candidate:
        result = await retrieve_patient(db, target_candidate, current_user)
        # Authoritative terminal statuses bypass LLM completely (Zero Hallucinations)
        if result.status == LookupStatus.invalid_input:
            return system_prompt, result.message, result
        if result.status == LookupStatus.not_found:
            return system_prompt, result.message, result
        if result.status == LookupStatus.forbidden:
            return system_prompt, result.message, result
        if result.status in (LookupStatus.service_unavailable, LookupStatus.error):
            return system_prompt, result.message, result

        # Success: Inject verified structured patient facts into LLM prompt
        p_data = result.data or {}
        
        # Check if query is a direct patient lookup (e.g., "PAT260055", "pat 260055", "check PAT260055", "PAT260055 details")
        lookup_pattern = r"^(?:check|lookup|patient|find|view|show|record|summary)?\s*#?\s*(?:pat)?\s*\d{4,8}\s*(?:details|info|record|summary|status)?$"
        is_direct_lookup = bool(re.match(lookup_pattern, msg_trimmed, re.IGNORECASE))

        if is_direct_lookup:
            import json
            p_code = p_data.get('patient_code', target_candidate)
            p_name = p_data.get('name', 'N/A')
            p_age = p_data.get('age', 'N/A')
            p_gender = str(p_data.get('gender', 'N/A')).title()
            p_mobile = p_data.get('mobile', 'N/A')
            p_status = str(p_data.get('status', 'N/A')).replace('_', ' ').title()
            p_sample_date = p_data.get('sample_date', 'N/A')
            p_doctor = p_data.get('referred_by', 'Self')
            p_tests = p_data.get("booked_tests", [])
            p_total = p_data.get('total_amount', 0)
            p_paid = p_data.get('amount_paid', 0)
            p_due = p_data.get('amount_due', 0)
            p_pay_status = str(p_data.get('payment_status', 'Pending')).replace('_', ' ').title()

            latest_report = None
            if p_data.get("reports"):
                r0 = p_data["reports"][0]
                latest_report = {
                    "download_url": r0.get('download_url'),
                    "uploaded_at": r0.get('uploaded_at'),
                    "version_label": r0.get('version_label', 'Latest')
                }

            abnormal_items = [
                f"{tr['parameter']}: {tr['value']} {tr['unit']}"
                for tr in p_data.get("test_results", [])
                if tr.get('is_abnormal')
            ]

            card_obj = {
                "__card": "patient",
                "code": p_code,
                "name": p_name,
                "age": p_age,
                "gender": p_gender,
                "mobile": p_mobile,
                "status": p_status,
                "sample_date": p_sample_date,
                "doctor": p_doctor,
                "tests": p_tests,
                "total": p_total,
                "paid": p_paid,
                "due": p_due,
                "pay_status": p_pay_status,
                "report": latest_report,
                "abnormal": ", ".join(abnormal_items) if abnormal_items else None
            }
            direct_response = json.dumps(card_obj)
            return system_prompt, direct_response, result

        # Reports — ONLY the single latest report version is displayed
        reports_summary = "No reports uploaded."
        if p_data.get("reports"):
            latest_r = p_data["reports"][0]
            v_tag = f" ({latest_r.get('version_label', 'Latest')})" if latest_r.get('version_label') else ""
            reports_summary = f"\n  - [View / Download Latest Report{v_tag} (Uploaded: {latest_r['uploaded_at']})]({latest_r['download_url']})"

        # Booked Tests
        tests_summary = ", ".join(p_data.get("booked_tests", [])) or "None specified"

        # Test Results
        results_summary = "No test results recorded yet."
        if p_data.get("test_results"):
            tr_items = []
            for tr in p_data.get("test_results", []):
                ref = f" [Normal: {tr['normal_range']}]" if tr.get('normal_range') else ""
                abn = " (ABNORMAL)" if tr.get('is_abnormal') else ""
                tr_items.append(f"{tr['parameter']}: {tr['value']} {tr['unit']}{ref}{abn}")
            results_summary = "\n  - " + "\n  - ".join(tr_items)

        patient_fact_block = (
            f"\n\nCRITICAL LIVE DATA (Verified Patient Record from Backend):\n"
            f"- Patient Code: {p_data.get('patient_code', target_candidate)}\n"
            f"- Name: {p_data.get('name')}\n"
            f"- Age: {p_data.get('age')} | Gender: {p_data.get('gender')}\n"
            f"- Mobile: {p_data.get('mobile')}\n"
            f"- Status: {p_data.get('status')}\n"
            f"- Sample Date: {p_data.get('sample_date')}\n"
            f"- Referred By: {p_data.get('referred_by')}\n"
            f"- Collected By: {p_data.get('collected_by')}\n"
            f"- Booked Tests: {tests_summary}\n"
            f"- Total Bill: Rs {p_data.get('total_amount')} | Discount: Rs {p_data.get('discount_amount')}\n"
            f"- Amount Paid: Rs {p_data.get('amount_paid')} | Amount Due: Rs {p_data.get('amount_due')}\n"
            f"- Payment Status: {p_data.get('payment_status')}\n"
            f"- Diagnostic Reports:{reports_summary}\n"
            f"- Test Results:{results_summary}\n\n"
            f"SPECIAL INSTRUCTION: Answer directly, clearly, and concisely in 2-5 lines. "
            f"If the user asks to analyze the report ('report analyse kro uska', etc.), summarize any abnormal/out-of-range test parameters "
            f"against their normal reference intervals, provide a crisp 2-3 line clinical observation, and advise physician correlation. "
            f"NEVER use emojis under any circumstances. Keep responses token-optimized."
        )
        system_prompt += patient_fact_block
        return system_prompt, None, result

    # 2. MOBILE NUMBER LOOKUP
    phone_matches = PHONE_SCAN_REGEX.findall(message)
    if phone_matches:
        phone = phone_matches[0]
        result = await retrieve_by_phone(db, phone, current_user)
        if result.status == LookupStatus.not_found:
            # Fallback: Check if this phone number belongs to a staff member
            staff_fallback = await retrieve_staff_by_phone(db, phone, current_user)
            if staff_fallback.status == LookupStatus.success and staff_fallback.data:
                d = staff_fallback.data
                direct_response = (
                    f"**Staff Profile**\n\n"
                    f"• Name: {d['name']}\n"
                    f"• Staff Code: {d['staff_code']}\n"
                    f"• Role: {d['role']}\n"
                    f"• Status: {d['status']}\n"
                    f"• Mobile: {d['mobile']}\n"
                    f"• Email: {d['email']}\n"
                    f"• View Scope: {d['view_scope']}\n"
                    f"• Registered On: {d['registered_on']}"
                )
                return system_prompt, direct_response, staff_fallback
            return system_prompt, result.message or f"No patient records found associated with mobile number {phone}.", result

        if result.status in (LookupStatus.invalid_input, LookupStatus.service_unavailable):
            return system_prompt, result.message, result

        if result.status == LookupStatus.success and result.data:
            summary_items = []
            for p in result.data:
                summary_items.append(
                    f"{p['patient_code']} - {p['name']} (Age: {p['age']}, Status: {p['status']}, Paid: Rs {p['amount_paid']}, Due: Rs {p['amount_due']})"
                )
            system_prompt += f"\n\nCRITICAL LIVE DATA:\n[Patients with Mobile {phone}]: Found {len(result.data)} record(s): " + " | ".join(summary_items)
            return system_prompt, None, result

    # 2.3. LATEST / LAST REGISTERED PATIENT
    latest_patient_keywords = [
        "last patient", "latest patient", "registered last", "patient registered last",
        "last registered", "latest registered", "recent patient", "recent patients",
        "who was added last", "last patient added", "aakhri patient", "patient registered"
    ]
    if any(k in msg_lower for k in latest_patient_keywords) and not any(k in msg_lower for k in ["find", "search", "phone", "mobile"]):
        result = await retrieve_latest_patient(db, current_user)
        if result.status == LookupStatus.success and result.data:
            p_data = result.data
            direct_msg = (
                f"**Latest Registered Patient**\n\n"
                f"• Patient Code: {p_data.get('patient_code')}\n"
                f"• Name: {p_data.get('name')}\n"
                f"• Age / Gender: {p_data.get('age')} Y / {p_data.get('gender')}\n"
                f"• Mobile: {p_data.get('mobile')}\n"
                f"• Registered Date: {p_data.get('sample_date')}\n"
                f"• Status: {str(p_data.get('status')).replace('_', ' ').title()}\n"
                f"• Referred By: {p_data.get('referred_by')}\n"
                f"• Booked Tests: {', '.join(p_data.get('booked_tests', [])) or 'None'}\n"
                f"• Billing: Total Rs {p_data.get('total_amount')} | Paid Rs {p_data.get('amount_paid')} | Due Rs {p_data.get('amount_due')}"
            )
            return system_prompt, direct_msg, result
        elif result.status == LookupStatus.not_found:
            return system_prompt, "No patient records found in the system.", result

    # 2.5. PATIENT NAME SEARCH (e.g. "patient Om Raj", "find patient Kunal", "search patient Ramesh")
    p_name_match = re.search(r'\b(?:find patient|search patient|patient named|patient name)\s+([A-Za-z\s]{2,40})', message, re.IGNORECASE)
    if not p_name_match:
        # Match only strict "^patient\s+[FirstName](?:\s+[LastName])?$" without clinical or conversational words
        strict_m = re.match(r'^(?:patient|record for)\s+([A-Za-z]{2,20}(?:\s+[A-Za-z]{2,20}){0,2})$', msg_trimmed, re.IGNORECASE)
        if strict_m:
            p_name_match = strict_m

    if p_name_match and not target_candidate:
        name_cand = p_name_match.group(1).strip()
        stop_words = {
            "registered", "pending", "admitted", "list", "status", "count", "details",
            "all", "today", "yesterday", "tomorrow", "ko", "ka", "ki", "ke", "chahiye",
            "kitna", "kya", "kaise", "who", "what", "how", "why", "when", "report",
            "reports", "bill", "billing", "sample", "fasting", "test", "tests", "last",
            "latest", "new", "sugar", "blood", "cbc", "vial", "tube", "range", "normal",
            "hours", "ghanta", "ghante"
        }
        cand_words = set(name_cand.lower().split())
        if not (cand_words & stop_words) and name_cand.upper() not in RESERVED_WORDS:
            result = await retrieve_by_patient_name(db, name_cand, current_user)
            if result.status in (LookupStatus.not_found, LookupStatus.forbidden, LookupStatus.invalid_input):
                return system_prompt, result.message, result
            if result.status == LookupStatus.success and result.data:
                pts = result.data
                if len(pts) == 1:
                    p = pts[0]
                    card_obj = {
                        "__card": "patient",
                        "code": p.get('patient_code'),
                        "name": p.get('name'),
                        "age": p.get('age'),
                        "gender": str(p.get('gender', 'N/A')).title(),
                        "mobile": p.get('mobile'),
                        "status": str(p.get('status', 'N/A')).replace('_', ' ').title(),
                        "sample_date": p.get('sample_date'),
                        "doctor": p.get('referred_by', 'Self'),
                        "tests": p.get("booked_tests", []),
                        "total": p.get('total_amount', 0),
                        "paid": p.get('amount_paid', 0),
                        "due": p.get('amount_due', 0),
                        "pay_status": str(p.get('payment_status', 'Pending')).replace('_', ' ').title(),
                        "report": p["reports"][0] if p.get("reports") else None,
                        "abnormal": None
                    }
                    import json
                    return system_prompt, json.dumps(card_obj), result
                else:
                    items = [f"• {p['patient_code']} — {p['name']} (Age: {p['age']}, Status: {p['status']}, Due: Rs {p['amount_due']})" for p in pts]
                    direct_msg = f"**Found {len(items)} patient record(s) matching '{name_cand}':**\n\n" + "\n".join(items)
                    return system_prompt, direct_msg, result

    # 3. TEST CATALOG LOOKUP & RATE LIST
    test_catalog_keywords = ["all tests", "test list", "rate list", "test rates", "test catalog", "test prices", "price list", "show tests", "list of tests"]
    if any(k in msg_lower for k in test_catalog_keywords):
        result = await retrieve_all_tests(db)
        if result.status == LookupStatus.success and result.data:
            items = [f"• {t['name']} ({t['test_code']}) — Rs {t['price']} [{t['category']}]" for t in result.data]
            direct_msg = f"**Akriti Diagnostics Official Test Catalog & Rates ({len(items)} tests)**\n\n" + "\n".join(items)
            return system_prompt, direct_msg, result

    # Specific Test Query (by code or known test keywords)
    test_matches = TEST_CODE_SCAN_REGEX.findall(message)
    test_candidate = test_matches[0] if test_matches else None
    if not test_candidate:
        common_test_names = [
            "cbc", "lft", "kft", "rft", "t3,t4,tsh", "ft3", "ft4", "tsh", "thyroid", "urine culture",
            "arthritis profile", "lipid profile", "blood sugar", "fasting sugar", "hb%", "hemoglobin",
            "crp", "widal", "dengue", "vitamin d", "vitamin b12", "esr", "serum calcium", "uric acid",
            "blood urea", "creatinine", "sgpt", "sgot", "bilirubin", "electrolyte"
        ]
        for ctn in common_test_names:
            if re.search(r'\b' + re.escape(ctn) + r'\b', msg_lower):
                test_candidate = ctn
                break

    if test_candidate:
        result = await retrieve_test(db, test_candidate)
        if result.status == LookupStatus.success and result.data:
            t = result.data
            param_str = ", ".join(t.get("parameters", [])) or "Standard clinical parameters"
            test_info = (
                f"**Test Information: {t['name']}**\n\n"
                f"• Test Code: {t['test_code']}\n"
                f"• Name: {t['name']}\n"
                f"• Official Price: Rs {t['price']}\n"
                f"• Category: {t['category']}\n"
                f"• Active: {'Yes' if t['is_active'] else 'No'}\n"
                f"• Parameters Measured: {param_str}"
            )
            # If user asks price, cost, rate, or details, return authoritative directly
            price_keywords = ["price", "cost", "rate", "charge", "charges", "fees", "fee", "rupaye", "rupees", "kitne ka"]
            is_price_q = any(w in msg_lower for w in price_keywords) or (
                "kitna" in msg_lower and not any(t_w in msg_lower for t_w in ["ghanta", "ghante", "hour", "hours", "time", "din", "day"])
            )
            if is_price_q:
                return system_prompt, test_info, result
            system_prompt += f"\n\nCRITICAL LIVE DATA:\n{test_info}"
            return system_prompt, None, result
        elif test_matches: # If explicitly searched by code and not found
            return system_prompt, result.message or f"No laboratory test exists with code '{test_candidate}' in the test catalog.", result

    # 3.5. DOCTORS DIRECTORY & LOOKUP
    doctor_catalog_keywords = ["doctor list", "all doctors", "referring doctors", "show doctors", "list of doctors"]
    if any(k in msg_lower for k in doctor_catalog_keywords):
        result = await retrieve_doctors(db, current_user)
        if result.status == LookupStatus.success and result.data:
            items = []
            for d in result.data:
                comm_str = f" | Commission: {d['commission_pct']}%" if "commission_pct" in d else ""
                items.append(f"• {d['name']} — Clinic: {d['clinic_name']}{comm_str}")
            direct_msg = f"**Akriti Diagnostics Referring Doctors ({len(items)} doctors)**\n\n" + "\n".join(items)
            return system_prompt, direct_msg, result

    dr_search_match = re.search(r'\b(?:dr\.?|doctor)\s+([A-Za-z]{3,30})\b', message, re.IGNORECASE)
    if dr_search_match and not any(k in msg_lower for k in ["list", "all", "refer"]):
        doc_q = dr_search_match.group(1).strip()
        result = await retrieve_doctors(db, current_user, doc_q)
        if result.status == LookupStatus.not_found:
            return system_prompt, result.message, result
        if result.status == LookupStatus.success and result.data:
            items = []
            for d in result.data:
                comm_str = f" | Commission: {d['commission_pct']}%" if "commission_pct" in d else ""
                items.append(f"• {d['name']} — Clinic: {d['clinic_name']}{comm_str}")
            direct_msg = f"**Doctor Details:**\n\n" + "\n".join(items)
            return system_prompt, direct_msg, result

    # 4. FINANCIAL ANALYTICS (Admin Only)
    finance_keywords = ["revenue", "earning", "collection", "profit", "loss", "expense", "expenses", "turnover", "sales"]
    if any(k in msg_lower for k in finance_keywords):
        if getattr(current_user, 'role', None) != RoleEnum.admin:
            return system_prompt, "You do not have permission to access financial information.", None

        # Check for specific date
        specific_date = None
        try:
            from dateutil.parser import parse
            parsed = parse(message, fuzzy=True)
            if parsed.year >= 2020:
                specific_date = parsed.date()
        except Exception:
            pass

        result = await retrieve_finance(db, current_user, specific_date)
        if result.status == LookupStatus.success and result.data:
            d = result.data
            fin_text = (
                f"\n\nCRITICAL LIVE DATA (Verified Finance):\n"
                f"Today Revenue: Rs {d['today_revenue']} | Expenses: Rs {d['today_expense']} | Net: Rs {d['today_net']}.\n"
                f"Yesterday Revenue: Rs {d['yesterday_revenue']} | Expenses: Rs {d['yesterday_expense']} | Net: Rs {d['yesterday_net']}.\n"
                f"This Month Revenue: Rs {d['month_revenue']} | Expenses: Rs {d['month_expense']} | Net: Rs {d['month_net']}.\n"
                f"Total Revenue: Rs {d['total_revenue']} | Total Expenses: Rs {d['total_expense']} | Net: Rs {d['total_net']}."
            )
            if "specific_date" in d:
                fin_text += f"\nRevenue for date {d['specific_date']}: Rs {d['specific_date_revenue']}."
            system_prompt += fin_text
            return system_prompt, None, result

    # 5. PENDING REPORTS
    pending_keywords = ["pending report", "pending reports", "pending status", "due report", "remaining report", "not ready"]
    if any(k in msg_lower for k in pending_keywords):
        result = await retrieve_pending_reports(db, current_user)
        if result.status == LookupStatus.success and result.data is not None:
            if not result.data:
                return system_prompt, "No pending reports found in the system. All diagnostic reports are ready.", result
            items = [f"{p['patient_code']} - {p['name']} (Status: {p['status']}, Date: {p['date']})" for p in result.data]
            system_prompt += f"\n\nCRITICAL LIVE DATA:\n[Pending Reports ({len(items)} records)]:\n" + "\n".join(items)
            return system_prompt, None, result

    # 5.5. LATEST / RELEASED REPORTS (e.g. "which patient report is released last")
    latest_report_keywords = [
        "released last", "last released", "latest report", "last report",
        "recent report", "recent reports", "latest reports", "last released report",
        "report is released", "reports released", "report release", "last report ready",
        "latest report ready", "report released last", "konsa report release", "report release hua",
        "report ready", "report released"
    ]
    if any(k in msg_lower for k in latest_report_keywords):
        result = await retrieve_latest_reports(db, current_user, limit=5)
        if result.status == LookupStatus.success and result.data:
            reports_list = result.data
            last_rep = reports_list[0]
            rep_text = (
                f"\n\nCRITICAL LIVE DATA (Verified Latest Diagnostic Report Released from Backend):\n"
                f"- Most Recent Released Patient Report:\n"
                f"  * Patient Code: {last_rep.get('patient_code')}\n"
                f"  * Patient Name: {last_rep.get('name')}\n"
                f"  * Age: {last_rep.get('age')}, Gender: {last_rep.get('gender')}\n"
                f"  * Current Status: {last_rep.get('status')}\n"
                f"  * Release / Upload Date & Time: {last_rep.get('latest_report_uploaded_at', 'Available')}\n"
                f"  * Booked Tests: {', '.join(last_rep.get('booked_tests', [])) or 'Diagnostic Tests'}\n"
                f"  * Referred By: {last_rep.get('referred_by')}\n"
                f"  * Report Download Link: [📄 View / Download Diagnostic Report]({last_rep.get('latest_report_url', '')})\n"
            )
            if len(reports_list) > 1:
                other_reps = [
                    f"- {r.get('patient_code')} - {r.get('name')} (Status: {r.get('status')}, Uploaded: {r.get('latest_report_uploaded_at', 'N/A')})"
                    for r in reports_list[1:4]
                ]
                rep_text += "\nOther Recent Released Reports:\n" + "\n".join(other_reps)

            rep_text += (
                f"\n\nSPECIAL INSTRUCTION: Clearly and directly tell the user which patient's report was released last, "
                f"including Patient Name, Patient ID, Release Date/Time, and ALWAYS include the clickable markdown link to view/download the report."
            )
            system_prompt += rep_text
            return system_prompt, None, result
        elif result.status == LookupStatus.service_unavailable:
            return system_prompt, result.message, result
        else:
            return system_prompt, "No released patient reports were found in the system yet.", result

    # 6. AUDIT LOGS (Admin Only)
    audit_keywords = ["audit", "audit log", "audit logs", "system log", "activity log", "security log"]
    if any(k in msg_lower for k in audit_keywords):
        if getattr(current_user, 'role', None) != RoleEnum.admin:
            return system_prompt, "You do not have permission to access audit logs.", None
        logs = db.query(AuditLog).order_by(AuditLog.occurred_at.desc()).limit(15).all()
        if not logs:
            return system_prompt, "No audit logs are available yet.", None
        log_items = []
        for l in logs:
            l_actor = getattr(l, 'actor', None)
            actor = l_actor.name if l_actor else "System"
            l_occ = getattr(l, 'occurred_at', None)
            if l_occ:
                if l_occ.tzinfo is None:
                    l_occ = l_occ.replace(tzinfo=timezone.utc)
                t_str = l_occ.astimezone(IST).strftime('%d %b %Y, %I:%M %p')
            else:
                t_str = "N/A"
            log_items.append(f"[{t_str}] Action: {l.action} | Performed By: {actor} | Entity: {getattr(l, 'entity_type', 'N/A')}")
        system_prompt += f"\n\nCRITICAL LIVE DATA:\n[Audit Logs (Top {len(log_items)})]:\n" + "\n".join(log_items)
        return system_prompt, None, None

    # 7. GENERAL ACCESSIBLE PATIENT SUMMARY (If asking "how many patients", "show patients", "total patients")
    patient_overview_triggers = ["how many patients", "total patients", "patient count", "show patients", "list patients", "all patients", "kitne patient", "kitne mareez"]
    if any(k in msg_lower for k in patient_overview_triggers) and not target_candidate:
        query = db.query(Patient).filter(Patient.deleted_at.is_(None))
        if getattr(current_user, 'role', None) == RoleEnum.staff and getattr(current_user, 'view_scope', None) != ViewScopeEnum.all:
            query = query.filter(Patient.collected_by == current_user.id)
        count = query.count()
        recent = query.order_by(Patient.created_at.desc()).limit(5).all()
        r_list = [f"{p.patient_code} - {p.name} (Status: {p.status.value if hasattr(p.status, 'value') else str(p.status)})" for p in recent]
        system_prompt += f"\n\nCRITICAL LIVE DATA:\n[Patients Overview]: Total accessible patients: {count}. Recent entries: " + " | ".join(r_list)
        return system_prompt, None, None

    # 8. GENERAL TEST CATALOG SEARCH
    if any(k in msg_lower for k in ["test", "tests", "price", "panel", "catalog"]):
        active_tests = db.query(Test).filter(Test.is_active == True).limit(8).all()
        t_summary = ", ".join([f"{t.name} (Code: {t.test_code}, Rs {t.price})" for t in active_tests])
        system_prompt += f"\n\nCRITICAL LIVE DATA:\n[Sample Active Tests]: {t_summary}"
        return system_prompt, None, None

    return system_prompt, None, None


def build_copilot_context(message: str, current_user: User, db: Session, history: Optional[list] = None) -> str:
    """Synchronous adapter preserving existing signature for legacy callers."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If in a running loop, create a new loop in a thread or execute
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                system_prompt, direct_resp, _ = pool.submit(
                    lambda: asyncio.run(build_copilot_context_async(message, current_user, db, history=history))
                ).result()
        else:
            system_prompt, direct_resp, _ = loop.run_until_complete(
                build_copilot_context_async(message, current_user, db, history=history)
            )
        if direct_resp:
            return f"{system_prompt}\n\nCRITICAL DIRECT RESPONSE REQUIRED: You MUST output exactly: '{direct_resp}'"
        return system_prompt
    except Exception as e:
        logger.warning(f"Error in sync copilot context adapter: {e}")
        return _get_base_system_prompt(current_user)
