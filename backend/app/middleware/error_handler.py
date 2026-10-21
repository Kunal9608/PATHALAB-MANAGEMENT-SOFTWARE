"""Global error handler — consistent, secure, and production-ready error handling per PathLab OS specifications."""
import os
import uuid
import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("akriti.error_handler")

# Resolve project frontend directory
ROOT = Path(__file__).resolve().parent.parent.parent.parent
FRONTEND_DIR = ROOT / "frontend"


def _json_safe(data):
    if isinstance(data, BaseException):
        return str(data)
    elif isinstance(data, bytes):
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.hex()
    elif isinstance(data, dict):
        return {str(k): _json_safe(v) for k, v in data.items()}
    elif isinstance(data, (list, set)):
        return [_json_safe(item) for item in data]
    elif isinstance(data, tuple):
        return tuple(_json_safe(item) for item in data)
    elif not isinstance(data, (str, int, float, bool, type(None))):
        return str(data)
    return data


def _generate_request_id() -> str:
    return str(uuid.uuid4())


async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Centralized HTTP exception handler.
    - Serves branded 404.html with status 404 for browser page navigation.
    - Returns pure 404 JSON for missing assets (never serves HTML for .js/.css).
    - Returns structured, safe JSON for API endpoints.
    """
    path = request.url.path
    status_code = exc.status_code
    req_id = _generate_request_id()

    # 1. Static asset missing check — NEVER return HTML fallback for missing assets
    asset_extensions = (
        ".js", ".css", ".png", ".jpg", ".jpeg", ".svg", ".ico",
        ".woff", ".woff2", ".ttf", ".eot", ".map", ".json", ".webp"
    )
    is_asset = path.startswith("/assets/") or any(path.lower().endswith(ext) for ext in asset_extensions)
    if is_asset:
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "detail": f"Static asset not found: {path.split('/')[-1]}",
                "message": "Asset not found",
                "request_id": req_id
            }
        )

    # 2. Browser HTML page navigation — serve custom branded 404.html
    accept_header = request.headers.get("accept", "")
    is_html_navigation = (
        not path.startswith("/api/") and
        (
            "text/html" in accept_header or
            "." not in path.split("/")[-1]
        )
    )

    if status_code == 404 and is_html_navigation:
        four_o_four_file = FRONTEND_DIR / "404.html"
        if four_o_four_file.is_file():
            return FileResponse(
                str(four_o_four_file),
                status_code=404,
                media_type="text/html",
                headers={"X-PathLab-Error": "404-Page-Not-Found"}
            )

    # 3. Structured JSON for API routes and non-HTML requests
    detail_msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail or "An error occurred")
    code_map = {
        400: "BAD_REQUEST",
        401: "UNAUTHORIZED",
        403: "FORBIDDEN",
        404: "RESOURCE_NOT_FOUND",
        405: "METHOD_NOT_ALLOWED",
        409: "CONFLICT",
        429: "RATE_LIMIT_EXCEEDED",
        500: "INTERNAL_SERVER_ERROR",
        502: "BAD_GATEWAY",
        503: "SERVICE_UNAVAILABLE",
        504: "GATEWAY_TIMEOUT",
    }
    error_code = code_map.get(status_code, f"HTTP_{status_code}")

    logger.warning(f"HTTP {status_code} [{error_code}] on {request.method} {request.url}: {detail_msg} (req_id: {req_id})")

    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "detail": detail_msg,
            "message": detail_msg,
            "error": {
                "code": error_code,
                "message": detail_msg,
                "request_id": req_id
            }
        }
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    req_id = _generate_request_id()
    errors = _json_safe(exc.errors())
    logger.info(f"Validation error on {request.method} {request.url} (req_id: {req_id})")
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "detail": errors,
            "message": "Validation error in request payload",
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Validation error in request payload",
                "request_id": req_id
            }
        },
    )


async def value_error_handler(request: Request, exc: ValueError):
    req_id = _generate_request_id()
    logger.warning(f"ValueError on {request.method} {request.url}: {exc} (req_id: {req_id})")
    clean_msg = str(exc) if str(exc) else "A validation error occurred. Please check your inputs."
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "detail": clean_msg,
            "message": clean_msg,
            "error": {
                "code": "VALUE_ERROR",
                "message": clean_msg,
                "request_id": req_id
            }
        },
    )


async def permission_error_handler(request: Request, exc: PermissionError):
    req_id = _generate_request_id()
    logger.warning(f"PermissionError on {request.method} {request.url} (req_id: {req_id})")
    return JSONResponse(
        status_code=403,
        content={
            "success": False,
            "detail": "You do not have permission to perform this action.",
            "message": "Forbidden",
            "error": {
                "code": "FORBIDDEN",
                "message": "You do not have permission to perform this action.",
                "request_id": req_id
            }
        },
    )


async def timeout_exception_handler(request: Request, exc: TimeoutError):
    req_id = _generate_request_id()
    logger.error(f"Timeout on {request.method} {request.url} (req_id: {req_id})")
    return JSONResponse(
        status_code=504,
        content={
            "success": False,
            "detail": "The server timed out waiting for the request to complete. Please try again.",
            "message": "Gateway Timeout",
            "error": {
                "code": "GATEWAY_TIMEOUT",
                "message": "Request timed out",
                "request_id": req_id
            }
        }
    )


async def generic_exception_handler(request: Request, exc: Exception):
    req_id = _generate_request_id()
    logger.exception(f"Unhandled 500 error on {request.method} {request.url} (req_id: {req_id}): {exc}")
    # Never expose stack traces or raw database statements to client in production
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "detail": "An internal error occurred. Please contact laboratory support if this persists.",
            "message": "Something went wrong. Please try again.",
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An internal error occurred",
                "request_id": req_id
            }
        },
    )
