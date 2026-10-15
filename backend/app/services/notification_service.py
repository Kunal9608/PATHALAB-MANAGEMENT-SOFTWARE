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

logger = logging.getLogger(__name__)

EMAIL_NOTIFICATIONS_ENABLED = True


class NotificationProvider(ABC):
    @abstractmethod
    def send(self, event_type: str, recipient_email: str, context: Dict[str, Any]) -> bool:
        pass


class EmailProvider(NotificationProvider):
    def send(self, event_type: str, recipient_email: str, context: Dict[str, Any]) -> bool:
        try:
            from backend.app.config import settings
            
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

            subject_map = {
                "otp": f"Your OTP for Akriti Diagnostics — {context.get('otp', '')}",
                "password_reset": "Reset your Akriti Lab password",
                "report_ready": f"Your lab report is ready — {context.get('patient_name', '')}",
                "welcome_staff": f"Welcome to Akriti Diagnostics Center — {context.get('name', '')}",
                "password_change": f"Your OTP for password change — {context.get('otp', '')}",
                "delete_verify": f"Your OTP for hard deleting patient data — {context.get('otp', '')}",
            }
            body_map = {
                "otp": f"""
                <div style="font-family:'Manrope', -apple-system, sans-serif; max-width: 480px; margin: 20px auto; border: 1px solid #E7E7E3; border-radius: 12px; overflow: hidden; background-color: #FFFFFF; box-shadow: 0 4px 12px rgba(22,32,28,0.04);">
                  <div style="background-color: #0E5C4E; padding: 24px; text-align: center;">
                    <h2 style="color: #FFFFFF; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.5px;">Akriti Diagnostics Center</h2>
                  </div>
                  <div style="padding: 32px; color: #16201C; line-height: 1.6;">
                    <p style="margin-top: 0; font-size: 15px; font-weight: 500;">Hello,</p>
                    <p style="font-size: 14px; color: #7A8880;">Use the following One-Time Password (OTP) to securely log in to your account. This code is valid for 5 minutes.</p>
                    <div style="font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #0E5C4E; padding: 18px; background-color: #E4EEEB; border-radius: 8px; text-align: center; margin: 24px 0; border: 1px solid #C4DFD8;">{context.get('otp','')}</div>
                    <p style="color: #A7B2AC; font-size: 12px; margin-bottom: 0; text-align: center;">If you did not request this login code, you can safely ignore this email.</p>
                  </div>
                </div>
                """,
                "password_reset": f"""
                <div style="font-family:'Manrope', -apple-system, sans-serif; max-width: 480px; margin: 20px auto; border: 1px solid #E7E7E3; border-radius: 12px; overflow: hidden; background-color: #FFFFFF; box-shadow: 0 4px 12px rgba(22,32,28,0.04);">
                  <div style="background-color: #0E5C4E; padding: 24px; text-align: center;">
                    <h2 style="color: #FFFFFF; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.5px;">Akriti Diagnostics Center</h2>
                  </div>
                  <div style="padding: 32px; color: #16201C; line-height: 1.6;">
                    <p style="margin-top: 0; font-size: 15px; font-weight: 500;">Password Reset Request,</p>
                    <p style="font-size: 14px; color: #7A8880;">Use the following One-Time Password (OTP) to complete your password reset. This code is valid for 5 minutes.</p>
                    <div style="font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #0E5C4E; padding: 18px; background-color: #E4EEEB; border-radius: 8px; text-align: center; margin: 24px 0; border: 1px solid #C4DFD8;">{context.get('otp','')}</div>
                    <p style="color: #A7B2AC; font-size: 12px; margin-bottom: 0; text-align: center;">If you did not request a password reset, please contact system support immediately.</p>
                  </div>
                </div>
                """,
                "report_ready": f"""
                <div style="font-family:'Manrope', -apple-system, sans-serif; max-width: 480px; margin: 20px auto; border: 1px solid #E7E7E3; border-radius: 12px; overflow: hidden; background-color: #FFFFFF; box-shadow: 0 4px 12px rgba(22,32,28,0.04);">
                  <div style="background-color: #0E5C4E; padding: 24px; text-align: center;">
                    <h2 style="color: #FFFFFF; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.5px;">Akriti Diagnostics Center</h2>
                  </div>
                  <div style="padding: 32px; color: #16201C; line-height: 1.6;">
                    <p style="margin-top: 0; font-size: 15px; font-weight: 600;">Dear {context.get('patient_name','Patient')},</p>
                    <p style="font-size: 14px; color: #7A8880;">Your diagnostic lab reports are ready and have been generated successfully.</p>
                    <div style="background-color: #FAFAF8; padding: 18px; border-radius: 8px; margin: 24px 0; border: 1px solid #E7E7E3;">
                      <div style="font-size: 13px; margin-bottom: 6px;"><strong style="color: #7A8880;">Patient ID:</strong> <span style="font-family: monospace; font-weight: 600;">{context.get('patient_code','')}</span></div>
                      <div style="font-size: 13px;"><strong style="color: #7A8880;">Status:</strong> <span style="color: #2F8F5B; font-weight: 600;">REPORT READY</span></div>
                    </div>
                    <p style="font-size: 13px; color: #7A8880; margin-bottom: 0;">Your report is attached to this email as a PDF. You may also collect a hard copy from our lab reception.</p>
                  </div>
                </div>
                """,
                "welcome_staff": f"""
                <div style="font-family:'Manrope', -apple-system, sans-serif; max-width: 480px; margin: 20px auto; border: 1px solid #E7E7E3; border-radius: 12px; overflow: hidden; background-color: #FFFFFF; box-shadow: 0 4px 12px rgba(22,32,28,0.04);">
                  <div style="background-color: #0E5C4E; padding: 24px; text-align: center;">
                    <h2 style="color: #FFFFFF; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.5px;">Welcome to Akriti Diagnostics</h2>
                  </div>
                  <div style="padding: 32px; color: #16201C; line-height: 1.6;">
                    <p style="margin-top: 0; font-size: 15px; font-weight: 600;">Dear {context.get('name','')},</p>
                    <p style="font-size: 14px; color: #7A8880;">Your staff profile has been registered successfully. Use the temporary password below to log in and configure your account:</p>
                    <div style="font-size: 24px; font-weight: 800; color: #0E5C4E; padding: 18px; background-color: #E4EEEB; border-radius: 8px; text-align: center; margin: 24px 0; border: 1px solid #C4DFD8; font-variant-numeric: tabular-nums;">{context.get('temp_password','')}</div>
                    <p style="font-size: 13px; color: #7A8880;">You will be prompted to choose a new secure password on your first login.</p>
                    <hr style="border: 0; border-top: 1px solid #E7E7E3; margin: 24px 0;">
                    <p style="color: #A7B2AC; font-size: 12px; margin-bottom: 0; text-align: center;">Akriti Diagnostics Center · Administration portal</p>
                  </div>
                </div>
                """,
                "password_change": f"""
                <div style="font-family:'Manrope', -apple-system, sans-serif; max-width: 480px; margin: 20px auto; border: 1px solid #E7E7E3; border-radius: 12px; overflow: hidden; background-color: #FFFFFF; box-shadow: 0 4px 12px rgba(22,32,28,0.04);">
                  <div style="background-color: #0E5C4E; padding: 24px; text-align: center;">
                    <h2 style="color: #FFFFFF; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.5px;">Akriti Diagnostics Center</h2>
                  </div>
                  <div style="padding: 32px; color: #16201C; line-height: 1.6;">
                    <p style="margin-top: 0; font-size: 15px; font-weight: 500;">Hello,</p>
                    <p style="font-size: 14px; color: #7A8880;">Use the following One-Time Password (OTP) to securely change your password. This code is valid for 5 minutes.</p>
                    <div style="font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #0E5C4E; padding: 18px; background-color: #E4EEEB; border-radius: 8px; text-align: center; margin: 24px 0; border: 1px solid #C4DFD8;">{context.get('otp','')}</div>
                    <p style="color: #A7B2AC; font-size: 12px; margin-bottom: 0; text-align: center;">If you did not request this, please secure your account immediately.</p>
                  </div>
                </div>
                """,
                "delete_verify": f"""
                <div style="font-family:'Manrope', -apple-system, sans-serif; max-width: 480px; margin: 20px auto; border: 1px solid #E7E7E3; border-radius: 12px; overflow: hidden; background-color: #FFFFFF; box-shadow: 0 4px 12px rgba(22,32,28,0.04);">
                  <div style="background-color: #9A0002; padding: 24px; text-align: center;">
                    <h2 style="color: #FFFFFF; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -0.5px;">Akriti Diagnostics Center</h2>
                  </div>
                  <div style="padding: 32px; color: #16201C; line-height: 1.6;">
                    <p style="margin-top: 0; font-size: 15px; font-weight: 600; color: #9A0002;">CRITICAL ACTION — Hard Delete Patient Data</p>
                    <p style="font-size: 14px; color: #7A8880;">You have requested to hard delete patient data from the system. Use the following One-Time Password (OTP) to verify and authorize this wipe. This code is valid for 5 minutes.</p>
                    <div style="font-size: 32px; font-weight: 800; letter-spacing: 6px; color: #9A0002; padding: 18px; background-color: #FDF3F3; border-radius: 8px; text-align: center; margin: 24px 0; border: 1px solid #F3D3D3;">{context.get('otp','')}</div>
                    <p style="color: #A7B2AC; font-size: 12px; margin-bottom: 0; text-align: center;">If you did not request this delete action, contact admin support immediately.</p>
                  </div>
                </div>
                """,
            }

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

            subject = subject_map.get(event_type, "Notification from Akriti Diagnostics")
            html_body = body_map.get(event_type, f"<p>{context}</p>")

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
                "htmlContent": html_body
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

            # --- WASENDER CONFIG CHECK ---
            if not settings.WASENDER_API_KEY:
                print("  [WASENDER WARNING] WASender API Key not configured — settings.WASENDER_API_KEY is empty")
                logger.warning("WASender API Key not configured — skipping notification")
                return False

            # Recipient should be a phone number. In context.get("mobile") we might have a cleaner mobile.
            mobile = context.get("mobile") or recipient_email
            if not mobile:
                logger.warning("No recipient mobile number provided — skipping WhatsApp notification")
                return False

            # Clean non-digits
            mobile = "".join(filter(str.isdigit, str(mobile)))
            if len(mobile) == 10:
                mobile = "91" + mobile

            # We need to map event type to message template
            templates = {
                "patient_registered": "Hello {patient_name}, you have been successfully registered at Akriti Diagnostics Center. Your Patient ID is {patient_code}.",
                "status_update": "Dear {patient_name}, the status of your lab report (ID: {patient_code}) has been updated to: {status}.",
                "report_ready": "Dear {patient_name}, your diagnostic lab report for Patient ID {patient_code} is ready.",
            }

            if event_type not in templates:
                logger.warning(f"Unhandled WhatsApp event type: {event_type}")
                return False

            text_message = templates[event_type].format(
                patient_name=context.get("patient_name", "Patient"),
                patient_code=context.get("patient_code", ""),
                status=context.get("status", "").replace("_", " ").upper() if context.get("status") else ""
            )

            attachment_bytes = context.get("attachment_bytes")
            attachment_name = context.get("attachment_name", "document.pdf")

            headers = {
                "Authorization": f"Bearer {settings.WASENDER_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            # If there's an attachment, we upload it first to get a public URL
            document_url = None
            if attachment_bytes:
                encoded_bytes = base64.b64encode(attachment_bytes).decode("utf-8")
                upload_payload = {
                    "mimetype": "application/pdf",
                    "base64": f"data:application/pdf;base64,{encoded_bytes}"
                }
                
                try:
                    resp = httpx.post(
                        "https://wasenderapi.com/api/upload",
                        json=upload_payload,
                        headers=headers,
                        timeout=15.0
                    )
                    resp.raise_for_status()
                    resp_data = resp.json()
                    if resp_data.get("success"):
                        document_url = resp_data.get("publicUrl")
                        logger.info(f"WASender upload success: {document_url}")
                    else:
                        logger.error(f"WASender upload failed: {resp_data}")
                        return False
                except Exception as e:
                    logger.error(f"WASender upload exception: {e}")
                    return False

            # Prepare payload for send-message
            payload = {
                "to": f"+{mobile}",
                "text": text_message
            }

            if document_url:
                payload["documentUrl"] = document_url
                payload["fileName"] = attachment_name

            resp = httpx.post(
                "https://wasenderapi.com/api/send-message",
                json=payload,
                headers=headers,
                timeout=15.0
            )
            resp.raise_for_status()
            resp_data = resp.json()
            logger.info(f"WASender send-message response: {resp_data}")

            print(f"  [WASENDER OK] WhatsApp sent successfully: {event_type} -> {mobile}")
            return True

        except httpx.HTTPStatusError as he:
            logger.error(f"WASender HTTP Error: {he.response.status_code} - {he.response.text}")
            print(f"  [WASENDER HTTP ERROR] Code: {he.response.status_code}, Detail: {he.response.text}")
            return False
        except Exception as e:
            logger.error(f"WASender error: {e}")
            print(f"  [WASENDER ERROR] {e}")
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
