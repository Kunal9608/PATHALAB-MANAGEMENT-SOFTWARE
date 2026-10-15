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
- Admin can access everything.
- Staff can ONLY access records they are authorized to view.
- If user lacks permission, reply: "You do not have permission to access this information."

STRICT DOMAIN LIMIT:
- Only answer PathLab Management System related questions.
- If unrelated, reply: "I can only assist with the PathLab Management System."

STRICT ANTI-HALLUCINATION POLICY:
- Backend is always the ONLY source of truth.
- NEVER invent patient names, financial figures, test codes, or statuses.
- Use ONLY the verified data explicitly provided in CRITICAL LIVE DATA below.
- NEVER output <think> or </think> tags.

PRESENTATION & FORMATTING GUIDELINES:
- Use clean Markdown with bullet points, bold labels (**Label:**), and markdown links ([Text](url)).
- When a Patient Record is found, provide a COMPLETE, thorough, and beautifully formatted response containing:
  1. **Patient Info**: Name, Code, Age, Gender, Mobile Number.
  2. **Status & Timeline**: Current Status (e.g. Report Ready, Sample Collected), Sample Date.
  3. **Doctor & Staff**: Referred By (Doctor Name), Sample Collected By (Staff Name).
  4. **Booked Tests**: Names of all tests booked for this patient.
  5. **Billing & Accounts**: Total Bill, Discount, Amount Paid, Amount Due, Payment Status.
  6. **Diagnostic Reports**: If a report is uploaded / ready, ALWAYS output ONLY the single latest report link: [📄 View / Download Latest Report (vX - Uploaded: ...)](download_url). NEVER list duplicate or older superseded versions.
  7. **Test Results**: If parameter values are recorded, list each parameter name, entered value, unit, and note any ⚠️ (ABNORMAL) findings clearly.
