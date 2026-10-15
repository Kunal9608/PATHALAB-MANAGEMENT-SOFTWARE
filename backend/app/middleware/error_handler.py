"""Global error handler — consistent JSON error shape per SRS §9."""
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging

logger = logging.getLogger(__name__)


def _json_safe(data):
    if isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.hex()
    elif isinstance(data, dict):
        return {k: _json_safe(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_json_safe(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(_json_safe(item) for item in data)
    return data


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = _json_safe(exc.errors())
    return JSONResponse(
        status_code=422,
        content={"detail": errors, "message": "Validation error"},
    )


async def value_error_handler(request: Request, exc: ValueError):
    logger.exception(f"Validation error (ValueError) on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=422,
        content={"detail": "A validation error occurred. Please check your inputs.", "message": "Validation Error"},
    )


async def permission_error_handler(request: Request, exc: PermissionError):
    # Do not leak raw exception text; return a generic 403 message
    return JSONResponse(
        status_code=403,
        content={"detail": "You do not have permission to perform this action.", "message": "Forbidden"},
    )


async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error on {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred", "message": "Something went wrong. Please try again."},
    )
