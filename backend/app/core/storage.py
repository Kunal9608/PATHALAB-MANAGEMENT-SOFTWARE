"""
Unified Storage Adapter for PathLab OS.
Dedicated to Joy.services S3 object storage (with local disk fallback).
"""
import os
import logging
from pathlib import Path
from typing import Optional, Tuple
from backend.app.config import settings

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("uploads/reports")
ATTACHMENTS_DIR = Path("uploads/attachments")
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
ATTACHMENTS_DIR.mkdir(parents=True, exist_ok=True)


def get_s3_client():
    """Create and return a configured boto3 S3 client for Joy.services."""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL,
        aws_access_key_id=settings.S3_ACCESS_KEY_ID,
        aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
        region_name=settings.S3_REGION_NAME or "default",
        config=Config(
            signature_version=settings.S3_SIGNATURE_VERSION or "s3v4",
            s3={"addressing_style": settings.S3_ADDRESSING_STYLE or "path"},
            request_checksum_calculation="when_required",
            response_checksum_validation="when_required",
            connect_timeout=10,
            read_timeout=30,
        ),
    )


def parse_storage_path(storage_path: str) -> Tuple[str, str, str]:
    """
    Parse storage path URI.
    Returns (provider, bucket_or_dir, key_or_filename).
    Examples:
      's3:pathlab-reprts/reports/file.pdf' -> ('s3', 'pathlab-reprts', 'reports/file.pdf')
      'uploads/reports/file.pdf' -> ('local', 'uploads/reports', 'file.pdf')
    """
    if storage_path.startswith("s3:"):
        rest = storage_path[3:]
        parts = rest.split("/", 1)
        bucket = parts[0]
        key = parts[1] if len(parts) > 1 else ""
        return "s3", bucket, key

    if storage_path.startswith("supabase:"):
        # Supabase bucket has been decommissioned by user
        return "supabase", "", ""

    p = Path(storage_path)
    return "local", str(p.parent), p.name


def upload_file_bytes(
    file_bytes: bytes,
    filename: str,
    content_type: str = "application/pdf",
    folder: str = "reports"
) -> str:
    """
    Upload file bytes to Joy.services S3 storage (or local disk fallback).
    Returns canonical storage path URI stored in database: 's3:pathlab-reprts/reports/<filename>'.
    """
    provider = (settings.STORAGE_PROVIDER or "s3").lower()

    # Joy.services S3 (Primary)
    if provider in ("s3", "joy") or (settings.S3_ACCESS_KEY_ID and settings.S3_SECRET_ACCESS_KEY):
        if not settings.S3_ACCESS_KEY_ID or not settings.S3_SECRET_ACCESS_KEY:
            raise ValueError("S3 storage requested but S3_ACCESS_KEY_ID or S3_SECRET_ACCESS_KEY is missing")

        s3 = get_s3_client()
        key = f"{folder}/{filename}" if folder else filename
        bucket = settings.S3_BUCKET_NAME or "pathlab-reprts"

        try:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=file_bytes,
                ContentType=content_type,
            )
            logger.info(f"File uploaded to Joy S3: bucket={bucket}, key={key}")
            return f"s3:{bucket}/{key}"
        except Exception as e:
            logger.error(f"Joy S3 upload error: {e}")
            raise ValueError(f"Storage Error: Failed to upload file to Joy S3: {e}")

    # Local Filesystem Fallback
    target_dir = ATTACHMENTS_DIR if folder == "attachments" else REPORTS_DIR
    file_path = target_dir / filename
    file_path.write_bytes(file_bytes)
    try:
        os.chmod(file_path, 0o600)
    except Exception:
        pass
    return str(file_path)


def download_file_bytes(storage_path: str) -> bytes:
    """Download and return raw file bytes from Joy S3 or local disk."""
    provider, bucket, key = parse_storage_path(storage_path)

    if provider == "s3":
        s3 = get_s3_client()
        try:
            resp = s3.get_object(Bucket=bucket, Key=key)
            return resp["Body"].read()
        except Exception as e:
            logger.error(f"Joy S3 download failed for {storage_path}: {e}")
            raise FileNotFoundError(f"File not found in Joy S3: {e}")

    elif provider == "supabase":
        raise FileNotFoundError("Supabase storage bucket has been decommissioned. Files are stored on Joy S3.")

    else:
        p = Path(storage_path)
        if not p.is_file():
            raise FileNotFoundError("File not found on local disk")
        return p.read_bytes()


def delete_file_object(storage_path: str) -> bool:
    """Safely delete file object from Joy S3 or local filesystem."""
    provider, bucket, key = parse_storage_path(storage_path)

    try:
        if provider == "s3":
            s3 = get_s3_client()
            s3.delete_object(Bucket=bucket, Key=key)
            return True
        elif provider == "supabase":
            return True  # Already decommissioned
        else:
            p = Path(storage_path)
            if p.is_file():
                p.unlink()
            return True
    except Exception as e:
        logger.warning(f"Failed to delete file object {storage_path}: {e}")
        return False


def generate_presigned_download_url(storage_path: str, expires_in: int = 3600) -> Optional[str]:
    """Generate a presigned download URL from Joy S3."""
    provider, bucket, key = parse_storage_path(storage_path)
    if provider == "s3":
        s3 = get_s3_client()
        try:
            return s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )
        except Exception as e:
            logger.error(f"Failed to generate presigned Joy S3 URL: {e}")
            return None
    return None
