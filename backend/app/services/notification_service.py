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
        # --- additional design tokens for the redesigned templates ---
        "page": "#EEF3F1",
        "body": "#3F5148",
        "primary_border": "#CFE6DA",
        "danger_dark": "#7C1F27",
        "danger_border": "#F0CCCC",
        "warning": "#7A4E00",
        "warning_accent": "#E0A100",
        "warning_soft": "#FFF8E6",
        "warning_border": "#F2DEAA",
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

    # ------------------------------------------------------------------
    # Design system helpers
    # NOTE: every helper below expects HTML-SAFE input. Dynamic values must
    # already have been passed through self._escape() before being handed in.
    # ------------------------------------------------------------------
    OTP_VALIDITY_MINUTES = 5
    FONT_STACK = "'Segoe UI',-apple-system,BlinkMacSystemFont,Roboto,'Helvetica Neue',Arial,sans-serif"
    MONO_STACK = "'SF Mono',SFMono-Regular,Menlo,Consolas,'Liberation Mono','Courier New',monospace"

    # Responsive tweaks (clients that ignore <style> still get a clean 600px layout from inline styles).
    _MOBILE_CSS = """
    body, table, td, a { -webkit-text-size-adjust:100%; -ms-text-size-adjust:100%; }
    table, td { mso-table-lspace:0pt; mso-table-rspace:0pt; }
    a[x-apple-data-detectors] { color:inherit!important; text-decoration:none!important; }
    @media only screen and (max-width:620px) {
      .container { width:100%!important; max-width:100%!important; }
      .outer-pad { padding:14px 8px!important; }
      .px { padding-left:22px!important; padding-right:22px!important; }
      .h1 { font-size:25px!important; line-height:32px!important; }
      .code { font-size:30px!important; line-height:38px!important; letter-spacing:6px!important; padding-left:6px!important; }
      .cred { font-size:17px!important; }
      .hide-sm { display:none!important; }
      .btn-td, .btn-a { display:block!important; width:100%!important; }
    }
    """

    def _tone(self, tone: str) -> Dict[str, str]:
        """Colour set for the 'success' (brand green) or 'danger' (red) tone."""
        c = self.COLORS
        if tone == "danger":
            return {"accent": c["danger"], "dark": c["danger_dark"], "soft": c["danger_soft"],
                    "border": c["danger_border"], "dash": "#E3A3A8"}
        return {"accent": c["primary"], "dark": c["primary_dark"], "soft": c["primary_soft"],
                "border": c["primary_border"], "dash": "#9CCDB8"}

    @staticmethod
    def _gap(px: int = 16) -> str:
        return f'<div style="height:{px}px;line-height:{px}px;font-size:0;">&nbsp;</div>'

    def _p(self, html_text: str, *, muted: bool = False, size: int = 15, mb: int = 14) -> str:
        c = self.COLORS
        color = c["muted"] if muted else c["body"]
        line = int(size * 1.65)
        return f'<p style="margin:0 0 {mb}px;font-size:{size}px;line-height:{line}px;color:{color};">{html_text}</p>'

    def _code_card(self, *, label: str, code: str, tone: str = "success", note: str = "") -> str:
        """Large, easy-to-read code box (OTP / confirmation code)."""
        t = self._tone(tone)
        pill = ""
        if note:
            pill = (
                f'<tr><td align="center" style="padding:6px 16px 22px;">'
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;border-spacing:0;"><tr>'
                f'<td style="padding:5px 13px;border-radius:999px;background-color:#FFFFFF;border:1px solid {t["border"]};'
                f'font-size:12px;line-height:16px;font-weight:700;color:{t["accent"]};">&#9201;&nbsp; {note}</td>'
                f'</tr></table></td></tr>'
            )
        else:
            pill = '<tr><td style="height:18px;line-height:18px;font-size:0;">&nbsp;</td></tr>'
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;">
<tr><td style="background-color:{t['soft']};border:2px dashed {t['dash']};border-radius:16px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">
<tr><td align="center" style="padding:22px 16px 4px;font-size:11px;line-height:16px;letter-spacing:1.6px;text-transform:uppercase;font-weight:700;color:{t['accent']};">{label}</td></tr>
<tr><td align="center" style="padding:6px 12px 6px;"><div class="code" style="font-family:{self.MONO_STACK};font-size:38px;line-height:46px;font-weight:700;letter-spacing:9px;padding-left:9px;color:{t['dark']};word-break:break-all;">{code}</div></td></tr>
{pill}
</table>
</td></tr></table>'''

    def _credential_card(self, *, label: str, value: str, hint: str = "") -> str:
        """Monospace box for a temporary password / credential."""
        c = self.COLORS
        t = self._tone("success")
        hint_html = f'<div style="padding-top:8px;font-size:12px;line-height:18px;color:{c["muted"]};">{hint}</div>' if hint else ""
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;">
<tr><td style="padding:18px 20px;background-color:{c['surface']};border:1px solid {c['border']};border-left:4px solid {t['accent']};border-radius:12px;">
<div style="font-size:11px;line-height:16px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:{c['muted']};">{label}</div>
<div class="cred" style="padding-top:8px;font-family:{self.MONO_STACK};font-size:20px;line-height:28px;font-weight:700;overflow-wrap:anywhere;word-break:break-all;color:{c['ink']};">{value}</div>
{hint_html}
</td></tr></table>'''

    def _steps(self, title: str, items: list, tone: str = "success") -> str:
        """Numbered 'what to do next' list so the user always knows the next action."""
        c = self.COLORS
        t = self._tone(tone)
        rows = ""
        for i, item in enumerate(items, 1):
            pad = 0 if i == len(items) else 14
            rows += f'''<tr>
<td width="40" valign="top" style="width:40px;padding:0 0 {pad}px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="28" style="width:28px;border-collapse:separate;border-spacing:0;"><tr><td align="center" valign="middle" width="28" height="28" style="width:28px;height:28px;border-radius:14px;background-color:{t['accent']};color:#FFFFFF;font-size:13px;line-height:28px;font-weight:700;">{i}</td></tr></table>
</td>
<td valign="top" style="padding:3px 0 {pad}px;font-size:14px;line-height:22px;color:{c['ink']};">{item}</td>
</tr>'''
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;">
<tr><td style="padding:20px 22px;background-color:#FFFFFF;border:1px solid {c['border']};border-radius:14px;">
<div style="padding-bottom:14px;font-size:11px;line-height:16px;font-weight:700;letter-spacing:1.4px;text-transform:uppercase;color:{c['muted']};">{title}</div>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">{rows}</table>
</td></tr></table>'''

    def _callout(self, title: str, body: str, kind: str = "info") -> str:
        """Highlighted note. kind: info | success | warning | danger."""
        c = self.COLORS
        palette = {
            "info": (c["surface"], c["border"], c["primary"], c["ink"]),
            "success": (c["primary_soft"], c["primary_border"], c["primary"], c["primary_dark"]),
            "warning": (c["warning_soft"], c["warning_border"], c["warning_accent"], c["warning"]),
            "danger": (c["danger_soft"], c["danger_border"], c["danger"], c["danger_dark"]),
        }
        bg, border, bar, title_color = palette.get(kind, palette["info"])
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;">
<tr><td style="padding:14px 18px;background-color:{bg};border:1px solid {border};border-left:4px solid {bar};border-radius:12px;">
<div style="font-size:14px;line-height:20px;font-weight:700;color:{title_color};">{title}</div>
<div style="padding-top:4px;font-size:13px;line-height:21px;color:{c['body']};">{body}</div>
</td></tr></table>'''

    def _details_card(self, rows: list, tone: str = "success") -> str:
        """Key / value summary card. rows = [(label, html_safe_value), ...]."""
        c = self.COLORS
        t = self._tone(tone)
        body = ""
        for idx, (label, value) in enumerate(rows):
            border = "" if idx == len(rows) - 1 else f"border-bottom:1px solid {c['border']};"
            body += f'''<tr>
<td valign="top" style="padding:11px 0;{border}font-size:12px;line-height:18px;font-weight:700;letter-spacing:.6px;text-transform:uppercase;color:{c['muted']};width:42%;">{label}</td>
<td valign="top" align="right" style="padding:11px 0;{border}font-size:14px;line-height:20px;font-weight:700;color:{c['ink']};overflow-wrap:anywhere;">{value}</td>
</tr>'''
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:separate;border-spacing:0;">
<tr><td style="padding:6px 20px;background-color:{c['surface']};border:1px solid {c['border']};border-top:3px solid {t['accent']};border-radius:12px;">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;">{body}</table>
</td></tr></table>'''

    def _button(self, label: str, url: str, tone: str = "success") -> str:
        """Bulletproof CTA button. Returns '' unless url is a valid http(s) link."""
        url = str(url or "").strip()
        if not url.lower().startswith(("https://", "http://")):
            return ""
        t = self._tone(tone)
        safe_url = self._escape(url)
        return f'''<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;border-collapse:collapse;"><tr><td align="center">
