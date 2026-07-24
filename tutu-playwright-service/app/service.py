from __future__ import annotations
import asyncio, hashlib, json, logging, os, re, time
from urllib.parse import parse_qsl, urlsplit
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
from .models import AvailabilityCheckRequest, AvailabilityCheckResponse, AvailabilityStatus, Diagnostics, JourneyAvailabilityResponse
from .settings import settings

logger = logging.getLogger(__name__)
LOCATION_AUTOCOMPLETE_TIMEOUT_MS = 20_000
ROUTE_FIELD_LABELS = {
    "origin": ("откуда", "город отправления", "пункт отправления", "станция отправления"),
    "destination": ("куда", "город прибытия", "пункт прибытия", "станция прибытия"),
}

MAX_DIAGNOSTIC_ITEMS = 50
MAX_DIAGNOSTIC_STRING = 500

AUTOCOMPLETE_NETWORK_KEYWORDS = ("suggest", "autocomplete", "station", "city", "route", "search", "railway", "poezda")
AUTOCOMPLETE_BODY_SAMPLE_LIMIT = 16 * 1024
SAFE_HEADER_DENY_RE = re.compile(r"(cookie|authorization|token|session|secret|set-cookie)", re.I)
SAFE_QUERY_DENY_RE = re.compile(r"(token|session|sessionid|sid|uid|auth|authorization|cookie|key|secret|email|phone|user|need_propagation)", re.I)
ANALYTICS_ENDPOINT_RE = re.compile(r"(api-x\.tutu\.ru/v2/data|targetads|uxfeedback|metrics.*/collect|collect/event|advertising)", re.I)
AUTOCOMPLETE_ENDPOINT_RE = re.compile(r"(suggest|autocomplete|station|city)", re.I)
SECRET_KEY_RE = re.compile(r"(cookie|session|sessionid|token|auth|authorization|uid|sid|need_propagation|secret)", re.I)


def _safe_url(url: str) -> str:
    from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
    try:
        parts = urlsplit(url)
        safe_q = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if SAFE_QUERY_DENY_RE.search(key):
                value = "[redacted]"
            elif len(value) > 120:
                value = value[:80] + "…[truncated]"
            safe_q.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(safe_q, doseq=True), ""))
    except Exception:
        return _safe_text(url, 1000) or ""


def _safe_headers(headers: dict | None) -> dict:
    out = {}
    for key, value in (headers or {}).items():
        if SAFE_HEADER_DENY_RE.search(str(key)):
            continue
        out[str(key)[:80]] = _safe_text(value, 300)
    return out


def _endpoint(url: str) -> str:
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(url)
        return f"{parts.netloc}{parts.path}"
    except Exception:
        return _safe_text(url, 200) or ""


def _network_contains_city(*values, city: str | None = None) -> bool:
    city_norm = normalize_location_text(city or "")
    if not city_norm:
        return False
    return any(city_norm in normalize_location_text(str(value or "")) for value in values)


def _is_analytics_endpoint(url: str) -> bool:
    return bool(ANALYTICS_ENDPOINT_RE.search(url or ""))


def _looks_autocomplete_related(url: str, post_data: str | None = None, city: str | None = None) -> bool:
    if _is_analytics_endpoint(url):
        return False
    haystack = f"{url or ''} {post_data or ''}"
    return bool(AUTOCOMPLETE_ENDPOINT_RE.search(haystack)) or _network_contains_city(url, post_data, city=city)


