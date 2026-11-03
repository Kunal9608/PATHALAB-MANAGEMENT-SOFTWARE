"""
Comprehensive Unit & Regression Tests for Upload Security & Malware Pipeline (CRIT-02)
"""
import pytest
from unittest.mock import patch, MagicMock
import socket

from backend.app.core.upload_security import (
    execute_secure_upload_pipeline,
    scan_file_for_malware,
    validate_pdf_structure,
    sanitize_filename,
    ScanStatus,
    EICAR_SIGNATURE
)
from backend.app.config import settings


# Fixture for a minimal valid, clean clinical PDF
VALID_CLEAN_PDF = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< >>\n%%EOF"


def test_clean_pdf_upload_passes():
    """Verify clean PDF passes end-to-end security pipeline when ClamAV is disabled."""
    with patch.object(settings, "ENABLE_CLAMAV", False), \
         patch.object(settings, "CLAMAV_REQUIRED_IN_PROD", False):
        result = execute_secure_upload_pipeline(
            file_bytes=VALID_CLEAN_PDF,
            original_filename="blood_report.pdf",
            allowed_extensions=(".pdf",),
            max_size=10 * 1024 * 1024
        )
        assert result.status == ScanStatus.APPROVED
        assert result.is_clean is True
        assert result.detected_mime == "application/pdf"
        assert result.sanitized_filename == "blood_report.pdf"
        assert len(result.sha256_hash) == 64


def test_eicar_signature_rejected():
    """Verify standard EICAR antivirus test signature is caught immediately by heuristic engine."""
    infected_payload = VALID_CLEAN_PDF + b"\n" + EICAR_SIGNATURE
    status, detail, scanner = scan_file_for_malware(infected_payload, "test.pdf")
    assert status == ScanStatus.MALWARE_DETECTED
    assert "EICAR" in detail


def test_corrupted_pdf_missing_header():
    """Verify file without %PDF- header is rejected."""
    corrupted = b"NOT_A_PDF_DOCUMENT_1234567890\n%%EOF"
    with pytest.raises(ValueError, match="Invalid file signature"):
        validate_pdf_structure(corrupted)


def test_corrupted_pdf_missing_eof():
    """Verify PDF truncated before %%EOF trailer is rejected."""
    truncated = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj"
    with pytest.raises(ValueError, match="Corrupted PDF"):
        validate_pdf_structure(truncated)


def test_pdf_with_launch_exploit_rejected():
    """Verify PDF containing /launch process execution action is rejected."""
    exploit_pdf = b"%PDF-1.4\n<< /Type /Action /S /Launch /F (cmd.exe) >>\n%%EOF"
    with pytest.raises(ValueError, match="interactive script or launch action"):
        validate_pdf_structure(exploit_pdf)


def test_pdf_with_javascript_exploit_rejected():
    """Verify PDF containing /JavaScript action is rejected."""
    js_pdf = b"%PDF-1.4\n<< /Type /Action /S /JavaScript /JS (app.alert(1)) >>\n%%EOF"
    with pytest.raises(ValueError, match="interactive script or launch action"):
        validate_pdf_structure(js_pdf)


def test_clamav_fail_closed_when_unreachable():
    """Verify fail-closed policy: when ClamAV is enabled, an unreachable scanner raises SCANNER_UNAVAILABLE."""
    with patch.object(settings, "ENABLE_CLAMAV", True), \
         patch.object(settings, "CLAMAV_HOST", "127.0.0.1"), \
         patch.object(settings, "CLAMAV_PORT", 9999):  # Closed port
        status, detail, scanner = scan_file_for_malware(VALID_CLEAN_PDF, "clean.pdf")
        assert status == ScanStatus.SCANNER_UNAVAILABLE
        assert "fail-closed" in detail


def test_clamav_clean_response_approved():
    """Verify ClamAV stream returning OK approves the file."""
    mock_socket = MagicMock()
    mock_socket.recv.return_value = b"stream: OK\n"

    with patch.object(settings, "ENABLE_CLAMAV", True), \
         patch("socket.socket", return_value=mock_socket):
        status, detail, scanner = scan_file_for_malware(VALID_CLEAN_PDF, "clean.pdf")
        assert status == ScanStatus.APPROVED
        assert detail is None
        assert scanner == "clamav"


def test_clamav_threat_detected():
    """Verify ClamAV stream detecting a threat returns MALWARE_DETECTED."""
    mock_socket = MagicMock()
    mock_socket.recv.return_value = b"stream: Win.Trojan.Generic FOUND\n"

    with patch.object(settings, "ENABLE_CLAMAV", True), \
         patch("socket.socket", return_value=mock_socket):
        status, detail, scanner = scan_file_for_malware(VALID_CLEAN_PDF, "clean.pdf")
        assert status == ScanStatus.MALWARE_DETECTED
        assert "Win.Trojan.Generic" in detail


def test_filename_sanitization_path_traversal():
    """Verify path traversal characters and double dots in upload filename are sanitized."""
    assert sanitize_filename("../../../etc/passwd.pdf") == "passwd.pdf"
    assert sanitize_filename("..\\..\\windows\\system32\\cmd.pdf") == "cmd.pdf"
    assert sanitize_filename("report..double.pdf") == "report_double.pdf"
    with pytest.raises(ValueError, match="forbidden null byte"):
        sanitize_filename("report\x00.pdf")
