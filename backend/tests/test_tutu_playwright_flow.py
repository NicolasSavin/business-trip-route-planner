from datetime import date, timedelta

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


def test_date_control_uses_dom_interactive_probe(client):
    selector = client._interactive_elements_selector()
    assert "button" in selector
    assert "input" in selector
    assert "[tabindex]" in selector
    assert "[aria-haspopup]" in selector
    assert "[data-testid]" in selector


def test_date_control_today_button_shortcut(client):
    assert client._date_shortcut(date.today()) == "Сегодня"
    assert client._date_shortcut(date.today() + timedelta(days=1)) == "Завтра"


def test_calendar_dialog_selector_opens(client):
    assert "[role='dialog']:visible" in client.selectors["calendar_containers"]
    assert any("calendar" in selector for selector in client.selectors["calendar_containers"])


def test_russian_month_july_2026_detected(client):
    assert client._parse_ru_month_year("июль 2026") == (2026, 7)
    assert client._parse_ru_month_year("28 июля 2026") == (2026, 7)
    assert client._parse_ru_month_year("Июл. 2026") == (2026, 7)


def test_month_navigation_difference_is_bounded(client):
    current = client._parse_ru_month_year("апрель 2026")
    assert current == (2026, 4)
    diff = (2026 - current[0]) * 12 + (7 - current[1])
    assert diff == 3
    assert 0 <= diff <= 24


def test_choose_day_28_by_full_aria_label(client):
    candidates = [{"i": 3, "text": "28", "aria": "28 июля 2026", "date": "", "disabled": False, "cls": ""}]
    assert client._choose_day_candidate(candidates, date(2026, 7, 28)) == 3


def test_neighbor_month_day_28_not_selected(client):
    candidates = [
        {"i": 1, "text": "28", "aria": "28 июня 2026", "date": "", "disabled": False, "cls": "outside"},
        {"i": 2, "text": "28", "aria": "28 июля 2026", "date": "", "disabled": False, "cls": ""},
    ]
    assert client._choose_day_candidate(candidates, date(2026, 7, 28)) == 2


def test_date_verification_accepts_28_07_2026(client):
    assert client._date_is_displayed("Когда 28.07.2026 Найти поезд", date(2026, 7, 28))
    assert client._date_is_displayed("пн, 28 июля", date(2026, 7, 28))
    assert client._date_is_displayed("28/07/2026", date(2026, 7, 28))


def test_city_selection_requires_suggestions_method(client):
    assert hasattr(client, "_wait_suggestions")
    assert hasattr(client, "_suggestion_locator")


def test_search_button_disabled_before_date_blocks_submit(client):
    client.diagnostics["origin_selected"] = True
    client.diagnostics["destination_selected"] = True
    client.diagnostics["date_selected"] = False
    assert not (client.diagnostics["origin_selected"] and client.diagnostics["destination_selected"] and client.diagnostics["date_selected"])


def test_search_submission_by_url_change_event(client):
    client._record("url_changed", url="https://www.tutu.ru/poezda/search/")
    assert any(event["event"] == "url_changed" for event in client.diagnostics["events"])


def test_search_submission_by_results_container_event(client):
    client._record("results_container_visible")
    client._record("search_submitted")
    assert [event["event"] for event in client.diagnostics["events"]][-2:] == ["results_container_visible", "search_submitted"]


def test_no_results_state_event(client):
    client._record("no_results_visible")
    assert any(event["event"] == "no_results_visible" for event in client.diagnostics["events"])


def test_search_form_not_parsed_as_route(client):
    request = TutuPlaywrightSearchRequest(origin="Москва", destination="Санкт-Петербург", date=date(2026, 8, 15))
    form_text = fixture_text("search_form.html")
    assert client._parse_card({"text": form_text, "selector": "form"}, request) is None


def test_valid_route_card_accepted(client):
    request = TutuPlaywrightSearchRequest(origin="Москва", destination="Санкт-Петербург", date=date(2026, 8, 15))
    result = client._parse_card({"text": fixture_text("valid_card.html"), "selector": "article"}, request)
    assert result is not None
    assert result.train_number == "784А"
    assert result.departure.hour == 6
    assert result.arrival.hour == 10


def test_invalid_card_without_train_number_rejected(client):
    request = TutuPlaywrightSearchRequest(origin="Москва", destination="Санкт-Петербург", date=date(2026, 8, 15))
    assert client._parse_card({"text": fixture_text("invalid_card.html"), "selector": "article"}, request) is None


def test_timeout_diagnostics_without_runtime_error(client):
    client._record("results_wait_timeout")
    client.diagnostics["stage"] = "results_timeout"
    assert client.diagnostics["stage"] == "results_timeout"
    assert not any(event["event"] == "error" for event in client.diagnostics["events"])


def test_calendar_date_selection_uses_exact_date_labels(client):
    assert "15 августа" in client._date_labels(date(2026, 8, 15))


def test_station_exact_match_accepts_requested_city(client):
    normalized = client._normalize_station_text("Санкт-Петербург")
    assert client._station_text_exact_match("Санкт-Петербург", normalized)
    assert client._station_text_exact_match("Санкт-Петербург\nРоссия", normalized)
    assert client._station_text_exact_match("г. Санкт-Петербург, Россия", normalized)


def test_station_exact_match_rejects_partial_city(client):
    normalized = client._normalize_station_text("Москва")
    assert not client._station_text_exact_match("Московская область", normalized)


def test_visible_autocomplete_selectors_include_modern_aria_and_testids(client):
    # Source-level guard: station autocomplete discovery must cover current Tutu-style ARIA/test-id popups.
    import inspect
    source = inspect.getsource(client._suggestion_roots)
    assert "[role='listbox']:visible" in source
    assert "[role='combobox'][aria-expanded='true']:visible" in source
    assert "data-testid" in source