def _redact_sensitive(value):
    if isinstance(value, dict):
        return {str(k)[:80]: ("[redacted]" if SECRET_KEY_RE.search(str(k)) else _redact_sensitive(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive(v) for v in value]
    if isinstance(value, str):
        text = re.sub(r"(?i)(cookie|sessionid|sessionId|uid|token|authorization|auth|need_propagation)([\s:=\"]+)([^&;\s,}]+)", r"\1\2[redacted]", value)
        text = re.sub(r"(?i)(Cookie|Authorization):\s*[^\r\n]+", r"\1: [redacted]", text)
        return text
    return value


def _safe_body_sample(url: str, post_data: str | None, limit: int = 2000) -> str | None:
    if post_data is None:
        return None
    if _is_analytics_endpoint(url):
        return "[redacted analytics payload]"
    try:
        data = json.loads(post_data)
        return _safe_text(json.dumps(_redact_sensitive(data), ensure_ascii=False), limit)
    except Exception:
        return _safe_text(_redact_sensitive(post_data), limit)


def _json_probe(text: str | None, requested_city: str | None) -> dict:
    probe = {"is_json": False, "is_array": False, "item_count": None, "contains_requested_city": False, "top_level_keys": [], "text_values_sample": []}
    if not text:
        return probe
    probe["contains_requested_city"] = _network_contains_city(text, city=requested_city)
    try:
        data = json.loads(text)
    except Exception:
        return probe
    probe["is_json"] = True
    probe["is_array"] = isinstance(data, list)
    if isinstance(data, list):
        probe["item_count"] = len(data)
    elif isinstance(data, dict):
        probe["top_level_keys"] = [str(k)[:80] for k in list(data.keys())[:20]]
        for value in data.values():
            if isinstance(value, list):
                probe["item_count"] = len(value)
                break
    samples = []
    def walk(value):
        if len(samples) >= 8:
            return
        if isinstance(value, str) and value.strip():
            samples.append(_safe_text(value, 200))
        elif isinstance(value, dict):
            for v in list(value.values())[:20]: walk(v)
        elif isinstance(value, list):
            for v in value[:20]: walk(v)
    walk(data)
    probe["text_values_sample"] = samples
    probe["contains_requested_city"] = probe["contains_requested_city"] or any(_network_contains_city(v, city=requested_city) for v in samples)
    return probe


def _network_summary(requests: list[dict], responses: list[dict], failures: list[dict], popup_rendered: bool = False) -> dict:
    statuses = {}
    endpoints = {}
    for response in responses:
        status = str(response.get("status"))
        statuses[status] = statuses.get(status, 0) + 1
    for request in requests:
        endpoint = request.get("endpoint") or _endpoint(request.get("url") or "")
        endpoints[endpoint] = endpoints.get(endpoint, 0) + 1
    with_city = any(r.get("contains_requested_city") for r in requests)
    response_with_options = any((r.get("json_probe") or {}).get("contains_requested_city") and ((r.get("json_probe") or {}).get("item_count") or 0) > 0 for r in responses)
    reason = "unknown"
    if not requests:
        reason = "autocomplete_request_not_triggered"
    elif failures:
        reason = "request_failed"
    elif any(400 <= (r.get("status") or 0) < 500 for r in responses):
        reason = "response_4xx"
    elif any((r.get("status") or 0) >= 500 for r in responses):
        reason = "response_5xx"
    elif responses and all((not r.get("body_size")) or ((r.get("json_probe") or {}).get("item_count") == 0) for r in responses):
        reason = "response_empty"
    elif any(r.get("body_read_error") for r in responses) and not any(r.get("body_sample") for r in responses):
        reason = "response_body_unreadable"
    elif responses and not any((r.get("json_probe") or {}).get("contains_requested_city") for r in responses):
        reason = "response_contains_no_matching_city"
    elif response_with_options and not popup_rendered:
        reason = "request_sent_but_popup_not_rendered"
    return {"total_xhr_fetch": len(requests), "relevant_requests": len(requests), "relevant_responses": len(responses), "failed_requests": len(failures), "statuses": statuses, "endpoints": endpoints, "request_with_city_found": with_city, "successful_response_with_options_detected": response_with_options, "probable_failure_reason": reason}


class TutuAutocompleteNetworkCapture:
    def __init__(self, page, field_name: str, requested_city: str):
        self.page=page; self.field_name=field_name; self.requested_city=requested_city; self.stage="before_typing"; self.requests=[]; self.responses=[]; self.failures=[]; self._by_request={}; self._started={}; self._counter=0; self._attached=False
    def attach(self):
        if not hasattr(self.page, "on"): return self
        self.page.on("request", self._on_request); self.page.on("response", self._on_response); self.page.on("requestfailed", self._on_request_failed); self._attached=True; return self
    def detach(self):
        if not self._attached: return
        for event, cb in (("request", self._on_request),("response", self._on_response),("requestfailed", self._on_request_failed)):
            try: self.page.remove_listener(event, cb)
            except Exception:
                try: self.page.off(event, cb)
                except Exception: pass
        self._attached=False
    def _rid(self, request):
        if request not in self._by_request:
            self._counter += 1; self._by_request[request] = f"{self.field_name}-{self._counter}"
        return self._by_request[request]
    def _request_payload(self, request):
        post = None
        try: post = request.post_data
        except Exception: post = None
        return post
    def _request_relevant(self, request, post):
        try: rtype = request.resource_type
        except Exception: rtype = ""
        try: url = request.url
        except Exception: url = ""
        if rtype not in {"xhr", "fetch"} and not (rtype in {"document", "script"} and _looks_autocomplete_related(url, None, None)):
            return False
        return _looks_autocomplete_related(url, post, self.requested_city)
    def _on_request(self, request):
        post = self._request_payload(request)
        if not self._request_relevant(request, post): return
        rid = self._rid(request); self._started[rid]=time.monotonic()
        raw_url = getattr(request,"url",None) or ""
        query_value = _autocomplete_query_value(raw_url)
        query_matches = _autocomplete_query_matches(self.requested_city, query_value)
        item={"timestamp": datetime.now(timezone.utc).isoformat(), "field_name": self.field_name, "requested_city": self.requested_city, "method": getattr(request,"method",None), "url": _safe_url(raw_url), "endpoint": _endpoint(raw_url), "resource_type": getattr(request,"resource_type",None), "post_data_sample": _safe_body_sample(raw_url, post, 2000), "request_headers_safe": _safe_headers(getattr(request,"headers",{}) or {}), "stage": self.stage, "request_id": rid, "contains_requested_city": _network_contains_city(raw_url, post, city=self.requested_city), "autocomplete_query_value": query_value, "autocomplete_query_matches_requested": query_matches, "malformed_autocomplete_query": bool(query_value is not None and not query_matches), "diagnostics_redaction_applied": True}
        self.requests.append(item); logger.info("tutu_autocomplete_request", extra={"field_name": self.field_name, "requested_city": self.requested_city, "method": item["method"], "endpoint": item["endpoint"], "status": None, "elapsed_ms": None, "response_item_count": None, "contains_requested_city": item["contains_requested_city"], "autocomplete_query_value": query_value, "query_matches_requested": query_matches, "probable_failure_reason": None})
        logger.info("tutu_autocomplete_query_observed", extra={"field_name": self.field_name, "requested_city": self.requested_city, "strategy": self.stage, "autocomplete_query_value": query_value, "query_matches_requested": query_matches, "response_item_count": None})
    async def _on_response(self, response):
        request = response.request; rid = self._rid(request)
        if rid not in self._started and not any(r.get("request_id")==rid for r in self.requests): return
        headers = getattr(response, "headers", {}) or {}; ctype = headers.get("content-type") or headers.get("Content-Type") or ""
        body_sample=None; body_size=None; body_read_error=None
        if not re.search(r"(image|font|octet-stream|zip|pdf|protobuf)", ctype, re.I):
            try:
                body = await response.text(); body_size=len(body.encode("utf-8")); body_sample=_safe_body_sample(getattr(response,"url",None) or "", body, AUTOCOMPLETE_BODY_SAMPLE_LIMIT)
            except Exception as exc: body_read_error=type(exc).__name__
        probe = _json_probe(body_sample, self.requested_city)
        elapsed = int((time.monotonic()-self._started.get(rid, time.monotonic()))*1000)
        item={"request_id": rid, "status": getattr(response,"status",None), "status_text": getattr(response,"status_text",None), "url": _safe_url(getattr(response,"url",None) or ""), "content_type": ctype, "response_headers_safe": _safe_headers(headers), "elapsed_ms": elapsed, "body_sample": body_sample, "body_size": body_size, "body_read_error": body_read_error, "json_probe": probe, "diagnostics_redaction_applied": True}
        self.responses.append(item); logger.info("tutu_autocomplete_response", extra={"field_name": self.field_name, "requested_city": self.requested_city, "method": None, "endpoint": _endpoint(item["url"]), "status": item["status"], "elapsed_ms": elapsed, "response_item_count": probe.get("item_count"), "contains_requested_city": probe.get("contains_requested_city"), "probable_failure_reason": None})
    def _on_request_failed(self, request):
        post = self._request_payload(request)
        if not self._request_relevant(request, post): return
        rid = self._rid(request); failure = None
        try: failure = request.failure
        except Exception: failure = None
        item={"request_id": rid, "url": _safe_url(getattr(request,"url",None) or ""), "method": getattr(request,"method",None), "failure_reason": failure, "stage": self.stage, "requested_city": self.requested_city, "field_name": self.field_name}
        self.failures.append(item); logger.info("tutu_autocomplete_request_failed", extra={"field_name": self.field_name, "requested_city": self.requested_city, "method": item["method"], "endpoint": _endpoint(item["url"]), "failure_reason": failure})
    def diagnostics(self, popup_rendered: bool = False) -> dict:
        summary = _network_summary(self.requests, self.responses, self.failures, popup_rendered)
        logger.info("tutu_autocomplete_network_summary", extra={"field_name": self.field_name, "requested_city": self.requested_city, "probable_failure_reason": summary.get("probable_failure_reason"), "relevant_requests": summary.get("relevant_requests"), "relevant_responses": summary.get("relevant_responses"), "failed_requests": summary.get("failed_requests")})
        return {"network_events": self.requests + self.responses + self.failures, "autocomplete_requests": self.requests, "autocomplete_responses": self.responses, "autocomplete_request_failures": self.failures, "network_summary": summary}



def _autocomplete_query_value(url: str | None) -> str | None:
    try:
        parts = urlsplit(url or "")
        if "/suggest/railway_simple/" not in parts.path:
            return None
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key == "name":
                return value
    except Exception:
        return None
    return None


def _autocomplete_query_matches(requested_city: str, query_value: str | None) -> bool:
    if query_value is None:
        return False
    requested = requested_city or ""
    return query_value == requested or (bool(query_value) and requested.startswith(query_value))


def _is_cyrillic_text(value: str) -> bool:
    return bool(re.search(r"[А-Яа-яЁё]", value or ""))


def _popular_city_response_without_requested(responses: list[dict], requested_city: str) -> bool:
    popular = {"москва", "санкт петербург", "казань"}
    for response in responses or []:
        probe = response.get("json_probe") or {}
        samples = {normalize_location_text(v) for v in (probe.get("text_values_sample") or [])}
        if popular.intersection(samples) and not probe.get("contains_requested_city"):
            return True
    return False

def _safe_text(value, limit: int = MAX_DIAGNOSTIC_STRING):
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text[:limit]


def _limit_diagnostic(value, max_items: int = MAX_DIAGNOSTIC_ITEMS):
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_limit_diagnostic(item, max_items) for item in value[:max_items]]
    if isinstance(value, tuple):
        return [_limit_diagnostic(item, max_items) for item in value[:max_items]]
    if isinstance(value, dict):
        return {str(k)[:80]: _limit_diagnostic(v, max_items) for k, v in list(value.items())[:max_items]}
    return value


def _ensure_station_diagnostics(diagnostics: dict | None):
    if diagnostics is None:
        return None
    diagnostics.setdefault("station_steps", [])
    diagnostics.setdefault("origin_station_selection", {})
    diagnostics.setdefault("destination_station_selection", {})
    diagnostics.setdefault("popup_candidates", {})
    diagnostics.setdefault("autocomplete_discovery", {})
    diagnostics.setdefault("selected_inputs", {})
    diagnostics.setdefault("field_resolution_collision", None)
    diagnostics.setdefault("origin_destination_same_element", None)
    diagnostics.setdefault("form_reacquired_after_origin", False)
    diagnostics.setdefault("final_origin_value", None)
    diagnostics.setdefault("final_destination_value", None)
    diagnostics.setdefault("network_events", {})
    diagnostics.setdefault("autocomplete_requests", {})
    diagnostics.setdefault("autocomplete_responses", {})
    diagnostics.setdefault("autocomplete_request_failures", {})
    diagnostics.setdefault("network_summary", {})
    diagnostics["diagnostics_redaction_applied"] = True
    return diagnostics


def _station_log(event: str, step: dict, popup_count: int = 0, option_count: int = 0) -> None:
    logger.info(event, extra={
        "field_name": step.get("field_name"),
        "city_name": step.get("requested_city"),
        "requested_city": step.get("requested_city"),
        "current_textbox_value": step.get("current_textbox_value") or step.get("value_after_blur") or step.get("value_after_clicking_suggestion") or step.get("textbox_value_after_typing"),
        "popup_count": popup_count,
        "option_count": option_count,
        "failure_reason": step.get("failure_reason"),
    })


class TutuDiagnosticError(Exception):
    def __init__(self, message: str, diagnostics: Diagnostics):
        super().__init__(message)
        self.diagnostics = diagnostics


def normalize_location_text(value: str) -> str:
    value = (value or "").split(",", 1)[0].lower().replace("ё", "е").strip()
    return re.sub(r"[\s\-]+", " ", value).strip()


def location_matches(candidate: str, city_name: str) -> tuple[int, bool]:
    candidate_norm = normalize_location_text(candidate)
    city_norm = normalize_location_text(city_name)
    if not candidate_norm or not city_norm:
        return (99, False)
    if candidate_norm == city_norm:
        return (0, True)
    if candidate_norm.startswith(city_norm) or city_norm.startswith(candidate_norm):
        return (1, True)
    if city_norm in candidate_norm or candidate_norm in city_norm:
        return (2, True)
    return (99, False)


async def _locator_count(locator) -> int:
    try:
        return await locator.count()
    except Exception:
        return 0


async def _visible_locator_count(locator) -> int:
    total = await _locator_count(locator)
    visible = 0
    for index in range(total):
        item = locator.nth(index)
        try:
            if await item.is_visible(timeout=200):
                visible += 1
        except Exception:
            continue
    return visible


async def _candidate_options(page):
    locators = [
        page.get_by_role("listbox").get_by_role("option"),
        page.get_by_role("option"),
        page.locator('[role="combobox"][aria-expanded="true"] [role="option"]'),
        page.locator('[role="listbox"] [role="option"]'),
        page.locator('[data-testid*="suggest" i], [class*="suggest" i], [class*="autocomplete" i], [class*="popup" i]').locator('text=/\\S/'),
    ]
    for locator in locators:
        if await _visible_locator_count(locator):
            return locator
    return locators[-1]


async def _candidate_options_for_input(page, textbox, field_name: str):
    class_hint = "from" if field_name == "origin" else "to"
    try:
        scoped = textbox.locator(
            "xpath=ancestor::*[contains(@class,'station') or contains(@class,'search') or contains(@class,'route') or self::form][1]"
        ).locator(
            f"[role='listbox'] [role='option'], [role='option'], [class*='j-city_{class_hint}_suggest_container'] *, [class*='suggest' i] [role='option'], [class*='autocomplete' i] [role='option']"
        )
        if await _visible_locator_count(scoped):
            return scoped
    except Exception:
        pass
    try:
        controls = await textbox.evaluate("el => (el.getAttribute('aria-controls') || '').split(/\\s+/).filter(Boolean)")
        if controls:
            selector = ", ".join(f"#{control.replace(chr(34), '').replace(chr(39), '')} [role='option'], #{control.replace(chr(34), '').replace(chr(39), '')}" for control in controls)
            linked_locator = page.locator(selector)
            if await _visible_locator_count(linked_locator):
                return linked_locator
    except Exception:
        pass
    try:
        field_popup = page.locator(f"[class*='j-city_{class_hint}_suggest_container'], [class*='city_{class_hint}' i][class*='suggest' i]")
        field_options = field_popup.locator("[role='option'], li, button, div, span")
        if hasattr(field_options, "filter"):
            field_options = field_options.filter(has_text=re.compile(r"\S"))
        if await _visible_locator_count(field_options):
            return field_options
    except Exception:
        pass
    return await _candidate_options(page)


async def _autocomplete_is_closed(page) -> bool:
    options = await _candidate_options(page)
    return await _visible_locator_count(options) == 0


async def _element_identity(locator) -> str:
    return await locator.evaluate(
        """
        el => {
            if (!el.dataset.tutuPwIdentity) el.dataset.tutuPwIdentity = `tutu-${Date.now()}-${Math.random().toString(36).slice(2)}`;
            return el.dataset.tutuPwIdentity;
        }
        """
    )


async def _same_element(left, right) -> bool:
    try:
        return await left.evaluate("(left, right) => left === right", await right.element_handle())
    except Exception:
        return await _element_identity(left) == await _element_identity(right)


def _diagnostics_model_kwargs(diagnostic_payload: dict, page_url: str | None = None, shots: list[str] | None = None, htmls: list[str] | None = None, matched_by: str | None = None):
    return dict(
        matched_by=matched_by,
        page_url=page_url,
        screenshots=shots or [],
        html_artifacts=htmls or [],
        selected_inputs=diagnostic_payload["selected_inputs"],
        station_steps=diagnostic_payload["station_steps"],
        origin_station_selection=diagnostic_payload["origin_station_selection"],
        destination_station_selection=diagnostic_payload["destination_station_selection"],
        popup_candidates=diagnostic_payload["popup_candidates"],
        autocomplete_discovery=diagnostic_payload["autocomplete_discovery"],
        field_resolution_collision=diagnostic_payload.get("field_resolution_collision"),
        origin_destination_same_element=diagnostic_payload.get("origin_destination_same_element"),
        form_reacquired_after_origin=diagnostic_payload.get("form_reacquired_after_origin"),
        final_origin_value=diagnostic_payload.get("final_origin_value"),
        final_destination_value=diagnostic_payload.get("final_destination_value"),
        network_events=diagnostic_payload.get("network_events", {}),
        autocomplete_requests=diagnostic_payload.get("autocomplete_requests", {}),
        autocomplete_responses=diagnostic_payload.get("autocomplete_responses", {}),
        autocomplete_request_failures=diagnostic_payload.get("autocomplete_request_failures", {}),
        network_summary=diagnostic_payload.get("network_summary", {}),
    )


async def _capture_location_artifacts(page, field_name: str, city_name: str) -> None:
    artifact_dir = Path(settings.artifact_dir) / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    sp = artifact_dir / "location_not_found.png"
    hp = artifact_dir / "location_not_found.html"
    try:
        await page.screenshot(path=str(sp), full_page=True)
        hp.write_text(await page.content(), encoding="utf-8")
        logger.info("location autocomplete artifacts saved", extra={"field_name": field_name, "city_name": city_name, "screenshot": str(sp), "html_artifact": str(hp)})
    except Exception:
        logger.exception("location autocomplete artifact capture caught exception", extra={"field_name": field_name, "city_name": city_name})


async def _save_step_artifact(page, step: str, artifacts: dict[str, list[str]] | None = None) -> None:
    artifact_dir = Path(settings.artifact_dir) / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    safe_step = re.sub(r"[^a-z0-9_-]+", "_", step.lower())
    screenshot = artifact_dir / f"{safe_step}-{stamp}.png"
    html = artifact_dir / f"{safe_step}-{stamp}.html"
    try:
        await page.screenshot(path=str(screenshot), full_page=True)
        html.write_text(await page.content(), encoding="utf-8")
        if artifacts is not None:
            artifacts.setdefault("screenshots", []).append(str(screenshot))
            artifacts.setdefault("html_artifacts", []).append(str(html))
        logger.info("tutu step artifacts saved", extra={"step": step, "screenshot": str(screenshot), "html_artifact": str(html)})
    except Exception:
        logger.exception("tutu step artifact capture caught exception", extra={"step": step})


async def collect_autocomplete_discovery(page, field_name: str, city_name: str) -> dict:
    selector = "[role='listbox'], [role='menu'], [role='dialog'], [role='option'], [class*='suggest' i], [class*='autocomplete' i], [class*='popup' i], [class*='dropdown' i], [data-testid*='suggest' i], [data-testid*='autocomplete' i]"
    try:
        discovery = await page.locator(selector).evaluate_all(
            """
            elements => {
                const safe = value => (value || '').toString().trim().replace(/\\s+/g, ' ').slice(0, 500);
                const attrs = element => {
                    const names = ['id','class','role','aria-label','aria-selected','aria-expanded','aria-hidden','aria-controls','data-testid','data-ti','name'];
                    const out = {};
                    names.forEach(name => { const value = element.getAttribute(name); if (value) out[name] = safe(value); });
                    return out;
                };
                const visible = element => {
                    const style = window.getComputedStyle(element);
                    return !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length) && style.display !== 'none' && style.visibility !== 'hidden';
                };
                const box = element => { const r = element.getBoundingClientRect(); return {x:r.x,y:r.y,width:r.width,height:r.height}; };
                const describe = (element, index) => ({index, text: safe(element.innerText || element.textContent), attrs: attrs(element), bounding_box: box(element), visible: visible(element)});
                const visibleElements = elements.filter(visible).slice(0, 50);
                return {
                    containers: visibleElements.map(describe),
                    options: Array.from(document.querySelectorAll('[role="option"]')).filter(visible).slice(0, 50).map(describe),
                    iframes: Array.from(document.querySelectorAll('iframe')).slice(0, 20).map((frame, index) => ({index, attrs: attrs(frame), bounding_box: box(frame), visible: visible(frame)})),
                    shadow_roots: Array.from(document.querySelectorAll('*')).filter(e => e.shadowRoot).slice(0, 20).map((host, index) => ({index, host: host.tagName.toLowerCase(), attrs: attrs(host), text: safe(host.shadowRoot.textContent), bounding_box: box(host), visible: visible(host)})),
                    body_text_sample: safe(document.body ? document.body.innerText : ''),
                };
            }
            """
        )
    except Exception:
        logger.exception("station autocomplete discovery failed", extra={"field_name": field_name, "city_name": city_name})
        discovery = {"containers": [], "options": [], "iframes": [], "shadow_roots": [], "body_text_sample": None}
    if not isinstance(discovery, dict):
        discovery = {"containers": discovery or [], "options": discovery or [], "iframes": [], "shadow_roots": [], "body_text_sample": None}
    discovery = _limit_diagnostic(discovery)
    logger.info("station_autocomplete_discovered", extra={"field_name": field_name, "city_name": city_name, "requested_city": city_name, "popup_count": len(discovery.get("containers", [])), "option_count": len(discovery.get("options", [])), "current_textbox_value": None, "failure_reason": None})
    return discovery


async def inspect_textboxes(page) -> list[dict]:
    try:
        inventory = await page.locator("input, textarea, [role='textbox'], [contenteditable='true']").evaluate_all(
            """
            elements => elements.map((element, index) => {
                const text = node => (node && (node.innerText || node.textContent) || '').trim().replace(/\\s+/g, ' ').slice(0, 500);
                const domPath = node => {
                    const parts = [];
                    while (node && node.nodeType === Node.ELEMENT_NODE) {
                        let part = node.tagName.toLowerCase();
                        if (node.id) part += `#${node.id}`;
                        const parent = node.parentElement;
                        if (parent) {
                            const siblings = Array.from(parent.children).filter(child => child.tagName === node.tagName);
                            if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
                        }
                        parts.unshift(part);
                        node = parent;
                    }
                    return parts.join(' > ');
                };
                const labelTexts = [];
                if (element.id) document.querySelectorAll(`label[for="${CSS.escape(element.id)}"]`).forEach(label => labelTexts.push(text(label)));
                const wrappingLabel = element.closest('label');
                if (wrappingLabel) labelTexts.push(text(wrappingLabel));
                const labelledBy = (element.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
                labelledBy.forEach(id => labelTexts.push(text(document.getElementById(id))));
                let ancestor = element.parentElement;
                const nearby = [];
                for (let depth = 0; ancestor && depth < 4; depth += 1, ancestor = ancestor.parentElement) {
                    nearby.push(text(ancestor));
                }
                const form = element.closest('form');
                const rect = element.getBoundingClientRect();
                const style = window.getComputedStyle(element);
                const visible = !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length) && style.visibility !== 'hidden' && style.display !== 'none';
                return {
                    index,
                    tag_name: element.tagName.toLowerCase(),
                    type: element.getAttribute('type'),
                    name: element.getAttribute('name'),
                    id: element.id || null,
                    class: element.getAttribute('class'),
                    placeholder: element.getAttribute('placeholder'),
                    aria_label: element.getAttribute('aria-label'),
                    autocomplete: element.getAttribute('autocomplete'),
                    current_value: element.value || element.textContent || '',
                    bounding_box: {x: rect.x, y: rect.y, width: rect.width, height: rect.height},
                    nearby_label_text: Array.from(new Set(labelTexts.concat(nearby).filter(Boolean))).slice(0, 8),
                    ancestor_form_text: text(form),
                    visible,
                    enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
                    editable: !element.readOnly && !element.disabled,
                    aria_controls: element.getAttribute('aria-controls'),
                    aria_expanded: element.getAttribute('aria-expanded'),
                    dom_path: domPath(element),
                };
            })
            """
        )
    except Exception:
        logger.exception("textbox inventory collection caught exception")
        return []
    logger.info("tutu textbox inventory", extra={"textbox_count": len(inventory), "textboxes": inventory})
    for item in inventory:
        logger.info("tutu textbox inventory item", extra={"textbox": item})
    return inventory


async def detect_station_input(page, field_name: str):
    inventory = await inspect_textboxes(page)
    if field_name not in {"origin", "destination"}:
        raise ValueError(f"Unsupported station field: {field_name}")
    labels = ROUTE_FIELD_LABELS[field_name]
    attr_tokens = ("from", "station_from", "j-station_from", "schedule_station_from") if field_name == "origin" else ("to", "station_to", "j-station_to", "schedule_station_to")
    opposite_tokens = ("to", "station_to", "j-station_to", "schedule_station_to", "куда") if field_name == "origin" else ("from", "station_from", "j-station_from", "schedule_station_from", "откуда")
    scored = []
    for item in inventory:
        attrs = " ".join(str(item.get(k) or "") for k in ("name", "id", "class", "placeholder", "aria_label", "autocomplete", "aria_controls")).lower()
        nearby = " ".join(item.get("nearby_label_text") or []).lower()
        haystack = f"{attrs} {nearby} {str(item.get('ancestor_form_text') or '').lower()}"
        signals = []
        score = 0
        placeholder = str(item.get("placeholder") or "").lower()
        name = str(item.get("name") or "").lower()
        classes = str(item.get("class") or "").lower()
        if any(label in placeholder for label in labels):
            score += 40; signals.append("placeholder")
        if any(token in name for token in attr_tokens):
            score += 35; signals.append("name")
        if any(token in classes or token in attrs for token in attr_tokens if token != "to"):
            score += 25; signals.append("station_attribute")
        if any(label in nearby for label in labels):
            score += 20; signals.append("nearby_label_or_ancestor")
        if any(label in haystack for label in labels) and "semantic_text" not in signals:
            score += 10; signals.append("semantic_text")
        if "поезд" in haystack or "ж/д" in haystack or "poezd" in haystack or "train" in haystack:
            score += 3
        if item.get("visible"):
            score += 2; signals.append("visible")
        if item.get("enabled") and item.get("editable"):
            score += 2; signals.append("editable")
        if any(token in placeholder or token in name or token in classes for token in opposite_tokens):
            score -= 45; signals.append("opposite_field_penalty")
        if score:
            enriched = {**item, "selector_strategy": "semantic_station_input", "confidence_score": score, "matched_semantic_signals": signals}
            scored.append((score, enriched))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["index"]))
    if not scored:
        logger.info("tutu route input semantic detection failed", extra={"field_name": field_name, "inventory": inventory})
        raise ValueError(f"Tutu route {field_name} input not found")
    selected = scored[0][1]
    logger.info("station_input_detected", extra={"field_name": field_name, "score": scored[0][0], "selected_input": selected})
    return page.locator("input, textarea, [role='textbox'], [contenteditable='true']").nth(selected["index"]), selected, inventory


