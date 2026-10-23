"""
Notification service — abstracted provider interface.
Only EmailProvider is implemented. WhatsApp/SMS are stubs.
"""
import logging
import urllib.request
import urllib.error
import json
import base64
import httpx
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod
from backend.app.config import settings

logger = logging.getLogger(__name__)

EMAIL_NOTIFICATIONS_ENABLED = True


class NotificationProvider(ABC):
    @abstractmethod
    def send(self, event_type: str, recipient_email: str, context: Dict[str, Any]) -> bool:
        pass


class EmailProvider(NotificationProvider):
    BRAND = "Akriti Diagnostics Center"
    BRAND_SHORT = "Akriti Diagnostics"
    # A restrained clinical palette: deep blue ink, soft paper, and one calm teal accent.
    COLORS = {
        "ink": "#183243",
        "body": "#344B59",
        "muted": "#627581",
        "accent": "#286C7B",
        "accent_soft": "#F1F7F9",
        "border": "#DCE6EB",
        "page": "#F2F5F7",
        "surface": "#F8FAFB",
        "white": "#FFFFFF",
    }

    @staticmethod
    def _value(context: Dict[str, Any], key: str, default: str = "") -> str:
        value = context.get(key, default)
        return default if value is None else str(value)

    @staticmethod
    def _escape(value: Any) -> str:
        # Escape dynamic values before inserting them into HTML email content.
        import html
        return html.escape("" if value is None else str(value), quote=True)

    @staticmethod
    def _subject_value(value: Any) -> str:
        # Prevent line breaks in dynamic subject fragments.
        return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:120]

    def _layout(self, *, preheader: str, title: str, content: str,
                footer_note: str = "This is an automated message from Akriti Diagnostics Center.") -> str:
        # Email-client-safe premium layout built with tables and inline CSS.
        safe_preheader = self._escape(preheader)
        safe_title = self._escape(title)
        safe_footer = self._escape(footer_note)
        c = self.COLORS
        return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>{safe_title}</title>
</head>
<body style="margin:0;padding:0;background-color:{c['page']};font-family:'Segoe UI',Arial,Helvetica,sans-serif;color:{c['body']};-webkit-text-size-adjust:100%;">
  <div style="display:none!important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;overflow:hidden;mso-hide:all;max-height:0;">{safe_preheader}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="{c['page']}" style="width:100%;border-collapse:collapse;background-color:{c['page']};">
    <tr><td align="center" style="padding:28px 12px 30px;">
      <table role="presentation" width="580" cellpadding="0" cellspacing="0" border="0" bgcolor="{c['white']}" style="width:100%;max-width:580px;border-collapse:separate;border-spacing:0;background-color:{c['white']};border:1px solid {c['border']};border-radius:15px;overflow:hidden;">
        <tr><td height="4" bgcolor="{c['accent']}" style="height:4px;line-height:4px;font-size:0;background-color:{c['accent']};">&nbsp;</td></tr>
        <tr><td style="padding:21px 26px 20px;background-color:{c['white']};border-bottom:1px solid {c['border']};">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;width:100%;">
            <tr>
              <td width="42" valign="middle" style="width:42px;padding:0 12px 0 0;">
                <table role="presentation" width="38" height="38" cellpadding="0" cellspacing="0" border="0" bgcolor="{c['accent_soft']}" style="width:38px;height:38px;border-collapse:separate;border-spacing:0;background-color:{c['accent_soft']};border:1px solid #D8E7EC;border-radius:10px;">
                  <tr><td align="center" valign="middle" style="font-family:Arial,Helvetica,sans-serif;font-size:18px;line-height:38px;font-weight:700;color:{c['accent']};">A</td></tr>
                </table>
              </td>
              <td valign="middle" style="font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:16px;line-height:22px;font-weight:700;letter-spacing:-0.2px;color:{c['ink']};">Akriti Diagnostics Center</td>
            </tr>
          </table>
        </td></tr>
        <tr><td style="padding:29px 30px 30px;background-color:{c['white']};font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
          <h1 style="margin:0 0 17px;font-family:'Segoe UI',Arial,Helvetica,sans-serif;font-size:25px;line-height:32px;font-weight:700;letter-spacing:-0.45px;color:{c['ink']};">{safe_title}</h1>
          <div style="font-size:15px;line-height:25px;color:{c['body']};">{content}</div>
        </td></tr>
        <tr><td style="padding:18px 26px 20px;background-color:{c['surface']};border-top:1px solid {c['border']};font-family:'Segoe UI',Arial,Helvetica,sans-serif;">
          <div style="font-size:12px;line-height:19px;color:{c['muted']};">{safe_footer}</div>
          <div style="padding-top:7px;font-size:12px;line-height:18px;font-weight:700;letter-spacing:0.15px;color:{c['ink']};">DO NOT REPLY TO THIS EMAIL.</div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>'''

    def _code_panel(self, code: str, label: str = "Your one-time code") -> str:
        # Compact code focus without loud blocks or unnecessary decoration.
        c = self.COLORS
        safe_label = self._escape(label)
        safe_code = self._escape(code)
        return f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:22px 0 18px;">
  <tr><td align="center" bgcolor="{c['accent_soft']}" style="padding:21px 14px 20px;background-color:{c['accent_soft']};border:1px solid #D5E5EA;border-radius:11px;text-align:center;">
    <div style="text-align:center;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;font-weight:600;color:{c['muted']};">{safe_label}</div>
    <div style="padding-top:7px;text-align:center;font-family:Arial,Helvetica,sans-serif;font-size:30px;line-height:39px;font-weight:700;letter-spacing:5px;color:{c['ink']};overflow-wrap:anywhere;">{safe_code}</div>
    <div style="padding-top:8px;text-align:center;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:18px;color:{c['muted']};">Valid for 5 minutes</div>
  </td></tr>
</table>'''

    def _render_template(self, event_type: str, context: Dict[str, Any]):
        # Return subject, HTML and plain-text bodies for each notification event.
        c = self.COLORS
        raw_name = self._value(context, "name", "there").strip() or "there"
        name = self._escape(raw_name)
        raw_patient_name = self._value(context, "patient_name", "Patient").strip() or "Patient"
        patient_name = self._escape(raw_patient_name)
        raw_patient_code = self._value(context, "patient_code").strip()
        patient_code = self._escape(raw_patient_code)
        raw_otp = self._value(context, "otp").strip()
        otp = self._escape(raw_otp)
        raw_temp_password = self._value(context, "temp_password").strip()
        temp_password = self._escape(raw_temp_password)

        if event_type == "otp":
            subject = "Your verification code | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 8px;font-weight:600;color:{c['ink']};">Hello {name},</p>