- If the user asks a specific question (e.g. only "what is the bill" or "is report ready"), answer that directly while still being helpful.
"""


async def build_copilot_context_async(
    message: str,
    current_user: User,
    db: Session
) -> Tuple[str, Optional[str], Optional[BackendLookupResult]]:
    """
    Asynchronous deterministic context builder.
    Returns:
        (system_prompt, direct_authoritative_response, lookup_result)
        If direct_authoritative_response is not None, the router streams this
        exact message directly, bypassing the LLM to guarantee 100% factual accuracy.
    """
    msg_trimmed = message.strip()
    msg_lower = msg_trimmed.lower()
    system_prompt = _get_base_system_prompt(current_user)

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
        
        # Reports — ONLY the single latest report version is displayed
        reports_summary = "No reports uploaded."
        if p_data.get("reports"):
            latest_r = p_data["reports"][0]
            v_tag = f" ({latest_r.get('version_label', 'Latest')})" if latest_r.get('version_label') else ""
            reports_summary = f"\n  - [📄 View / Download Latest Report{v_tag} (Uploaded: {latest_r['uploaded_at']})]({latest_r['download_url']})"

        # Booked Tests
        tests_summary = ", ".join(p_data.get("booked_tests", [])) or "None specified"

        # Test Results
        results_summary = "No test results recorded yet."
        if p_data.get("test_results"):
            tr_items = [
                f"{tr['parameter']}: {tr['value']} {tr['unit']}{' ⚠️ (ABNORMAL)' if tr.get('is_abnormal') else ''}"
                for tr in p_data.get("test_results", [])
            ]
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
            f"SPECIAL INSTRUCTION: Present the COMPLETE detailed patient summary containing ALL the verified fields above. "
            f"If diagnostic reports exist, you MUST provide ONLY the single latest report link (e.g. v5): [📄 View / Download Latest Report (vX - Uploaded: ...)](URL) so the user can click it directly. NEVER list multiple or older superseded report versions. "
            f"If test results exist, display them clearly. Never skip the Doctor, Staff, Booked Tests, or Reports links."
        )
        system_prompt += patient_fact_block
        return system_prompt, None, result

    # 2. MOBILE NUMBER LOOKUP
    phone_matches = PHONE_SCAN_REGEX.findall(message)
    if phone_matches:
        phone = phone_matches[0]
        result = await retrieve_by_phone(db, phone, current_user)
        if result.status in (LookupStatus.invalid_input, LookupStatus.not_found, LookupStatus.service_unavailable):
            return system_prompt, result.message, result

        if result.status == LookupStatus.success and result.data:
            summary_items = []
            for p in result.data:
                summary_items.append(
                    f"{p['patient_code']} - {p['name']} (Age: {p['age']}, Status: {p['status']}, Paid: Rs {p['amount_paid']}, Due: Rs {p['amount_due']})"
                )
            system_prompt += f"\n\nCRITICAL LIVE DATA:\n[Patients with Mobile {phone}]: Found {len(result.data)} record(s): " + " | ".join(summary_items)
            return system_prompt, None, result

    # 3. TEST CATALOG LOOKUP
    test_matches = TEST_CODE_SCAN_REGEX.findall(message)
    if test_matches:
        test_code = test_matches[0]
        result = await retrieve_test(db, test_code)
        if result.status == LookupStatus.not_found:
            return system_prompt, result.message, result
        if result.status == LookupStatus.success and result.data:
            t = result.data
            param_str = ", ".join(t.get("parameters", [])) or "None"
            system_prompt += f"\n\nCRITICAL LIVE DATA:\n[Test {t['test_code']}]: Name: {t['name']}, Price: Rs {t['price']}, Category: {t['category']}, Parameters: {param_str}."
            return system_prompt, None, result

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

    # 5.6. LATEST / LAST REGISTERED PATIENT
    latest_patient_keywords = [
        "last patient", "latest patient", "registered last", "patient registered last",
        "last registered", "latest registered", "recent patient", "recent patients",
        "who was added last", "last patient added", "aakhri patient"
    ]
    if any(k in msg_lower for k in latest_patient_keywords):
        result = await retrieve_latest_patient(db, current_user)
        if result.status == LookupStatus.success and result.data:
            p_data = result.data
            p_text = (
                f"\n\nCRITICAL LIVE DATA (Verified Latest Registered Patient from Backend):\n"
                f"- Patient Code: {p_data.get('patient_code')}\n"
                f"- Name: {p_data.get('name')}\n"
                f"- Age: {p_data.get('age')}, Gender: {p_data.get('gender')}\n"
                f"- Mobile: {p_data.get('mobile')}\n"
                f"- Status: {p_data.get('status')}\n"
                f"- Sample Date: {p_data.get('sample_date')}\n"
                f"- Referred By: {p_data.get('referred_by')}\n"
                f"- Booked Tests: {', '.join(p_data.get('booked_tests', [])) or 'None'}\n"
                f"- Total Bill: Rs {p_data.get('total_amount')} | Paid: Rs {p_data.get('amount_paid')} | Due: Rs {p_data.get('amount_due')}\n"
                f"- Payment Status: {p_data.get('payment_status')}\n"
            )
            system_prompt += p_text
            return system_prompt, None, result

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

    # 7. GENERAL ACCESSIBLE PATIENT SUMMARY (If asking "how many patients", "show patients")
    if any(k in msg_lower for k in ["patient", "patients"]) and not target_candidate:
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


def build_copilot_context(message: str, current_user: User, db: Session) -> str:
    """Synchronous adapter preserving existing signature for legacy callers."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If in a running loop, create a new loop in a thread or execute
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                system_prompt, direct_resp, _ = pool.submit(
                    lambda: asyncio.run(build_copilot_context_async(message, current_user, db))
                ).result()
        else:
            system_prompt, direct_resp, _ = loop.run_until_complete(
                build_copilot_context_async(message, current_user, db)
            )
        if direct_resp:
            return f"{system_prompt}\n\nCRITICAL DIRECT RESPONSE REQUIRED: You MUST output exactly: '{direct_resp}'"
        return system_prompt
    except Exception as e:
        logger.warning(f"Error in sync copilot context adapter: {e}")
        return _get_base_system_prompt(current_user)