<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:separate;border-spacing:0;"><tr>
<td class="btn-td" align="center" bgcolor="{t['accent']}" style="border-radius:12px;background-color:{t['accent']};">
<a class="btn-a" href="{safe_url}" target="_blank" style="display:inline-block;padding:14px 34px;font-family:{self.FONT_STACK};font-size:15px;line-height:20px;font-weight:700;color:#FFFFFF;text-decoration:none;border-radius:12px;">{label}</a>
</td></tr></table>
</td></tr></table>'''

    # ------------------------------------------------------------------
    # Master layout
    # ------------------------------------------------------------------
    def _layout(self, *, preheader: str, eyebrow: str, title: str, content: str,
                tone: str = "success", footer_note: str = "This is an automated message.",
                icon: str = "&#128274;") -> str:
        """Render a premium, mobile-friendly, table-based email layout compatible with major email clients.

        `icon` is a trusted HTML entity (e.g. "&#128274;"), not user input.
        """
        c = self.COLORS
        t = self._tone(tone)
        safe_preheader = self._escape(preheader)
        safe_eyebrow = self._escape(eyebrow)
        safe_title = self._escape(title)
        safe_footer = self._escape(footer_note)
        filler = "&zwnj;&nbsp;" * 45  # stops body copy leaking into the inbox preview line

        return f'''<!doctype html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="x-apple-disable-message-reformatting">
  <meta name="format-detection" content="telephone=no,address=no,email=no,date=no,url=no">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>{safe_title}</title>
  <style>{self._MOBILE_CSS}</style>
