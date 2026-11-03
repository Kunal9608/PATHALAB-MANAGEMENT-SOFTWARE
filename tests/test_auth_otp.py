"""
Comprehensive Unit & Security Regression Tests for OTP Purpose Validation (HIGH-01)
"""
import uuid
from datetime import datetime, timedelta, timezone
import pytest
from unittest.mock import patch, MagicMock

from backend.app.services.auth_service import verify_otp_code, hash_otp
from backend.app.models.user import User, RoleEnum
from backend.app.models.otp_request import OtpRequest, OtpPurposeEnum


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def test_user():
    return User(
        id=uuid.uuid4(),
        email="doctor@akritidc.in",
        name="Dr. Kunal",
        role=RoleEnum.admin,
        is_active=True,
        must_reset_password=False,
        is_locked=False
    )


def create_mock_otp(email: str, code: str, purpose: str, expired: bool = False, used: bool = False):
    otp = MagicMock(spec=OtpRequest)
    otp.email = email
    otp.otp_hash = hash_otp(code)
    otp.purpose = purpose
    now = datetime.now(timezone.utc)
    otp.expires_at = now - timedelta(minutes=1) if expired else now + timedelta(minutes=5)
    otp.used_at = now - timedelta(minutes=2) if used else None
    return otp


def test_login_otp_issues_login_tokens(mock_db, test_user):
    """Verify purpose='login' produces access_token and refresh_token."""
    otp_code = "654321"
    otp_obj = create_mock_otp(test_user.email, otp_code, "login")

    # Mock DB queries
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = otp_obj

    with patch("backend.app.repositories.user_repo.get_by_email", return_value=test_user), \
         patch("backend.app.repositories.session_repo.revoke_all_user_sessions"), \
         patch("backend.app.repositories.session_repo.create_session") as mock_create_sess:
        
        mock_sess = MagicMock()
        mock_sess.id = uuid.uuid4()
        mock_create_sess.return_value = mock_sess

        result = verify_otp_code(mock_db, test_user.email, otp_code, "login")

        assert result["requires_password_reset"] is False
        assert "access_token" in result
        assert "refresh_token" in result
        assert result["user"]["email"] == test_user.email


def test_password_reset_otp_does_not_issue_login_tokens(mock_db, test_user):
    """HIGH-01: Verify purpose='password_reset' ONLY issues reset_token and NEVER login access_token."""
    otp_code = "112233"
    otp_obj = create_mock_otp(test_user.email, otp_code, "password_reset")

    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = otp_obj

    with patch("backend.app.repositories.user_repo.get_by_email", return_value=test_user), \
         patch("backend.app.repositories.session_repo.revoke_all_user_sessions") as mock_revoke:

        result = verify_otp_code(mock_db, test_user.email, otp_code, "password_reset")

        assert result["requires_password_reset"] is True
        assert "reset_token" in result
        assert "access_token" not in result
        assert "refresh_token" not in result
        # Should not create session or revoke all sessions
        mock_revoke.assert_not_called()


def test_delete_verify_otp_does_not_issue_login_tokens(mock_db, test_user):
    """HIGH-01: Verify purpose='delete_verify' ONLY issues verification_token and NEVER login access_token."""
    otp_code = "998877"
    otp_obj = create_mock_otp(test_user.email, otp_code, "delete_verify")

    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = otp_obj

    with patch("backend.app.repositories.user_repo.get_by_email", return_value=test_user), \
         patch("backend.app.repositories.session_repo.revoke_all_user_sessions") as mock_revoke:

        result = verify_otp_code(mock_db, test_user.email, otp_code, "delete_verify")

        assert result["verified"] is True
        assert result["purpose"] == "delete_verify"
        assert "verification_token" in result
        assert "access_token" not in result
        assert "refresh_token" not in result
        mock_revoke.assert_not_called()


@pytest.mark.parametrize("arbitrary_purpose", [
    "admin_bypass",
    "super_login",
    "arbitrary_string",
    "privilege_escalation"
])
def test_arbitrary_purpose_strictly_rejected(mock_db, test_user, arbitrary_purpose):
    """HIGH-01: Verify any arbitrary purpose is rejected with ValueError and produces zero tokens."""
    otp_code = "777888"
    otp_obj = create_mock_otp(test_user.email, otp_code, arbitrary_purpose)

    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = otp_obj

    with patch("backend.app.repositories.user_repo.get_by_email", return_value=test_user):
        with pytest.raises(ValueError, match="Invalid or unauthorized OTP purpose"):
            verify_otp_code(mock_db, test_user.email, otp_code, arbitrary_purpose)


def test_invalid_otp_code_rejected(mock_db, test_user):
    """Verify non-numeric OTP code is rejected immediately."""
    with pytest.raises(ValueError, match="numeric characters"):
        verify_otp_code(mock_db, test_user.email, "abc123", "login")


def test_expired_otp_rejected(mock_db, test_user):
    """Verify expired OTP is rejected."""
    mock_db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None

    with pytest.raises(ValueError, match="Invalid or expired OTP"):
        verify_otp_code(mock_db, test_user.email, "123456", "login")