# Backward-compatible alias for older tests/imports. New flow must use detect_station_input.
detect_route_input = detect_station_input


async def inspect_popup_candidates(page, textbox, field_name: str, city_name: str) -> list[str]:
    await _log_autocomplete_diagnostics(page, field_name, city_name)
    try:
        linked = await textbox.evaluate(
            """
            element => {
                const ids = (element.getAttribute('aria-controls') || '').split(/\\s+/).filter(Boolean);
                const out = [];
                ids.forEach(id => {
                    const target = document.getElementById(id);
                    if (target) out.push((target.innerText || target.textContent || '').trim());
                });
                return out.filter(Boolean);
            }
            """
        )
        logger.info("autocomplete linked popup descendants", extra={"field_name": field_name, "city_name": city_name, "linked_popup_texts": linked})
    except Exception:
        pass
    selector = "[role='listbox'], [role='option'], [class*='suggest' i], [class*='autocomplete' i], [class*='popup' i], [class*='dropdown' i]"
    try:
        texts = await page.locator(selector).evaluate_all("els => els.filter(e => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length)).map(e => (e.innerText || e.textContent || '').trim()).filter(Boolean).slice(0, 50)")
    except Exception:
        texts = []
    logger.info("autocomplete popup candidate inventory", extra={"field_name": field_name, "city_name": city_name, "popup_candidate_texts": texts})
    return texts