</head>
<body style="margin:0;padding:0;background-color:{c['page']};font-family:{self.FONT_STACK};color:{c['ink']};-webkit-text-size-adjust:100%;">
  <div style="display:none!important;visibility:hidden;opacity:0;color:transparent;height:0;width:0;max-height:0;overflow:hidden;mso-hide:all;">{safe_preheader}{filler}</div>
  <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="width:100%;background-color:{c['page']};border-collapse:collapse;">
    <tr><td class="outer-pad" align="center" style="padding:32px 14px;">
      <table role="presentation" class="container" cellpadding="0" cellspacing="0" border="0" width="600" style="width:100%;max-width:600px;border-collapse:separate;border-spacing:0;background-color:#FFFFFF;border:1px solid {c['border']};border-radius:22px;overflow:hidden;box-shadow:0 10px 34px rgba(16,77,62,.10);">

        <!-- Brand header -->
        <tr><td class="px" bgcolor="{t['dark']}" style="padding:22px 36px;background-color:{t['dark']};background-image:linear-gradient(135deg,{t['dark']} 0%,{t['accent']} 100%);">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" style="border-collapse:collapse;width:100%;"><tr>
            <td width="46" valign="middle" style="width:46px;padding-right:12px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="42" style="width:42px;border-collapse:separate;border-spacing:0;"><tr><td align="center" valign="middle" width="42" height="42" style="width:42px;height:42px;border-radius:13px;background-color:#FFFFFF;color:{t['dark']};font-size:22px;line-height:42px;font-weight:800;">A</td></tr></table>
            </td>
            <td valign="middle" style="font-size:16px;line-height:21px;font-weight:700;color:#FFFFFF;">{self.BRAND}<div style="padding-top:2px;font-size:10px;line-height:14px;font-weight:600;letter-spacing:1.6px;color:rgba(255,255,255,.78);">DIAGNOSTIC SERVICES</div></td>
            <td class="hide-sm" align="right" valign="middle" style="font-size:10px;line-height:15px;font-weight:700;letter-spacing:1px;color:#FFFFFF;text-transform:uppercase;white-space:nowrap;">&#128274;&nbsp;Secure message</td>
          </tr></table>
        </td></tr>

        <!-- Hero -->
        <tr><td class="px" align="center" style="padding:38px 36px 6px;background-color:#FFFFFF;">
          <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="64" style="width:64px;border-collapse:separate;border-spacing:0;margin:0 auto;"><tr><td align="center" valign="middle" width="64" height="64" style="width:64px;height:64px;border-radius:32px;background-color:{t['soft']};border:1px solid {t['border']};font-size:28px;line-height:64px;">{icon}</td></tr></table>
          <div style="padding-top:18px;font-size:11px;line-height:16px;font-weight:700;letter-spacing:1.8px;text-transform:uppercase;color:{t['accent']};">{safe_eyebrow}</div>
          <div class="h1" style="padding-top:8px;font-size:29px;line-height:36px;font-weight:800;letter-spacing:-.5px;color:{c['ink']};">{safe_title}</div>
        </td></tr>

        <!-- Body -->
        <tr><td class="px" style="padding:24px 36px 34px;background-color:#FFFFFF;font-size:15px;line-height:25px;color:{c['body']};">
          {content}
        </td></tr>

        <!-- Footer -->
        <tr><td class="px" style="padding:24px 36px 26px;background-color:{c['surface']};border-top:1px solid {c['border']};">
          <div style="font-size:12px;line-height:19px;color:{c['body']};">{safe_footer}</div>
          <div style="padding-top:14px;font-size:11px;line-height:16px;font-weight:700;letter-spacing:.8px;color:{c['ink']};">DO NOT REPLY TO THIS EMAIL</div>
          <div style="padding-top:4px;font-size:11px;line-height:17px;color:{c['muted']};">This mailbox is used only for automated notifications from {self.BRAND}.</div>
        </td></tr>
      </table>
      <div style="max-width:540px;padding:16px 10px 0;font-size:11px;line-height:17px;color:{c['muted']};text-align:center;">Please keep verification codes, passwords and diagnostic reports private. If this message was not intended for you, do not use any code or attachment.</div>
    </td></tr>
  </table>
