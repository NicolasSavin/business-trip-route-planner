from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from app.browser import BrowserConfiguration, BrowserManager, BrowserPool, BrowserSession
from app.providers.tutu.playwright.models import SeatAvailability, TutuPlaywrightResult, TutuPlaywrightSearchRequest


class TutuPlaywrightClient:
    home_url = "https://www.tutu.ru/"
    selectors = {
        "cookie_buttons": ["button:has-text('Принять')", "button:has-text('Согласен')", "button:has-text('Понятно')", "[data-ti='accept-cookies']"],
        "origin_input": ["input[placeholder*='Откуда']", "input[aria-label*='Откуда']", "input[name='st1']"],
        "destination_input": ["input[placeholder*='Куда']", "input[aria-label*='Куда']", "input[name='st2']"],
        "date_input": ["input[placeholder*='Дата']", "input[aria-label*='Дата']", "input[name='date']"],
        "search_button": ["button:has-text('Найти')", "button[type='submit']"],
        "result_cards": ["[data-ti*='train']:visible", "article:visible", ".train:visible", "[class*='card']:visible"],
    }

    def __init__(self, pool: BrowserPool | None = None) -> None:
        self.pool = pool or BrowserPool(BrowserManager(config=BrowserConfiguration.from_env().with_playwright_enabled()))
        self.session: BrowserSession | None = None
        self.page: Any | None = None
        self._last_request: TutuPlaywrightSearchRequest | None = None
        self.diagnostics: dict[str, Any] = {}

    def open_home(self) -> None:
        self.session = self.pool.acquire()
        self.page = self.session.new_page()
        self.session.navigate(self.home_url)
        self.page.wait_for_load_state("domcontentloaded")
        self._close_cookie_popup()
        self._record("opened_home", url=self.page.url, title=self.page.title())

    def search(self, origin: str, destination: str, date: date, passengers: int = 1) -> None:
        if self.page is None:
            self.open_home()
        assert self.page is not None
        self._last_request = TutuPlaywrightSearchRequest(origin=origin, destination=destination, date=date, passengers=passengers)
        self._fill_station("origin_input", origin)
        self._fill_station("destination_input", destination)
        self._fill_date(date)
        self._click_first(self.selectors["search_button"])
        self.wait_results()

    def wait_results(self) -> None:
        if self.page is None:
            raise RuntimeError("Tutu page is not opened")
        self.page.wait_for_load_state("domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=30000)
        except Exception as exc:
            self._record("networkidle_timeout", error=str(exc)[:300])
        for selector in self.selectors["result_cards"]:
            try:
                self.page.locator(selector).first.wait_for(state="visible", timeout=15000)
                self._record("results_visible", selector=selector, url=self.page.url)
                return
            except Exception as exc:
                self._record("results_wait_miss", selector=selector, error=str(exc)[:200])

    def parse_results(self) -> list[TutuPlaywrightResult]:
        if self.page is None:
            raise RuntimeError("Tutu page is not opened")
        request = self._last_request
        parsed: list[dict[str, Any]] = []
        for selector in self.selectors["result_cards"]:
            try:
                loc = self.page.locator(selector)
                for index in range(min(loc.count(), 30)):
                    item = loc.nth(index)
                    if item.is_visible():
                        text = item.inner_text(timeout=2000).replace("\xa0", " ")
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
        return results

    def live_test(self, origin: str, destination: str, departure_date: date) -> dict[str, Any]:
        try:
            self.open_home()
            self.search(origin, destination, departure_date)
            results = self.parse_results()
            return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "routes_found": len(results), "routes": [self._route_json(r) for r in results], "diagnostics": self.diagnostics if not results else {"url": self.page.url if self.page else None}}
        except Exception as exc:
            self._record("error", type=exc.__class__.__name__, message=str(exc))
            return {"origin": origin, "destination": destination, "date": departure_date.isoformat(), "routes_found": 0, "routes": [], "diagnostics": self.diagnostics | self._page_diagnostics()}
        finally:
            self.close()

    def close(self) -> None:
        if self.session is not None:
            self.pool.release(self.session)
        self.session = None
        self.page = None

    def _fill_station(self, key: str, value: str) -> None:
        loc = self._locator_first(self.selectors[key])
        loc.click()
        loc.press("Control+A")
        loc.type(value, delay=40)
        self.page.wait_for_timeout(600)
        self.page.keyboard.press("ArrowDown")
        self.page.keyboard.press("Enter")
        self._record("filled_station", field=key, value=value)

    def _fill_date(self, value: date) -> None:
        loc = self._locator_first(self.selectors["date_input"])
        loc.click()
        loc.press("Control+A")
        loc.type(value.strftime("%d.%m.%Y"), delay=35)
        self.page.keyboard.press("Enter")
        self._record("filled_date", value=value.isoformat())

    def _close_cookie_popup(self) -> None:
        if self.page is None:
            return
        for selector in self.selectors["cookie_buttons"]:
            try:
                button = self.page.locator(selector).first
                if button.is_visible(timeout=1500):
                    button.click()
                    self._record("cookie_popup_closed", selector=selector)
                    return
            except Exception:
                continue

    def _locator_first(self, selectors: list[str]) -> Any:
        assert self.page is not None
        for selector in selectors:
            loc = self.page.locator(selector).first
            try:
                if loc.is_visible(timeout=3000):
                    return loc
            except Exception:
                continue
        raise RuntimeError(f"Visible element not found for selectors: {selectors}")

    def _click_first(self, selectors: list[str]) -> None:
        self._locator_first(selectors).click()
        self._record("submitted_search")

    def _parse_card(self, item: dict[str, Any], request: TutuPlaywrightSearchRequest | None) -> TutuPlaywrightResult | None:
        text = item.get("text", "")
        times = re.findall(r"\b\d{1,2}:\d{2}\b", text)
        if len(times) < 2 or request is None:
            return None
        train = re.search(r"(?:№\s*)?([0-9]{1,3}[А-ЯA-Z]?)", text)
        return TutuPlaywrightResult(
            train_number=train.group(1) if train else "Unknown",
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

    def _page_diagnostics(self) -> dict[str, Any]:
        if self.page is None:
            return {}
        try:
            return {"url": self.page.url, "title": self.page.title(), "visible_text_sample": self.page.locator("body").inner_text(timeout=2000)[:2000]}
        except Exception:
            return {"url": getattr(self.page, "url", None)}