<p style="margin:0;color:{c['body']};">Use this code to complete verification in Akriti Diagnostics Center.</p>
{self._code_panel(raw_otp)}
<p style="margin:0 0 11px;font-size:13px;line-height:21px;color:{c['muted']};">For your security, do not share this code with anyone.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">Didn't request a code? You can safely ignore this email.</p>'''
            text_body = f"Hello {raw_name},\n\nYour verification code is: {raw_otp}\n\nUse it in Akriti Diagnostics Center to complete verification. It is valid for 5 minutes. Do not share it with anyone. If you did not request it, ignore this email."
            html_body = self._layout(preheader="Your verification code is inside. It is valid for 5 minutes.", title="Your verification code", content=content)

        elif event_type == "password_reset":
            subject = "Password reset code | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 8px;font-weight:600;color:{c['ink']};">Hello {name},</p>
<p style="margin:0;color:{c['body']};">We received a request to reset your password. Enter the code below on the password-reset screen to continue.</p>
{self._code_panel(raw_otp, "Password reset code")}
<p style="margin:0 0 11px;font-size:13px;line-height:21px;color:{c['muted']};">This code expires in 5 minutes. Keep it private and do not forward this email.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you didn't request a password reset, don't use the code. Contact your administrator through a trusted channel if you're concerned about your account.</p>'''
            text_body = f"Hello {raw_name},\n\nYour password reset code is: {raw_otp}\n\nEnter it on the password-reset screen. It expires in 5 minutes. Do not share it. If you did not request a reset, do not use the code and contact your administrator through a trusted channel if concerned."
            html_body = self._layout(preheader="Use this code on the password-reset screen. It expires in 5 minutes.", title="Reset your password", content=content)

        elif event_type == "password_change":
            subject = "Confirm your password change | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 8px;font-weight:600;color:{c['ink']};">Hello {name},</p>
