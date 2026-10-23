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
    COLORS = {
        "primary": "#176B55",
        "primary_dark": "#104D3E",
        "primary_soft": "#EAF5F0",
        "ink": "#172923",
        "muted": "#65756E",
        "border": "#DCE8E2",
        "surface": "#F5F8F6",
        "white": "#FFFFFF",
        "danger": "#A62B35",
        "danger_soft": "#FFF1F1",
    }

    @staticmethod
    def _value(context: Dict[str, Any], key: str, default: str = "") -> str:
        value = context.get(key, default)
        return default if value is None else str(value)

    @staticmethod
    def _escape(value: Any) -> str:
        """Escape dynamic values before inserting them into HTML email content."""
        import html
        return html.escape("" if value is None else str(value), quote=True)

    @staticmethod
    def _subject_value(value: Any) -> str:
        """Prevent line breaks in dynamic subject fragments."""
        return " ".join(str(value or "").replace("\r", " ").replace("\n", " ").split())[:120]

    def _layout(self, *, preheader: str, eyebrow: str, title: str, content: str,
                tone: str = "success", footer_note: str = "This is an automated message. Please do not reply to this email.") -> str:
        """Render a conservative table-based layout with inline CSS for email clients."""
        c = self.COLORS
        safe_preheader = self._escape(preheader)
        safe_eyebrow = self._escape(eyebrow)
        safe_title = self._escape(title)
        safe_footer = self._escape(footer_note)
        if tone == "danger":
            accent, soft = c["danger"], c["danger_soft"]
        else:
            accent, soft = c["primary"], c["primary_soft"]

        return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>{safe_title}</title>
</head>
<body style="margin:0;padding:0;background-color:{c['surface']};font-family:Arial,Helvetica,sans-serif;color:{c['ink']};-webkit-text-size-adjust:100%;">
  <div style="display:none!important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;overflow:hidden;mso-hide:all;">{safe_preheader}</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;background-color:{c['surface']};border-collapse:collapse;">
    <tr><td align="center" style="padding:28px 12px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600" style="width:100%;max-width:600px;border-collapse:separate;border-spacing:0;background-color:{c['white']};border:1px solid {c['border']};border-radius:16px;overflow:hidden;">
        <tr><td style="padding:0;background-color:{c['primary_dark']};">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
            <tr><td style="padding:26px 28px 24px;">
              <div style="font-size:11px;line-height:16px;font-weight:700;letter-spacing:1.7px;text-transform:uppercase;color:#CDE8DC;">{safe_eyebrow}</div>
              <div style="padding-top:8px;font-size:23px;line-height:30px;font-weight:700;letter-spacing:-0.35px;color:#FFFFFF;">{safe_title}</div>
              <div style="padding-top:8px;font-size:13px;line-height:20px;color:#DDEDE6;">{self.BRAND}</div>
            </td></tr>
          </table>
        </td></tr>
        <tr><td style="padding:30px 28px 26px;font-size:15px;line-height:25px;color:{c['ink']};">
          {content}
        </td></tr>
        <tr><td style="padding:18px 28px 22px;background-color:#FAFCFB;border-top:1px solid {c['border']};">
          <div style="font-size:12px;line-height:19px;color:{c['muted']};">{safe_footer}</div>
          <div style="padding-top:8px;font-size:11px;line-height:17px;color:#87958E;">{self.BRAND} &middot; Secure notifications</div>
        </td></tr>
      </table>
      <div style="max-width:560px;padding:14px 8px 0;font-size:11px;line-height:17px;color:#87958E;text-align:center;">If you believe this message was sent to you by mistake, you may ignore it unless the message describes an action you did not request.</div>
    </td></tr>
  </table>
</body>
</html>'''

    def _render_template(self, event_type: str, context: Dict[str, Any]):
        """Return subject, HTML and plain-text bodies for supported email events."""
        c = self.COLORS
        name = self._escape(self._value(context, "name", "there").strip() or "there")
        patient_name = self._escape(self._value(context, "patient_name", "Patient").strip() or "Patient")
        patient_code = self._escape(self._value(context, "patient_code").strip() or "Not provided")
        otp = self._escape(self._value(context, "otp").strip())
        temp_password = self._escape(self._value(context, "temp_password").strip())

        if event_type == "otp":
            subject = "Your secure verification code | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 14px;">Hello {name},</p>
<p style="margin:0 0 20px;color:{c['muted']};">Use this one-time password to verify your request. For your security, the code is time-limited.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 20px;"><tr><td align="center" style="padding:22px 14px;background-color:{c['primary_soft']};border:1px solid #C9E3D7;border-radius:12px;">
<div style="font-size:11px;line-height:16px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;color:{c['primary']};">One-time password</div>
<div style="padding-top:8px;font-family:Consolas,'Courier New',monospace;font-size:32px;line-height:40px;font-weight:700;letter-spacing:7px;color:{c['primary_dark']};">{otp}</div>
</td></tr></table>
<p style="margin:0 0 10px;font-size:13px;line-height:21px;color:{c['muted']};">This code is valid for 5 minutes. Do not share it with anyone, including someone claiming to be from support.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you did not request this code, you can ignore this email.</p>'''
            text_body = f"Hello {self._value(context, 'name', 'there')},\n\nYour one-time verification code is: {self._value(context, 'otp')}\n\nThis code is valid for 5 minutes. Do not share it with anyone. If you did not request it, ignore this email."
            html_body = self._layout(preheader="Your secure verification code is ready.", eyebrow="Account security", title="Verify your request", content=content)

        elif event_type == "password_reset":
            subject = "Password reset verification | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 14px;">Hello {name},</p>
