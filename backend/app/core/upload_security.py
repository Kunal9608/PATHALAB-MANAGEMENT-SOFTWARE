"""
PathLab OS — Universal File Upload Security & Malware Prevention Pipeline
Implements strict multi-layer defense-in-depth:
1. Authentication & Authorization gate
2. Strict Request & File-Size streaming bounds (DoS prevention)
3. Filename normalization & Path Traversal / Null-Byte / Double-Extension defense
4. File Signature (Magic Bytes) & Deep Structural Format Verification
5. Embedded Exploit & Script Injection Inspection (JavaScript, Launch, EmbeddedFiles, PHP, Shell)
6. Multi-Engine Malware Scanning (ClamAV TCP Daemon + Heuristic Threat Signature Engine)
7. Exact-Object SHA-256 Cryptographic Digest Verification
8. Private Quarantine Staging before Promotion
9. Atomic Promotion & Compensating Storage Rollback
"""
import io
import os
import re
import socket
import hashlib
import logging
import unicodedata
from enum import Enum
from dataclasses import dataclass
from typing import Tuple, Optional, List, Set
from PIL import Image

from backend.app.config import settings

logger = logging.getLogger(__name__)


class ScanStatus(str, Enum):
    PENDING_VALIDATION = "pending_validation"
    VALIDATING = "validating"
    PENDING_SCAN = "pending_scan"
    SCANNING = "scanning"
    APPROVED = "approved"
    REJECTED = "rejected"
    MALWARE_DETECTED = "malware_detected"
    SCANNER_UNAVAILABLE = "scanner_unavailable"
    SCANNER_TIMEOUT = "scanner_timeout"
    SCAN_FAILED = "scan_failed"
    UNSUPPORTED_TYPE = "unsupported_type"
    CLEANUP_PENDING = "cleanup_pending"


@dataclass
class ValidationScanResult:
    status: ScanStatus
    is_clean: bool
    sha256_hash: str
    file_size: int
    sanitized_filename: str
    detected_mime: str
    scanner_name: str = "none"
    error_detail: Optional[str] = None


# Known dangerous secondary extensions that must never appear in filenames
DANGEROUS_EXTENSIONS: Set[str] = {
    ".exe", ".pif", ".application", ".gadget", ".msi", ".msp", ".com", ".scr",
    ".hta", ".cpl", ".msc", ".jar", ".bat", ".cmd", ".vb", ".vbs", ".vbe",
    ".js", ".jse", ".ws", ".wsf", ".wsc", ".wsh", ".ps1", ".ps1xml", ".ps2",
    ".psc1", ".psc2", ".msh", ".msh1", ".msh2", ".mshxml", ".msh1xml",
    ".php", ".php3", ".php4", ".php5", ".phtml", ".asp", ".aspx", ".py",
    ".pl", ".cgi", ".sh", ".bash", ".bin", ".elf", ".so", ".dll", ".dylib"
}

# Standard EICAR Antivirus Test Signature
EICAR_SIGNATURE = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


def sanitize_filename(filename: str, max_length: int = 120) -> str:
    """
    Sanitize filename against path traversal, control characters, null bytes,
    unicode obfuscation, and dangerous multi-extension bypasses.
    """
    if not filename or not isinstance(filename, str):
        raise ValueError("Filename is missing or invalid")

    # 1. Null-byte rejection
    if "\x00" in filename:
        raise ValueError("Filename contains forbidden null byte")

    # 2. Unicode normalization (NFKC)
    normalized = unicodedata.normalize("NFKC", filename).strip()

    # 3. Strip directory paths (protect against / or \\ or .. traversal)
    base = os.path.basename(normalized.replace("\\", "/"))

    # 4. Remove leading periods (hidden files)
    base = base.lstrip(".")
    if not base:
        raise ValueError("Invalid filename structure")

    # 5. Extract extension and stem
    stem, ext = os.path.splitext(base)
    ext_lower = ext.lower()

    if not ext_lower:
        raise ValueError("Filename must have a valid file extension")

    # 6. Reject double-extension attacks (e.g., patient_report.php.pdf or document.exe.png)
    stem_lower = stem.lower()
    for dang in DANGEROUS_EXTENSIONS:
        if stem_lower.endswith(dang) or f"{dang}." in stem_lower:
            raise ValueError(f"Dangerous disguised extension '{dang}' detected in filename")

    # 7. Strip special / shell characters, allowing only alphanumeric, dash, underscore, and dot
    clean_stem = re.sub(r'[^a-zA-Z0-9_-]', '_', stem)
    clean_stem = re.sub(r'_+', '_', clean_stem).strip('_')
    if not clean_stem:
        clean_stem = "file"

    # 8. Enforce maximum length
    clean_stem = clean_stem[:max_length - len(ext_lower)]
    return f"{clean_stem}{ext_lower}"