<p style="margin:0;color:{c['body']};">Enter this code in the app to confirm your password-change request.</p>
{self._code_panel(raw_otp, "Password change code")}
<p style="margin:0 0 11px;font-size:13px;line-height:21px;color:{c['muted']};">The code expires in 5 minutes. Do not share it with anyone.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you did not request this change, do not use the code. Contact your administrator through a trusted channel.</p>'''
            text_body = f"Hello {raw_name},\n\nYour password-change code is: {raw_otp}\n\nEnter it in the app to confirm your request. It expires in 5 minutes. Do not share it. If you did not request this change, do not use the code and contact your administrator through a trusted channel."
            html_body = self._layout(preheader="Confirm your password-change request with this code.", title="Confirm password change", content=content)

        elif event_type == "delete_verify":
            subject = "Confirm your deletion request | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 8px;font-weight:600;color:{c['ink']};">Hello {name},</p>
<p style="margin:0 0 16px;color:{c['body']};">A verification code was requested for a patient-data deletion action. Only continue if you started this request in the application.</p>
{self._code_panel(raw_otp, "Deletion confirmation code")}
<p style="margin:0 0 11px;font-size:13px;line-height:21px;color:{c['muted']};">This code expires in 5 minutes. Entering it verifies the request; it does not, by itself, mean deletion has completed.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you did not start this request, do not use or share the code. Contact your administrator through a trusted channel immediately.</p>'''
            text_body = f"Hello {raw_name},\n\nA code was requested to verify a patient-data deletion action: {raw_otp}\n\nOnly use it if you started the request in the application. It expires in 5 minutes. The code does not itself confirm that deletion is complete. If you did not start this request, do not use or share the code and contact your administrator."
            html_body = self._layout(preheader="A verification code was requested for a sensitive action.", title="Confirm deletion request", content=content, footer_note="This email contains a sensitive verification code. Keep it private.")

        elif event_type == "welcome_staff":
            subject = "Your staff account is ready | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 8px;font-weight:600;color:{c['ink']};">Welcome, {name}.</p>
<p style="margin:0 0 18px;color:{c['body']};">Your staff account has been created. Use the temporary credential below to sign in to the system.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 18px;">
  <tr><td bgcolor="{c['surface']}" style="padding:16px 18px;background-color:{c['surface']};border:1px solid {c['border']};border-radius:10px;">
    <div style="font-size:12px;line-height:18px;color:{c['muted']};">Temporary password</div>
    <div style="padding-top:7px;font-family:Arial,Helvetica,sans-serif;font-size:16px;line-height:24px;font-weight:700;color:{c['ink']};overflow-wrap:anywhere;word-break:break-word;">{temp_password}</div>
  </td></tr>
</table>
<p style="margin:0 0 10px;font-size:13px;line-height:21px;color:{c['muted']};">Change this password after signing in if prompted. Never share it or reuse it on another service.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you were not expecting this account, contact your administrator before signing in.</p>'''
            text_body = f"Welcome, {raw_name}.\n\nYour staff account has been created. Temporary password: {raw_temp_password}\n\nChange this password after signing in if prompted. Never share it or reuse it on another service. If you were not expecting this account, contact your administrator before signing in."
            html_body = self._layout(preheader="Your Akriti Diagnostics staff account has been created.", title="Your staff account is ready", content=content, footer_note="This email contains a temporary sign-in credential. Store it securely.")

        elif event_type in ("report_ready", "report_released"):
            subject = "Your diagnostic report is ready | Akriti Diagnostics"
            has_attachment = bool(context.get("attachment_bytes") and context.get("attachment_name"))
            if raw_patient_code:
                report_reference = f'''<tr><td style="padding:13px 16px;border-bottom:1px solid {c['border']};font-size:13px;line-height:20px;color:{c['muted']};">Patient ID</td><td align="right" style="padding:13px 16px;border-bottom:1px solid {c['border']};font-size:14px;line-height:20px;font-weight:700;color:{c['ink']};">{patient_code}</td></tr>'''
            else:
                report_reference = ""
            if has_attachment:
                report_message = "Your diagnostic report is attached as a PDF. Open the attachment to view your report."
            else:
                report_message = "Your diagnostic report has been prepared. Please contact the laboratory reception to receive a copy."
            content = f'''<p style="margin:0 0 8px;font-weight:600;color:{c['ink']};">Dear {patient_name},</p>
<p style="margin:0 0 18px;color:{c['body']};">Your diagnostic report is ready.</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 18px;border:1px solid {c['border']};border-radius:10px;">
  {report_reference}
  <tr><td style="padding:13px 16px;font-size:13px;line-height:20px;color:{c['muted']};">Status</td><td align="right" style="padding:13px 16px;font-size:14px;line-height:20px;font-weight:700;color:{c['accent']};">Ready</td></tr>