async def _log_autocomplete_diagnostics(page, field_name: str, city_name: str) -> None:
    selector = "[role='listbox'], [role='option'], [role='combobox'], [class*='suggest' i], [class*='autocomplete' i], [class*='popup' i], [class*='dropdown' i], [data-testid*='suggest' i], [data-testid*='autocomplete' i], [data-ti*='suggest' i], [data-ti*='autocomplete' i]"
    try:
        containers = await page.locator(selector).evaluate_all(
            """
            elements => elements.map((element, index) => {
                const domPath = node => {
                    const parts = [];
                    while (node && node.nodeType === Node.ELEMENT_NODE) {
                        let part = node.tagName.toLowerCase();
                        if (node.id) part += `#${node.id}`;
                        const parent = node.parentElement;
                        if (parent) {
                            const siblings = Array.from(parent.children).filter(child => child.tagName === node.tagName);
                            if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(node) + 1})`;
                        }
                        parts.unshift(part);
                        node = parent;
                    }
                    return parts.join(' > ');
                };
                const style = window.getComputedStyle(element);
                const rect = element.getBoundingClientRect();
                const options = Array.from(element.querySelectorAll('[role="option"], li, button, [data-testid], [data-ti], a, div, span'))
                    .map(option => ({
                        text: (option.innerText || option.textContent || '').trim(),
                        dom_path: domPath(option),
                        visibility: {
                            visible: !!(option.offsetWidth || option.offsetHeight || option.getClientRects().length),
                            display: window.getComputedStyle(option).display,
                            visibility: window.getComputedStyle(option).visibility,
                            opacity: window.getComputedStyle(option).opacity,
                        },
                        role: option.getAttribute('role'),
                        aria_expanded: option.getAttribute('aria-expanded'),
                        aria_selected: option.getAttribute('aria-selected'),
                        aria_hidden: option.getAttribute('aria-hidden'),
                        classes: option.className,
                    }))
                    .filter(option => option.text);
                return {
                    index,
                    text: (element.innerText || element.textContent || '').trim(),
                    dom_path: domPath(element),
                    visibility: {
                        visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
                        display: style.display,
                        visibility: style.visibility,
                        opacity: style.opacity,
                        rect: { x: rect.x, y: rect.y, width: rect.width, height: rect.height },
                    },
                    role: element.getAttribute('role'),
                    aria_expanded: element.getAttribute('aria-expanded'),
                    aria_hidden: element.getAttribute('aria-hidden'),
                    classes: element.className,
                    options,
                };
            })
            """
        )
    except Exception:
        logger.exception("autocomplete diagnostics collection caught exception", extra={"field_name": field_name, "city_name": city_name})
        return
    if not containers:
        logger.info("no autocomplete popup found", extra={"field_name": field_name, "city_name": city_name})
        return
    logger.info("autocomplete containers found", extra={"field_name": field_name, "city_name": city_name, "containers_count": len(containers)})
    for container in containers:
        logger.info("autocomplete container diagnostics", extra={"field_name": field_name, "city_name": city_name, "container": container})
        if not container.get("options"):
            logger.info("autocomplete container has no options", extra={"field_name": field_name, "city_name": city_name, "dom_path": container.get("dom_path")})
        for option in container.get("options", []):
            logger.info("autocomplete option diagnostics", extra={"field_name": field_name, "city_name": city_name, "container_dom_path": container.get("dom_path"), "option": option})


