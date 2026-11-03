"""
Automated unit tests for Settings, Environment normalization, and OpenAPI schema security.
Verifies HIGH-02 (ENVIRONMENT normalization) and LOW-01 (Disable /openapi.json in production).
"""
import pytest
from pydantic import ValidationError
from backend.app.config import Settings


def test_environment_normalization():
    """Verify various shorthand values for ENVIRONMENT are correctly normalized."""
    s_prod = Settings(
        ENVIRONMENT="prod",
        JWT_SECRET_KEY="a" * 32 + "1234567890!@#$",
        PASSWORD_PEPPER="b" * 32 + "1234567890!@#$",
        AADHAAR_PEPPER="c" * 32 + "1234567890!@#$",
        WHATSAPP_ENABLED=False,
    )
    assert s_prod.ENVIRONMENT == "production"
    assert s_prod.is_production is True
    assert s_prod.cookie_secure is True

    s_prd = Settings(
        ENVIRONMENT="PRD",
        JWT_SECRET_KEY="a" * 32 + "1234567890!@#$",
        PASSWORD_PEPPER="b" * 32 + "1234567890!@#$",
        AADHAAR_PEPPER="c" * 32 + "1234567890!@#$",
        WHATSAPP_ENABLED=False,
    )
    assert s_prd.ENVIRONMENT == "production"
    assert s_prd.is_production is True

    s_dev = Settings(ENVIRONMENT="dev")
    assert s_dev.ENVIRONMENT == "development"
    assert s_dev.is_production is False
    assert s_dev.cookie_secure is False

    s_test = Settings(ENVIRONMENT="testing")
    assert s_test.ENVIRONMENT == "testing"
    assert s_test.is_production is False


def test_production_enforces_cryptographic_secrets_when_env_is_prod():
    """When ENVIRONMENT='prod', insecure secrets must be strictly rejected."""
    # Insecure placeholder secret
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="prod",
            JWT_SECRET_KEY="change-this-secret",
            PASSWORD_PEPPER="b" * 32 + "1234567890!@#$",
            AADHAAR_PEPPER="c" * 32 + "1234567890!@#$",
            WHATSAPP_ENABLED=False,
        )
    assert "JWT_SECRET_KEY is using an insecure default" in str(exc_info.value)

    # Missing PASSWORD_PEPPER
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="prod",
            JWT_SECRET_KEY="a" * 32 + "1234567890!@#$",
            PASSWORD_PEPPER="",
            AADHAAR_PEPPER="c" * 32 + "1234567890!@#$",
            WHATSAPP_ENABLED=False,
        )
    assert "PASSWORD_PEPPER must be configured in production" in str(exc_info.value)

    # Missing AADHAAR_PEPPER
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="prod",
            JWT_SECRET_KEY="a" * 32 + "1234567890!@#$",
            PASSWORD_PEPPER="b" * 32 + "1234567890!@#$",
            AADHAAR_PEPPER="",
            WHATSAPP_ENABLED=False,
        )
    assert "AADHAAR_PEPPER must be configured in production" in str(exc_info.value)

    # Identical AADHAAR_PEPPER and PASSWORD_PEPPER
    shared_pepper = "shared_secret_pepper_with_lots_of_entropy_12345!"
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            ENVIRONMENT="prod",
            JWT_SECRET_KEY="a" * 32 + "1234567890!@#$",
            PASSWORD_PEPPER=shared_pepper,
            AADHAAR_PEPPER=shared_pepper,
            WHATSAPP_ENABLED=False,
        )
    assert "AADHAAR_PEPPER must not be identical to PASSWORD_PEPPER" in str(exc_info.value)


def test_main_app_docs_and_openapi_urls():
    """Verify that backend.app.main respects is_production for docs and openapi schemas."""
    import backend.app.main as app_module
    from backend.app.config import settings

    if settings.is_production:
        assert app_module.app.docs_url is None
        assert app_module.app.redoc_url is None
        assert app_module.app.openapi_url is None
    else:
        assert app_module.app.docs_url == "/docs"
        assert app_module.app.redoc_url == "/redoc"
        assert app_module.app.openapi_url == "/openapi.json"