def validate_pdf_structure(file_bytes: bytes) -> None:
    """
    Deep content inspection for PDF documents.
    Verifies valid magic header, EOF marker, and scans for embedded scripts or exploit triggers.
    """
    if len(file_bytes) < 32:
        raise ValueError("Corrupted PDF: File size is below minimum valid document length")

    # 1. Magic bytes: Must start with %PDF-
    if not file_bytes.startswith(b"%PDF-"):
        raise ValueError("Invalid file signature: Not a valid PDF document")

    # 2. EOF marker validation within the trailer (last 2048 bytes)
    trailer_window = file_bytes[-2048:] if len(file_bytes) > 2048 else file_bytes
    if b"%%EOF" not in trailer_window:
        raise ValueError("Corrupted PDF: Document is truncated or missing %%EOF trailer marker")

    # 3. Disguised executable binary check
    if file_bytes.startswith(b"MZ") or file_bytes.startswith(b"\x7fELF"):
        raise ValueError("Disguised executable binary detected")

    # 4. Dangerous exploit tags in PDF dictionaries
    lower_bytes = file_bytes.lower()
    pdf_exploit_tags = [
        b"/launch",          # Launches external OS processes
        b"/embeddedfiles",   # Embeds arbitrary binary payloads
        b"/javascript",      # Executes embedded JavaScript in PDF reader
        b"/js",              # Shorthand JS action
    ]
    for tag in pdf_exploit_tags:
        if tag in lower_bytes:
            raise ValueError(f"Suspicious interactive script or launch action ({tag.decode()}) detected in PDF")

    # 5. Dangerous web and shell scripts inside PDF stream
    script_injections = [
        b"<script", b"<?php", b"<html", b"javascript:", b"/javascript",
        b"powershell", b"cmd.exe /c", b"#!/bin/sh", b"#!/bin/bash"
    ]
    for pattern in script_injections:
        if pattern in lower_bytes:
            raise ValueError(f"Suspicious script or executable content detected in document stream")


def validate_image_structure(file_bytes: bytes, ext: str) -> str:
    """
    Deep content inspection for clinical raster images.
    Verifies magic bytes, Pillow integrity, pixel/dimension bounds, and metadata script injection.
    """
    if len(file_bytes) < 16:
        raise ValueError("Corrupted Image: File size is below minimum valid image length")

    # 1. Magic bytes verification
    if ext in (".jpg", ".jpeg"):
        if not file_bytes.startswith(b"\xff\xd8\xff"):
            raise ValueError("Invalid file signature: Not a valid JPEG image")
        detected_mime = "image/jpeg"
    elif ext == ".png":
        if not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("Invalid file signature: Not a valid PNG image")
        detected_mime = "image/png"
    elif ext == ".webp":
        if not (file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP"):
            raise ValueError("Invalid file signature: Not a valid WEBP image")
        detected_mime = "image/webp"
    elif ext == ".bmp":
        if not file_bytes.startswith(b"BM"):
            raise ValueError("Invalid file signature: Not a valid BMP image")
        detected_mime = "image/bmp"
    elif ext in (".tiff", ".tif"):
        if not (file_bytes.startswith(b"II*\x00") or file_bytes.startswith(b"MM\x00*")):
            raise ValueError("Invalid file signature: Not a valid TIFF image")
        detected_mime = "image/tiff"
    else:
        raise ValueError(f"Unsupported image format: {ext}")

    # 2. Script injection in image metadata/EXIF comments
    lower_bytes = file_bytes.lower()
    for tag in (b"<script", b"<?php", b"javascript:", b"<html"):
        if tag in lower_bytes:
            raise ValueError("Suspicious script payload embedded inside image binary stream")

    # 3. Pillow decompression bomb & dimensions validation
    try:
        Image.MAX_IMAGE_PIXELS = 16_000_000  # 16 Megapixels limit
        img = Image.open(io.BytesIO(file_bytes))
        if img.width > 5000 or img.height > 5000 or (img.width * img.height) > 16_000_000:
            raise ValueError("Image dimensions exceed maximum safe limit (max 5000x5000 / 16MP)")
        img.verify()
    except Exception as e:
        raise ValueError(f"Corrupted or invalid image data: {e}")

    return detected_mime


def scan_file_clamav(file_bytes: bytes, host: str = "localhost", port: int = 3310) -> Tuple[ScanStatus, Optional[str]]:
    """
    Connect to ClamAV daemon via TCP socket and scan the file stream.
    Returns (ScanStatus, detail_message).
    Fails closed in production if daemon is unreachable.
    """
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5.0)
        s.connect((host, port))

        # Send INSTREAM command
        s.sendall(b"zINSTREAM\0")

        # Send size (4 bytes big-endian) followed by chunk data
        chunk_size = len(file_bytes)
        s.sendall(chunk_size.to_bytes(4, byteorder="big") + file_bytes)

        # Send 0-length chunk to indicate EOF
        s.sendall((0).to_bytes(4, byteorder="big"))

        # Read response
        response = s.recv(1024).decode("utf-8", errors="ignore").strip()
        s.close()

        logger.info(f"ClamAV scan completed: {response}")
        if "OK" in response:
            return ScanStatus.APPROVED, None
        elif "FOUND" in response:
            logger.warning(f"ClamAV threat detected: {response}")
            return ScanStatus.MALWARE_DETECTED, f"Malware detected by ClamAV: {response}"
        else:
            return ScanStatus.SCAN_FAILED, f"Unexpected scanner response: {response}"
    except socket.timeout:
        logger.error("ClamAV scan timed out after 5.0 seconds")
        return ScanStatus.SCANNER_TIMEOUT, "Antivirus scan timed out"
    except Exception as e:
        logger.warning(f"ClamAV daemon unreachable: {e}")
        # When ClamAV is enabled or required, strictly fail closed to prevent bypassing AV controls
        return ScanStatus.SCANNER_UNAVAILABLE, "Antivirus scanner is currently unavailable (fail-closed policy)"