</body>
</html>'''

    # ------------------------------------------------------------------
    # Event templates
    # ------------------------------------------------------------------
    def _render_template(self, event_type: str, context: Dict[str, Any]):
        """Return subject, HTML and plain-text bodies for supported email events."""
        c = self.COLORS
        minutes = self.OTP_VALIDITY_MINUTES

        raw_name = self._value(context, "name", "there").strip() or "there"
        raw_patient_name = self._value(context, "patient_name", "Patient").strip() or "Patient"
        raw_patient_code = self._value(context, "patient_code").strip() or "Not provided"
        raw_otp = self._value(context, "otp").strip()
        raw_temp_password = self._value(context, "temp_password").strip()

        name = self._escape(raw_name)
        patient_name = self._escape(raw_patient_name)
        patient_code = self._escape(raw_patient_code)
        otp = self._escape(raw_otp)
        temp_password = self._escape(raw_temp_password)

        expiry_pill = f"Expires in {minutes} minutes"
        never_share = ("Akriti Diagnostics will <strong>never</strong> ask you for this code by phone, chat or email. "
                       "Please don't share it with anyone.")

        if event_type == "otp":
            subject = "Your secure verification code | Akriti Diagnostics"
            content = (
                self._p(f"Hello {name},", mb=6)
                + self._p("You asked for a one-time code to verify a request on your Akriti Diagnostics account. Here it is:", mb=20)
                + self._code_card(label="Your one-time code", code=otp, note=expiry_pill)
                + self._gap(20)
                + self._steps("What to do next", [
                    "Go back to the screen where you asked for this code.",
                    "Type the code in <strong>exactly as shown</strong> above.",
                    f"Submit it within <strong>{minutes} minutes</strong>. After that, simply request a new code.",
                ])
                + self._gap(20)
                + self._callout("Keep this code private", never_share, "warning")
                + self._gap(12)
                + self._callout("Didn't request this?", "You can safely ignore this email and do not use the code.", "info")
            )
            text_body = "\n".join([
                f"Hello {raw_name},",
                "",
                f"Your one-time verification code is: {raw_otp}",
                f"This code expires in {minutes} minutes.",
                "",
                "What to do next:",
                "1. Go back to the screen where you asked for this code.",
                "2. Type the code in exactly as shown.",
                f"3. Submit it within {minutes} minutes. After that, request a new code.",
                "",
                "Keep it private: Akriti Diagnostics will never ask you for this code by phone, chat or email. Do not share it with anyone.",
                "",
                "Didn't request this? You can safely ignore this email and do not use the code.",
            ])
            html_body = self._layout(preheader=f"Your secure verification code is ready. It expires in {minutes} minutes.",
                                     eyebrow="Account security", title="Your verification code", content=content,
                                     icon="&#128272;")

        elif event_type == "password_reset":
            subject = "Password reset verification | Akriti Diagnostics"
            content = (
                self._p(f"Hello {name},", mb=6)
                + self._p("We received a request to reset the password for your account. Use the code below to continue.", mb=20)
                + self._code_card(label="Password reset code", code=otp, note=expiry_pill)
                + self._gap(20)
                + self._steps("How to reset your password", [
                    "Return to the <strong>Reset password</strong> screen.",
                    "Enter the code above exactly as shown.",
                    "Choose a <strong>new, strong password</strong> when asked, then sign in with it.",
                ])
                + self._gap(20)
                + self._callout("Keep this code private", never_share, "warning")
                + self._gap(12)
                + self._callout("Didn't ask to reset your password?",
                                "Do not use the code. Your password will stay as it is. If you think someone else is trying to access your account, "
                                "contact your administrator through a trusted channel.", "info")
            )
            text_body = "\n".join([
                f"Hello {raw_name},",
                "",
                "We received a request to reset the password for your account.",
                f"Your password reset code is: {raw_otp}",
                f"This code expires in {minutes} minutes.",
                "",
                "How to reset your password:",
                "1. Return to the Reset password screen.",
                "2. Enter the code exactly as shown.",
                "3. Choose a new, strong password when asked, then sign in with it.",
                "",
                "Keep it private: never share this code with anyone.",
                "",
                "Didn't ask to reset your password? Do not use the code. If you suspect someone is trying to access your account, contact your administrator through a trusted channel.",
            ])
            html_body = self._layout(preheader=f"Complete your password reset securely. The code expires in {minutes} minutes.",
                                     eyebrow="Account security", title="Reset your password", content=content,
                                     icon="&#128273;")

        elif event_type == "password_change":
            subject = "Password change verification | Akriti Diagnostics"
            content = (
                self._p(f"Hello {name},", mb=6)
                + self._p("A request was made to change your account password. Enter the code below to confirm it was you.", mb=20)
                + self._code_card(label="Verification code", code=otp, note=expiry_pill)
                + self._gap(20)
                + self._steps("How to confirm the change", [
                    "Go back to the <strong>Change password</strong> screen.",
                    "Enter the code above exactly as shown.",
                    f"Complete the step within <strong>{minutes} minutes</strong>.",
                ])
                + self._gap(20)
                + self._callout("Keep this code private", never_share, "warning")
                + self._gap(12)
                + self._callout("Didn't request this change?",
                                "Do not use the code, and contact your administrator through a trusted channel so your account can be checked.", "info")
            )
            text_body = "\n".join([
                f"Hello {raw_name},",
                "",
                "A request was made to change your account password.",
                f"Your password-change verification code is: {raw_otp}",
                f"This code expires in {minutes} minutes.",
                "",
                "How to confirm the change:",
                "1. Go back to the Change password screen.",
                "2. Enter the code exactly as shown.",
                f"3. Complete the step within {minutes} minutes.",
                "",
                "Keep it private: never share this code with anyone.",
                "",
                "Didn't request this change? Do not use the code and contact your administrator through a trusted channel.",
            ])
            html_body = self._layout(preheader="Confirm your password-change request with the code inside.",
                                     eyebrow="Account security", title="Confirm password change", content=content,
                                     icon="&#128260;")

        elif event_type == "delete_verify":
            subject = "Confirmation required for a sensitive data-deletion request"
            content = (
                self._callout("Sensitive action: patient data deletion",
                              "Please read this carefully. Continue only if <strong>you</strong> started this request in the application.", "danger")
                + self._gap(20)
                + self._p(f"Hello {name},", mb=6)
                + self._p("A request was made to verify the deletion of patient data. To confirm that you started it, enter the code below.", mb=20)
                + self._code_card(label="Confirmation code", code=otp, tone="danger", note=expiry_pill)
                + self._gap(20)
                + self._steps("Before you continue", [
                    "Check that <strong>you</strong> started this deletion request in the application.",
                    "If yes, enter the code above exactly as shown.",
                    "If not, <strong>stop here</strong>, do not use the code, and contact your administrator.",
                ], tone="danger")
                + self._gap(20)
                + self._callout("Good to know",
                                "This code only verifies the request. It does not mean the deletion has already been completed.", "info")
                + self._gap(12)
                + self._callout("Didn't start this action?",
                                "Do not share or use the code. Contact your administrator through a trusted channel immediately.", "danger")
            )
            text_body = "\n".join([
                "SENSITIVE ACTION: PATIENT DATA DELETION",
                "",
                f"Hello {raw_name},",
                "",
                "A request was made to verify the deletion of patient data. Use the code below ONLY if you started this request in the application.",
                f"Your confirmation code is: {raw_otp}",
                f"This code expires in {minutes} minutes.",
                "",
                "Before you continue:",
                "1. Check that you started this deletion request in the application.",
                "2. If yes, enter the code exactly as shown.",
                "3. If not, stop here, do not use the code, and contact your administrator.",
                "",
                "Good to know: this code only verifies the request. It does not mean the deletion has already been completed.",
                "",
                "Didn't start this action? Do not share or use the code. Contact your administrator through a trusted channel immediately.",
            ])
            html_body = self._layout(preheader="Action required: confirm a sensitive deletion request, only if it was you.",
                                     eyebrow="Security confirmation", title="Confirm sensitive action", content=content,
                                     tone="danger", footer_note="Security notice: never share this verification code.",
                                     icon="&#9888;&#65039;")

        elif event_type == "welcome_staff":
            subject = "Your Akriti Diagnostics staff account"
            login_button = self._button("Open the staff portal", context.get("login_url"))
            content = (
                self._p(f"Welcome, {name}!", mb=6)
                + self._p("Your staff account at Akriti Diagnostics Center is ready. Use the temporary password below for your first sign-in.", mb=20)
                + self._credential_card(label="Temporary password", value=temp_password,
                                        hint="Select the password and copy it exactly. It is case-sensitive.")
                + self._gap(20)
                + (login_button + self._gap(20) if login_button else "")
                + self._steps("Getting started", [
                    "Open the Akriti Diagnostics staff portal using the link shared by your administrator.",
                    "Sign in with your account details and the <strong>temporary password</strong> above.",
                    "Change the temporary password when prompted and pick one you don't use anywhere else.",
                ])
                + self._gap(20)
                + self._callout("Keep your credentials safe",
                                "Never share your password and do not forward this email. Delete it once you have signed in and changed your password.", "warning")
                + self._gap(12)
                + self._callout("Not expecting this account?",
                                "Please don't sign in. Contact your administrator through a trusted channel first.", "info")
            )
            text_body = "\n".join([
                f"Welcome, {raw_name}!",
                "",
                "Your staff account at Akriti Diagnostics Center is ready.",
                f"Temporary password: {raw_temp_password}",
                "",
                "Getting started:",
                "1. Open the Akriti Diagnostics staff portal using the link shared by your administrator.",
                "2. Sign in with your account details and the temporary password above.",
                "3. Change the temporary password when prompted and pick one you don't use anywhere else.",
                "",
                "Keep your credentials safe: never share your password and do not forward this email.",
                "",
                "Not expecting this account? Please don't sign in. Contact your administrator through a trusted channel first.",
            ])
            html_body = self._layout(preheader="Your staff account is ready. Your temporary password is inside.",
                                     eyebrow="Staff account", title="Welcome to the team", content=content,
                                     footer_note="This message contains an initial sign-in credential. Store it securely and do not forward this email.",
                                     icon="&#128075;")

        elif event_type in ("report_ready", "report_released"):
            subject = "Your diagnostic report is ready | Akriti Diagnostics"
            has_attachment = bool(context.get("attachment_bytes") and context.get("attachment_name"))
            attachment_name = self._escape(self._value(context, "attachment_name").strip())
            registered_date = self._escape(self._value(context, "registered_date").strip())

            rows = [("Patient ID", patient_code), ("Patient name", patient_name)]
            if registered_date:
                rows.append(("Registered on", registered_date))
            if has_attachment and attachment_name:
                rows.append(("Report file", attachment_name))

            if has_attachment:
                access_block = (
                    self._callout("Your report is attached", "Open the PDF attached to this email to view your report. "
                                  "We suggest saving a copy somewhere safe.", "success")
                    + self._gap(12)
                )
                access_text = "Your report is attached to this email as a PDF. Please save a copy somewhere safe."
            else:
                access_block = (
                    self._callout("Collect your report", "Please collect your report from the laboratory reception desk. "
                                  "Keep your <strong>Patient ID</strong> above handy.", "success")
                    + self._gap(12)
                )
                access_text = "Please collect your report from the laboratory reception desk. Keep your Patient ID handy."

            content = (
                self._p(f"Dear {patient_name},", mb=6)
                + self._p("Good news: your diagnostic report has been prepared and is ready for you.", mb=20)
                + self._details_card(rows)
                + self._gap(20)
                + access_block
                + self._callout("Keep it confidential",
                                "Your report contains personal health information. Share it only with your doctor or another trusted healthcare professional.", "warning")
                + self._gap(12)
                + self._callout("Need help or a printed copy?",
                                "Contact the laboratory reception and we'll be glad to assist. "
                                "If this report reached you by mistake, please let the laboratory know and delete this email.", "info")
            )
            text_lines = [
                f"Dear {raw_patient_name},",
                "",
                "Good news: your diagnostic report has been prepared and is ready for you.",
                "",
                f"Patient ID: {raw_patient_code}",
                f"Patient name: {raw_patient_name}",
            ]
            raw_registered = self._value(context, "registered_date").strip()
            if raw_registered:
                text_lines.append(f"Registered on: {raw_registered}")
            text_lines += [
                "",
                access_text,
                "",
                "Keep it confidential: your report contains personal health information. Share it only with your doctor or another trusted healthcare professional.",
                "",
                "Need help or a printed copy? Contact the laboratory reception. If this report reached you by mistake, please let the laboratory know and delete this email.",
            ]
            text_body = "\n".join(text_lines)
            html_body = self._layout(preheader="Good news: your diagnostic report is ready.",
                                     eyebrow="Diagnostic services", title="Your report is ready", content=content,
                                     footer_note="Confidential: this email and any attached report are intended only for the recipient. If received in error, contact the laboratory and delete the message.",
                                     icon="&#128196;")

        else:
            # Never dump the full context into an email; it may contain sensitive data.
            subject = "A notification from Akriti Diagnostics"
            content = (
                self._p(f"Hello {name},", mb=6)
                + self._p("You have a new notification from Akriti Diagnostics Center.", mb=20)
                + self._callout("What should I do?",
                                "If any action is needed, please sign in through your usual trusted application entry point. "
                                "No action is required from this email alone.", "info")
            )
            text_body = "\n".join([
                f"Hello {raw_name},",
                "",
                "You have a new notification from Akriti Diagnostics Center.",
                "If any action is needed, please sign in through your usual trusted application entry point. No action is required from this email alone.",
            ])
            html_body = self._layout(preheader="A notification from Akriti Diagnostics Center.",
                                     eyebrow="Notification", title="You have a notification", content=content,
                                     icon="&#128276;")

        text_body = text_body.rstrip() + "\n\nDO NOT REPLY TO THIS EMAIL. This mailbox is used for automated notifications from Akriti Diagnostics Center."
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