</table>
<p style="margin:0 0 13px;color:{c['body']};">{report_message}</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">Please keep your report private and share it only with the appropriate healthcare professional. If you received this email by mistake, contact the laboratory through a trusted channel.</p>'''
            attachment_text = "Your report PDF is attached to this email." if has_attachment else "Contact the laboratory reception to receive a copy of your report."
            text_body = f"Dear {raw_patient_name},\n\nYour diagnostic report is ready.\n" + (f"Patient ID: {raw_patient_code}\n" if raw_patient_code else "") + f"Status: Ready\n\n{attachment_text}\n\nPlease keep your report private and share it only with the appropriate healthcare professional. If you received this email by mistake, contact the laboratory through a trusted channel."
            html_body = self._layout(preheader="Your diagnostic report is ready.", title="Your report is ready", content=content, footer_note="Confidential: this message and any attached report are intended only for the recipient.")

        else:
            # Do not expose arbitrary context values in generic notification emails.
            subject = "A notification from Akriti Diagnostics"
            content = f'''<p style="margin:0 0 8px;font-weight:600;color:{c['ink']};">Hello {name},</p>
<p style="margin:0;color:{c['body']};">You have received a notification from Akriti Diagnostics Center. If action is needed, sign in through your usual trusted application entry point.</p>'''
            text_body = f"Hello {raw_name},\n\nYou have received a notification from Akriti Diagnostics Center. If action is needed, sign in through your usual trusted application entry point."
            html_body = self._layout(preheader="A notification from Akriti Diagnostics Center.", title="You have a notification", content=content)

        text_body = text_body.rstrip() + "\n\nThis is an automated message from Akriti Diagnostics Center.\nDO NOT REPLY TO THIS EMAIL."
        return subject, html_body, text_body

    def send(self, event_type: str, recipient_email: str, context: Dict[str, Any]) -> bool:
        try:
            if not recipient_email or "@" not in str(recipient_email):
                return False

            # --- BREVO CONFIG CHECK ---
            if not settings.BREVO_API_KEY:
                print("  [BREVO WARNING] Brevo API Key not configured — settings.BREVO_API_KEY is empty")
                logger.warning("Brevo API Key not configured — skipping notification")
                return False

            # --- COMMENTED OUT SMTP CONFIGURATION (DO NOT REMOVE) ---
            # if not settings.MAIL_USERNAME or not settings.MAIL_PASSWORD:
            #     print("  [MAIL WARNING] Email not configured — settings.MAIL_USERNAME or settings.MAIL_PASSWORD is empty")
            #     logger.warning("Email not configured — skipping notification")
            #     return False
            #
            # import smtplib
            # from email.mime.text import MIMEText
            # from email.mime.multipart import MIMEMultipart
            # from email.mime.base import MIMEBase
            # from email import encoders
            # --------------------------------------------------------

            subject, html_body, text_body = self._render_template(event_type, context or {})

            attachment_bytes = context.get("attachment_bytes")
            attachment_name  = context.get("attachment_name")

            # --- COMMENTED OUT SMTP EMAIL CONSTRUCTION (DO NOT REMOVE) ---
            # if attachment_bytes and attachment_name:
            #     msg = MIMEMultipart("mixed")
            #     html_part = MIMEMultipart("alternative")
            #     html_body = body_map.get(event_type, f"<p>{context}</p>")
            #     html_part.attach(MIMEText(html_body, "html"))
            #     msg.attach(html_part)
            #
            #     # Attach the PDF
            #     part = MIMEBase("application", "pdf")
            #     part.set_payload(attachment_bytes)
            #     encoders.encode_base64(part)
            #     part.add_header(
            #         "Content-Disposition",
            #         "attachment",
            #         filename=attachment_name,
            #     )
            #     msg.attach(part)
            # else:
            #     msg = MIMEMultipart("alternative")
            #     html_body = body_map.get(event_type, f"<p>{context}</p>")
            #     msg.attach(MIMEText(html_body, "html"))
            #
            # msg["Subject"] = subject_map.get(event_type, "Notification from Akriti Diagnostics")
            # msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>"
            # msg["To"] = recipient_email
            #
            # with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=10.0) as server:
            #     server.ehlo()
            #     if settings.MAIL_TLS:
            #         server.starttls()
            #     server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            #     server.sendmail(settings.MAIL_FROM, recipient_email, msg.as_string())
            # -------------------------------------------------------------

            # --- ACTIVE BREVO TRANSACTIONAL EMAIL REST CLIENT IMPLEMENTATION ---

            payload = {
                "sender": {
                    "name": settings.MAIL_FROM_NAME,
                    "email": settings.MAIL_FROM
                },
                "to": [
                    {
                        "email": recipient_email
                    }
                ],
                "subject": subject,
                "htmlContent": html_body,
                "textContent": text_body
            }

            if attachment_bytes and attachment_name:
                attachment_content = base64.b64encode(attachment_bytes).decode("utf-8")
                payload["attachment"] = [
                    {
                        "name": attachment_name,
                        "content": attachment_content
                    }
                ]

            headers = {
                "api-key": settings.BREVO_API_KEY,
                "Content-Type": "application/json",
                "Accept": "application/json"
            }

            req = urllib.request.Request(
                "https://api.brevo.com/v3/smtp/email",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST"
            )

            with urllib.request.urlopen(req, timeout=10.0) as response:
                resp_data = response.read().decode("utf-8")
                logger.info(f"Brevo API response: {resp_data}")

            print(f"  [BREVO OK] Email sent successfully via Brevo API: {event_type} -> {recipient_email}")
            logger.info(f"Email sent via Brevo API: {event_type} -> {recipient_email}")
            return True

        except urllib.error.HTTPError as he:
            try:
                err_body = he.read().decode("utf-8")
            except Exception:
                err_body = "Could not read error body"
            print(f"  [BREVO HTTP ERROR] Code: {he.code}, Detail: {err_body}")
            logger.error(f"Brevo HTTP Error: {he.code} - {err_body}")
            return False
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  [BREVO ERROR] Email send failed: {e}")
            logger.error(f"Email send failed via Brevo API: {e}")
            return False


