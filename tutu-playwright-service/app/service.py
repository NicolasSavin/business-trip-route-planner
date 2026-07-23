from __future__ import annotations
import asyncio, hashlib, json, logging, os, re, time
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


async def _autocomplete_is_closed(page) -> bool:
    options = await _candidate_options(page)
    return await _visible_locator_count(options) == 0


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


async def detect_route_input(page, field_name: str):
    inventory = await inspect_textboxes(page)
    labels = ROUTE_FIELD_LABELS[field_name]
    scored = []
    for item in inventory:
        haystack = " ".join(str(item.get(k) or "") for k in ("name", "id", "placeholder", "aria_label", "ancestor_form_text") ) + " " + " ".join(item.get("nearby_label_text") or [])
        haystack = haystack.lower()
        score = sum(10 for label in labels if label in haystack)
        if "поезд" in haystack or "ж/д" in haystack or "poezd" in haystack or "train" in haystack:
            score += 3
        if item.get("visible"):
            score += 2
        if item.get("enabled") and item.get("editable"):
            score += 2
        if score:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["index"]))
    if not scored:
        logger.info("tutu route input semantic detection failed", extra={"field_name": field_name, "inventory": inventory})
        raise ValueError(f"Tutu route {field_name} input not found")
    selected = scored[0][1]
    logger.info("tutu route input selected", extra={"field_name": field_name, "score": scored[0][0], "selected_input": selected})
    return page.locator("input, textarea, [role='textbox'], [contenteditable='true']").nth(selected["index"]), selected, inventory


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
    await _save_step_artifact(page, f"{field_name}_selection_failed", step.get("artifacts_ref"))
    step.pop("artifacts_ref", None)
    await _finish_station_step(diagnostics, field_name, step)
    _station_log("station_selection_failed", step, len((step.get("autocomplete_discovery") or {}).get("containers", [])), len((step.get("autocomplete_discovery") or {}).get("options", [])))
    await _fail_location_not_found(page, field_name, city_name)


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
        "clicked_candidate": None,
        "textbox_ref": textbox,
        "artifacts_ref": artifacts,
    }
    _station_log("station_selection_started", step)
    await _save_step_artifact(page, f"{field_name}_before_typing", artifacts)
    try:
        await textbox.focus()
    except Exception:
        pass
    step["textbox_value_before_typing"] = await _textbox_value(textbox)
    _station_log("station_selection_step", {**step, "current_textbox_value": step["textbox_value_before_typing"]})

    await textbox.fill(city_name)
    try:
        await textbox.evaluate("""(el, value) => { el.value = value; el.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertText', data: value})); el.dispatchEvent(new Event('change', {bubbles: true})); }""", city_name)
    except Exception:
        pass
    step["textbox_value_after_typing"] = await _textbox_value(textbox)
    await _save_step_artifact(page, f"{field_name}_after_typing", artifacts)
    _station_log("station_selection_step", {**step, "current_textbox_value": step["textbox_value_after_typing"]})

    deadline = time.monotonic() + LOCATION_AUTOCOMPLETE_TIMEOUT_MS / 1000
    options = None
    count = 0
    while time.monotonic() < deadline:
        options = await _candidate_options(page)
        count = await _visible_locator_count(options)
        if count:
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

    if not count and not candidates:
        await _fail_location_not_found_with_step(page, field_name, city_name, step, diagnostics, "autocomplete_not_opened")

    matches = sorted((c for c in candidates if c[4]), key=lambda c: (c[0], c[1]))
    if matches:
        rank, _index, text, option, _matched = matches[0]
        step["clicked_candidate"] = text
        await _save_step_artifact(page, f"{field_name}_before_click", artifacts)
        await option.click(timeout=LOCATION_AUTOCOMPLETE_TIMEOUT_MS)
        logger.info("station_candidate_selected", extra={"field_name": field_name, "city_name": city_name, "requested_city": city_name, "selected_candidate": text, "match_rank": rank, "current_textbox_value": await _textbox_value(textbox), "popup_count": len(discovery.get("containers", [])), "option_count": len(discovery.get("options", [])), "failure_reason": None})
        step["value_after_clicking_suggestion"] = await _textbox_value(textbox)
        await _save_step_artifact(page, f"{field_name}_after_click", artifacts)
    else:
        await _save_step_artifact(page, f"{field_name}_before_click", artifacts)
        await _fail_location_not_found_with_step(page, field_name, city_name, step, diagnostics, "matching_candidate_not_found")

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
    step["station_selected"] = True
    step.pop("textbox_ref", None)
    step.pop("artifacts_ref", None)
    await _finish_station_step(diagnostics, field_name, step)
    _station_log("station_selection_finished", {**step, "current_textbox_value": final_value}, len(discovery.get("containers", [])), len(discovery.get("options", [])))
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
        logger.info("configuration", extra={"enabled": settings.enabled, "mock_mode": settings.mock_mode, "timeout_seconds": settings.timeout_seconds, "concurrency": settings.concurrency})
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
        browser=await self._browser_instance(); context=await browser.new_context(locale="ru-RU"); page=await context.new_page(); logger.info("page opened", extra={"locale": "ru-RU"}); page.set_default_timeout(settings.timeout_seconds*1000)
        shots=[]; htmls=[]; diagnostic_payload={"selected_inputs": {}, "station_steps": [], "origin_station_selection": {}, "destination_station_selection": {}, "popup_candidates": {}, "autocomplete_discovery": {}}
        try:
            logger.info("navigating to tutu.ru", extra={"url": "https://www.tutu.ru/poezda/"})
            await page.goto("https://www.tutu.ru/poezda/", wait_until="domcontentloaded")
            frame_infos = [{"url": frame.url, "name": frame.name} for frame in page.frames]
            logger.info("tutu frame inventory", extra={"frame_count": len(frame_infos), "frames": frame_infos})
            if len(page.frames) > 1:
                logger.info("tutu search widget iframe candidates detected", extra={"frames": frame_infos})
            await _save_step_artifact(page, "before_filling_origin", {"screenshots": shots, "html_artifacts": htmls})

            # Public UI only. Inputs are selected from live DOM metadata rather than positional textboxes.
            origin_input, origin_meta, _ = await detect_route_input(page, "origin")
            diagnostic_payload["selected_inputs"]["origin"] = origin_meta
            await select_location(page, origin_input, req.origin, "origin", {"screenshots": shots, "html_artifacts": htmls}, diagnostic_payload)

            destination_input, destination_meta, _ = await detect_route_input(page, "destination")
            diagnostic_payload["selected_inputs"]["destination"] = destination_meta
            try:
                await select_location(page, destination_input, req.destination, "destination", {"screenshots": shots, "html_artifacts": htmls}, diagnostic_payload)
            except Exception:
                await _save_step_artifact(page, "destination_selection_failed", {"screenshots": shots, "html_artifacts": htmls})
                raise
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
            return AvailabilityCheckResponse(status=AvailabilityStatus.UNKNOWN, matched_train=matched, train_number=req.train_number, message="Tutu UI parsed; detailed seat extraction requires current markup", warnings=["Tutu diagnostic metadata includes selected route inputs and autocomplete candidates"], diagnostics=Diagnostics(matched_by="train_number" if matched else None, page_url=page.url, screenshots=shots, html_artifacts=htmls, selected_inputs=diagnostic_payload["selected_inputs"], station_steps=diagnostic_payload["station_steps"], origin_station_selection=diagnostic_payload["origin_station_selection"], destination_station_selection=diagnostic_payload["destination_station_selection"], popup_candidates=diagnostic_payload["popup_candidates"], autocomplete_discovery=diagnostic_payload["autocomplete_discovery"]))
        except Exception as exc:
            stamp=datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            sp=os.path.join(settings.artifact_dir,f"error-{stamp}.png"); hp=os.path.join(settings.artifact_dir,f"error-{stamp}.html")
            try: await page.screenshot(path=sp, full_page=True); Path(hp).write_text(await page.content(), encoding="utf-8"); shots.append(sp); htmls.append(hp)
            except Exception:
                logger.exception("artifact capture caught exception")
            logger.exception("playwright availability caught exception", extra={"screenshots": shots, "html_artifacts": htmls, "selected_inputs": diagnostic_payload["selected_inputs"], "popup_candidates": diagnostic_payload["popup_candidates"]})
            raise TutuDiagnosticError(str(exc), Diagnostics(page_url=page.url, screenshots=shots, html_artifacts=htmls, selected_inputs=diagnostic_payload["selected_inputs"], station_steps=diagnostic_payload["station_steps"], origin_station_selection=diagnostic_payload["origin_station_selection"], destination_station_selection=diagnostic_payload["destination_station_selection"], popup_candidates=diagnostic_payload["popup_candidates"], autocomplete_discovery=diagnostic_payload["autocomplete_discovery"])) from exc
        finally:
            await context.close()
service=TutuAvailabilityService()