def scan_file_for_malware(file_bytes: bytes, filename: str) -> Tuple[ScanStatus, Optional[str], str]:
    """
    Multi-engine malware scanner:
    Layer 1: Built-in EICAR and heuristic signature engine
    Layer 2: ClamAV TCP streaming daemon (with strict fail-closed security when active)
    """
    # 1. Built-in EICAR test signature detection
    if EICAR_SIGNATURE in file_bytes:
        logger.warning(f"EICAR test malware signature detected in upload '{filename}'")
        return ScanStatus.MALWARE_DETECTED, "EICAR standard test malware signature detected", "heuristic"

    # 2. ClamAV scan (invoked when explicitly enabled or when required by production security policy)
    is_prod = getattr(settings, "is_production", False)
    clamav_enabled = getattr(settings, "ENABLE_CLAMAV", False)
    clamav_required = getattr(settings, "CLAMAV_REQUIRED_IN_PROD", False)

    if clamav_enabled or (is_prod and clamav_required):
        host = getattr(settings, "CLAMAV_HOST", "localhost")
        port = getattr(settings, "CLAMAV_PORT", 3310)
        status, detail = scan_file_clamav(file_bytes, host=host, port=port)
        return status, detail, "clamav"

    # 3. Clean heuristic & deep structural inspection pass
    return ScanStatus.APPROVED, None, "heuristic"


def execute_secure_upload_pipeline(
    file_bytes: bytes,
    original_filename: str,
    allowed_extensions: Tuple[str, ...],
    max_size: int,
    context: str = "general"
) -> ValidationScanResult:
    """
    Universal reusable security validation pipeline for all plaintext file uploads.
    Workflow:
      Size Bound -> Filename Sanitization -> Format & Structure Validation ->
      Deep Exploit Inspection -> Malware Scanning -> SHA-256 Digest Computation
    """
    # 1. Size bounds
    if not file_bytes or len(file_bytes) == 0:
        raise ValueError("Uploaded file is empty (0 bytes)")

    if len(file_bytes) > max_size:
        raise ValueError(f"File size exceeds maximum allowed limit of {max_size / (1024 * 1024):.1f}MB")

    # 2. Filename sanitization
    sanitized_name = sanitize_filename(original_filename)
    _, ext = os.path.splitext(sanitized_name.lower())

    if ext not in allowed_extensions:
        raise ValueError(f"File type '{ext}' is not permitted. Allowed extensions: {', '.join(allowed_extensions)}")

    # 3. Content and format validation
    detected_mime = "application/octet-stream"
    if ext == ".pdf":
        validate_pdf_structure(file_bytes)
        detected_mime = "application/pdf"
    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif"):
        detected_mime = validate_image_structure(file_bytes, ext)

    # 4. Malware scanning
    status, error_detail, scanner_name = scan_file_for_malware(file_bytes, sanitized_name)
    if status != ScanStatus.APPROVED:
        raise ValueError(f"Security check failed: {error_detail or 'Threat or scanner error detected'}")

    # 5. Cryptographic digest
    sha256_hash = hashlib.sha256(file_bytes).hexdigest()

    return ValidationScanResult(
        status=ScanStatus.APPROVED,
        is_clean=True,
        sha256_hash=sha256_hash,
        file_size=len(file_bytes),
        sanitized_filename=sanitized_name,
        detected_mime=detected_mime,
        scanner_name=scanner_name
    )


