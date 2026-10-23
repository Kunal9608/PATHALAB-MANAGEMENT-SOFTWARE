import logging
import httpx
from backend.app.config import settings

logger = logging.getLogger(__name__)

def verify_recaptcha_token(token: str) -> bool:
    """
    Verify Google reCAPTCHA v3 token.
    Returns True if verification is disabled or passes successfully.
    """
    if not settings.ENABLE_RECAPTCHA:
        logger.info("reCAPTCHA verification is disabled")
        return True

    if not token:
        logger.warning("reCAPTCHA validation failed: token is missing")
        return False

    # Test key handling: allow in development/test only, strictly reject in production
    test_keys = {
        "6LeIxAcTAAAAAGG-vFI1TnFTxWGRtAUMuO_FnD4Q",
        "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"
    }
    if settings.RECAPTCHA_SECRET_KEY in test_keys:
        if settings.is_production:
            logger.error("reCAPTCHA configuration error: Public test key cannot be used in production.")
            return False
        logger.info("reCAPTCHA: Public test key detected in non-production. Approving verification.")
        return True

    try:
        url = "https://www.google.com/recaptcha/api/siteverify"
        payload = {
            "secret": settings.RECAPTCHA_SECRET_KEY,
            "response": token
        }

        # Verify with Google API using httpx POST
        response = httpx.post(url, data=payload, timeout=5.0)
        result = response.json()

        success = result.get("success", False)
        score = result.get("score", 0.0)
        error_codes = result.get("error-codes", [])

        # Log safely without secret keys or raw token
        logger.info(f"reCAPTCHA validation result: success={success}, score={score}")

        if success:
            # For reCAPTCHA v3, score is 0.0 (bot) to 1.0 (human). Standard threshold is 0.5.
            if "score" in result and score < 0.5:
                logger.warning(f"reCAPTCHA validation blocked due to low score: {score}")
                return False
            return True

        # Hostname mismatch handling: reject in production
        if "hostname-mismatch" in error_codes:
            if settings.is_production:
                logger.error("reCAPTCHA validation failed: hostname-mismatch is rejected in production.")
                return False
            logger.warning(f"reCAPTCHA: hostname-mismatch on {result.get('hostname')}. Allowed in non-production.")
            return True

        logger.warning(f"reCAPTCHA validation rejected with error codes: {error_codes}")
        return False

    except Exception as e:
        logger.error(f"reCAPTCHA verification network/API exception: {e}")
        # In production, fail closed to prevent authentication/anti-abuse bypass
        if settings.is_production:
            return False
        # Development fallback
        return True
