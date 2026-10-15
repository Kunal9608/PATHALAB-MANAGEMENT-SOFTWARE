"""
PathLab OS — WhatsApp Service Client
Manages communication between FastAPI backend and the internal Node.js WhatsApp microservice.
Enforces admin-only operations, token authentication, error handling, and timeout limits.
"""
import logging
import httpx
import base64
from typing import Optional, Dict, Any
from backend.app.config import settings

logger = logging.getLogger("akriti.whatsapp.service")


class WhatsAppServiceClient:
    def __init__(self):
        self.service_url = settings.WHATSAPP_SERVICE_URL.rstrip("/")
        self.service_token = settings.WHATSAPP_SERVICE_TOKEN
        self.timeout = float(settings.WHATSAPP_MESSAGE_TIMEOUT_SECONDS)
        self._effective_url: Optional[str] = None

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.service_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "PathLabOS-FastAPI-Client/1.0"
        }

    def _candidate_urls(self) -> list:
        urls = []
        if self._effective_url:
            urls.append(self._effective_url)
        if self.service_url and self.service_url not in urls:
            urls.append(self.service_url)
        for candidate in [
            "http://whatsapp:3001",
            "http://host.docker.internal:3001",
            "http://127.0.0.1:3001",
            "http://localhost:3001",
        ]:
            if candidate not in urls:
                urls.append(candidate)
        return urls

    def get_status(self) -> Dict[str, Any]:
        """Fetch current connection status of the WhatsApp client."""
        if not settings.WHATSAPP_ENABLED:
            return {
                "enabled": False,
                "connected": False,
                "status": "disabled",
                "message": "WhatsApp service is disabled in configuration"
            }

        last_error = None
        for candidate in self._candidate_urls():
            try:
                with httpx.Client(timeout=4.0) as client:
                    resp = client.get(f"{candidate}/status", headers=self._get_headers())
                    if resp.status_code == 200:
                        self._effective_url = candidate
                        data = resp.json().get("data", {})
                        user_data = data.get("user") or {}
                        phone_val = user_data.get("phone") or (user_data.get("id", "").split(":")[0] if isinstance(user_data, dict) else "")
                        return {
                            "enabled": True,
                            "service_online": True,
                            "connected": data.get("connected", False),
                            "status": data.get("status", "disconnected"),
                            "user": user_data,
                            "phone": phone_val,
                            "name": user_data.get("name", "Akriti Diagnostics WhatsApp") if isinstance(user_data, dict) else "Akriti Diagnostics WhatsApp",
                            "connected_at": data.get("lastConnectedAt"),
                            "lastConnectedAt": data.get("lastConnectedAt"),
                            "lastDisconnectedAt": data.get("lastDisconnectedAt"),
                            "lastError": data.get("lastError"),
                            "hasSavedSession": data.get("hasSavedSession", False)
                        }
                    else:
                        last_error = f"Service responded with status {resp.status_code}"
            except Exception as e:
                last_error = str(e)
                continue

        logger.error(f"WhatsApp service offline or unreachable on all candidates: {last_error}")
        return {
            "enabled": True,
            "service_online": False,
            "connected": False,
            "status": "service_offline",
            "message": "WhatsApp microservice is offline or unreachable"
        }

    def connect(self) -> Dict[str, Any]:
        """Trigger connection initialization to generate a QR code."""
        if not settings.WHATSAPP_ENABLED:
            return {"success": False, "error": "WhatsApp integration is disabled in configuration"}

        for candidate in self._candidate_urls():
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(f"{candidate}/connect", headers=self._get_headers())
                    if resp.status_code == 200:
                        self._effective_url = candidate
                        return resp.json()
            except Exception as e:
                continue

        return {"success": False, "error": "Failed to connect: WhatsApp service unreachable"}

    def get_qr(self) -> Dict[str, Any]:
        """Retrieve the current QR code data URL."""
        if not settings.WHATSAPP_ENABLED:
            return {"success": False, "error": "WhatsApp integration is disabled"}

        for candidate in self._candidate_urls():
            try:
                with httpx.Client(timeout=5.0) as client:
                    resp = client.get(f"{candidate}/qr", headers=self._get_headers())
                    if resp.status_code == 200:
                        self._effective_url = candidate
                        return resp.json().get("data", {})
            except Exception:
                continue

        return {"success": False, "error": "WhatsApp microservice is offline"}

    def disconnect(self) -> Dict[str, Any]:
        """Log out and clear the active WhatsApp session."""
        for candidate in self._candidate_urls():
            try:
                with httpx.Client(timeout=10.0) as client:
                    resp = client.post(f"{candidate}/disconnect", headers=self._get_headers())
                    if resp.status_code == 200:
                        self._effective_url = candidate
                        return resp.json()
            except Exception:
                continue

        return {"success": False, "error": "WhatsApp service unreachable"}

    def send_text(self, to: str, text: str, idempotency_key: Optional[str] = None) -> bool:
        """Send a standard text message."""
        if not settings.WHATSAPP_ENABLED:
            logger.info("WhatsApp disabled — skipping text send")
            return False

        payload = {
            "to": to,
            "text": text,
            "idempotencyKey": idempotency_key
        }

        for candidate in self._candidate_urls():
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(
                        f"{candidate}/messages/send",
                        json=payload,
                        headers=self._get_headers()
                    )
                    if resp.status_code == 200 and resp.json().get("success"):
                        self._effective_url = candidate
                        logger.info(f"WhatsApp text message sent successfully to {to}")
                        return True
                    else:
                        logger.error(f"WhatsApp send failed on {candidate}: {resp.status_code} - {resp.text}")
            except Exception as e:
                continue

        return False

    def send_document(
        self,
        to: str,
        document_bytes: bytes,
        file_name: str,
        caption: str = "",
        mimetype: str = "application/pdf",
        idempotency_key: Optional[str] = None
    ) -> bool:
        """Send a document (e.g. PDF Report) with optional caption."""
        if not settings.WHATSAPP_ENABLED:
            logger.info("WhatsApp disabled — skipping document send")
            return False

        b64_doc = base64.b64encode(document_bytes).decode("utf-8")
        payload = {
            "to": to,
            "type": "document",
            "document": b64_doc,
            "fileName": file_name,
            "caption": caption,
            "mimetype": mimetype,
            "idempotencyKey": idempotency_key
        }

        for candidate in self._candidate_urls():
            try:
                with httpx.Client(timeout=self.timeout * 2) as client:
                    resp = client.post(
                        f"{candidate}/messages/send",
                        json=payload,
                        headers=self._get_headers()
                    )
                    if resp.status_code == 200 and resp.json().get("success"):
                        self._effective_url = candidate
                        logger.info(f"WhatsApp document sent successfully to {to}: {file_name}")
                        return True
                    else:
                        logger.error(f"WhatsApp document send failed on {candidate}: {resp.status_code} - {resp.text}")
            except Exception as e:
                continue

        return False

    def send_otp(self, mobile: str, otp_code: str, name: Optional[str] = None) -> bool:
        """Deliver a 6-digit OTP to patient's mobile number via WhatsApp."""
        clean_mobile = "".join(filter(str.isdigit, str(mobile)))
        greeting = f"Hello {name}," if name else "Hello,"
        message = (
            f"*{settings.LAB_NAME}*\n\n"
            f"{greeting}\n"
            f"Your verification One-Time Password (OTP) is: *{otp_code}*\n\n"
            f"This OTP is valid for 5 minutes. Please do not share this code with anyone.\n\n"
            f"_Akriti Diagnostics Center_"
        )
        return self.send_text(clean_mobile, message, idempotency_key=f"otp:{clean_mobile}:{otp_code}")

    def send_report(
        self,
        mobile: str,
        patient_name: str,
        patient_code: str,
        pdf_bytes: Optional[bytes] = None,
        file_name: Optional[str] = None
    ) -> bool:
        """Deliver diagnostic report via WhatsApp to patient's mobile number."""
        clean_mobile = "".join(filter(str.isdigit, str(mobile)))
        if not clean_mobile:
            logger.warning("No valid mobile number for WhatsApp report delivery")
            return False

        caption = (
            f"*{settings.LAB_NAME} — Diagnostic Report*\n\n"
            f"Dear *{patient_name}*,\n"
            f"Your diagnostic lab report for Patient ID *{patient_code}* is now ready.\n\n"
            f"The official signed PDF report is attached below.\n"
            f"Thank you for choosing Akriti Diagnostics Center."
        )

        fname = file_name or f"Report_{patient_code}.pdf"

        if pdf_bytes:
            return self.send_document(
                to=clean_mobile,
                document_bytes=pdf_bytes,
                file_name=fname,
                caption=caption,
                mimetype="application/pdf",
                idempotency_key=f"report:{patient_code}:{clean_mobile}"
            )
        else:
            # Fallback text notification if no direct bytes
            return self.send_text(
                to=clean_mobile,
                text=caption,
                idempotency_key=f"report_text:{patient_code}:{clean_mobile}"
            )


whatsapp_service = WhatsAppServiceClient()
