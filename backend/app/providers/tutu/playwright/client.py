from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import quote_plus

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
        "result_cards": ["[data-ti*='train']", "article", ".train", "[class*='card']"],
    }

    def __init__(self, pool: BrowserPool | None = None) -> None:
        self.pool = pool or BrowserPool(BrowserManager(config=BrowserConfiguration.from_env().with_playwright_enabled()))
        self.session: BrowserSession | None = None
        self.page: Any | None = None
        self._last_request: TutuPlaywrightSearchRequest | None = None

    def open_home(self) -> None:
        self.session = self.pool.acquire()
        self.page = self.session.new_page()
        self.session.navigate(self.home_url)
        self.page.wait_for_load_state("networkidle")
        self._close_cookie_popup()

    def search(self, origin: str, destination: str, date: date, passengers: int = 1) -> None:
        if self.page is None:
            self.open_home()
        assert self.page is not None
        self._last_request = TutuPlaywrightSearchRequest(origin=origin, destination=destination, date=date, passengers=passengers)
        if not self._try_form_search(origin, destination, date):
            url = f"https://www.tutu.ru/poezda/rasp_d.php?st1={quote_plus(origin)}&st2={quote_plus(destination)}&date={date:%d.%m.%Y}"
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        self.wait_results()

    def wait_results(self) -> None:
        if self.page is None:
            raise RuntimeError("Tutu page is not opened")
        self.page.wait_for_load_state("domcontentloaded")
        try:
            self.page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        for selector in self.selectors["result_cards"]:
            try:
                self.page.locator(selector).first.wait_for(timeout=10000)
                return
            except Exception:
                continue

    def parse_results(self) -> list[TutuPlaywrightResult]:
        if self.page is None:
            raise RuntimeError("Tutu page is not opened")
        request = self._last_request
        parsed = self.page.evaluate(r"""
        () => Array.from(document.querySelectorAll('[data-ti*=train], article, .train, [class*=card]')).slice(0, 12).map((el) => ({
          text: (el.innerText || '').replace(/\s+/g, ' ').trim(),
          price: (el.innerText || '').match(/[0-9 ][0-9 ]+\s*₽/)?.[0] || null
        })).filter(x => x.text.length > 20)
        """)

        results: list[TutuPlaywrightResult] = []
        for item in parsed:
            result = self._parse_card(item, request)
            if result is not None:
                results.append(result)
        return results[:8]

    def close(self) -> None:
        if self.session is not None:
            self.pool.release(self.session)
        self.session = None
        self.page = None

    def _close_cookie_popup(self) -> None:
        if self.page is None:
            return
        for selector in self.selectors["cookie_buttons"]:
            try:
                button = self.page.locator(selector).first
                if button.is_visible(timeout=1500):
                    button.click()
                    return
            except Exception:
                continue

    def _try_form_search(self, origin: str, destination: str, travel_date: date) -> bool:
        assert self.page is not None
        try:
            self._fill_first(self.selectors["origin_input"], origin)
            self._fill_first(self.selectors["destination_input"], destination)
            self._fill_first(self.selectors["date_input"], travel_date.strftime("%d.%m.%Y"))
            self._click_first(self.selectors["search_button"])
            return True
        except Exception:
            return False

    def _fill_first(self, selectors: list[str], value: str) -> None:
        assert self.page is not None
        for selector in selectors:
            loc = self.page.locator(selector).first
            if loc.count():
                loc.fill(value)
                return
        raise RuntimeError("input not found")

    def _click_first(self, selectors: list[str]) -> None:
        assert self.page is not None
        for selector in selectors:
            loc = self.page.locator(selector).first
            if loc.count():
                loc.click()
                return
        raise RuntimeError("button not found")

    def _parse_card(self, item: dict[str, Any], request: TutuPlaywrightSearchRequest | None) -> TutuPlaywrightResult | None:
        text = item.get("text", "")
        times = re.findall(r"\b\d{1,2}:\d{2}\b", text)
        if len(times) < 2 or request is None:
            return None
        train = re.search(r"(?:№\s*)?([0-9]{1,3}[А-ЯA-Z]?)", text)
        price = item.get("price")
        return TutuPlaywrightResult(
            train_number=train.group(1) if train else "Unknown",
            origin_station=self._station_before_time(text, times[0]) or request.origin,
            destination_station=self._station_before_time(text, times[1]) or request.destination,
            departure=self._combine(request.date, times[0]),
            arrival=self._arrival(request.date, times[0], times[1]),
            duration_minutes=self._duration_minutes(text, times[0], times[1]),
            transfers=0 if "без пересад" in text.lower() else len(re.findall(r"пересад", text.lower())),
            carriage_type=self._carriage_type(text),
            available_seats=self._seat_availability(text),
            price=self._price(price or text),
            raw={"text": text[:1000]},
        )

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
        match = re.search(r"([0-9 ][0-9 ]+)\s*₽", text)
        return float(match.group(1).replace(" ", "")) if match else None

    def _seat_availability(self, text: str) -> SeatAvailability:
        def count(label: str) -> int | str:
            match = re.search(rf"(\d+)\s+(?:мест[ао]?\s+)?{label}", text, re.I)
            return int(match.group(1)) if match else "Unknown"
        total_match = re.search(r"(\d+)\s+мест", text, re.I)
        return SeatAvailability(total=int(total_match.group(1)) if total_match else "Unknown", upper=count("верх"), lower=count("ниж"), side=count("бок"), platzkart=count("плац"), coupe=count("куп"), sv=count("СВ"), seated=count("сид"))

    def _carriage_type(self, text: str) -> str:
        for label in ("плацкарт", "купе", "СВ", "сидячий", "люкс"):
            if label.lower() in text.lower():
                return label
        return "Unknown"

    def _station_before_time(self, text: str, time_value: str) -> str | None:
        before = text.split(time_value)[0].strip().split(" ")
        return before[-1] if before else None