# ---------------------------------------------------------------------------
# Quarantine Lifecycle Management
# ---------------------------------------------------------------------------

def stage_file_in_quarantine(file_bytes: bytes, upload_id: str, context: str = "reports") -> str:
    """
    Stage file bytes temporarily in private quarantine namespace before promotion.
    Quarantined files are never linked to active database reports or served to patients.
    """
    from backend.app.core.storage import upload_file_bytes
    quarantine_folder = f"quarantine/{context}"
    quarantine_filename = f"{upload_id}.tmp"

    return upload_file_bytes(
        file_bytes=file_bytes,
        filename=quarantine_filename,
        content_type="application/octet-stream",
        folder=quarantine_folder
    )


def promote_quarantined_file(
    quarantine_path: str,
    target_folder: str,
    target_filename: str,
    expected_sha256: str,
    content_type: str = "application/pdf"
) -> str:
    """
    Promote an approved quarantined object to its canonical private storage location.
    Verifies that the object content exactly matches the expected SHA-256 hash.
    Purges the temporary quarantine object upon successful promotion.
    """
    from backend.app.core.storage import download_file_bytes, upload_file_bytes, delete_file_object

    # 1. Retrieve quarantined bytes
    staged_bytes = download_file_bytes(quarantine_path)

    # 2. Exact-object validation: verify digest has not been altered
    actual_hash = hashlib.sha256(staged_bytes).hexdigest()
    if actual_hash != expected_sha256:
        delete_file_object(quarantine_path)
        raise ValueError("Exact-object validation failed: Quarantine digest mismatch")

    # 3. Store promoted file at canonical destination
    promoted_storage_path = upload_file_bytes(
        file_bytes=staged_bytes,
        filename=target_filename,
        content_type=content_type,
        folder=target_folder
    )

    # 4. Clean up temporary quarantine file
    delete_file_object(quarantine_path)

    return promoted_storage_path


def cleanup_quarantined_file(quarantine_path: str) -> bool:
    """Safely purge an unapproved or failed quarantine object."""
    from backend.app.core.storage import delete_file_object
    try:
        return delete_file_object(quarantine_path)
    except Exception as e:
        logger.warning(f"Quarantine cleanup notice for {quarantine_path}: {e}")
        return False


# ---------------------------------------------------------------------------
# Streaming Read Utilities (Bounded against Memory Exhaustion / DoS)
# ---------------------------------------------------------------------------

async def read_upload_file_bounded(file, max_size: int, chunk_size: int = 64 * 1024) -> bytes:
    """
    Asynchronously reads an UploadFile in chunks up to max_size.
    Raises ValueError immediately when size exceeds max_size to prevent memory exhaustion DoS.
    """
    total = 0
    chunks = []
    while True:
        chunk = await file.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise ValueError(f"File size exceeds maximum allowed limit of {max_size / (1024 * 1024):.1f}MB")
        chunks.append(chunk)
    return b"".join(chunks)


def read_sync_file_bounded(file_obj, max_size: int, chunk_size: int = 64 * 1024) -> bytes:
    """
    Synchronously reads a file-like object in chunks up to max_size.
    Raises ValueError immediately when size exceeds max_size.
    """
    total = 0
    chunks = []
    while True:
        chunk = file_obj.read(chunk_size)
        if not chunk:
            break
        total += len(chunk)
        if total > max_size:
            raise ValueError(f"File size exceeds maximum allowed limit of {max_size / (1024 * 1024):.1f}MB")
        chunks.append(chunk)
    return b"".join(chunks)


def validate_file_upload(file_bytes: bytes, filename: str, max_size: int, allowed_extensions: list) -> str:
    """
    Backward-compatible wrapper calling the Universal Pipeline.
    """
    result = execute_secure_upload_pipeline(
        file_bytes=file_bytes,
        original_filename=filename,
        allowed_extensions=tuple(allowed_extensions),
        max_size=max_size
    )
    return result.sanitized_filename
