from datetime import date, timedelta

import asyncio
import re
from pathlib import Path

import pytest

from app.providers.tutu.playwright.client import TutuPlaywrightClient
from app.providers.tutu.playwright.models import TutuPlaywrightSearchRequest


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tutu_playwright"


def fixture_text(name: str) -> str:
    return re.sub(r"<[^>]+>", " ", (FIXTURE_DIR / name).read_text(encoding="utf-8"))


@pytest.fixture
def client():
    return TutuPlaywrightClient(pool=None)


def test_today_shortcut_label(client):
    assert client._date_shortcut(date.today()) == "Сегодня"


def test_tomorrow_shortcut_label(client):
    assert client._date_shortcut(date.today() + timedelta(days=1)) == "Завтра"


def test_calendar_date_selection_uses_exact_date_labels(client):
    seen_selectors: list[str] = []

    class FakeLocator:
        async def click(self):
            return None

    async def fake_locator_first(selectors, field="element"):
        seen_selectors.extend(selectors)
        return FakeLocator() if "role=button|^15\\ августа$" in selectors else None

    client._locator_first = fake_locator_first  # type: ignore[method-assign]

    assert asyncio.run(client._click_calendar_date(date(2026, 8, 15))) is True
    assert "role=button|^15\\ августа$" in seen_selectors
    assert any(selector.startswith("text=^15") for selector in seen_selectors)


def test_date_control_supports_button_implementations(client):
    selectors = client.selectors["date_control"]
    assert any(selector.startswith("role=button|") for selector in selectors)
    assert "[role='button']:has-text('Сегодня')" in selectors
    assert "button:has-text('Завтра')" in selectors


def test_search_form_not_parsed_as_route(client):
    request = TutuPlaywrightSearchRequest(origin="Москва", destination="Санкт-Петербург", date=date(2026, 8, 15))
    form_text = fixture_text("search_form.html")

    assert client._parse_card({"text": form_text, "selector": "form"}, request) is None


def test_valid_route_card_accepted(client):
    request = TutuPlaywrightSearchRequest(origin="Москва", destination="Санкт-Петербург", date=date(2026, 8, 15))
    card_text = fixture_text("valid_card.html")

    result = client._parse_card({"text": card_text, "selector": "article"}, request)

    assert result is not None
    assert result.train_number == "784А"
    assert result.departure.hour == 6
    assert result.arrival.hour == 10


def test_invalid_card_without_train_number_rejected(client):
    request = TutuPlaywrightSearchRequest(origin="Москва", destination="Санкт-Петербург", date=date(2026, 8, 15))
    card_text = fixture_text("invalid_card.html")

    assert client._parse_card({"text": card_text, "selector": "article"}, request) is None