class WhatsAppProvider(NotificationProvider):
    def send(self, event_type: str, recipient_email: str, context: Dict[str, Any]) -> bool:
        try:
            from backend.app.config import settings
            from backend.app.services.whatsapp_service import whatsapp_service

            if not settings.WHATSAPP_ENABLED:
                logger.info("WhatsApp notifications disabled in settings — skipping")
                return False

            mobile = context.get("mobile") or recipient_email
            if not mobile:
                logger.warning("No recipient mobile number provided — skipping WhatsApp notification")
                return False

            clean_mobile = "".join(filter(str.isdigit, str(mobile)))
            if not clean_mobile:
                return False

            patient_name = context.get("patient_name", "Patient")
            patient_code = context.get("patient_code", "")

            # 1. Report Ready Event — TEXT NOTIFICATION ONLY (No PDF attached)
            if event_type == "report_ready":
                age = context.get("age", "")
                age_str = f"• Age: *{age} yrs*\n" if age else ""
                reg_date = context.get("registered_date", "")
                date_str = f"• Registered Date: *{reg_date}*\n" if reg_date else ""

                text = (
                    f"*{settings.LAB_NAME}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"🔔 *Diagnostic Report Ready*\n\n"
                    f"Dear *{patient_name}*,\n"
                    f"Your diagnostic test report is now *READY*.\n\n"
                    f"📋 *Patient Details:*\n"
                    f"• Patient ID: *{patient_code}*\n"
                    f"• Name: *{patient_name}*\n"
                    f"{age_str}"
                    f"{date_str}\n"
                    f"📢 *Important Notice:*\n"
                    f"Your report is ready, please collect your printed report from our lab staff / reception desk.\n\n"
                    f"Thank you for choosing *{settings.LAB_NAME}*!"
                )
                return whatsapp_service.send_text(
                    clean_mobile,
                    text,
                    idempotency_key=f"report_ready:{patient_code}:{clean_mobile}"
                )

            # 1b. Report Released Event — DISPATCH OFFICIAL PDF DOCUMENT
            elif event_type == "report_released":
                attachment_bytes = context.get("attachment_bytes")
                attachment_name = context.get("attachment_name", f"Report_{patient_code}.pdf")
                return whatsapp_service.send_report(
                    mobile=clean_mobile,
                    patient_name=patient_name,
                    patient_code=patient_code,
                    pdf_bytes=attachment_bytes,
                    file_name=attachment_name
                )

            # 2. Patient Registration Event — SEND NAME, NUMBER, AGE, PATIENT ID, BILL AMOUNT
            elif event_type == "patient_registered":
                mobile_no = context.get("mobile", clean_mobile)
                age = context.get("age", "")
                age_str = f"• Age: *{age} yrs*\n" if age else ""
                reg_date = context.get("registered_date", "")
                date_str = f"• Date: *{reg_date}*\n" if reg_date else ""

                total_amt = context.get("total_amount")
                paid_amt = context.get("amount_paid")
                due_amt = context.get("due_amount")

                billing_lines = ""
                if total_amt is not None:
                    billing_lines = f"• Total Bill Amount: *₹{float(total_amt):,.2f}*\n"
                    if paid_amt is not None and float(paid_amt) > 0:
                        billing_lines += f"• Amount Paid: *₹{float(paid_amt):,.2f}*\n"
                    if due_amt is not None and float(due_amt) > 0:
                        billing_lines += f"• Balance Due: *₹{float(due_amt):,.2f}*\n"

                text = (
                    f"*{settings.LAB_NAME}*\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"✅ *Registration Successful!*\n\n"
                    f"Hello *{patient_name}*,\n"
                    f"You have been successfully registered with our lab.\n\n"
                    f"📋 *Registration Details:*\n"
                    f"• Patient ID: *{patient_code}*\n"
                    f"• Name: *{patient_name}*\n"
                    f"• Mobile: *{mobile_no}*\n"
                    f"{age_str}"
                    f"{date_str}"
                    f"{billing_lines}\n"
                    f"We will notify you on WhatsApp as soon as your diagnostic report is ready.\n\n"
                    f"Thank you for choosing *{settings.LAB_NAME}*!"
                )
                return whatsapp_service.send_text(
                    clean_mobile,
                    text,
                    idempotency_key=f"registered:{patient_code}:{clean_mobile}"
                )

            # 3. Status Update Event
            elif event_type == "status_update":
                status = context.get("status", "").replace("_", " ").upper()
                text = (
                    f"*{settings.LAB_NAME}*\n\n"
                    f"Dear *{patient_name}*,\n"
                    f"The status of your sample (Patient ID: *{patient_code}*) is now: *{status}*."
                )
                return whatsapp_service.send_text(
                    clean_mobile,
                    text,
                    idempotency_key=f"status:{patient_code}:{status}:{clean_mobile}"
                )

            # 4. OTP Event
            elif event_type == "otp":
                otp_code = context.get("otp", "")
                return whatsapp_service.send_otp(clean_mobile, otp_code, name=patient_name)

            else:
                logger.warning(f"Unhandled WhatsApp notification event: {event_type}")
                return False

        except Exception as e:
            logger.error(f"WhatsApp notification provider error: {e}")
            return False