async def _fail_location_not_found(page, field_name: str, city_name: str) -> None:
    await _capture_location_artifacts(page, field_name, city_name)
    await _log_autocomplete_diagnostics(page, field_name, city_name)
    raise ValueError(f"Location suggestion not found: {city_name}")


async def _textbox_value(textbox) -> str:
    try:
        return (await textbox.input_value() or "").strip()
    except Exception:
        try:
            return (await textbox.evaluate("el => el.value || el.textContent || ''") or "").strip()
        except Exception:
            return ""


async def _finish_station_step(diagnostics: dict | None, field_name: str, step: dict) -> None:
    target = _ensure_station_diagnostics(diagnostics)
    if target is None:
        return
    limited = _limit_diagnostic(step)
    target["station_steps"].append(limited)
    target[f"{field_name}_station_selection"] = limited


async def _fail_location_not_found_with_step(page, field_name: str, city_name: str, step: dict, diagnostics: dict | None, reason: str) -> None:
    step["failure_reason"] = reason
    step["station_selected"] = False
    step["current_textbox_value"] = await _textbox_value(step.get("textbox_ref")) if step.get("textbox_ref") is not None else None
    step.pop("textbox_ref", None)
    capture = step.pop("network_capture_ref", None)
    if capture is not None:
        capture.detach()
    await _save_step_artifact(page, f"{field_name}_selection_failed", step.get("artifacts_ref"))
    step.pop("artifacts_ref", None)
    await _finish_station_step(diagnostics, field_name, step)
    _station_log("station_selection_failed", step, len((step.get("autocomplete_discovery") or {}).get("containers", [])), len((step.get("autocomplete_discovery") or {}).get("options", [])))
    await _fail_location_not_found(page, field_name, city_name)



async def _active_element_snapshot(page) -> dict | None:
    try:
        return await page.evaluate("""() => { const el = document.activeElement; return el ? {tag_name: el.tagName.toLowerCase(), name: el.getAttribute('name'), id: el.id || null, class: el.getAttribute('class'), value: el.value || el.textContent || ''} : null; }""")
    except Exception:
        return None


async def _service_fields_snapshot(textbox, field_name: str) -> dict:
    class_hint = "from" if field_name == "origin" else "to"
    script = """
    (el, classHint) => {
        const safe = value => (value || '').toString().slice(0, 300);
        const root = el.closest('form') || el.closest('[class*=station]') || el.parentElement || document;
        const wanted = /(station.*(from|to)|schedule_station|data-station-id|station_id|station_code)/i;
        const nodes = Array.from(root.querySelectorAll('input[type=hidden], input[name], [data-station-id], [data-station-code]')).filter(node => {
            const attrs = [node.name, node.id, node.className, node.getAttribute('data-station-id'), node.getAttribute('data-station-code')].join(' ');
            return wanted.test(attrs) && (!/(from|to)/i.test(attrs) || new RegExp(classHint, 'i').test(attrs));
        }).slice(0, 20);
        return nodes.map((node, index) => ({index, name: safe(node.name), id: safe(node.id), class: safe(node.className), type: safe(node.type), value: safe(node.value), data_station_id: safe(node.getAttribute('data-station-id')), data_station_code: safe(node.getAttribute('data-station-code'))}));
    }
    """
    try:
        return {"fields": await textbox.evaluate(script, class_hint)}
    except Exception:
        return {"fields": []}


def _service_fields_changed(before: dict | None, after: dict | None) -> bool:
    return json.dumps(before or {}, sort_keys=True, ensure_ascii=False) != json.dumps(after or {}, sort_keys=True, ensure_ascii=False) and bool((after or {}).get("fields"))


async def _install_keyboard_event_counters(textbox) -> dict:
    try:
        return await textbox.evaluate("""el => {
            el.__tutuPwKeyboardCounters = {keydown:0, keyup:0, input:0, change:0};
            ['keydown','keyup','input','change'].forEach(type => el.addEventListener(type, () => { el.__tutuPwKeyboardCounters[type] += 1; }));
            return el.__tutuPwKeyboardCounters;
        }""")
    except Exception:
        return {"keydown": 0, "keyup": 0, "input": 0, "change": 0}


async def _keyboard_event_counters(textbox) -> dict:
    try:
        return await textbox.evaluate("el => el.__tutuPwKeyboardCounters || {keydown:0, keyup:0, input:0, change:0}")
    except Exception:
        return {"keydown": 0, "keyup": 0, "input": 0, "change": 0}


async def _clear_station_input(page, textbox):
    try:
        if hasattr(textbox, "click"):
            await textbox.click(timeout=3000)
        elif hasattr(textbox, "focus"):
            await textbox.focus()
    except Exception:
        pass
    try: await textbox.press("Control+A")
    except Exception: pass
    try: await textbox.press("Backspace")
    except Exception: pass
    try:
        value = await _textbox_value(textbox)
        if value:
            await textbox.evaluate("el => { const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set; setter ? setter.call(el, '') : (el.value = ''); el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); }")
    except Exception:
        if hasattr(textbox, "value"):
            textbox.value = ""


async def _dispatch_unicode_autocomplete_events(textbox, city_name: str, include_input: bool = True):
    if include_input:
        try:
            await textbox.dispatch_event("input")
        except Exception:
            try:
                await textbox.evaluate("el => el.dispatchEvent(new Event('input', {bubbles:true}))")
            except Exception:
                pass
    try:
        await textbox.dispatch_event("keyup", {"key": "Unidentified", "code": "", "keyCode": 0, "which": 0, "bubbles": True})
    except Exception:
        try:
            await textbox.evaluate("el => el.dispatchEvent(new KeyboardEvent('keyup', {key:'Unidentified', code:'', keyCode:0, which:0, bubbles:true}))")
        except Exception:
            pass


