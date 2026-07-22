from __future__ import annotations

import re
from pathlib import Path
from datetime import date, datetime, timedelta
from typing import Any

from app.browser import BrowserConfiguration, BrowserManager, BrowserPool, BrowserSession
from app.providers.tutu.playwright.models import SeatAvailability, TutuPlaywrightResult, TutuPlaywrightSearchRequest


class TutuPlaywrightClient:
    home_url = "https://www.tutu.ru/"
    selectors = {
        "cookie_buttons": ["role=button|Принять", "role=button|Согласен", "role=button|Понятно", "[data-ti='accept-cookies']"],
        "railway_tab": ["role=tab|Ж/д", "role=button|Ж/д", "role=link|Ж/д билеты", "text=Ж/д"],
        "origin_input": [
            "label=Откуда",
            "placeholder=Откуда",
            "role=combobox|Откуда",
            "role=textbox|Откуда",
            "input[autocomplete*='from' i]",
            "input[name='st1']",
            "input[name='stl']",
            "input[placeholder*='Откуда']",
            "input[aria-label*='Откуда']",
        ],
        "destination_input": [
            "label=Куда",
            "placeholder=Куда",
            "role=combobox|Куда",
            "role=textbox|Куда",
            "input[autocomplete*='to' i]",
            "input[name='st2']",
            "input[placeholder*='Куда']",
            "input[aria-label*='Куда']",
        ],
        "date_control": [
            "testid=date",
            "testid=departure-date",
            "testid=search-date",
            "role=button|Дата|Сегодня|Завтра|\\d{1,2}\\s+[а-я]+|\\d{1,2}\\.\\d{1,2}",
            "text=Сегодня",
            "text=Завтра",
            "label=Дата",
            "input[name='date']",
            "input[placeholder*='Дата']",
            "input[aria-label*='Дата']",
            "[role='button']:has-text('Дата')",
            "[role='button']:has-text('Сегодня')",
            "[role='button']:has-text('Завтра')",
            "button:has-text('Дата')",
            "button:has-text('Сегодня')",
            "button:has-text('Завтра')",
        ],
        "calendar_containers": ["role=dialog|", "[role='dialog']:visible", "[class*='calendar' i]:visible", "[data-testid*='calendar' i]:visible"],
        "search_button": ["role=button|Найти поезд", "role=button|Найти", "button:has-text('Найти поезд')", "button:has-text('Найти')", "button[type='submit']"],
        "results_containers": ["main:has-text('Выберите поезд')", "main:has-text('поезд')", "[data-testid*='result' i]", "[data-ti*='result' i]", "[class*='result' i]"],
        "result_cards": ["[data-testid*='train' i]:visible", "[data-ti*='train' i]:visible", "article:has-text('мест'):visible", "[class*='train' i]:has-text('мест'):visible", "[class*='card' i]:has-text('мест'):visible"],
    }

    def __init__(self, pool: BrowserPool | None = None) -> None:
        self.pool = pool or BrowserPool(BrowserManager(config=BrowserConfiguration.from_env().with_playwright_enabled()))
        self.session: BrowserSession | None = None
        self.page: Any | None = None
        self._last_request: TutuPlaywrightSearchRequest | None = None
        self.diagnostics: dict[str, Any] = {}

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
            return
        if not await self._fill_station("destination_input", destination):
            return
        if not await self._select_date(date):
            return
        if not await self._submit_search():
            return
        await self.wait_results()

    async def wait_results(self) -> None:
        if self.page is None:
            raise RuntimeError("Tutu page is not opened")
        await self.page.wait_for_load_state("domcontentloaded")
        try:
            await self.page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as exc:
            self._record("networkidle_timeout", error=str(exc)[:300])
        for selector in self.selectors["result_cards"]:
            try:
                await self.page.locator(selector).first.wait_for(state="visible", timeout=15000)
                self._record("results_page_loaded", selector=selector, url=self.page.url)
                return
            except Exception as exc:
                self._record("results_wait_miss", selector=selector, error=str(exc)[:200])

    async def parse_results(self) -> list[TutuPlaywrightResult]:
        if self.page is None:
            raise RuntimeError("Tutu page is not opened")
        request = self._last_request
        parsed: list[dict[str, Any]] = []
        container = await self._results_container()
        for selector in self.selectors["result_cards"]:
            try:
                loc = container.locator(selector)
                for index in range(min(await loc.count(), 30)):
                    item = loc.nth(index)
                    if await item.is_visible():
                        text = (await item.inner_text(timeout=2000)).replace("\xa0", " ")
                        text = re.sub(r"\s+", " ", text).strip()
                        if len(text) > 20:
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
                    results.append(result)
                    seen.add(key)
        self._record("valid_route_cards_found", count=len(results))
        if not results:
            await self._save_artifact("result_cards_not_found", html=True, screenshot=True)
        return results

    async def live_test(self, origin: str, destination: str, departure_date: date) -> dict[str, Any]:
        try:
            await self.open_home()
            await self.search(origin, destination, departure_date)
            results = await self.parse_results()
            if not results:
                return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "routes_found": 0, "routes": [], "diagnostics": self.diagnostics | await self._page_diagnostics()}
            return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "routes_found": len(results), "routes": [self._route_json(r) for r in results], "diagnostics": self.diagnostics | await self._page_diagnostics()}
        except Exception as exc:
            self._record("error", type=exc.__class__.__name__, message=str(exc))
            return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "routes_found": 0, "routes": [], "diagnostics": self.diagnostics | await self._page_diagnostics()}
        finally:
            await self.close()

    async def close(self) -> None:
        if self.session is not None:
            await self.pool.release(self.session)
        self.session = None
        self.page = None

    async def _fill_station(self, key: str, value: str) -> bool:
        loc = await self._locator_first(self.selectors[key], field=key)
        if loc is None:
            return False
        await self._save_artifact(f"before_typing_{key}", screenshot=True)
        await loc.click()
        await loc.press("Control+A")
        await loc.type(value, delay=40)
        await self.page.wait_for_timeout(600)
        await self.page.keyboard.press("ArrowDown")
        await self.page.keyboard.press("Enter")
        self._record("origin_selected" if key == "origin_input" else "destination_selected", field=key, value=value)
        return True

    async def _select_date(self, value: date) -> bool:
        assert self.page is not None
        shortcut = self._date_shortcut(value)
        if shortcut:
            loc = await self._locator_first([f"role=button|{shortcut}", f"text={shortcut}"], field="date_shortcut")
            if loc is not None:
                self._record("date_control_found", strategy="shortcut", label=shortcut)
                await loc.click()
                self._record("requested_date_selected", value=value.isoformat(), strategy=shortcut)
                return await self._verify_date_displayed(value)

        control = await self._locator_first(self.selectors["date_control"], field="date_control")
        if control is None:
            await self._save_artifact("date_control_not_found", html=True, screenshot=True)
            return False
        self._record("date_control_found", strategy="calendar")
        await control.click()
        if not await self._wait_calendar_open():
            await self._save_artifact("date_selection_failed", html=True, screenshot=True)
            return False
        if not await self._click_calendar_date(value):
            await self._save_artifact("date_selection_failed", html=True, screenshot=True)
            return False
        self._record("requested_date_selected", value=value.isoformat(), strategy="calendar")
        return await self._verify_date_displayed(value)

    async def _wait_calendar_open(self) -> bool:
        for selector in self.selectors["calendar_containers"]:
            try:
                loc = self._build_locator(selector)
                if await loc.count() and await loc.first.is_visible(timeout=3000):
                    self._record("calendar_opened", selector=selector)
                    return True
            except Exception as exc:
                self._record("calendar_open_miss", selector=selector, error=str(exc)[:200])
        return False

    async def _click_calendar_date(self, value: date) -> bool:
        labels = self._date_labels(value)
        candidates = []
        for label in labels:
            candidates.extend([f"role=button|^{re.escape(label)}$", f"label=^{re.escape(label)}$", f"text=^{re.escape(label)}$"])
        for selector in candidates:
            loc = await self._locator_first([selector], field="calendar_date")
            if loc is not None:
                await loc.click()
                return True
        return False

    async def _verify_date_displayed(self, value: date) -> bool:
        text = await self.page.locator("body").inner_text(timeout=3000)
        shortcut = self._date_shortcut(value)
        ok = any(label in text for label in self._date_labels(value)) or (shortcut is not None and shortcut in text)
        if not ok:
            self._record("date_selection_failed", value=value.isoformat())
            await self._save_artifact("date_selection_failed", html=True, screenshot=True)
            return False
        self._record("date_selected", value=value.isoformat())
        return True

    async def _submit_search(self) -> bool:
        assert self.page is not None
        before_url = self.page.url
        loc = await self._locator_first(self.selectors["search_button"], field="search_button")
        if loc is None:
            await self._save_artifact("search_submission_failed", html=True, screenshot=True)
            return False
        await loc.click()
        self._record("search_button_clicked")
        submitted = False
        try:
            await self.page.wait_for_url(lambda url: url != before_url, timeout=10000)
            submitted = True
        except Exception:
            for selector in self.selectors["results_containers"] + self.selectors["result_cards"]:
                try:
                    await self._build_locator(selector).first.wait_for(state="visible", timeout=3000)
                    submitted = True
                    break
                except Exception:
                    pass
        self.diagnostics["search_submitted"] = submitted
        if not submitted:
            await self._save_artifact("search_submission_failed", html=True, screenshot=True)
        return submitted

    async def _close_cookie_popup(self) -> None:
        if self.page is None:
            return
        for selector in self.selectors["cookie_buttons"]:
            try:
                buttons = self._build_locator(selector)
                count = await buttons.count()
                self._record("selector_checked", field="cookie_button", selector=selector, count=count)
                for index in range(min(count, 5)):
                    button = buttons.nth(index)
                    if await button.is_visible(timeout=1500):
                        await button.click()
                        self._record("cookie_popup_closed", selector=selector, count=count, index=index)
                        return
            except Exception as exc:
                self._record("selector_error", field="cookie_button", selector=selector, error=str(exc)[:200])
                continue

    async def _locator_first(self, selectors: list[str], field: str = "element") -> Any | None:
        assert self.page is not None
        misses: list[dict[str, Any]] = []
        for selector in selectors:
            loc = self._build_locator(selector)
            try:
                count = await loc.count()
                self._record("selector_checked", field=field, selector=selector, count=count)
                for index in range(min(count, 10)):
                    item = loc.nth(index)
                    if await item.is_visible(timeout=1000):
                        self._record("selector_chosen", field=field, selector=selector, count=count, index=index)
                        return item
                misses.append({"selector": selector, "count": count, "reason": "no visible matches"})
            except Exception as exc:
                misses.append({"selector": selector, "error": str(exc)[:200]})
                self._record("selector_error", field=field, selector=selector, error=str(exc)[:200])
        self._record("selector_not_found", field=field, selectors=selectors, misses=misses)
        await self._save_artifact(f"selector_not_found_{field}", html=True, screenshot=True)
        return None

    async def _click_first(self, selectors: list[str]) -> bool:
        loc = await self._locator_first(selectors, field="search_button")
        if loc is None:
            return False
        await loc.click()
        self._record("submitted_search")
        return True

    async def _ensure_railway_tab(self) -> None:
        loc = await self._locator_first(self.selectors["railway_tab"], field="railway_tab")
        if loc is None:
            self._record("railway_tab_not_found_continuing")
            return
        try:
            await loc.click()
            try:
                await self.page.wait_for_load_state("domcontentloaded", timeout=5000)
            except Exception:
                pass
            await self.page.wait_for_timeout(1000)
            self._record("railway_tab_opened", url=self.page.url)
        except Exception as exc:
            self._record("railway_tab_click_failed", error=str(exc)[:200])

    def _build_locator(self, selector: str) -> Any:
        assert self.page is not None
        if selector.startswith("role="):
            role, name = selector.removeprefix("role=").split("|", 1)
            return self.page.get_by_role(role, name=re.compile(name, re.I))
        if selector.startswith("label="):
            return self.page.get_by_label(re.compile(selector.removeprefix("label="), re.I))
        if selector.startswith("placeholder="):
            return self.page.get_by_placeholder(re.compile(selector.removeprefix("placeholder="), re.I))
        if selector.startswith("text="):
            return self.page.get_by_text(re.compile(selector.removeprefix("text="), re.I))
        if selector.startswith("testid="):
            return self.page.get_by_test_id(selector.removeprefix("testid="))
        return self.page.locator(selector)

    async def _save_artifact(self, name: str, html: bool = False, screenshot: bool = False) -> None:
        if self.page is None:
            return
        artifact_dir = Path("/tmp/tutu-playwright-diagnostics")
        artifact_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name)
        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
        paths: dict[str, str] = {}
        if html:
            path = artifact_dir / f"{timestamp}_{safe_name}.html"
            path.write_text(await self.page.content(), encoding="utf-8")
            paths["html"] = str(path)
        if screenshot:
            path = artifact_dir / f"{timestamp}_{safe_name}.png"
            await self.page.screenshot(path=str(path), full_page=True)
            paths["screenshot"] = str(path)
        self._record("artifact_saved", name=name, **paths)

    def _parse_card(self, item: dict[str, Any], request: TutuPlaywrightSearchRequest | None) -> TutuPlaywrightResult | None:
        text = item.get("text", "")
        times = re.findall(r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b", text)
        if len(times) < 2 or request is None:
            return None
        train = re.search(r"(?:поезд\s*|№\s*)([0-9]{1,3}[А-ЯA-Z]{0,2}(?:/[0-9]{1,3}[А-ЯA-Z]{0,2})?)\b|\b([0-9]{1,3}[А-ЯA-Z]{1,2}(?:/[0-9]{1,3}[А-ЯA-Z]{1,2})?)\b", text, re.I)
        if train is None:
            return None
        train_number = train.group(1) or train.group(2)
        return TutuPlaywrightResult(
            train_number=train_number,
            train_name=self._train_name(text),
            origin_station=request.origin,
            destination_station=request.destination,
            departure=self._combine(request.date, times[0]),
            arrival=self._arrival(request.date, times[0], times[1]),
            duration_minutes=self._duration_minutes(text, times[0], times[1]),
            carriage_type=self._carriage_type(text),
            available_seats=self._seat_availability(text),
            price=self._price(text),
            raw={"visible_text": text[:1000], "selector": item.get("selector")},
        )

    def _route_json(self, r: TutuPlaywrightResult) -> dict[str, Any]:
        return {
            "departure_time": r.departure.isoformat(),
            "arrival_time": r.arrival.isoformat(),
            "duration": f"{r.duration_minutes // 60}ч {r.duration_minutes % 60}м",
            "duration_minutes": r.duration_minutes,
            "train_number": r.train_number,
            "train_name": r.train_name,
            "price": r.price,
            "seat_counts": {
                "platskart": r.available_seats.platzkart,
                "coupe": r.available_seats.coupe,
                "SV": r.available_seats.sv,
                "seated": r.available_seats.seated,
            },
        }

    def _combine(self, d: date, hhmm: str) -> datetime:
        h, m = map(int, hhmm.split(":"))
        return datetime(d.year, d.month, d.day, h, m)

    def _arrival(self, d: date, dep: str, arr: str) -> datetime:
        value = self._combine(d, arr)
        return value + timedelta(days=1) if arr < dep else value

    def _duration_minutes(self, text: str, dep: str, arr: str) -> int:
        match = re.search(r"(\d+)\s*ч(?:\s*(\d+)\s*м)?", text)
        if match:
            return int(match.group(1)) * 60 + int(match.group(2) or 0)
        return int((self._arrival(date.today(), dep, arr) - self._combine(date.today(), dep)).total_seconds() // 60)

    def _price(self, text: str) -> float | None:
        match = re.search(r"(?:от\s*)?([0-9 ][0-9 ]+)\s*(?:₽|руб)", text, re.I)
        return float(match.group(1).replace(" ", "")) if match else None

    def _seat_availability(self, text: str) -> SeatAvailability:
        def count(*labels: str) -> int | str:
            for label in labels:
                patterns = [rf"{label}[^0-9]{{0,20}}(\d+)\s+мест", rf"(\d+)\s+мест[^А-Яа-я]{{0,20}}{label}", rf"(\d+)\s+{label}"]
                for pattern in patterns:
                    match = re.search(pattern, text, re.I)
                    if match:
                        return int(match.group(1))
            return "Unknown"
        total_match = re.search(r"(\d+)\s+мест", text, re.I)
        return SeatAvailability(total=int(total_match.group(1)) if total_match else "Unknown", platzkart=count("плацкарт", "плац"), coupe=count("купе", "куп"), sv=count("СВ"), seated=count("сидяч", "сид"))

    def _carriage_type(self, text: str) -> str:
        for label in ("плацкарт", "купе", "СВ", "сидячий", "люкс"):
            if label.lower() in text.lower():
                return label
        return "Unknown"

    def _train_name(self, text: str) -> str | None:
        quoted = re.search(r"[«\"]([^»\"]+)[»\"]", text)
        return quoted.group(1) if quoted else None

    def _record(self, event: str, **data: Any) -> None:
        self.diagnostics.setdefault("events", []).append({"event": event, **data})


    async def _results_container(self) -> Any:
        assert self.page is not None
        for selector in self.selectors["results_containers"]:
            try:
                loc = self._build_locator(selector)
                if await loc.count() and await loc.first.is_visible(timeout=1000):
                    return loc.first
            except Exception:
                pass
        return self.page.locator("body")

    def _date_shortcut(self, value: date) -> str | None:
        today = date.today()
        if value == today:
            return "Сегодня"
        if value == today + timedelta(days=1):
            return "Завтра"
        return None

    def _date_labels(self, value: date) -> list[str]:
        months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
        return [value.strftime("%d.%m.%Y"), value.strftime("%d.%m"), f"{value.day} {months[value.month - 1]}", str(value.day)]

    async def _page_diagnostics(self) -> dict[str, Any]:
        if self.page is None:
            return {}
        try:
            return {"stage": self.diagnostics.get("events", [{}])[-1].get("event"), "current_url": self.page.url, "page_title": await self.page.title(), "search_submitted": self.diagnostics.get("search_submitted", False), "calendar_opened": any(e.get("event") == "calendar_opened" for e in self.diagnostics.get("events", [])), "date_selected": any(e.get("event") == "date_selected" for e in self.diagnostics.get("events", [])), "visible_text_sample": (await self.page.locator("body").inner_text(timeout=2000))[:2000]}
        except Exception:
            return {"url": getattr(self.page, "url", None)}
