from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import httpx

DIAGNOSTICS_DIR = Path("/tmp/business-trip-planner-diagnostics")
RETURN_BODY_LIMIT_BYTES = 1024 * 1024


def _safe_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    return {str(k): str(v) for k, v in dict(headers).items()}


def _safe_params(params: dict[str, Any]) -> dict[str, Any]:
    # Avoid leaking the API key into route diagnostics while preserving all
    # non-secret query parameters needed to reproduce the Yandex request.
    return {key: ("***redacted***" if key.lower() == "apikey" else value) for key, value in params.items()}


def _decode_body(content: bytes) -> str:
    return content.decode("utf-8", errors="replace")


def _truncate_for_return(body: str) -> str:
    encoded = body.encode("utf-8")
    if len(encoded) <= RETURN_BODY_LIMIT_BYTES:
        return body
    return encoded[:RETURN_BODY_LIMIT_BYTES].decode("utf-8", errors="replace") + "\n...[truncated for API response; full body saved in artifact]"


def write_yandex_diagnostics(*, request: httpx.Request, response: httpx.Response | None = None, exception: BaseException | None = None, parsed_json: Any = None, json_exception: BaseException | None = None) -> dict[str, Any]:
    DIAGNOSTICS_DIR.mkdir(parents=True, exist_ok=True)
    request_params = _safe_params(dict(request.url.params))
    request_payload = {"request_url": str(request.url).split("?", 1)[0], "request_params": request_params, "method": request.method}
    (DIAGNOSTICS_DIR / "yandex_request.json").write_text(json.dumps(request_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    headers = _safe_headers(response.headers) if response is not None else {}
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    raw_body = _decode_body(response.content) if response is not None else ""
    (DIAGNOSTICS_DIR / "yandex_response.txt").write_text(raw_body, encoding="utf-8")
    (DIAGNOSTICS_DIR / "yandex_headers.json").write_text(json.dumps(headers, ensure_ascii=False, indent=2), encoding="utf-8")

    exception_text = ""
    if exception is not None:
        exception_text = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))
    elif json_exception is not None:
        exception_text = "".join(traceback.format_exception(type(json_exception), json_exception, json_exception.__traceback__))
    (DIAGNOSTICS_DIR / "yandex_exception.txt").write_text(exception_text, encoding="utf-8")

    artifact_paths = {
        "request": str(DIAGNOSTICS_DIR / "yandex_request.json"),
        "response_json": str(DIAGNOSTICS_DIR / "yandex_response.json"),
        "response_body": str(DIAGNOSTICS_DIR / "yandex_response.txt"),
        "headers": str(DIAGNOSTICS_DIR / "yandex_headers.json"),
        "exception": str(DIAGNOSTICS_DIR / "yandex_exception.txt"),
    }
    diagnostics = {
        "request_url": str(request.url).split("?", 1)[0],
        "request_params": request_params,
        "status_code": response.status_code if response is not None else None,
        "headers": headers,
        "content_type": content_type,
        "raw_body": _truncate_for_return(raw_body),
        "json": parsed_json,
        "exception": repr(exception or json_exception) if (exception or json_exception) else None,
        "traceback": exception_text,
        "artifact_paths": artifact_paths,
    }
    (DIAGNOSTICS_DIR / "yandex_response.json").write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return diagnostics
