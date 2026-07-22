from __future__ import annotations

import re
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

from app.browser import BrowserConfiguration, BrowserManager, BrowserPool, BrowserSession
from app.providers.tutu.playwright.models import SeatAvailability, TutuPlaywrightResult, TutuPlaywrightSearchRequest


RU_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}


class TutuPlaywrightClient:
    home_url = "https://www.tutu.ru/"
    selectors = {
        "cookie_buttons": ["role=button|Принять", "role=button|Согласен", "role=button|Понятно", "[data-ti='accept-cookies']"],
        "railway_tab": ["role=tab|Ж/д", "role=button|Ж/д", "role=link|Ж/д билеты", "text=Ж/д"],
        "origin_input": ["label=Откуда", "placeholder=Откуда", "role=combobox|Откуда", "role=textbox|Откуда", "input[name='st1']", "input[placeholder*='Откуда']", "input[aria-label*='Откуда']"],
        "destination_input": ["label=Куда", "placeholder=Куда", "role=combobox|Куда", "role=textbox|Куда", "input[name='st2']", "input[placeholder*='Куда']", "input[aria-label*='Куда']"],
        "calendar_containers": ["role=dialog|", "[role='dialog']:visible", "[class*='calendar' i]:visible", "[data-testid*='calendar' i]:visible", "[data-ti*='calendar' i]:visible"],
        "search_button": ["role=button|Найти поезд", "role=button|Найти", "button:has-text('Найти поезд')", "button:has-text('Найти')", "button[type='submit']"],
        "results_containers": ["main:has-text('Выберите поезд')", "main:has-text('поезд')", "[data-testid*='result' i]", "[data-ti*='result' i]", "[class*='result' i]"],
        "result_cards": ["article:visible", "[data-testid*='train' i]:visible", "[data-ti*='train' i]:visible", "[class*='train' i]:visible", "[class*='card' i]:visible"],
    }

    def __init__(self, pool: BrowserPool | None = None) -> None:
        self.pool = pool or BrowserPool(BrowserManager(config=BrowserConfiguration.from_env().with_playwright_enabled()))
        self.session: BrowserSession | None = None
        self.page: Any | None = None
        self._last_request: TutuPlaywrightSearchRequest | None = None
        self.diagnostics: dict[str, Any] = {"origin_selected": False, "destination_selected": False, "date_control_found": False, "calendar_opened": False, "target_month_reached": False, "date_selected": False, "search_button_clicked": False, "search_submitted": False}

    async def open_home(self) -> None:
        self.session = await self.pool.acquire()
        self.page = await self.session.new_page()
        await self.session.navigate(self.home_url)
        await self.page.wait_for_load_state("domcontentloaded")
        await self._close_cookie_popup()
        await self._ensure_railway_tab()
        self._record("opened_home", url=self.page.url, title=await self.page.title())

    async def search(self, origin: str, destination: str, date: date, passengers: int = 1) -> None:
        if self.page is None:
            await self.open_home()
        assert self.page is not None
        self._last_request = TutuPlaywrightSearchRequest(origin=origin, destination=destination, date=date, passengers=passengers)
        if not await self._fill_station("origin_input", origin):
            self.diagnostics["stage"] = "origin_selection_failed"; return
        if not await self._fill_station("destination_input", destination):
            self.diagnostics["stage"] = "destination_selection_failed"; return
        if not await self._select_date(date):
            return
        if not await self._submit_search():
            return
        await self.wait_results()

    async def wait_results(self) -> None:
        assert self.page is not None
        self._record("results_wait_started")
        start_url = self.page.url
        deadline = datetime.utcnow() + timedelta(seconds=60)
        while datetime.utcnow() < deadline:
            if self.page.url != start_url or re.search(r"railway|train|tickets|search", self.page.url, re.I):
                self._record("url_changed", url=self.page.url)
            if await self._has_visible_text(r"ничего не найдено|нет поездов|билетов нет"):
                self._record("no_results_visible"); self._record("results_page_loaded"); return
            if await self._results_signal_visible():
                self._record("results_container_visible"); self._record("results_page_loaded"); return
            if await self._has_visible_text(r"загрузка|ищем|подождите"):
                self._record("loading_visible")
            await self.page.wait_for_timeout(1000)
        self._record("results_wait_timeout"); self.diagnostics["stage"] = "results_timeout"; await self._save_artifact("results_timeout", html=True, screenshot=True)

    async def parse_results(self) -> list[TutuPlaywrightResult]:
        if self.page is None:
            raise RuntimeError("Tutu page is not opened")
        request = self._last_request
        parsed: list[dict[str, Any]] = []
        container = await self._results_container()
        for selector in self.selectors["result_cards"]:
            try:
                loc = container.locator(selector)
                for index in range(min(await loc.count(), 60)):
                    item = loc.nth(index)
                    if await item.is_visible():
                        text = self._clean_text(await item.inner_text(timeout=2000))
                        if self._looks_like_route_card(text):
                            parsed.append({"text": text, "selector": selector})
                if parsed:
                    break
            except Exception as exc:
                self._record("parse_selector_error", selector=selector, error=str(exc)[:200])
        self._record("visible_cards_parsed", count=len(parsed), samples=[p["text"][:180] for p in parsed[:3]])
        results: list[TutuPlaywrightResult] = []
        seen: set[tuple[str, datetime, datetime]] = set()
        for item in parsed:
            result = self._parse_card(item, request)
            if result is not None:
                key = (result.train_number, result.departure, result.arrival)
                if key not in seen:
                    results.append(result); seen.add(key)
        self._record("valid_route_cards_found", count=len(results))
        if not results:
            self.diagnostics.setdefault("stage", "result_cards_not_found")
            await self._save_artifact("result_cards_not_found", html=True, screenshot=True)
        return results

    async def live_test(self, origin: str, destination: str, departure_date: date) -> dict[str, Any]:
        try:
            await self.open_home(); await self.search(origin, destination, departure_date); results = await self.parse_results()
            return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "routes_found": len(results), "routes": [self._route_json(r) for r in results], "diagnostics": self.diagnostics | await self._page_diagnostics()}
        except Exception as exc:
            self._record("error", type=exc.__class__.__name__, message=str(exc)); self.diagnostics["stage"] = "runtime_error"
            return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "routes_found": 0, "routes": [], "diagnostics": self.diagnostics | await self._page_diagnostics()}
        finally:
            await self.close()

    async def close(self) -> None:
        if self.session is not None:
            await self.pool.release(self.session)
        self.session = None; self.page = None

    async def _fill_station(self, key: str, value: str) -> bool:
        assert self.page is not None
        form = await self._railway_form()
        loc = await self._locator_first(self.selectors[key], field=key, root=form)
        if loc is None: return False
        await loc.click(); await loc.press("Control+A"); await loc.type(value, delay=40)
        if not await self._wait_suggestions(value):
            await self._save_artifact(f"{key}_suggestions_not_found", html=True, screenshot=True); return False
        event_open = "origin_suggestions_opened" if key == "origin_input" else "destination_suggestions_opened"
        event_selected = "origin_selected" if key == "origin_input" else "destination_selected"
        self._record(event_open, value=value)
        option = await self._suggestion_locator(value)
        if option is None: return False
        await option.click()
        await self.page.wait_for_timeout(500)
        ok = await self._input_contains(loc, value)
        if ok:
            self.diagnostics[event_selected] = True; self._record(event_selected, value=value)
        return ok

    async def _select_date(self, value: date) -> bool:
        assert self.page is not None
        form = await self._railway_form()
        control = await self._date_control(form)
        if control is None:
            self.diagnostics["stage"] = "date_control_not_found"; await self._save_artifact("date_control_not_found", html=True, screenshot=True); return False
        self.diagnostics["date_control_found"] = True; self._record("date_control_found", strategy="dom_interactive_probe")
        calendar = await self._wait_calendar_open()
        if calendar is None:
            self.diagnostics["stage"] = "calendar_open_failed"; await self._save_artifact("calendar_open_failed", html=True, screenshot=True); return False
        if not await self._navigate_calendar_to(value, calendar): return False
        if not await self._click_calendar_date(value, calendar): return False
        self._record("requested_date_clicked", value=value.isoformat())
        if not await self._verify_date_displayed(value):
            self.diagnostics["stage"] = "date_verification_failed"; await self._save_artifact("date_verification_failed", html=True, screenshot=True); return False
        return True

    async def _wait_calendar_open(self) -> Any | None:
        assert self.page is not None
        deadline = datetime.utcnow() + timedelta(seconds=8)
        while datetime.utcnow() < deadline:
            for selector in self.selectors["calendar_containers"]:
                try:
                    loc = self._build_locator(selector)
                    if await loc.count() and await loc.first.is_visible(timeout=500):
                        self.diagnostics["calendar_opened"] = True; self._record("calendar_opened", selector=selector); return loc.first
                except Exception: pass
            await self.page.wait_for_timeout(300)
        return None

    async def _navigate_calendar_to(self, value: date, calendar: Any) -> bool:
        current = await self._detect_calendar_month(calendar)
        if current is None:
            self.diagnostics["stage"] = "calendar_navigation_failed"; await self._save_artifact("calendar_navigation_failed", html=True, screenshot=True); return False
        diff = (value.year - current[0]) * 12 + (value.month - current[1])
        if diff < 0 or diff > 24:
            self.diagnostics["stage"] = "calendar_navigation_failed"; self._record("calendar_navigation_failed", current=current, diff=diff); return False
        for _ in range(diff):
            before = current
            button = await self._next_month_button(calendar)
            if button is None:
                self.diagnostics["stage"] = "calendar_navigation_failed"; await self._save_artifact("calendar_navigation_failed", html=True, screenshot=True); return False
            await button.click(); self._record("calendar_next_clicked")
            await self.page.wait_for_timeout(500)
            current = await self._wait_month_changed(calendar, before)
            if current is None:
                self.diagnostics["stage"] = "calendar_navigation_failed"; await self._save_artifact("calendar_navigation_failed", html=True, screenshot=True); return False
        ok = current == (value.year, value.month)
        self.diagnostics["target_month_reached"] = ok
        if ok: self._record("target_month_reached", year=value.year, month=value.month)
        else: self.diagnostics["stage"] = "calendar_navigation_failed"
        return ok

    async def _click_calendar_date(self, value: date, calendar: Any | None = None) -> bool:
        assert self.page is not None
        root = calendar or await self._wait_calendar_open() or self.page
        candidates = await root.locator("button, [role='button'], [aria-label], [data-date], time, td, div").evaluate_all("""(els) => els.slice(0,300).map((el, i) => ({i, tag: el.tagName.toLowerCase(), text: (el.innerText||el.textContent||'').trim(), aria: el.getAttribute('aria-label')||'', date: el.getAttribute('data-date')||el.getAttribute('datetime')||'', disabled: el.disabled || el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('disabled'), cls: el.className ? String(el.className) : ''}))""")
        safe = [c for c in candidates if str(value.day) in (c.get("text") or "") or str(value.day) in (c.get("aria") or "") or value.isoformat() in (c.get("date") or "")]
        self._record("target_day_candidates", count=len(safe), candidates=safe[:20])
        idx = self._choose_day_candidate(safe, value)
        if idx is None:
            self.diagnostics["stage"] = "date_not_found"; await self._save_artifact("date_not_found", html=True, screenshot=True); return False
        await root.locator("button, [role='button'], [aria-label], [data-date], time, td, div").nth(idx).click()
        return True

    async def _verify_date_displayed(self, value: date) -> bool:
        assert self.page is not None
        form = await self._railway_form()
        text = self._clean_text(await form.inner_text(timeout=3000))
        ok = self._date_is_displayed(text, value)
        if ok:
            self.diagnostics["date_selected"] = True; self._record("requested_date_verified", value=value.isoformat()); self._record("date_selected", value=value.isoformat())
        return ok

    async def _submit_search(self) -> bool:
        assert self.page is not None
        if not (self.diagnostics.get("origin_selected") and self.diagnostics.get("destination_selected") and self.diagnostics.get("date_selected")):
            self.diagnostics["stage"] = "search_submit_failed"; return False
        before_url = self.page.url; form = await self._railway_form()
        loc = await self._locator_first(self.selectors["search_button"], field="search_button", root=form)
        if loc is None or not await loc.is_enabled():
            self.diagnostics["stage"] = "search_submit_failed"; await self._save_artifact("search_submit_failed", html=True, screenshot=True); return False
        await loc.click(); self.diagnostics["search_button_clicked"] = True; self._record("search_button_clicked")
        deadline = datetime.utcnow() + timedelta(seconds=20)
        while datetime.utcnow() < deadline:
            if self.page.url != before_url or await self._results_signal_visible() or await self._has_visible_text(r"ничего не найдено|нет поездов|загрузка|ищем"):
                self.diagnostics["search_submitted"] = True; self._record("search_submitted", url=self.page.url); return True
            await self.page.wait_for_timeout(500)
        self.diagnostics["stage"] = "search_submit_failed"; await self._save_artifact("search_submit_failed", html=True, screenshot=True); return False

    async def _close_cookie_popup(self) -> None:
        if self.page is None: return
        for selector in self.selectors["cookie_buttons"]:
            try:
                buttons = self._build_locator(selector)
                for index in range(min(await buttons.count(), 5)):
                    button = buttons.nth(index)
                    if await button.is_visible(timeout=1000): await button.click(); self._record("cookie_popup_closed", selector=selector); return
            except Exception: continue

    async def _locator_first(self, selectors: list[str], field: str = "element", root: Any | None = None) -> Any | None:
        assert self.page is not None
        root = root or self.page
        misses = []
        for selector in selectors:
            loc = self._build_locator(selector, root=root)
            try:
                count = await loc.count(); self._record("selector_checked", field=field, selector=selector, count=count)
                for index in range(min(count, 10)):
                    item = loc.nth(index)
                    if await item.is_visible(timeout=800): self._record("selector_chosen", field=field, selector=selector, index=index); return item
                misses.append({"selector": selector, "count": count})
            except Exception as exc: misses.append({"selector": selector, "error": str(exc)[:200]})
        self._record("selector_not_found", field=field, misses=misses); return None

    async def _ensure_railway_tab(self) -> None:
        loc = await self._locator_first(self.selectors["railway_tab"], field="railway_tab")
        if loc is None: self._record("railway_tab_not_found_continuing"); return
        try:
            await loc.click(); await self.page.wait_for_timeout(1000); self._record("railway_tab_opened", url=self.page.url)
        except Exception as exc: self._record("railway_tab_click_failed", error=str(exc)[:200])

    def _build_locator(self, selector: str, root: Any | None = None) -> Any:
        assert self.page is not None
        root = root or self.page
        if selector.startswith("role="):
            role, name = selector.removeprefix("role=").split("|", 1)
            return root.get_by_role(role, name=re.compile(name, re.I))
        if selector.startswith("label="): return root.get_by_label(re.compile(selector.removeprefix("label="), re.I))
        if selector.startswith("placeholder="): return root.get_by_placeholder(re.compile(selector.removeprefix("placeholder="), re.I))
        if selector.startswith("text="): return root.get_by_text(re.compile(selector.removeprefix("text="), re.I))
        if selector.startswith("testid="): return root.get_by_test_id(selector.removeprefix("testid="))
        return root.locator(selector)

    async def _railway_form(self) -> Any:
        assert self.page is not None
        for selector in ["form:has-text('Откуда'):has-text('Куда')", "main:has-text('Откуда'):has-text('Куда')", "body"]:
            loc = self.page.locator(selector).first
            try:
                if await loc.count() and await loc.is_visible(timeout=500): return loc
            except Exception: pass
        return self.page.locator("body")

    async def _date_control(self, form: Any) -> Any | None:
        candidates = await self._discover_date_control_candidates(form)
        self.diagnostics["date_control_candidates"] = [self._public_date_candidate(item) for item in candidates]
        self._record("date_control_candidates", count=len(candidates), candidates=self.diagnostics["date_control_candidates"])
        if not candidates:
            await self._save_named_artifact("date_control_candidates", html=True, screenshot=True)
            return None

        for candidate in candidates:
            locator = form.locator(self._interactive_elements_selector()).nth(candidate["i"])
            before_expanded = candidate.get("aria_expanded", "")
            before_dom = await self._dom_signature()
            try:
                await locator.scroll_into_view_if_needed(timeout=1000)
                await locator.click(timeout=3000)
            except Exception as exc:
                candidate["click_error"] = str(exc)[:200]
                candidate["opened_calendar"] = False
                continue
            await self.page.wait_for_timeout(2000)
            after_expanded = ""
            try:
                after_expanded = await locator.get_attribute("aria-expanded", timeout=500) or ""
            except Exception:
                after_expanded = ""
            calendar = await self._calendar_signal()
            after_dom = await self._dom_signature()
            candidate["aria_expanded_after"] = after_expanded
            candidate["dom_changed"] = before_dom != after_dom
            candidate["opened_calendar"] = bool(calendar) or after_expanded == "true" and before_expanded != "true"
            self.diagnostics["date_control_candidates"] = [self._public_date_candidate(item) for item in candidates]
            self._record("date_control_candidate_clicked", candidate=self._public_date_candidate(candidate))
            if candidate["opened_calendar"]:
                self.diagnostics["date_control_found"] = True
                self.diagnostics["calendar_opened"] = True
                self.diagnostics["date_control_opened_candidate"] = self._public_date_candidate(candidate)
                return locator
            try:
                await self.page.keyboard.press("Escape")
            except Exception:
                pass
        await self._save_named_artifact("date_control_candidates", html=True, screenshot=True)
        self._record("date_control_candidates_exhausted", count=len(candidates), candidates=self.diagnostics["date_control_candidates"])
        return None

    async def _record_date_control_candidates(self, form: Any) -> None:
        candidates = await self._discover_date_control_candidates(form)
        self.diagnostics["date_control_candidates"] = [self._public_date_candidate(item) for item in candidates]
        self._record("date_control_candidates", count=len(candidates), candidates=self.diagnostics["date_control_candidates"])

    def _interactive_elements_selector(self) -> str:
        return "button, input, div[role='button'], span[role='button'], [tabindex], [aria-haspopup], [aria-expanded], [data-testid], [onclick]"

    async def _discover_date_control_candidates(self, form: Any) -> list[dict[str, Any]]:
        selector = self._interactive_elements_selector()
        items = await form.locator(selector).evaluate_all("""
        (els) => els.map((el, i) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            const text = ((el.innerText || el.value || el.textContent || '') + '').trim().replace(/\\s+/g, ' ');
            const nearby = [el, el.parentElement, el.previousElementSibling, el.nextElementSibling].filter(Boolean)
                .map(n => ((n.innerText || n.textContent || '') + ' ' + (n.getAttribute('aria-label') || '') + ' ' + (n.className || '') + ' ' + (n.getAttribute('data-testid') || ''))).join(' ');
            return {
                i,
                tag: el.tagName.toLowerCase(),
                text: text.slice(0, 160),
                aria_label: el.getAttribute('aria-label') || '',
                placeholder: el.getAttribute('placeholder') || '',
                role: el.getAttribute('role') || '',
                class: el.className ? String(el.className).slice(0, 240) : '',
                data_testid: el.getAttribute('data-testid') || el.getAttribute('data-ti') || '',
                bounding_box: {x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height)},
                visible: !!(rect.width && rect.height && style.visibility !== 'hidden' && style.display !== 'none'),
                enabled: !(el.disabled || el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('disabled')),
                aria_expanded: el.getAttribute('aria-expanded') || '',
                aria_haspopup: el.getAttribute('aria-haspopup') || '',
                onclick: !!el.onclick || el.hasAttribute('onclick'),
                pointer_cursor: style.cursor === 'pointer',
                nearby: nearby.slice(0, 500),
            };
        })
        """)
        date_words = re.compile(r"когда|дата|сегодня|завтра|calendar|date|календар", re.I)
        candidates = []
        for item in items:
            hay = " ".join(str(item.get(k, "")) for k in ("text", "aria_label", "placeholder", "role", "class", "data_testid", "nearby"))
            if item.get("visible") and item.get("enabled") and date_words.search(hay):
                item["opened_calendar"] = False
                candidates.append(item)
        return candidates

    def _public_date_candidate(self, item: dict[str, Any]) -> dict[str, Any]:
        return {key: item.get(key) for key in ("tag", "text", "role", "aria_label", "placeholder", "class", "data_testid", "bounding_box", "visible", "enabled", "opened_calendar", "aria_expanded", "aria_expanded_after", "dom_changed", "click_error")}

    async def _calendar_signal(self) -> Any | None:
        assert self.page is not None
        for selector in self.selectors["calendar_containers"]:
            try:
                loc = self._build_locator(selector)
                if await loc.count() and await loc.first.is_visible(timeout=300):
                    return loc.first
            except Exception:
                pass
        if await self._has_visible_text(r"январ|феврал|март|апрел|ма[йя]|июн|июл|август|сентябр|октябр|ноябр|декабр"):
            return self.page.locator("body")
        return None

    async def _dom_signature(self) -> str:
        assert self.page is not None
        return await self.page.locator("body").evaluate("el => String(el.innerHTML.length) + ':' + (el.innerText || '').length")

    async def _wait_suggestions(self, value: str) -> bool:
        assert self.page is not None
        for _ in range(12):
            if await self._suggestion_locator(value) is not None: return True
            await self.page.wait_for_timeout(250)
        return False

    async def _suggestion_locator(self, value: str) -> Any | None:
        assert self.page is not None
        pattern = re.compile(re.escape(value.split()[0]), re.I)
        for selector in ["[role='option']", "li", "[class*='suggest' i]", "[class*='autocomplete' i]", "[data-testid*='suggest' i]"]:
            loc = self.page.locator(selector).filter(has_text=pattern)
            try:
                if await loc.count() and await loc.first.is_visible(timeout=300): return loc.first
            except Exception: pass
        return None

    async def _input_contains(self, loc: Any, value: str) -> bool:
        try: actual = await loc.input_value(timeout=1000)
        except Exception:
            try: actual = await loc.inner_text(timeout=1000)
            except Exception: actual = ""
        return value.lower().split()[0] in actual.lower()

    async def _detect_calendar_month(self, calendar: Any) -> tuple[int, int] | None:
        text = self._clean_text(await calendar.inner_text(timeout=2000))
        result = self._parse_ru_month_year(text)
        if result: self._record("calendar_month_detected", year=result[0], month=result[1])
        return result

    async def _wait_month_changed(self, calendar: Any, before: tuple[int, int]) -> tuple[int, int] | None:
        for _ in range(12):
            current = await self._detect_calendar_month(calendar)
            if current and current != before: return current
            await self.page.wait_for_timeout(250)
        return None

    async def _next_month_button(self, calendar: Any) -> Any | None:
        return await self._locator_first(["role=button|следующ", "[aria-label*='следующ' i]", "[title*='следующ' i]", "[data-testid*='next' i]", "[data-ti*='next' i]", "button:has(svg)"], field="calendar_next", root=calendar)

    async def _results_signal_visible(self) -> bool:
        assert self.page is not None
        if await self._has_visible_text(r"\b\d{1,3}[А-ЯA-Z]{1,2}\b.*\b[0-2]?\d:[0-5]\d\b.*\b[0-2]?\d:[0-5]\d\b"): return True
        for selector in self.selectors["results_containers"]:
            try:
                loc = self._build_locator(selector)
                if await loc.count() and await loc.first.is_visible(timeout=300): return True
            except Exception: pass
        return False

    async def _has_visible_text(self, pattern: str) -> bool:
        try: return await self.page.get_by_text(re.compile(pattern, re.I)).first.is_visible(timeout=300)
        except Exception: return False

    async def _results_container(self) -> Any:
        assert self.page is not None
        for selector in self.selectors["results_containers"]:
            try:
                loc = self._build_locator(selector)
                if await loc.count() and await loc.first.is_visible(timeout=1000): return loc.first
            except Exception: pass
        return self.page.locator("main").first if await self.page.locator("main").count() else self.page.locator("body")

    def _parse_card(self, item: dict[str, Any], request: TutuPlaywrightSearchRequest | None) -> TutuPlaywrightResult | None:
        text = self._clean_text(item.get("text", ""))
        if not self._looks_like_route_card(text) or request is None: return None
        times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text)
        train = re.search(r"(?:поезд\s*|№\s*)([0-9]{1,3}[А-ЯA-Z]{0,2}(?:/[0-9]{1,3}[А-ЯA-Z]{0,2})?)\b|\b([0-9]{1,3}[А-ЯA-Z]{1,2}(?:/[0-9]{1,3}[А-ЯA-Z]{1,2})?)\b", text, re.I)
        if len(times) < 2 or train is None: return None
        train_number = train.group(1) or train.group(2)
        return TutuPlaywrightResult(train_number=train_number, train_name=self._train_name(text), origin_station=request.origin, destination_station=request.destination, departure=self._combine(request.date, times[0]), arrival=self._arrival(request.date, times[0], times[1]), duration_minutes=self._duration_minutes(text, times[0], times[1]), carriage_type=self._carriage_type(text), available_seats=self._seat_availability(text), price=self._price(text), raw={"visible_text": text[:1000], "selector": item.get("selector")})

    def _looks_like_route_card(self, text: str) -> bool:
        cleaned = self._clean_text(text)
        if not cleaned or len(cleaned) < 20: return False
        form_words = ["Откуда", "Куда", "Когда", "Сегодня", "Завтра", "Найти поезд"]
        if all(w in cleaned for w in form_words) and not re.search(r"\b\d{1,3}[А-ЯA-Z]{1,2}\b", cleaned): return False
        return bool(re.search(r"\b\d{1,3}[А-ЯA-Z]{1,2}\b|поезд\s*№?\s*\d", cleaned, re.I) and len(re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", cleaned)) >= 2)

    def _choose_day_candidate(self, candidates: list[dict[str, Any]], value: date) -> int | None:
        for exact in (value.isoformat(), value.strftime("%d.%m.%Y"), value.strftime("%d/%m/%Y")):
            for c in candidates:
                if not c.get("disabled") and exact in f"{c.get('aria','')} {c.get('date','')}": return c["i"]
        month_forms = self._month_forms(value.month)
        for c in candidates:
            hay = f"{c.get('aria','')} {c.get('date','')} {c.get('text','')}".lower()
            if not c.get("disabled") and re.search(rf"(^|\D){value.day}(\D|$)", hay) and any(m in hay for m in month_forms) and str(value.year) in hay: return c["i"]
        for c in candidates:
            text = self._clean_text(c.get("text", ""))
            cls = str(c.get("cls", "")).lower()
            if not c.get("disabled") and text == str(value.day) and not re.search(r"other|outside|disabled|muted|prev|next", cls): return c["i"]
        return None

    def _date_is_displayed(self, text: str, value: date) -> bool:
        forms = [value.strftime("%d.%m.%Y"), value.strftime("%-d.%m.%Y"), value.strftime("%d/%m/%Y"), value.strftime("%-d/%m/%Y")]
        forms += [f"{value.day} {m}" for m in self._month_forms(value.month)]
        return any(f.lower() in text.lower() for f in forms)

    def _parse_ru_month_year(self, text: str) -> tuple[int, int] | None:
        lower = text.lower().replace("ё", "е")
        year_match = re.search(r"(20\d{2})", lower)
        if not year_match: return None
        year = int(year_match.group(1))
        for stem, month in RU_MONTHS.items():
            if re.search(rf"{stem}[а-я.]*\s+{year}|{year}\s+{stem}[а-я.]*", lower): return (year, month)
        return None

    def _month_forms(self, month: int) -> list[str]:
        names = {1: ["январь", "января", "янв"], 2: ["февраль", "февраля", "фев"], 3: ["март", "марта", "мар"], 4: ["апрель", "апреля", "апр"], 5: ["май", "мая"], 6: ["июнь", "июня", "июн"], 7: ["июль", "июля", "июл"], 8: ["август", "августа", "авг"], 9: ["сентябрь", "сентября", "сен", "сент"], 10: ["октябрь", "октября", "окт"], 11: ["ноябрь", "ноября", "ноя"], 12: ["декабрь", "декабря", "дек"]}
        return names[month]

    def _date_shortcut(self, value: date) -> str | None:
        today = date.today()
        if value == today: return "Сегодня"
        if value == today + timedelta(days=1): return "Завтра"
        return None

    def _date_labels(self, value: date) -> list[str]:
        return [value.strftime("%d.%m.%Y"), value.strftime("%d.%m"), f"{value.day} {self._month_forms(value.month)[1]}", str(value.day)]

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()

    def _route_json(self, r: TutuPlaywrightResult) -> dict[str, Any]:
        return {"departure_time": r.departure.isoformat(), "arrival_time": r.arrival.isoformat(), "duration": f"{r.duration_minutes // 60}ч {r.duration_minutes % 60}м", "duration_minutes": r.duration_minutes, "train_number": r.train_number, "train_name": r.train_name, "price": r.price, "seat_counts": {"platskart": r.available_seats.platzkart, "coupe": r.available_seats.coupe, "SV": r.available_seats.sv, "seated": r.available_seats.seated}}

    def _combine(self, d: date, hhmm: str) -> datetime:
        h, m = map(int, hhmm.split(":")); return datetime(d.year, d.month, d.day, h, m)
    def _arrival(self, d: date, dep: str, arr: str) -> datetime:
        value = self._combine(d, arr); return value + timedelta(days=1) if arr < dep else value
    def _duration_minutes(self, text: str, dep: str, arr: str) -> int:
        match = re.search(r"(\d+)\s*ч(?:\s*(\d+)\s*м)?", text)
        if match: return int(match.group(1)) * 60 + int(match.group(2) or 0)
        return int((self._arrival(date.today(), dep, arr) - self._combine(date.today(), dep)).total_seconds() // 60)
    def _price(self, text: str) -> float | None:
        match = re.search(r"(?:от\s*)?([0-9 ][0-9 ]+)\s*(?:₽|руб)", text, re.I); return float(match.group(1).replace(" ", "")) if match else None
    def _seat_availability(self, text: str) -> SeatAvailability:
        def count(*labels: str) -> int | str:
            for label in labels:
                for pattern in [rf"{label}[^0-9]{{0,20}}(\d+)\s+мест", rf"(\d+)\s+мест[^А-Яа-я]{{0,20}}{label}", rf"(\d+)\s+{label}"]:
                    match = re.search(pattern, text, re.I)
                    if match: return int(match.group(1))
            return "Unknown"
        total_match = re.search(r"(\d+)\s+мест", text, re.I)
        return SeatAvailability(total=int(total_match.group(1)) if total_match else "Unknown", platzkart=count("плацкарт", "плац"), coupe=count("купе", "куп"), sv=count("СВ"), seated=count("сидяч", "сид"))
    def _carriage_type(self, text: str) -> str:
        for label in ("плацкарт", "купе", "СВ", "сидячий", "люкс"):
            if label.lower() in text.lower(): return label
        return "Unknown"
    def _train_name(self, text: str) -> str | None:
        quoted = re.search(r"[«\"]([^»\"]+)[»\"]", text); return quoted.group(1) if quoted else None
    def _record(self, event: str, **data: Any) -> None:
        self.diagnostics.setdefault("events", []).append({"event": event, **data})
    async def _save_artifact(self, name: str, html: bool = False, screenshot: bool = False) -> None:
        if self.page is None: return
        artifact_dir = Path("/tmp/tutu-playwright-diagnostics"); artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name); timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f"); paths = {}
        if html:
            path = artifact_dir / f"{timestamp}_{safe_name}.html"; path.write_text(await self.page.content(), encoding="utf-8"); paths["html"] = str(path)
        if screenshot:
            path = artifact_dir / f"{timestamp}_{safe_name}.png"; await self.page.screenshot(path=str(path), full_page=True); paths["screenshot"] = str(path)
        self._record("artifact_saved", name=name, **paths)

    async def _save_named_artifact(self, name: str, html: bool = False, screenshot: bool = False) -> None:
        if self.page is None: return
        artifact_dir = Path("/tmp/tutu-playwright-diagnostics"); artifact_dir.mkdir(parents=True, exist_ok=True)
        paths = {}
        if html:
            path = artifact_dir / f"{name}.html"; path.write_text(await self.page.content(), encoding="utf-8"); paths["html"] = str(path)
        if screenshot:
            path = artifact_dir / f"{name}.png"; await self.page.screenshot(path=str(path), full_page=True); paths["screenshot"] = str(path)
        self._record("artifact_saved", name=name, **paths)
    async def _page_diagnostics(self) -> dict[str, Any]:
        if self.page is None: return {}
        try:
            stage = self.diagnostics.get("stage") or self.diagnostics.get("events", [{}])[-1].get("event")
            return {"stage": stage, "current_url": self.page.url, "page_title": await self.page.title()}
        except Exception: return {"url": getattr(self.page, "url", None)}