<p style="margin:0 0 20px;color:{c['muted']};">We received a request to reset your account password. Enter the one-time code below in the password-reset screen to continue.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 20px;"><tr><td align="center" style="padding:22px 14px;background-color:{c['primary_soft']};border:1px solid #C9E3D7;border-radius:12px;">
<div style="font-size:11px;line-height:16px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;color:{c['primary']};">Password reset code</div>
<div style="padding-top:8px;font-family:Consolas,'Courier New',monospace;font-size:32px;line-height:40px;font-weight:700;letter-spacing:7px;color:{c['primary_dark']};">{otp}</div>
</td></tr></table>
<p style="margin:0 0 10px;font-size:13px;line-height:21px;color:{c['muted']};">This code is valid for 5 minutes. Never share it with anyone.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you did not request a password reset, do not use the code. If you suspect someone has accessed your account, contact your administrator through a trusted channel.</p>'''
            text_body = f"Hello {self._value(context, 'name', 'there')},\n\nYour password reset verification code is: {self._value(context, 'otp')}\n\nThis code is valid for 5 minutes. Never share it. If you did not request a reset, do not use the code and contact your administrator through a trusted channel if concerned."
            html_body = self._layout(preheader="Complete your password reset securely.", eyebrow="Account security", title="Reset your password", content=content)

        elif event_type == "password_change":
            subject = "Password change verification | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 14px;">Hello {name},</p>
<p style="margin:0 0 20px;color:{c['muted']};">Use the verification code below to confirm your password-change request.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 20px;"><tr><td align="center" style="padding:22px 14px;background-color:{c['primary_soft']};border:1px solid #C9E3D7;border-radius:12px;">
<div style="font-size:11px;line-height:16px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;color:{c['primary']};">Verification code</div>
<div style="padding-top:8px;font-family:Consolas,'Courier New',monospace;font-size:32px;line-height:40px;font-weight:700;letter-spacing:7px;color:{c['primary_dark']};">{otp}</div>
</td></tr></table>
<p style="margin:0 0 10px;font-size:13px;line-height:21px;color:{c['muted']};">This code is valid for 5 minutes. Do not share it with anyone.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you did not request this change, do not use the code and contact your administrator through a trusted channel.</p>'''
            text_body = f"Hello {self._value(context, 'name', 'there')},\n\nYour password-change verification code is: {self._value(context, 'otp')}\n\nThis code is valid for 5 minutes. Do not share it. If you did not request this change, contact your administrator through a trusted channel."
            html_body = self._layout(preheader="Confirm your password-change request.", eyebrow="Account security", title="Confirm password change", content=content)

        elif event_type == "delete_verify":
            subject = "Confirmation required for a sensitive data-deletion request"
            content = f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 20px;"><tr><td style="padding:14px 16px;background-color:{c['danger_soft']};border:1px solid #F0CCCC;border-radius:10px;">
<div style="font-size:12px;line-height:18px;font-weight:700;letter-spacing:.8px;text-transform:uppercase;color:{c['danger']};">Sensitive action</div>
<div style="padding-top:4px;font-size:14px;line-height:22px;font-weight:700;color:#76232A;">Patient data deletion verification</div>
</td></tr></table>
<p style="margin:0 0 18px;">Hello {name},</p>
<p style="margin:0 0 20px;color:{c['muted']};">A request was made to verify a sensitive patient-data deletion action. Enter the one-time code below only if you initiated this request in the application.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 20px;"><tr><td align="center" style="padding:22px 14px;background-color:{c['danger_soft']};border:1px solid #F0CCCC;border-radius:12px;">
<div style="font-size:11px;line-height:16px;letter-spacing:1.5px;text-transform:uppercase;font-weight:700;color:{c['danger']};">Confirmation code</div>
<div style="padding-top:8px;font-family:Consolas,'Courier New',monospace;font-size:32px;line-height:40px;font-weight:700;letter-spacing:7px;color:{c['danger']};">{otp}</div>
</td></tr></table>
<p style="margin:0 0 10px;font-size:13px;line-height:21px;color:{c['muted']};">This code is valid for 5 minutes. It verifies the request; it does not itself confirm that deletion has completed.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you did not initiate this action, do not share or use the code. Contact your administrator through a trusted channel immediately.</p>'''
            text_body = f"Sensitive action verification\n\nHello {self._value(context, 'name', 'there')},\nA request was made to verify a patient-data deletion action. Use this code only if you initiated the request: {self._value(context, 'otp')}\n\nThe code is valid for 5 minutes. It does not itself mean deletion has completed. If you did not initiate this action, do not use or share the code and contact your administrator."
            html_body = self._layout(preheader="Verification is required for a sensitive deletion request.", eyebrow="Security confirmation", title="Confirm sensitive action", content=content, tone="danger", footer_note="Security notice: never share this verification code.")

        elif event_type == "welcome_staff":
            subject = "Your Akriti Diagnostics staff account"
            content = f'''<p style="margin:0 0 14px;">Welcome, {name}.</p>
