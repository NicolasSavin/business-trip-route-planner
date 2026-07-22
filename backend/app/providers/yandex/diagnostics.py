from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Any

import httpx

DIAGNOSTICS_DIR = Path("/tmp/business-trip-planner-diagnostics")
DEFAULT_PREVIEW_CHARS = 4000
DEFAULT_MAX_DETAILS_BYTES = 32768
TRACEBACK_LIMIT_CHARS = 4000
PARSED_JSON_PREVIEW_CHARS = 10000
SAFE_RESPONSE_HEADERS = {
    "cache-control",
    "content-language",
    "content-length",
    "content-type",
    "content-encoding",
    "date",
    "etag",
    "expires",
    "last-modified",
    "retry-after",
    "server",
    "vary",
    "x-request-id",
    "x-yandex-request-id",
}
BINARY_ENCODINGS = {"gzip", "br", "deflate", "compress", "zstd"}


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _safe_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {str(k).lower(): str(v) for k, v in dict(headers).items() if str(k).lower() in SAFE_RESPONSE_HEADERS}


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    return {key: ("***redacted***" if key.lower() == "apikey" else value) for key, value in params.items()}


def _content_encoding(headers: dict[str, str]) -> str:
    return headers.get("content-encoding", "")


def _is_binary_response(content: bytes, content_type: str, content_encoding: str) -> bool:
    if content_encoding.lower() in BINARY_ENCODINGS:
        return True
    if not content:
        return False
    lowered_type = content_type.lower()
    if not (lowered_type.startswith("text/") or "json" in lowered_type or "xml" in lowered_type or "javascript" in lowered_type):
        return True
    sample = content[: min(len(content), 1024)]
    if b"\x00" in sample:
        return True
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


def _text_preview(content: bytes, limit: int) -> tuple[str | None, bool]:
    if not content:
        return "", False
    head = content[: max(limit * 4, limit)]
    text = head.decode("utf-8", errors="replace")
    truncated = len(text) > limit or len(head) < len(content)
    return text[:limit], truncated


def _json_preview(parsed_json: Any) -> tuple[str | None, list[str] | None]:
    if parsed_json is None:
        return None, None
    keys = sorted(str(key) for key in parsed_json.keys()) if isinstance(parsed_json, dict) else None
    return json.dumps(parsed_json, ensure_ascii=False, default=str)[:PARSED_JSON_PREVIEW_CHARS], keys


def _truncate_text(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def _trim_to_max_bytes(details: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    while len(json.dumps(details, ensure_ascii=False, default=str).encode("utf-8")) > max_bytes:
        if details.get("parsed_json_preview"):
            details["parsed_json_preview"] = details["parsed_json_preview"][: max(0, len(details["parsed_json_preview"]) // 2)]
        elif details.get("raw_body_preview"):
            details["raw_body_preview"] = details["raw_body_preview"][: max(0, len(details["raw_body_preview"]) // 2)]
            details["raw_body_truncated"] = True
        elif details.get("traceback"):
            details["traceback"] = details["traceback"][: max(0, len(details["traceback"]) // 2)]
        else:
            break
    return details


def write_yandex_diagnostics(*, request: httpx.Request, response: httpx.Response | None = None, exception: BaseException | None = None, parsed_json: Any = None, json_exception: BaseException | None = None) -> dict[str, Any]:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    verbose = _env_bool("YANDEX_DIAGNOSTICS_VERBOSE", False)
    preview_chars = _env_int("YANDEX_DIAGNOSTICS_PREVIEW_CHARS", DEFAULT_PREVIEW_CHARS)
    max_details_bytes = _env_int("YANDEX_DIAGNOSTICS_MAX_DETAILS_BYTES", DEFAULT_MAX_DETAILS_BYTES)

    request_params = _safe_params(dict(request.url.params))
    request_payload = {"request_url": str(request.url).split("?", 1)[0], "request_params": request_params, "method": request.method}
    request_path = DIAGNOSTICS_DIR / "yandex_request.json"
    response_json_path = DIAGNOSTICS_DIR / "yandex_response.json"
    response_body_path = DIAGNOSTICS_DIR / "yandex_response.bin"
    headers_path = DIAGNOSTICS_DIR / "yandex_headers.json"
    exception_path = DIAGNOSTICS_DIR / "yandex_exception.txt"
    request_path.write_text(json.dumps(request_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    all_headers = {str(k).lower(): str(v) for k, v in dict(response.headers).items()} if response is not None else {}
    safe_headers = _safe_headers(all_headers)
    content_type = all_headers.get("content-type", "")
    content_encoding = _content_encoding(all_headers)
    raw_content = response.content if response is not None else b""
    response_body_path.write_bytes(raw_content)
    headers_path.write_text(json.dumps(safe_headers, ensure_ascii=False, indent=2), encoding="utf-8")

    exc_obj = exception or json_exception
    exception_text = ""
    if exc_obj is not None:
        exception_text = _truncate_text("".join(traceback.format_exception(type(exc_obj), exc_obj, exc_obj.__traceback__)), TRACEBACK_LIMIT_CHARS)
    exception_path.write_text(exception_text, encoding="utf-8")

    artifact_paths = {"request": str(request_path), "response_json": str(response_json_path), "response_body": str(response_body_path), "headers": str(headers_path), "exception": str(exception_path)}
    raw_size = len(raw_content)
    parsed_preview, response_keys = _json_preview(parsed_json)
    binary = _is_binary_response(raw_content, content_type, content_encoding)
    raw_preview, raw_truncated = (None, False) if binary else _text_preview(raw_content, preview_chars)

    base = {
        "request_url": request_payload["request_url"],
        "final_response_url": str(response.url).split("?", 1)[0] if response is not None else None,
        "request_params": request_params,
        "status_code": response.status_code if response is not None else None,
        "content_type": content_type,
        "content_encoding": content_encoding,
        "content_length": all_headers.get("content-length"),
        "response_headers": safe_headers,
        "response_keys": response_keys,
        "parsed_json_preview": parsed_preview,
        "raw_body_preview": raw_preview,
        "raw_body_size_bytes": raw_size,
        "raw_body_truncated": raw_truncated,
        "artifact_paths": artifact_paths,
        "exception_type": type(exc_obj).__name__ if exc_obj else None,
        "exception_message": str(exc_obj) if exc_obj else None,
    }
    if binary:
        base["raw_body_binary"] = True
    if verbose:
        base["traceback"] = exception_text
    else:
        base = {k: base[k] for k in ("status_code", "content_type", "content_encoding", "final_response_url", "response_keys", "raw_body_size_bytes", "artifact_paths")}

    details = _trim_to_max_bytes(base, max_details_bytes)
    response_json_path.write_text(json.dumps(details, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return details