class SmsProvider(NotificationProvider):
    """Stub — not enabled in v1. Fill in send() method to enable."""
    def send(self, event_type: str, recipient_email: str, context: Dict[str, Any]) -> bool:
        raise NotImplementedError("SMS provider not enabled in this version")


# Provider registry — add WhatsApp/SMS here when ready to enable
PROVIDER_REGISTRY: Dict[str, list] = {
    "otp": [EmailProvider()],
    "password_reset": [EmailProvider()],
    "report_ready": [EmailProvider(), WhatsAppProvider()],
    "report_released": [EmailProvider(), WhatsAppProvider()],
    "welcome_staff": [EmailProvider()],
    "password_change": [EmailProvider()],
    "delete_verify": [EmailProvider()],
    "patient_registered": [WhatsAppProvider()],
    "status_update": [WhatsAppProvider()],
}


def notify(event_type: str, recipient_email: str, context: Dict[str, Any]):
    print(f"  [MAIL START] notify() called: {event_type} -> {recipient_email}")
    """
    Single call point for all notifications throughout the system.
    Never call provider.send() directly — always go through this function.
    """
    if not EMAIL_NOTIFICATIONS_ENABLED:
        print(f"  [MAIL SKIP] Notification skipped (emails disabled globally): {event_type} -> {recipient_email}")
        logger.info(f"Notification skipped (emails disabled globally): {event_type} -> {recipient_email}")
        return

    providers = PROVIDER_REGISTRY.get(event_type, [])
    for provider in providers:
        try:
            provider.send(event_type, recipient_email, context)
        except NotImplementedError:
            pass
        except Exception as e:
            logger.error(f"Notification error [{event_type}]: {e}")
