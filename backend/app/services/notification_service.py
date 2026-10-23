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