async def _apply_unicode_input_strategy(page, textbox, city_name: str, strategy: str):
    await _clear_station_input(page, textbox)
    if strategy == "keyboard.insert_text":
        await page.keyboard.insert_text(city_name)
        await _dispatch_unicode_autocomplete_events(textbox, city_name, include_input=True)
    elif strategy == "native_value_setter_input_event":
        await textbox.evaluate(
            """
            (el, value) => {
                const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')?.set
                    || Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')?.set;
                setter ? setter.call(el, value) : (el.value = value);
                el.dispatchEvent(new InputEvent('input', {bubbles:true, data:value, inputType:'insertText'}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
                el.dispatchEvent(new KeyboardEvent('keyup', {key:'Unidentified', bubbles:true}));
            }
            """,
            city_name,
        )
    elif strategy == "locator.fill_explicit_events":
        await textbox.fill(city_name)
        await _dispatch_unicode_autocomplete_events(textbox, city_name, include_input=True)
    elif strategy == "press_sequentially_latin":
        if hasattr(textbox, "press_sequentially"):
            await textbox.press_sequentially(city_name, delay=80)
        elif hasattr(textbox, "type"):
            await textbox.type(city_name, delay=80)
        else:
            await textbox.fill(city_name)
    else:
        raise ValueError(f"unknown input strategy: {strategy}")


async def _type_station_like_user(page, textbox, city_name: str, step: dict, network_capture: TutuAutocompleteNetworkCapture):
    await _install_keyboard_event_counters(textbox)
    step["active_element_before_typing"] = await _active_element_snapshot(page)
    strategies = ["keyboard.insert_text", "native_value_setter_input_event", "locator.fill_explicit_events"] if _is_cyrillic_text(city_name) else ["press_sequentially_latin", "keyboard.insert_text", "native_value_setter_input_event", "locator.fill_explicit_events"]
    failures = []
    for strategy in strategies:
        logger.info("tutu_unicode_input_strategy_started", extra={"field_name": step.get("field_name"), "requested_city": city_name, "strategy": strategy, "autocomplete_query_value": None, "query_matches_requested": None, "response_item_count": None})
        before_requests = len(network_capture.requests)
        network_capture.stage = strategy
        step["typing_strategy"] = strategy
        step["unicode_input_strategy"] = strategy
        try:
            await _apply_unicode_input_strategy(page, textbox, city_name, strategy)
            step["characters_typed"] = len(city_name)
            await asyncio.sleep(0.35)
            new_requests = network_capture.requests[before_requests:]
            malformed = next((r for r in new_requests if r.get("malformed_autocomplete_query")), None)
            matching = next((r for r in new_requests if r.get("autocomplete_query_matches_requested")), None)
            if malformed:
                logger.info("tutu_autocomplete_query_malformed", extra={"field_name": step.get("field_name"), "requested_city": city_name, "strategy": strategy, "autocomplete_query_value": malformed.get("autocomplete_query_value"), "query_matches_requested": False, "response_item_count": None})
                failures.append({"strategy": strategy, "failure_reason": "malformed_autocomplete_query", "autocomplete_query_value": malformed.get("autocomplete_query_value")})
                logger.info("tutu_unicode_input_strategy_failed", extra={"field_name": step.get("field_name"), "requested_city": city_name, "strategy": strategy, "autocomplete_query_value": malformed.get("autocomplete_query_value"), "query_matches_requested": False, "response_item_count": None})
                await _clear_station_input(page, textbox)
                await asyncio.sleep(0.1)
                continue
            if matching or not new_requests:
                logger.info("tutu_unicode_input_strategy_succeeded", extra={"field_name": step.get("field_name"), "requested_city": city_name, "strategy": strategy, "autocomplete_query_value": (matching or {}).get("autocomplete_query_value"), "query_matches_requested": bool(matching), "response_item_count": None})
                step["unicode_input_strategy_failures"] = failures
                break
        except Exception as exc:
            failures.append({"strategy": strategy, "failure_reason": type(exc).__name__})
            logger.info("tutu_unicode_input_strategy_failed", extra={"field_name": step.get("field_name"), "requested_city": city_name, "strategy": strategy, "autocomplete_query_value": None, "query_matches_requested": None, "response_item_count": None})
    for ch in city_name:
        logger.info("tutu_station_character_typed", extra={"field_name": step.get("field_name"), "requested_city": city_name, "character": ch})
    counters = await _keyboard_event_counters(textbox) or {}
    step["keydown_count"] = counters.get("keydown", 0); step["keyup_count"] = counters.get("keyup", 0); step["input_event_count"] = counters.get("input", 0); step["change_event_count"] = counters.get("change", 0)
    step["active_element_after_typing"] = await _active_element_snapshot(page)