<p style="margin:0 0 18px;color:{c['muted']};">Your staff profile has been created in the Akriti Diagnostics Center system. Use the initial sign-in credential supplied by your administrator to access the portal.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 20px;"><tr><td style="padding:16px 18px;background-color:{c['surface']};border:1px solid {c['border']};border-radius:10px;">
<div style="font-size:11px;line-height:16px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{c['muted']};">Initial sign-in credential</div>
<div style="padding-top:8px;font-family:Consolas,'Courier New',monospace;font-size:18px;line-height:26px;font-weight:700;overflow-wrap:anywhere;color:{c['ink']};">{temp_password}</div>
</td></tr></table>
<p style="margin:0 0 10px;font-size:13px;line-height:21px;color:{c['muted']};">You must change the temporary password at your first sign-in if prompted. Never share your credentials or reuse this password on another service.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">If you were not expecting this account, contact your administrator through a trusted channel before signing in.</p>'''
            text_body = f"Welcome, {self._value(context, 'name', 'there')}.\n\nYour staff profile has been created. Initial sign-in credential: {self._value(context, 'temp_password')}\n\nChange the temporary password at first sign-in if prompted. Do not share it or reuse it elsewhere. If you were not expecting this account, contact your administrator."
            html_body = self._layout(preheader="Your staff account has been created.", eyebrow="Staff account", title="Welcome to the team", content=content, footer_note="This message contains an initial sign-in credential. Store it securely and do not forward this email.")

        elif event_type in ("report_ready", "report_released"):
            subject = "Your diagnostic report is ready | Akriti Diagnostics"
            content = f'''<p style="margin:0 0 14px;">Dear {patient_name},</p>
<p style="margin:0 0 20px;color:{c['muted']};">Your diagnostic report has been prepared. The attached PDF contains the report document for your reference.</p>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;margin:0 0 20px;"><tr><td style="padding:18px;background-color:{c['surface']};border:1px solid {c['border']};border-radius:10px;">
<div style="font-size:11px;line-height:16px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{c['muted']};">Report reference</div>
<div style="padding-top:6px;font-size:18px;line-height:25px;font-weight:700;color:{c['ink']};">{patient_code}</div>
<div style="padding-top:10px;font-size:13px;line-height:20px;color:{c['primary']};font-weight:700;">Report prepared</div>
</td></tr></table>
<p style="margin:0 0 10px;font-size:13px;line-height:21px;color:{c['muted']};">Please keep the attached report private and share it only with the appropriate healthcare professional. If you believe this report was sent to you in error, contact the laboratory through a trusted channel.</p>
<p style="margin:0;font-size:13px;line-height:21px;color:{c['muted']};">You may contact the laboratory reception if you need assistance or a printed copy.</p>'''
            text_body = f"Dear {self._value(context, 'patient_name', 'Patient')},\n\nYour diagnostic report has been prepared. Report reference: {self._value(context, 'patient_code', 'Not provided')}\n\nThe report PDF is attached if included with this email. Please keep it private and share it only with the appropriate healthcare professional. Contact the laboratory reception if you need assistance or a printed copy."
            html_body = self._layout(preheader="Your diagnostic report has been prepared.", eyebrow="Diagnostic services", title="Your report is ready", content=content, footer_note="Confidential: this email and any attached report are intended only for the recipient. If received in error, contact the laboratory and delete the message.")

        else:
            # Never dump the full context into an email; it may contain sensitive data.
            subject = "A notification from Akriti Diagnostics"
            content = f'''<p style="margin:0 0 12px;">Hello {name},</p>
<p style="margin:0;color:{c['muted']};">You have received a notification from Akriti Diagnostics Center. Please sign in through your usual trusted application entry point if further action is required.</p>'''
            text_body = f"Hello {self._value(context, 'name', 'there')},\n\nYou have received a notification from Akriti Diagnostics Center. Sign in through your usual trusted application entry point if further action is required."
            html_body = self._layout(preheader="A notification from Akriti Diagnostics Center.", eyebrow="Notification", title="You have a notification", content=content)

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
