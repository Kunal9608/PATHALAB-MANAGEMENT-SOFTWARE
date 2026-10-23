"""
Enterprise File Upload Security Validation Library.
Implements multi-layer security validation: Size, Extension, Magic Bytes,
Pillow image integrity, Script injection prevention, and ClamAV antivirus scans.
"""
import os
import re
import socket
import logging
from PIL import Image
import io

from backend.app.config import settings

logger = logging.getLogger(__name__)


def scan_file_clamav(file_bytes: bytes, host: str = "localhost", port: int = 3310) -> bool:
    """
    Connect to ClamAV daemon via TCP socket and scan the file stream.
    Returns True if clean, False if infected/suspicious.
    In production, fails closed (returns False) if ClamAV is unreachable.
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
        
        logger.info(f"ClamAV scan completed with response: {response}")
        if "OK" in response:
            return True
        elif "FOUND" in response:
            logger.warning("ClamAV found threat in uploaded file")
            return False
        else:
            logger.error("ClamAV returned unexpected response")
            # If ClamAV runs but response is unexpected, fail closed for security
            return False
    except Exception as e:
        logger.warning(f"ClamAV daemon unreachable: {e}")
        # In production, fail closed to prevent bypassing AV controls
        if getattr(settings, "is_production", False):
            logger.error("Rejecting file upload: ClamAV required in production but daemon is unreachable.")
            return False
        # Development / test fallback: allow local development without ClamAV daemon
        return True


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
    Validate file upload using multiple security layers.
    Returns the sanitized original filename or raises ValueError if invalid.
    """
    # 1. Enforce file size limit
    if len(file_bytes) > max_size:
        raise ValueError(f"File size exceeds the maximum limit of {max_size / (1024 * 1024):.1f}MB")

    # 2. Sanitize filename to prevent directory/path traversal and double extension attacks
    base = os.path.basename(filename)
    # Remove any non-alphanumeric, dot, underscore, or hyphen characters
    base_clean = re.sub(r'[^a-zA-Z0-9._-]', '_', base)
    if not base_clean or base_clean.startswith('.'):
        raise ValueError("Invalid filename structure")

    # 3. Verify extension
    ext = os.path.splitext(base_clean.lower())[1]
    if ext not in allowed_extensions:
        raise ValueError(f"File type '{ext}' is not allowed. Supported types: {', '.join(allowed_extensions)}")

    # 4. Check File Signatures (Magic Bytes) & content integrity
    # For PDF
    if ext == ".pdf":
        if not file_bytes.startswith(b"%PDF-"):
            raise ValueError("Invalid file signature: Not a valid PDF document")
        
        # Look for executable or script tags in binary data (e.g. PHP, HTML scripts)
        lower_bytes = file_bytes.lower()
        suspicious_patterns = [b"<script", b"<?php", b"<html", b"javascript:", b"/javascript"]
        for pattern in suspicious_patterns:
            if pattern in lower_bytes:
                raise ValueError("Suspicious script or executable content detected in PDF file")

    # For Images
    elif ext in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".heic", ".heif"):
        # Verify Magic Bytes
        if ext in (".jpg", ".jpeg"):
            if not file_bytes.startswith(b"\xff\xd8\xff"):
                raise ValueError("Invalid file signature: Not a valid JPEG image")
        elif ext == ".png":
            if not file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid file signature: Not a valid PNG image")
        elif ext == ".webp":
            if not (file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP"):
                raise ValueError("Invalid file signature: Not a valid WEBP image")
        elif ext == ".bmp":
            if not file_bytes.startswith(b"BM"):
                raise ValueError("Invalid file signature: Not a valid BMP image")
        elif ext in (".tiff", ".tif"):
            if not (file_bytes.startswith(b"II*\x00") or file_bytes.startswith(b"MM\x00*")):
                raise ValueError("Invalid file signature: Not a valid TIFF image")
        elif ext in (".heic", ".heif"):
            if b"ftyp" not in file_bytes[4:12]:
                raise ValueError("Invalid file signature: Not a valid HEIC/HEIF image")

        # Pillow image integrity & decompression bomb validation
        try:
            Image.MAX_IMAGE_PIXELS = 25_000_000
            img = Image.open(io.BytesIO(file_bytes))
            # Dimension bounds: limit resolution to prevent memory exhaustion
            if img.width > 5000 or img.height > 5000 or (img.width * img.height) > 16_000_000:
                raise ValueError("Image dimensions exceed maximum safe limit (max 5000x5000 / 16MP)")
            img.verify()
        except Exception as e:
            raise ValueError(f"Corrupted or invalid image data: {e}")

    # 5. Optional ClamAV scanner
    if getattr(settings, "ENABLE_CLAMAV", False):
        clam_host = getattr(settings, "CLAMAV_HOST", "localhost")
        clam_port = getattr(settings, "CLAMAV_PORT", 3310)
        if not scan_file_clamav(file_bytes, clam_host, clam_port):
            raise ValueError("File security check failed: Threat detected by Antivirus scanner or scanner unavailable")

    return base_clean