async def select_location(page, textbox, city_name, field_name, artifacts: dict[str, list[str]] | None = None, diagnostics: dict | None = None):
    diagnostics = _ensure_station_diagnostics(diagnostics)
    step = {
        "requested_city": city_name,
        "field_name": field_name,
        "textbox_value_before_typing": None,
        "textbox_value_after_typing": None,
        "value_after_waiting_for_autocomplete": None,
        "value_after_clicking_suggestion": None,
        "value_after_blur": None,
        "station_selected": False,
        "failure_reason": None,
        "typing_strategy": None,
        "characters_typed": 0,
        "keydown_count": 0,
        "keyup_count": 0,
        "input_event_count": 0,
        "change_event_count": 0,
        "active_element_before_typing": None,
        "active_element_after_typing": None,
        "autocomplete_request_triggered": False,
        "service_fields_before_typing": None,
        "service_fields_after_typing": None,
        "service_fields_after_selection": None,
        "diagnostics_redaction_applied": True,
        "clicked_candidate": None,
        "textbox_ref": textbox,
        "artifacts_ref": artifacts,
    }
    network_capture = TutuAutocompleteNetworkCapture(page, field_name, city_name).attach()
    step["network_capture_ref"] = network_capture
    _station_log("station_selection_started", step)
    await _save_step_artifact(page, f"{field_name}_before_typing", artifacts)
    try:
        await textbox.focus()
    except Exception:
        pass
    step["textbox_value_before_typing"] = await _textbox_value(textbox)
    _station_log("station_selection_step", {**step, "current_textbox_value": step["textbox_value_before_typing"]})

    step["service_fields_before_typing"] = await _service_fields_snapshot(textbox, field_name)
    await _type_station_like_user(page, textbox, city_name, step, network_capture)
    step["textbox_value_after_typing"] = await _textbox_value(textbox)
    step["service_fields_after_typing"] = await _service_fields_snapshot(textbox, field_name)
    await _save_step_artifact(page, f"{field_name}_after_typing", artifacts)
    _station_log("station_selection_step", {**step, "current_textbox_value": step["textbox_value_after_typing"]})

    network_capture.stage = "after_waiting"
    deadline = time.monotonic() + LOCATION_AUTOCOMPLETE_TIMEOUT_MS / 1000
    options = None
    count = 0
    while time.monotonic() < deadline:
        options = await _candidate_options_for_input(page, textbox, field_name)
        count = await _visible_locator_count(options)
        if count:
            break
        if network_capture.requests or _service_fields_changed(step.get("service_fields_before_typing"), await _service_fields_snapshot(textbox, field_name)):
            break
        await asyncio.sleep(0.2)
    step["value_after_waiting_for_autocomplete"] = await _textbox_value(textbox)
    discovery = await collect_autocomplete_discovery(page, field_name, city_name)
    step["autocomplete_discovery"] = discovery
    if diagnostics is not None:
        diagnostics["autocomplete_discovery"][field_name] = discovery
    await _save_step_artifact(page, f"{field_name}_after_waiting", artifacts)
    _station_log("station_selection_step", {**step, "current_textbox_value": step["value_after_waiting_for_autocomplete"]}, len(discovery.get("containers", [])), len(discovery.get("options", [])))

    candidates = []
    if options is not None:
        total = await _locator_count(options)
        for index in range(total):
            option = options.nth(index)
            try:
                if not await option.is_visible(timeout=200):
                    continue
                text = (await option.inner_text(timeout=1000)).strip()
            except Exception:
                continue
            if text:
                rank, matched = location_matches(text, city_name)
                candidates.append((rank, index, text, option, matched))
    popup_texts = await inspect_popup_candidates(page, textbox, field_name, city_name)
    candidate_texts = [c[2] for c in candidates]
    popup_payload = discovery.get("options") or discovery.get("containers") or candidate_texts or popup_texts
    if diagnostics is not None:
        diagnostics.setdefault("popup_candidates", {})[field_name] = _limit_diagnostic(popup_payload)
    step["popup_candidates"] = _limit_diagnostic(popup_payload)
    logger.info("autocomplete candidate texts", extra={"field_name": field_name, "city_name": city_name, "candidate_texts": candidate_texts})
    network_payload = network_capture.diagnostics(popup_rendered=bool(count or candidates or (discovery.get("options") or [])))
    step.update(network_payload)
    step["autocomplete_request_triggered"] = bool((network_payload.get("network_summary") or {}).get("relevant_requests"))
    observed_queries = [r.get("autocomplete_query_value") for r in network_payload.get("autocomplete_requests", []) if r.get("autocomplete_query_value") is not None]
    matching_queries = [r for r in network_payload.get("autocomplete_requests", []) if r.get("autocomplete_query_matches_requested")]
    malformed_queries = [r for r in network_payload.get("autocomplete_requests", []) if r.get("malformed_autocomplete_query")]
    step["requested_city"] = city_name
    step["textbox_value"] = step.get("value_after_waiting_for_autocomplete") or step.get("textbox_value_after_typing")
    step["autocomplete_query_value"] = (matching_queries[-1].get("autocomplete_query_value") if matching_queries else (observed_queries[-1] if observed_queries else None))
    step["autocomplete_query_matches_requested"] = bool(matching_queries)
    step["malformed_autocomplete_query"] = bool(malformed_queries)
    if step["malformed_autocomplete_query"]:
        logger.info("tutu_autocomplete_query_malformed", extra={"field_name": field_name, "requested_city": city_name, "strategy": step.get("unicode_input_strategy"), "autocomplete_query_value": (malformed_queries[-1] or {}).get("autocomplete_query_value"), "query_matches_requested": False, "response_item_count": None})
    if step["autocomplete_request_triggered"]:
        logger.info("tutu_autocomplete_request_triggered", extra={"field_name": field_name, "requested_city": city_name})
    else:
        logger.info("tutu_autocomplete_not_triggered", extra={"field_name": field_name, "requested_city": city_name})
    if diagnostics is not None:
        diagnostics["network_events"][field_name] = _limit_diagnostic(network_payload["network_events"])
        diagnostics["autocomplete_requests"][field_name] = _limit_diagnostic(network_payload["autocomplete_requests"])
        diagnostics["autocomplete_responses"][field_name] = _limit_diagnostic(network_payload["autocomplete_responses"])
        diagnostics["autocomplete_request_failures"][field_name] = _limit_diagnostic(network_payload["autocomplete_request_failures"])
        diagnostics["network_summary"][field_name] = _limit_diagnostic(network_payload["network_summary"])

    if step.get("malformed_autocomplete_query") or (_popular_city_response_without_requested(network_payload.get("autocomplete_responses", []), city_name) and not step.get("autocomplete_query_matches_requested")):
        await _fail_location_not_found_with_step(page, field_name, city_name, step, diagnostics, "malformed_autocomplete_query")

    if not count and not candidates:
        await _fail_location_not_found_with_step(page, field_name, city_name, step, diagnostics, "autocomplete_not_opened")

    matches = sorted((c for c in candidates if c[4]), key=lambda c: (c[0], c[1]))
    if matches:
        rank, _index, text, option, _matched = matches[0]
        step["clicked_candidate"] = text
        logger.info("tutu_station_option_found", extra={"field_name": field_name, "requested_city": city_name, "selected_candidate": text})
        network_capture.stage = "before_click"
        await _save_step_artifact(page, f"{field_name}_before_click", artifacts)
        await option.click(timeout=LOCATION_AUTOCOMPLETE_TIMEOUT_MS)
        network_capture.stage = "after_click"
        logger.info("station_candidate_selected", extra={"field_name": field_name, "city_name": city_name, "requested_city": city_name, "selected_candidate": text, "match_rank": rank, "current_textbox_value": await _textbox_value(textbox), "popup_count": len(discovery.get("containers", [])), "option_count": len(discovery.get("options", [])), "failure_reason": None})
        step["value_after_clicking_suggestion"] = await _textbox_value(textbox)
        step["service_fields_after_selection"] = await _service_fields_snapshot(textbox, field_name)
        await _save_step_artifact(page, f"{field_name}_after_click", artifacts)
    else:
        network_capture.stage = "before_click"
        await _save_step_artifact(page, f"{field_name}_before_click", artifacts)
        await _fail_location_not_found_with_step(page, field_name, city_name, step, diagnostics, "matching_candidate_not_found")

    network_capture.detach()
    try:
        await textbox.blur()
    except Exception:
        try:
            await page.locator("body").click(timeout=1000)
        except Exception:
            pass
    step["value_after_blur"] = await _textbox_value(textbox)
    final_value = step["value_after_blur"] or step["value_after_clicking_suggestion"] or ""
    clicked_norm = normalize_location_text(step.get("clicked_candidate") or "")
    final_norm = normalize_location_text(final_value)
    city_norm = normalize_location_text(city_name)
    clicked_persisted = not clicked_norm or clicked_norm == final_norm or clicked_norm in final_norm
    city_persisted = city_norm in final_norm or final_norm in city_norm
    if not clicked_persisted or not city_persisted:
        await _fail_location_not_found_with_step(page, field_name, city_name, step, diagnostics, "selected_value_not_persisted")
    closed = await _autocomplete_is_closed(page)
    service_changed = _service_fields_changed(step.get("service_fields_before_typing"), step.get("service_fields_after_selection"))
    option_clicked = bool(step.get("clicked_candidate"))
    if not (option_clicked or service_changed):
        await _fail_location_not_found_with_step(page, field_name, city_name, step, diagnostics, "selection_not_confirmed")
    step["selection_confirmation"] = "option_clicked_and_popup_closed" if option_clicked and closed else ("hidden_station_field_changed" if service_changed else "option_clicked")
    step["station_selected"] = True
    step.pop("textbox_ref", None)
    step.pop("artifacts_ref", None)
    step.pop("network_capture_ref", None)
    network_capture.detach()
    await _finish_station_step(diagnostics, field_name, step)
    _station_log("tutu_station_selection_verified", {**step, "current_textbox_value": final_value}, len(discovery.get("containers", [])), len(discovery.get("options", [])))
    return final_value

class TTLCache:
    def __init__(self, ttl:int): self.ttl=ttl; self.items={}
    def get(self,k):
        v=self.items.get(k)
        if not v: return None
        t,r=v
        if time.time()-t>self.ttl: self.items.pop(k,None); return None
        return r
    def set(self,k,v): self.items[k]=(time.time(),v)

class TutuAvailabilityService:
    def __init__(self):
        self.sem=asyncio.Semaphore(max(1, settings.concurrency)); self.cache=TTLCache(settings.cache_ttl_seconds); self._browser=None; self._pw=None
        Path(settings.artifact_dir).mkdir(parents=True, exist_ok=True)
    def key(self, req): return hashlib.sha256(req.model_dump_json().encode()).hexdigest()
    async def check(self, req: AvailabilityCheckRequest) -> AvailabilityCheckResponse:
        k=self.key(req); cached=self.cache.get(k)
        if cached:
            logger.info("response returned", extra={"source": "cache", "status": cached.status.value, "matched_train": cached.matched_train, "train_number": cached.train_number})
            return cached
        if not req.train_number:
            logger.info("early exit condition observed", extra={"reason": "missing train number", "will_exit_early": False})
        logger.info("configuration", extra={"enabled": settings.enabled, "mock_mode": settings.mock_mode, "timeout_seconds": settings.timeout_seconds, "operation_timeout_seconds": settings.operation_timeout_seconds, "concurrency": settings.concurrency})
        if settings.mock_mode or not settings.enabled:
            logger.info("early exit condition observed", extra={"reason": "disabled enrichment" if settings.mock_mode else "configuration", "mock_mode": settings.mock_mode, "enabled": settings.enabled})
        async with self.sem:
            try:
                res= await asyncio.wait_for(self._mock(req) if settings.mock_mode or not settings.enabled else self._playwright(req), timeout=settings.timeout_seconds)
            except asyncio.TimeoutError:
                logger.exception("availability check caught exception", extra={"reason": "timeout", "timeout_seconds": settings.timeout_seconds})
                logger.info("early exit condition observed", extra={"reason": "timeout"})
                res=AvailabilityCheckResponse(status=AvailabilityStatus.PROVIDER_ERROR, train_number=req.train_number, message="Tutu availability check timed out")
            except Exception as exc:
                logger.exception("availability check caught exception", extra={"reason": "provider_error"})
                diagnostics = exc.diagnostics if isinstance(exc, TutuDiagnosticError) else Diagnostics()
                res=AvailabilityCheckResponse(status=AvailabilityStatus.PROVIDER_ERROR, train_number=req.train_number, message="Tutu provider error", warnings=[str(exc), "Tutu route field diagnostics are included when available; seats were not confirmed"], diagnostics=diagnostics)
            self.cache.set(k,res); return res
    async def check_journey(self, segments):
        results=[await self.check(s) for s in segments]
        statuses={r.status for r in results}
        status=AvailabilityStatus.CONFIRMED if results and all(r.status==AvailabilityStatus.CONFIRMED for r in results) else (AvailabilityStatus.UNAVAILABLE if AvailabilityStatus.UNAVAILABLE in statuses else (AvailabilityStatus.PROVIDER_ERROR if AvailabilityStatus.PROVIDER_ERROR in statuses else AvailabilityStatus.PARTIALLY_CONFIRMED))
        return JourneyAvailabilityResponse(status=status, segments=results)
    async def _mock(self, req):
        if req.train_number and req.train_number.upper().startswith("NO"):
            logger.info("early exit condition observed", extra={"reason": "unsupported request", "train_number": req.train_number})
            return AvailabilityCheckResponse(status=AvailabilityStatus.UNKNOWN, matched_train=False, train_number=req.train_number, message="Mock: train was not found")
        places=[str(i*2+1) for i in range(req.passengers)] if req.berth_preference=="lower_only" else [str(i+1) for i in range(req.passengers)]
        return AvailabilityCheckResponse(status=AvailabilityStatus.CONFIRMED, matched_train=True, train_number=req.train_number, available_seats=max(req.passengers,4), selected_places=places, selected_carriages=["5"], selected_compartments=["1"], transport_class=(req.preferred_classes[0] if req.preferred_classes else "coupe"), same_carriage=True, same_compartment=req.require_same_compartment, lower_berths_confirmed=req.berth_preference=="lower_only", message="Mock: availability confirmed", diagnostics=Diagnostics(matched_by="train_number+departure_time", page_url="https://www.tutu.ru/poezda/"))
    async def _browser_instance(self):
        try:
            if not self._pw: self._pw=await async_playwright().start()
            if not self._browser:
                logger.info("browser launch started", extra={"headless": settings.headless})
                self._browser=await self._pw.chromium.launch(headless=settings.headless)
                logger.info("browser launched")
            return self._browser
        except Exception:
            logger.exception("browser startup failure")
            logger.info("early exit condition observed", extra={"reason": "browser startup failure"})
            raise
    async def restart(self):
        if self._browser: await self._browser.close(); self._browser=None
    async def _playwright(self, req):
        browser=await self._browser_instance(); context=await browser.new_context(locale="ru-RU"); page=await context.new_page(); logger.info("page opened", extra={"locale": "ru-RU"}); page.set_default_timeout(settings.operation_timeout_seconds*1000)
        shots=[]; htmls=[]; diagnostic_payload={"selected_inputs": {}, "station_steps": [], "origin_station_selection": {}, "destination_station_selection": {}, "popup_candidates": {}, "autocomplete_discovery": {}, "network_events": {}, "autocomplete_requests": {}, "autocomplete_responses": {}, "autocomplete_request_failures": {}, "network_summary": {}}
        try:
            logger.info("navigating to tutu.ru", extra={"url": "https://www.tutu.ru/poezda/"})
            await page.goto("https://www.tutu.ru/poezda/", wait_until="domcontentloaded")
            frame_infos = [{"url": frame.url, "name": frame.name} for frame in page.frames]
            logger.info("tutu frame inventory", extra={"frame_count": len(frame_infos), "frames": frame_infos})
            if len(page.frames) > 1:
                logger.info("tutu search widget iframe candidates detected", extra={"frames": frame_infos})
            await _save_step_artifact(page, "before_filling_origin", {"screenshots": shots, "html_artifacts": htmls})

            # Public UI only. Inputs are selected from live DOM metadata rather than positional textboxes.
            origin_input, origin_meta, _ = await detect_station_input(page, "origin")
            origin_meta["dom_identity"] = await _element_identity(origin_input)
            diagnostic_payload["selected_inputs"]["origin"] = origin_meta
            await select_location(page, origin_input, req.origin, "origin", {"screenshots": shots, "html_artifacts": htmls}, diagnostic_payload)
            await page.wait_for_timeout(500)

            destination_input, destination_meta, _ = await detect_station_input(page, "destination")
            diagnostic_payload["form_reacquired_after_origin"] = True
            logger.info("station_input_reacquired", extra={"field_name": "destination", "after_field": "origin"})
            destination_meta["dom_identity"] = await _element_identity(destination_input)
            diagnostic_payload["selected_inputs"]["destination"] = destination_meta
            if await _same_element(origin_input, destination_input):
                diagnostic_payload["origin_destination_same_element"] = True
                diagnostic_payload["field_resolution_collision"] = {"reason": "destination_resolved_to_origin", "origin": origin_meta, "destination": destination_meta}
                logger.info("station_input_collision", extra={"field_name": "destination", "failure_reason": "field_resolution_collision", "origin_input": origin_meta, "destination_input": destination_meta})
                raise ValueError("field_resolution_collision")
            try:
                await select_location(page, destination_input, req.destination, "destination", {"screenshots": shots, "html_artifacts": htmls}, diagnostic_payload)
            except Exception:
                await _save_step_artifact(page, "destination_selection_failed", {"screenshots": shots, "html_artifacts": htmls})
                raise
            origin_verify, origin_verify_meta, _ = await detect_station_input(page, "origin")
            destination_verify, destination_verify_meta, _ = await detect_station_input(page, "destination")
            diagnostic_payload["selected_inputs"]["origin"] = {**origin_verify_meta, "dom_identity": await _element_identity(origin_verify)}
            diagnostic_payload["selected_inputs"]["destination"] = {**destination_verify_meta, "dom_identity": await _element_identity(destination_verify)}
            same_final = await _same_element(origin_verify, destination_verify)
            diagnostic_payload["origin_destination_same_element"] = same_final
            diagnostic_payload["final_origin_value"] = await _textbox_value(origin_verify)
            diagnostic_payload["final_destination_value"] = await _textbox_value(destination_verify)
            logger.info("route_fields_verified", extra={"origin": diagnostic_payload["final_origin_value"], "destination": diagnostic_payload["final_destination_value"], "origin_destination_same_element": same_final})
            if same_final:
                raise ValueError("origin_destination_same_element")
            if normalize_location_text(req.origin) not in normalize_location_text(diagnostic_payload["final_origin_value"]) or normalize_location_text(req.destination) not in normalize_location_text(diagnostic_payload["final_destination_value"]):
                raise ValueError("route_fields_verified_failed")
            logger.info("search form filled", extra={"origin": req.origin, "destination": req.destination, "departure_date": req.departure_date.isoformat()})
            await page.get_by_role("button", name="Найти", exact=False).click()
            logger.info("search submitted")
            await page.get_by_text(req.train_number or "", exact=False).first.wait_for(timeout=15000)
            logger.info("search results received", extra={"page_url": page.url})
            text=await page.locator("body").inner_text()
            matched=bool(req.train_number and req.train_number in text)
            logger.info("journey matched", extra={"matched_train": matched, "train_number": req.train_number})
            logger.info("seat availability extraction started")
            logger.info("seat availability extracted", extra={"available_seats": None})
            return AvailabilityCheckResponse(status=AvailabilityStatus.UNKNOWN, matched_train=matched, train_number=req.train_number, message="Tutu UI parsed; detailed seat extraction requires current markup", warnings=["Tutu diagnostic metadata includes selected route inputs and autocomplete candidates"], diagnostics=Diagnostics(**_diagnostics_model_kwargs(diagnostic_payload, page.url, shots, htmls, "train_number" if matched else None)))
        except Exception as exc:
            stamp=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            sp=os.path.join(settings.artifact_dir,f"error-{stamp}.png"); hp=os.path.join(settings.artifact_dir,f"error-{stamp}.html")
            try: await page.screenshot(path=sp, full_page=True); Path(hp).write_text(await page.content(), encoding="utf-8"); shots.append(sp); htmls.append(hp)
            except Exception:
                logger.exception("artifact capture caught exception")
            logger.exception("playwright availability caught exception", extra={"screenshots": shots, "html_artifacts": htmls, "selected_inputs": diagnostic_payload["selected_inputs"], "popup_candidates": diagnostic_payload["popup_candidates"]})
            raise TutuDiagnosticError(str(exc), Diagnostics(**_diagnostics_model_kwargs(diagnostic_payload, page.url, shots, htmls))) from exc
        finally:
            await context.close()
service=TutuAvailabilityService()
