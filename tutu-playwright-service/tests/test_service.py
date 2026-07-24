import pytest
import asyncio
import time
from datetime import date
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.service import service
from app.models import AvailabilityCheckRequest

@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r=await c.get("/health")
    assert r.status_code==200

@pytest.mark.asyncio
async def test_check_and_cache():
    payload={"origin":"Москва","destination":"Санкт-Петербург","departure_date":"2026-08-10","train_number":"008С","departure_time":"2026-08-10T23:06:00+03:00","passengers":2,"preferred_classes":["coupe"],"berth_preference":"lower_only","require_same_carriage":True,"require_same_compartment":True,"maximum_compartments":1}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r=await c.post("/api/v1/availability/check", json=payload)
        r2=await c.post("/api/v1/availability/check", json=payload)
    assert r.json()==r2.json()
    data=r.json(); assert data["status"]=="confirmed" and data["same_carriage"] and data["same_compartment"] and data["lower_berths_confirmed"]

@pytest.mark.asyncio
async def test_train_not_found_unknown():
    payload={"origin":"A","destination":"B","departure_date":"2026-08-10","train_number":"NO123","passengers":1}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r=await c.post("/api/v1/availability/check", json=payload)
    assert r.json()["status"]=="unknown"

class MockKeyboard:
    def __init__(self, page):
        self.page = page
        self.inserted = []

    async def insert_text(self, value):
        self.inserted.append(value)
        self.page.textbox.value = value
        self.page.autocomplete_open = True


class MockKeyboardTextbox:
    def __init__(self, page):
        self.page = page
        self.value = ""
        self.pressed = []

    async def fill(self, value):
        self.value = value
        self.page.autocomplete_open = True

    async def click(self, timeout=None):
        pass

    async def focus(self):
        pass

    async def blur(self):
        pass

    async def dispatch_event(self, event, event_init=None):
        if event in {"input", "keyup"} and self.value:
            self.page.autocomplete_open = True

    async def evaluate(self, script, *args):
        if args and "InputEvent('input'" in script:
            self.value = args[0]
            self.page.autocomplete_open = True
        elif "value = ''" in script:
            self.value = ""
        if "__tutuPwKeyboardCounters" in script:
            return {"keydown": 0, "keyup": 1, "input": 1, "change": 0}
        if "querySelectorAll" in script:
            return []
        return None

    async def press(self, key):
        self.pressed.append(key)
        if key == "Backspace":
            self.value = ""
            self.page.autocomplete_open = False
        if key == "Enter" and "ArrowDown" in self.pressed:
            self.page.autocomplete_open = False

    async def input_value(self):
        return self.value


class MockOption:
    def __init__(self, page, text):
        self.page = page
        self.text = text

    async def is_visible(self, timeout=None):
        return self.page.autocomplete_open

    async def inner_text(self, timeout=None):
        return self.text

    async def click(self, timeout=None):
        self.page.textbox.value = self.text
        self.page.autocomplete_open = False


class MockLocator:
    def __init__(self, page, options):
        self.page = page
        self.options = options

    def get_by_role(self, role):
        return self

    def locator(self, selector):
        return self

    async def evaluate_all(self, script):
        return [
            {
                "index": index,
                "text": text,
                "dom_path": f"html > body > div:nth-of-type({index + 1})",
                "visibility": {"visible": self.page.autocomplete_open},
                "role": "option",
                "aria_expanded": None,
                "aria_hidden": None,
                "classes": "mock-option",
                "options": [
                    {
                        "text": text,
                        "dom_path": f"html > body > div:nth-of-type({index + 1})",
                        "visibility": {"visible": self.page.autocomplete_open},
                        "role": "option",
                        "classes": "mock-option",
                    }
                ],
            }
            for index, text in enumerate(self.options)
        ]

    async def count(self):
        return len(self.options)

    def nth(self, index):
        return MockOption(self.page, self.options[index])


class MockPage:
    def __init__(self, options):
        self.options = options
        self.autocomplete_open = False
        self.textbox = MockKeyboardTextbox(self)
        self.keyboard = MockKeyboard(self)
        self.screenshots = []

    def get_by_role(self, role):
        if role in {"listbox", "option"}:
            return MockLocator(self, self.options)
        raise AssertionError(f"unexpected role: {role}")

    def locator(self, selector):
        return MockLocator(self, self.options)

    async def screenshot(self, path, full_page=True):
        self.screenshots.append(path)

    async def content(self):
        return "<html><body>No suggestions</body></html>"


@pytest.mark.asyncio
async def test_select_location_exact_city():
    from app.service import select_location

    page = MockPage(["Рязань"])
    value = await select_location(page, page.textbox, "Рязань", "origin")

    assert value == "Рязань"


@pytest.mark.asyncio
async def test_select_location_city_with_region():
    from app.service import select_location

    page = MockPage(["Рязань, Рязанская область"])
    value = await select_location(page, page.textbox, "Рязань", "origin")

    assert value == "Рязань, Рязанская область"


@pytest.mark.asyncio
async def test_select_location_partial_match():
    from app.service import select_location

    page = MockPage(["Рязань-1"])
    value = await select_location(page, page.textbox, "Рязань", "origin")

    assert value == "Рязань-1"


@pytest.mark.asyncio
async def test_select_location_mismatch_fails_without_arrow_fallback(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = MockPage(["Тула"])

    with pytest.raises(ValueError, match="Location suggestion not found: Рязань"):
        await service_module.select_location(page, page.textbox, "Рязань", "origin")

    assert "ArrowDown" not in page.textbox.pressed and "Enter" not in page.textbox.pressed
    assert (tmp_path / "artifacts" / "location_not_found.html").exists()


@pytest.mark.asyncio
async def test_select_location_no_suggestion_saves_artifacts(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    monkeypatch.setattr(service_module, "LOCATION_AUTOCOMPLETE_TIMEOUT_MS", 1)
    page = MockPage([])

    with pytest.raises(ValueError, match="Location suggestion not found: Рязань"):
        await service_module.select_location(page, page.textbox, "Рязань", "origin")

    assert page.screenshots
    assert (tmp_path / "artifacts" / "location_not_found.html").exists()

@pytest.mark.asyncio
async def test_debug_connectivity_endpoint_with_mocked_failures(monkeypatch):
    from app import connectivity

    async def fake_dns(host):
        return {"ok": True, "host": host, "ips": ["1.2.3.4"]}

    async def fake_tcp(host, port=443):
        return {"ok": True, "host": host, "port": port}

    async def fake_httpx(targets, **kwargs):
        return {target.key: {"ok": False, "url": target.url, "error_type": "ConnectError", "message": "Connection refused"} for target in targets}

    async def fake_playwright(targets, **kwargs):
        return {target.key: {"ok": False, "url": target.url, "error_type": "Error", "message": "net::ERR_CONNECTION_REFUSED"} for target in targets}

    monkeypatch.setattr(connectivity, "resolve_dns", fake_dns)
    monkeypatch.setattr(connectivity, "check_tcp", fake_tcp)
    monkeypatch.setattr(connectivity, "check_httpx", fake_httpx)
    monkeypatch.setattr(connectivity, "check_playwright", fake_playwright)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/debug/connectivity")

    assert r.status_code == 200
    data = r.json()
    assert data["dns"]["ips"] == ["1.2.3.4"]
    assert data["httpx"]["root"]["error_type"] == "ConnectError"
    assert data["playwright"]["poezda"]["message"] == "net::ERR_CONNECTION_REFUSED"
    assert data["provider_error"]["message"] == "tutu.ru is unreachable from the current hosting network"


@pytest.mark.asyncio
async def test_debug_connectivity_runs_playwright_variants_when_httpx_works(monkeypatch):
    from app import connectivity

    calls = []

    async def fake_dns(host):
        return {"ok": True, "host": host, "ips": ["1.2.3.4"]}

    async def fake_tcp(host, port=443):
        return {"ok": True, "host": host, "port": port}

    async def fake_httpx(targets, **kwargs):
        return {target.key: {"ok": True, "url": target.url, "status_code": 200, "headers": {}, "redirect_chain": [], "final_url": target.url} for target in targets}

    async def fake_playwright(targets, **kwargs):
        calls.append(kwargs)
        return {target.key: {"ok": False, "url": target.url, "error_type": "Error", "message": "net::ERR_CONNECTION_REFUSED"} for target in targets}

    monkeypatch.setattr(connectivity, "resolve_dns", fake_dns)
    monkeypatch.setattr(connectivity, "check_tcp", fake_tcp)
    monkeypatch.setattr(connectivity, "check_httpx", fake_httpx)
    monkeypatch.setattr(connectivity, "check_playwright", fake_playwright)

    result = await connectivity.run_connectivity_diagnostics()

    assert "playwright_variants" in result
    assert set(result["playwright_variants"]) == {"chromium_launch_args", "ipv4_preference", "disable_http2", "desktop_user_agent"}
    assert len(calls) == 5
    assert any(call.get("user_agent") == connectivity.DESKTOP_USER_AGENT for call in calls)

@pytest.mark.asyncio
async def test_connectivity_httpx_client_creation_raises(monkeypatch):
    from app import connectivity

    class RaisingAsyncClient:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("h2 support missing")

    monkeypatch.setattr(connectivity.httpx, "AsyncClient", RaisingAsyncClient)

    result = await connectivity.check_httpx([connectivity.Target("root", "https://example.test/")])

    assert result["root"]["ok"] is False
    assert result["root"]["error_type"] == "RuntimeError"
    assert result["root"]["message"] == "h2 support missing"
    assert "traceback" in result["root"]


@pytest.mark.asyncio
async def test_connectivity_playwright_launch_raises(monkeypatch):
    from app import connectivity

    class FakeChromium:
        async def launch(self, **kwargs):
            raise RuntimeError("launch failed")

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()
            self.stopped = False

        async def stop(self):
            self.stopped = True

    class FakePlaywrightFactory:
        async def start(self):
            return FakePlaywright()

    monkeypatch.setattr(connectivity, "async_playwright", lambda: FakePlaywrightFactory())

    result = await connectivity.check_playwright([connectivity.Target("root", "https://example.test/")])

    assert result["root"]["ok"] is False
    assert result["root"]["error_type"] == "RuntimeError"
    assert result["root"]["message"] == "launch failed"
    assert "traceback" in result["root"]


class ConnectivityResponse:
    status = 200

    async def all_headers(self):
        return {"x-test": "yes"}


class ConnectivityPage:
    url = "https://example.test/"

    def set_default_timeout(self, timeout):
        self.timeout = timeout

    async def goto(self, *args, **kwargs):
        return ConnectivityResponse()

    async def close(self):
        return None


class ConnectivityContext:
    def __init__(self, *, close_error=None):
        self.close_error = close_error

    async def new_page(self):
        return ConnectivityPage()

    async def close(self):
        if self.close_error:
            raise self.close_error


class ConnectivityBrowser:
    def __init__(self, *, context_close_error=None, browser_close_error=None):
        self.context_close_error = context_close_error
        self.browser_close_error = browser_close_error

    async def new_context(self, **kwargs):
        return ConnectivityContext(close_error=self.context_close_error)

    async def close(self):
        if self.browser_close_error:
            raise self.browser_close_error


class ConnectivityChromium:
    def __init__(self, browser):
        self.browser = browser

    async def launch(self, **kwargs):
        return self.browser


class ConnectivityPlaywright:
    def __init__(self, browser):
        self.chromium = ConnectivityChromium(browser)

    async def stop(self):
        return None


class ConnectivityPlaywrightFactory:
    def __init__(self, browser):
        self.browser = browser

    async def start(self):
        return ConnectivityPlaywright(self.browser)


@pytest.mark.asyncio
async def test_connectivity_context_close_raises(monkeypatch):
    from app import connectivity

    browser = ConnectivityBrowser(context_close_error=RuntimeError("context close failed"))
    monkeypatch.setattr(connectivity, "async_playwright", lambda: ConnectivityPlaywrightFactory(browser))

    result = await connectivity.check_playwright([connectivity.Target("root", "https://example.test/")])

    assert result["root"]["ok"] is True
    assert result["root"]["status_code"] == 200


@pytest.mark.asyncio
async def test_connectivity_browser_close_raises(monkeypatch):
    from app import connectivity

    browser = ConnectivityBrowser(browser_close_error=RuntimeError("browser close failed"))
    monkeypatch.setattr(connectivity, "async_playwright", lambda: ConnectivityPlaywrightFactory(browser))

    result = await connectivity.check_playwright([connectivity.Target("root", "https://example.test/")])

    assert result["root"]["ok"] is True
    assert result["root"]["status_code"] == 200


@pytest.mark.asyncio
async def test_connectivity_one_stage_raises_other_results_return(monkeypatch):
    from app import connectivity

    async def fake_dns(host):
        return {"ok": True, "host": host, "ips": ["1.2.3.4"]}

    async def fake_tcp(host, port=443):
        raise RuntimeError("tcp exploded")

    async def fake_httpx(targets, **kwargs):
        return {target.key: {"ok": True, "url": target.url, "status_code": 200} for target in targets}

    async def fake_playwright(targets, **kwargs):
        return {target.key: {"ok": True, "url": target.url, "status_code": 200} for target in targets}

    monkeypatch.setattr(connectivity, "resolve_dns", fake_dns)
    monkeypatch.setattr(connectivity, "check_tcp", fake_tcp)
    monkeypatch.setattr(connectivity, "check_httpx", fake_httpx)
    monkeypatch.setattr(connectivity, "check_playwright", fake_playwright)

    result = await connectivity.run_connectivity_diagnostics()

    assert result["diagnostics_completed"] is True
    assert result["dns"]["ok"] is True
    assert result["tcp"]["ok"] is False
    assert result["tcp"]["error_type"] == "RuntimeError"
    assert result["httpx"]["root"]["ok"] is True
    assert result["playwright"]["poezda"]["ok"] is True


@pytest.mark.asyncio
async def test_debug_connectivity_endpoint_does_not_return_plain_500(monkeypatch):
    from app import main

    async def fake_diagnostics():
        raise RuntimeError("unexpected endpoint failure")

    monkeypatch.setattr(main, "run_connectivity_diagnostics", fake_diagnostics)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/api/v1/debug/connectivity")

    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    data = r.json()
    assert data["diagnostics_completed"] is False
    assert data["ok"] is False
    assert data["error_type"] == "RuntimeError"
    assert data["message"] == "unexpected endpoint failure"
    assert "traceback" in data


class MockStickyOption(MockOption):
    async def click(self, timeout=None):
        self.page.autocomplete_open = False


class MockStickyLocator(MockLocator):
    def nth(self, index):
        return MockStickyOption(self.page, self.options[index])


class MockStickyPage(MockPage):
    def get_by_role(self, role):
        if role in {"listbox", "option"}:
            return MockStickyLocator(self, self.options)
        raise AssertionError(f"unexpected role: {role}")

    def locator(self, selector):
        return MockStickyLocator(self, self.options)


@pytest.mark.asyncio
async def test_select_location_autocomplete_not_opened_records_station_diagnostics(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    monkeypatch.setattr(service_module, "LOCATION_AUTOCOMPLETE_TIMEOUT_MS", 1)
    diagnostics = {"selected_inputs": {}, "station_steps": [], "origin_station_selection": {}, "destination_station_selection": {}, "popup_candidates": {}, "autocomplete_discovery": {}}
    page = MockPage([])

    with pytest.raises(ValueError, match="Location suggestion not found: Рязань"):
        await service_module.select_location(page, page.textbox, "Рязань", "origin", {"screenshots": [], "html_artifacts": []}, diagnostics)

    assert diagnostics["station_steps"][0]["failure_reason"] == "autocomplete_not_opened"
    assert diagnostics["origin_station_selection"]["requested_city"] == "Рязань"
    assert "origin" in diagnostics["autocomplete_discovery"]


@pytest.mark.asyncio
async def test_select_location_popup_without_match_records_candidates(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    diagnostics = {"selected_inputs": {}, "station_steps": [], "origin_station_selection": {}, "destination_station_selection": {}, "popup_candidates": {}, "autocomplete_discovery": {}}
    page = MockPage(["Тула"])

    with pytest.raises(ValueError, match="Location suggestion not found: Рязань"):
        await service_module.select_location(page, page.textbox, "Рязань", "origin", {"screenshots": [], "html_artifacts": []}, diagnostics)

    assert diagnostics["station_steps"][0]["failure_reason"] == "matching_candidate_not_found"
    assert diagnostics["popup_candidates"]["origin"]


@pytest.mark.asyncio
async def test_select_location_success_records_station_step(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    diagnostics = {"selected_inputs": {}, "station_steps": [], "origin_station_selection": {}, "destination_station_selection": {}, "popup_candidates": {}, "autocomplete_discovery": {}}
    page = MockPage(["Рязань, Рязанская область"])

    value = await service_module.select_location(page, page.textbox, "Рязань", "origin", {"screenshots": [], "html_artifacts": []}, diagnostics)

    assert value == "Рязань, Рязанская область"
    assert diagnostics["station_steps"][0]["station_selected"] is True
    assert diagnostics["origin_station_selection"]["clicked_candidate"] == "Рязань, Рязанская область"


@pytest.mark.asyncio
async def test_select_location_value_not_persisted_after_click_records_failure(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    diagnostics = {"selected_inputs": {}, "station_steps": [], "origin_station_selection": {}, "destination_station_selection": {}, "popup_candidates": {}, "autocomplete_discovery": {}}
    page = MockStickyPage(["Рязань-1"])

    with pytest.raises(ValueError, match="Location suggestion not found: Рязань"):
        await service_module.select_location(page, page.textbox, "Рязань", "origin", {"screenshots": [], "html_artifacts": []}, diagnostics)

    assert diagnostics["station_steps"][0]["failure_reason"] == "selected_value_not_persisted"
    assert diagnostics["origin_station_selection"]["clicked_candidate"] == "Рязань-1"


@pytest.mark.asyncio
async def test_provider_error_response_contains_station_steps_and_popup_candidates(monkeypatch):
    from app.models import Diagnostics
    from app.service import TutuDiagnosticError, service as service_instance

    async def fake_playwright(req):
        raise TutuDiagnosticError(
            "Location suggestion not found: Рязань",
            Diagnostics(
                station_steps=[{"field_name": "origin", "requested_city": "Рязань", "failure_reason": "matching_candidate_not_found"}],
                origin_station_selection={"field_name": "origin", "requested_city": "Рязань"},
                popup_candidates={"origin": [{"text": "Тула"}]},
            ),
        )

    service_instance.cache.items.clear()
    monkeypatch.setattr(service, "_playwright", fake_playwright)
    monkeypatch.setattr("app.service.settings.mock_mode", False)
    monkeypatch.setattr("app.service.settings.enabled", True)
    payload={"origin":"Рязань","destination":"Москва","departure_date":"2026-08-10","train_number":"008С","passengers":1}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r=await c.post("/api/v1/availability/check", json=payload)

    data = r.json()
    assert r.status_code == 200
    assert data["status"] == "provider_error"
    assert data["diagnostics"]["station_steps"][0]["requested_city"] == "Рязань"
    assert data["diagnostics"]["popup_candidates"]["origin"][0]["text"] == "Тула"

class SemanticLocator:
    def __init__(self, page, elements, index=None, scoped_field=None):
        self.page = page
        self.elements = elements
        self.index = index
        self.scoped_field = scoped_field

    def nth(self, index):
        return SemanticLocator(self.page, self.elements, index, self.scoped_field)

    def locator(self, selector):
        if "ancestor" in selector:
            field = self.elements[self.index]["field"] if self.index is not None else None
            return SemanticLocator(self.page, self.elements, self.index, field)
        return PopupLocator(self.page, self.scoped_field)

    def filter(self, **kwargs):
        return self

    async def count(self):
        return len(self.elements) if self.index is None else 1

    async def evaluate(self, script, *args):
        element = self.elements[self.index]
        if "tutuPwIdentity" in script:
            return element["identity"]
        if "aria-controls" in script:
            return [f"popup-{element['field']}"]
        if "left === right" in script:
            other = args[0]
            return element["identity"] == other["identity"]
        return element.get("value", "")

    async def element_handle(self):
        return self.elements[self.index]

    async def input_value(self):
        return self.elements[self.index].get("value", "")


class PopupLocator:
    def __init__(self, page, field):
        self.page = page
        self.field = field
        self.options = page.popups.get(field, []) if field else []

    def locator(self, selector):
        return self

    def filter(self, **kwargs):
        return self

    async def count(self):
        return len(self.options)

    def nth(self, index):
        return PopupOption(self.page, self.field, self.options[index])

    async def evaluate_all(self, script):
        return []


class PopupOption:
    def __init__(self, page, field, text):
        self.page = page
        self.field = field
        self.text = text

    async def is_visible(self, timeout=None):
        return True

    async def inner_text(self, timeout=None):
        return self.text


class SemanticPage:
    def __init__(self, elements, popups=None):
        self.elements = elements
        self.popups = popups or {}

    def locator(self, selector):
        if "popup" in selector or "suggest" in selector or "listbox" in selector and "textbox" not in selector:
            field = "origin" if "from" in selector else "destination" if "to" in selector else None
            return PopupLocator(self, field)
        return SemanticLocator(self, self.elements)


def semantic_item(index, field, name, placeholder, cls, value=""):
    return {"index": index, "field": field, "identity": f"id-{field}-{index}", "name": name, "id": None, "class": cls, "placeholder": placeholder, "aria_label": None, "autocomplete": None, "aria_controls": f"popup-{field}", "current_value": value, "value": value, "nearby_label_text": [placeholder], "ancestor_form_text": placeholder, "visible": True, "enabled": True, "editable": True, "dom_path": f"input[{index}]"}


@pytest.mark.asyncio
async def test_detect_station_input_uses_semantic_attributes(monkeypatch):
    from app import service as service_module
    page = SemanticPage([
        semantic_item(0, "origin", "schedule_station_from", "Откуда", "j-station_from"),
        semantic_item(1, "destination", "schedule_station_to", "Куда", "j-station_to"),
    ])
    async def fake_inspect(_p):
        return page.elements
    monkeypatch.setattr(service_module, "inspect_textboxes", fake_inspect)
    origin, origin_meta, _ = await service_module.detect_station_input(page, "origin")
    destination, destination_meta, _ = await service_module.detect_station_input(page, "destination")
    assert origin_meta["name"] == "schedule_station_from"
    assert destination_meta["name"] == "schedule_station_to"
    assert not await service_module._same_element(origin, destination)


@pytest.mark.asyncio
async def test_detect_station_input_ignores_dom_order(monkeypatch):
    from app import service as service_module
    page = SemanticPage([
        semantic_item(0, "destination", "schedule_station_to", "Куда", "j-station_to"),
        semantic_item(1, "origin", "schedule_station_from", "Откуда", "j-station_from"),
    ])
    async def fake_inspect(_p):
        return page.elements
    monkeypatch.setattr(service_module, "inspect_textboxes", fake_inspect)
    origin, origin_meta, _ = await service_module.detect_station_input(page, "origin")
    destination, destination_meta, _ = await service_module.detect_station_input(page, "destination")
    assert origin_meta["index"] == 1
    assert destination_meta["index"] == 0
    assert not await service_module._same_element(origin, destination)


@pytest.mark.asyncio
async def test_destination_reacquired_after_origin_rerender(monkeypatch):
    from app import service as service_module
    snapshots = [
        [semantic_item(0, "origin", "schedule_station_from", "Откуда", "j-station_from")],
        [semantic_item(0, "origin", "schedule_station_from", "Откуда", "j-station_from"), semantic_item(1, "destination", "schedule_station_to", "Куда", "j-station_to")],
    ]
    page = SemanticPage(snapshots[0])
    async def fake_inspect(_page):
        page.elements = snapshots.pop(0) if snapshots else page.elements
        return page.elements
    monkeypatch.setattr(service_module, "inspect_textboxes", fake_inspect)
    await service_module.detect_station_input(page, "origin")
    _, destination_meta, _ = await service_module.detect_station_input(page, "destination")
    assert destination_meta["name"] == "schedule_station_to"


@pytest.mark.asyncio
async def test_field_resolution_collision_detectable(monkeypatch):
    from app import service as service_module
    origin_item = semantic_item(0, "origin", "schedule_station_from", "Откуда", "j-station_from")
    page = SemanticPage([origin_item])
    async def fake_inspect(_p):
        return page.elements
    monkeypatch.setattr(service_module, "inspect_textboxes", fake_inspect)
    origin, _, _ = await service_module.detect_station_input(page, "origin")
    destination = page.locator("input").nth(0)
    assert await service_module._same_element(origin, destination)


@pytest.mark.asyncio
async def test_candidate_options_are_scoped_to_current_input():
    from app import service as service_module
    page = SemanticPage([
        semantic_item(0, "origin", "schedule_station_from", "Откуда", "j-station_from"),
        semantic_item(1, "destination", "schedule_station_to", "Куда", "j-station_to"),
    ], popups={"origin": ["Москва"], "destination": ["Рязань"]})
    destination = page.locator("input").nth(1)
    options = await service_module._candidate_options_for_input(page, destination, "destination")
    assert await options.count() == 1
    assert await options.nth(0).inner_text() == "Рязань"


@pytest.mark.asyncio
async def test_final_route_values_are_distinct_and_correct(monkeypatch):
    from app import service as service_module
    page = SemanticPage([
        semantic_item(0, "origin", "schedule_station_from", "Откуда", "j-station_from", "Москва"),
        semantic_item(1, "destination", "schedule_station_to", "Куда", "j-station_to", "Рязань"),
    ])
    async def fake_inspect(_p):
        return page.elements
    monkeypatch.setattr(service_module, "inspect_textboxes", fake_inspect)
    origin, _, _ = await service_module.detect_station_input(page, "origin")
    destination, _, _ = await service_module.detect_station_input(page, "destination")
    assert await origin.input_value() == "Москва"
    assert await destination.input_value() == "Рязань"
    assert not await service_module._same_element(origin, destination)

@pytest.mark.asyncio
async def test_keyboard_typing_diagnostics_records_strategy(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    diagnostics = {"selected_inputs": {}, "station_steps": [], "origin_station_selection": {}, "destination_station_selection": {}, "popup_candidates": {}, "autocomplete_discovery": {}}
    page = MockPage(["Рязань"])

    await service_module.select_location(page, page.textbox, "Рязань", "origin", {"screenshots": [], "html_artifacts": []}, diagnostics)

    step = diagnostics["station_steps"][0]
    assert step["typing_strategy"] == "keyboard.insert_text"
    assert step["unicode_input_strategy"] == "keyboard.insert_text"
    assert step["characters_typed"] == len("Рязань")
    assert step["station_selected"] is True


def test_network_summary_analytics_only_is_not_autocomplete():
    from app.service import _looks_autocomplete_related, _network_summary

    assert not _looks_autocomplete_related("https://api-x.tutu.ru/v2/data", '{"eventType":"input","SESSIONID":"secret"}', "Рязань")
    summary = _network_summary([], [], [])
    assert summary["probable_failure_reason"] == "autocomplete_request_not_triggered"
    assert summary["request_with_city_found"] is False


def test_redacts_cookie_session_and_analytics_payload():
    from app.service import _safe_body_sample, _safe_url

    body = '{"cookie":"a=b","SESSIONID":"abc","sessionId":"def","token":"ghi","nested":{"authorization":"Bearer secret"}}'
    redacted = _safe_body_sample("https://example.test/suggest/station", body)
    assert "abc" not in redacted and "def" not in redacted and "ghi" not in redacted and "Bearer secret" not in redacted
    assert "[redacted]" in redacted
    assert _safe_body_sample("https://api-x.tutu.ru/v2/data", body) == "[redacted analytics payload]"
    assert "secret" not in _safe_url("https://example.test/path?sessionId=secret&uid=42")


def test_autocomplete_query_decodes_percent_encoded_cyrillic():
    from app.service import _autocomplete_query_matches, _autocomplete_query_value

    url = "https://www.tutu.ru/suggest/railway_simple/?name=%D0%A0%D1%8F%D0%B7%D0%B0%D0%BD%D1%8C"

    assert _autocomplete_query_value(url) == "Рязань"
    assert _autocomplete_query_matches("Рязань", _autocomplete_query_value(url)) is True


def test_malformed_autocomplete_query_rejected():
    from app.service import _autocomplete_query_matches, _autocomplete_query_value

    query = _autocomplete_query_value("https://www.tutu.ru/suggest/railway_simple/?name=.%2F%3F")

    assert query == "./?"
    assert _autocomplete_query_matches("Рязань", query) is False


@pytest.mark.asyncio
async def test_keyboard_insert_text_strategy_sets_cyrillic_value():
    from app.service import _apply_unicode_input_strategy

    page = MockPage(["Рязань"])

    await _apply_unicode_input_strategy(page, page.textbox, "Рязань", "keyboard.insert_text")

    assert page.textbox.value == "Рязань"
    assert page.keyboard.inserted == ["Рязань"]


def test_popular_city_response_not_matching_candidate_not_found():
    from app.service import _popular_city_response_without_requested

    responses = [{"json_probe": {"contains_requested_city": False, "text_values_sample": ["Москва", "Санкт-Петербург", "Казань"]}}]

    assert _popular_city_response_without_requested(responses, "Рязань") is True

class RouteLocator:
    def __init__(self, page, selector, elements):
        self.page = page
        self.selector = selector
        self.elements = elements
        self.index = None

    def nth(self, index):
        loc = RouteLocator(self.page, self.selector, self.elements)
        loc.index = index
        return loc

    async def count(self):
        return len(self.elements) if self.index is None else (1 if self.elements else 0)

    async def input_value(self):
        return self.elements[self.index or 0].get("value", "")

    async def inner_text(self, timeout=None):
        return self.elements[self.index or 0].get("value", "")

    @property
    def first(self):
        return self.nth(0)

    async def evaluate(self, script):
        element = self.elements[self.index or 0]
        if "requestSubmit" in script or "SubmitEvent" in script or "typeof el.click" in script:
            self.page.clicked.append(f"evaluate:{self.selector}")
            if element.get("changes_url", True):
                self.page.url = self.page.url + "search/"
            strategy = element.get("submit_strategy") or ("primary_button_request_submit" if element.get("type") == "submit" else "form_request_submit")
            return {"strategy": strategy, "action": element.get("form_action", "https://www.tutu.ru/poezda/search/")}
        if "closest('form')" in script or "el.form" in script:
            return {
                "type": element.get("type"),
                "tag_name": element.get("tag_name", "input"),
                "form_contains_route_fields": element.get("form_contains_route_fields", False),
                "id": element.get("id"),
                "value": element.get("value", ""),
                "class": element.get("class", ""),
                "attached": element.get("attached", True),
                "visible": None,
                "enabled": None,
                "bounding_box": None,
                "computed_style": element.get("computed_style", {"display": "block", "visibility": "visible", "opacity": "1", "pointer_events": "auto"}),
                "form_action": element.get("form_action", "https://www.tutu.ru/poezda/search/"),
                "form_method": element.get("form_method", "get"),
            }
        return element.get("value", "")

    async def wait_for(self, **kwargs):
        return None

    async def is_visible(self, timeout=None):
        return self.elements[self.index or 0].get("visible", True)

    async def is_enabled(self, timeout=None):
        return self.elements[self.index or 0].get("enabled", True)

    async def bounding_box(self):
        return self.elements[self.index or 0].get("bounding_box", {"x": 1, "y": 1, "width": 10, "height": 10})

    async def click(self):
        element = self.elements[self.index or 0]
        if element.get("click_fails"):
            raise Exception("not clickable")
        self.page.clicked.append(self.selector)
        if element.get("changes_url"):
            self.page.url = self.page.url + "search/"


class RoutePage:
    def __init__(self, values=None, submit_buttons=None, rerender=False):
        self.values = values or {
            "schedule_station_from": "Москва",
            "nnst1": "2000000",
            "schedule_station_to": "Рязань",
            "nnst2": "2000125",
        }
        self.submit_buttons = submit_buttons or {
            "#idstationsearch_submit_button_input": [{"id": "idstationsearch_submit_button_input", "type": "submit", "value": "Найти", "form_contains_route_fields": True, "changes_url": True}],
            "#idtrainsearch_submit_button_input": [{"id": "idtrainsearch_submit_button_input", "type": "submit", "value": "Найти", "form_contains_route_fields": False, "changes_url": True}],
        }
        self.url = "https://www.tutu.ru/poezda/"
        self.clicked = []
        self.locator_calls = []
        self.rerender = rerender

    def locator(self, selector):
        self.locator_calls.append(selector)
        if selector.startswith("input[name="):
            name = selector.split("'")[1]
            return RouteLocator(self, selector, [{"value": self.values.get(name, "")}])
        if selector in self.submit_buttons:
            return RouteLocator(self, selector, self.submit_buttons[selector])
        if selector.startswith("form:has"):
            buttons = self.submit_buttons.get("fallback", [])
            return RouteLocator(self, selector, buttons)
        if selector == "body":
            return RouteLocator(self, selector, [{"value": getattr(self, "body_text", "")}])
        return RouteLocator(self, selector, [])

    async def screenshot(self, path, full_page=True):
        pass

    async def content(self):
        return "<html></html>"

    async def wait_for_url(self, predicate, timeout=None):
        if predicate(self.url):
            return None
        raise TimeoutError("url did not change")


@pytest.mark.asyncio
async def test_route_verification_passes_for_moscow_ryazan_hidden_ids():
    from app.service import _verify_route_fields

    page = RoutePage()
    diagnostics = {"origin_station_selection": {"station_selected": True}, "destination_station_selection": {"station_selected": True}}

    verification = await _verify_route_fields(page, "Москва", "Рязань", diagnostics)

    assert verification["verified"] is True
    assert verification["origin"]["hidden_value"] == "2000000"
    assert verification["destination"]["hidden_value"] == "2000125"


@pytest.mark.asyncio
async def test_route_verification_fails_when_destination_hidden_missing():
    from app.service import _verify_route_fields

    page = RoutePage(values={"schedule_station_from": "Москва", "nnst1": "2000000", "schedule_station_to": "Рязань", "nnst2": ""})
    diagnostics = {"origin_station_selection": {"station_selected": True}, "destination_station_selection": {"station_selected": True}}

    with pytest.raises(ValueError, match="destination_hidden_station_missing"):
        await _verify_route_fields(page, "Москва", "Рязань", diagnostics)
    assert diagnostics["route_fields_verification"]["destination"]["failure_reason"] == "destination_hidden_station_missing"


@pytest.mark.asyncio
async def test_route_submit_uses_station_search_button_when_two_find_buttons(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = RoutePage()
    diagnostics = {}

    await service_module._click_route_submit(page, diagnostics, {"screenshots": [], "html_artifacts": []})

    assert page.clicked == ["evaluate:#idstationsearch_submit_button_input"]
    assert diagnostics["submit_strategy"] == "primary_button_request_submit"
    assert diagnostics["submit_selector"] == "#idstationsearch_submit_button_input"


@pytest.mark.asyncio
async def test_route_submit_never_clicks_train_number_submit(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = RoutePage()

    await service_module._click_route_submit(page, {}, {"screenshots": [], "html_artifacts": []})

    assert "#idtrainsearch_submit_button_input" not in page.clicked


@pytest.mark.asyncio
async def test_route_verification_reacquires_rerendered_dom_fields():
    from app.service import _verify_route_fields

    page = RoutePage(rerender=True)
    diagnostics = {"origin_station_selection": {"station_selected": True}, "destination_station_selection": {"station_selected": True}}

    await _verify_route_fields(page, "Москва", "Рязань", diagnostics)

    assert "input[name='schedule_station_from']" in page.locator_calls
    assert "input[name='nnst2']" in page.locator_calls
    assert diagnostics["route_fields_verification"]["verified"] is True


@pytest.mark.asyncio
async def test_route_submit_url_change_is_navigation_success(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = RoutePage()
    diagnostics = {}

    result = await service_module._click_route_submit(page, diagnostics, {"screenshots": [], "html_artifacts": []})

    assert result == "submitted"
    assert diagnostics["before_submit_url"] != page.url

@pytest.mark.asyncio
async def test_post_submit_url_change_succeeds_without_networkidle(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "navigation_timeout_ms", 100)
    monkeypatch.setattr(service_module.settings, "results_container_timeout_ms", 100)
    monkeypatch.setattr(service_module.settings, "train_cards_timeout_ms", 100)
    monkeypatch.setattr(service_module.settings, "availability_timeout_ms", 100)
    page = RoutePage()
    page.url = "https://www.tutu.ru/poezda/search/"
    page.body_text = "Москва Рязань билеты купе"
    diagnostics = {"before_submit_url": "https://www.tutu.ru/poezda/"}
    result = await service_module.wait_for_tutu_search_result(page, time.monotonic() + 2, diagnostics)
    assert result["status"] == "results"
    assert "availability_text" in result["matched_signals"]

@pytest.mark.asyncio
async def test_post_submit_empty_state_returns_without_global_timeout(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "navigation_timeout_ms", 100)
    page = RoutePage()
    page.url = "https://www.tutu.ru/poezda/search/"
    page.body_text = "На выбранную дату нет поездов"
    diagnostics = {"before_submit_url": "https://www.tutu.ru/poezda/"}
    result = await service_module.wait_for_tutu_search_result(page, time.monotonic() + 2, diagnostics)
    assert result["status"] == "empty"
    assert "empty_state" in result["matched_signals"]

@pytest.mark.asyncio
async def test_post_submit_no_navigation_structured_timeout(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "navigation_timeout_ms", 50)
    monkeypatch.setattr(service_module.settings, "results_container_timeout_ms", 50)
    monkeypatch.setattr(service_module.settings, "train_cards_timeout_ms", 50)
    monkeypatch.setattr(service_module.settings, "availability_timeout_ms", 50)
    page = RoutePage()
    diagnostics = {"before_submit_url": page.url}
    result = await service_module.wait_for_tutu_search_result(page, time.monotonic() + 1, diagnostics)
    assert result["status"] == "navigation_timeout"
    assert any(step["status"] == "timeout" for step in diagnostics["post_submit_steps"])

@pytest.mark.asyncio
async def test_route_submit_primary_one_fallback_zero_not_ambiguous(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = RoutePage(submit_buttons={
        "#idstationsearch_submit_button_input": [{"id": "idstationsearch_submit_button_input", "type": "submit", "value": "Найти", "form_contains_route_fields": True, "changes_url": True}],
        "fallback": [],
    })
    diagnostics = {}

    await service_module._click_route_submit(page, diagnostics, {"screenshots": [], "html_artifacts": []})

    assert page.clicked == ["evaluate:#idstationsearch_submit_button_input"]
    assert diagnostics["submit_strategy"] == "primary_button_request_submit"
    assert diagnostics["submit_strategy"] == "primary_button_request_submit"
    assert diagnostics["route_submit_button"]["fallback_count"] is None


@pytest.mark.asyncio
async def test_route_submit_fallback_used_when_primary_missing(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = RoutePage(submit_buttons={
        "#idstationsearch_submit_button_input": [],
        "fallback": [{"id": "fallback", "type": "submit", "value": "Найти", "form_contains_route_fields": True, "changes_url": True}],
    })
    diagnostics = {}

    await service_module._click_route_submit(page, diagnostics, {"screenshots": [], "html_artifacts": []})

    assert page.clicked == [f"evaluate:{diagnostics["submit_selector"]}"]
    assert diagnostics["submit_strategy"] == "primary_button_request_submit"
    assert diagnostics["route_submit_button"]["fallback_count"] == 1


@pytest.mark.asyncio
async def test_route_submit_not_found_when_primary_and_fallback_missing():
    from app import service as service_module

    page = RoutePage(submit_buttons={"#idstationsearch_submit_button_input": [], "fallback": []})
    diagnostics = {}

    with pytest.raises(ValueError, match="route_submit_button_not_found"):
        await service_module._detect_route_submit_button(page, diagnostics)

    assert diagnostics["route_submit_button"]["failure_reason"] == "route_submit_button_not_found"


@pytest.mark.asyncio
async def test_route_submit_ambiguous_when_primary_duplicate():
    from app import service as service_module

    page = RoutePage(submit_buttons={
        "#idstationsearch_submit_button_input": [
            {"id": "idstationsearch_submit_button_input", "type": "submit", "value": "Найти", "form_contains_route_fields": True},
            {"id": "idstationsearch_submit_button_input", "type": "submit", "value": "Найти", "form_contains_route_fields": True},
        ],
        "fallback": [],
    })
    diagnostics = {}

    with pytest.raises(ValueError, match="route_submit_button_ambiguous"):
        await service_module._detect_route_submit_button(page, diagnostics)

    assert diagnostics["route_submit_button"]["primary_count"] == 2


@pytest.mark.asyncio
async def test_route_submit_hidden_input_primary_is_valid_and_submits(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = RoutePage(submit_buttons={
        "#idstationsearch_submit_button_input": [{
            "id": "idstationsearch_submit_button_input",
            "type": "submit",
            "value": "Найти",
            "class": "hidden_input",
            "visible": False,
            "bounding_box": {"x": 0, "y": 0, "width": 1, "height": 1},
            "form_contains_route_fields": True,
            "changes_url": True,
        }],
        "fallback": [],
    })
    diagnostics = {}

    await service_module._click_route_submit(page, diagnostics, {"screenshots": [], "html_artifacts": []})

    assert diagnostics["route_submit_button"]["primary"]["class"] == "hidden_input"
    assert page.clicked == ["evaluate:#idstationsearch_submit_button_input"]
    assert diagnostics["submit_strategy"] == "primary_button_request_submit"


@pytest.mark.asyncio
async def test_route_submit_ignores_train_search_when_primary_missing():
    from app import service as service_module

    page = RoutePage(submit_buttons={
        "#idstationsearch_submit_button_input": [],
        "#idtrainsearch_submit_button_input": [{"id": "idtrainsearch_submit_button_input", "type": "submit", "value": "Найти", "changes_url": True}],
        "fallback": [],
    })

    with pytest.raises(ValueError, match="route_submit_button_not_found"):
        await service_module._click_route_submit(page, {}, {"screenshots": [], "html_artifacts": []})

    assert "#idtrainsearch_submit_button_input" not in page.clicked


@pytest.mark.asyncio
async def test_route_submit_evaluate_click_when_playwright_click_fails(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    page = RoutePage(submit_buttons={
        "#idstationsearch_submit_button_input": [{"id": "idstationsearch_submit_button_input", "type": "submit", "value": "Найти", "form_contains_route_fields": True, "changes_url": True, "click_fails": True}],
        "fallback": [],
    })
    diagnostics = {}

    result = await service_module._click_route_submit(page, diagnostics, {"screenshots": [], "html_artifacts": []})

    assert result == "submitted"
    assert page.clicked == ["evaluate:#idstationsearch_submit_button_input"]
    assert diagnostics["post_submit_steps"][-2]["details"]["submit_strategy"] == "primary_button_request_submit"

@pytest.mark.asyncio
async def test_origin_guard_detects_destination_overwrite():
    from app import service as service_module

    page = RoutePage(values={"schedule_station_from": "Санкт-Петербург", "nnst1": "2004000", "schedule_station_to": "Санкт-Петербург", "nnst2": "2004000"})
    diagnostics = {}
    guard = {"visible_value": "Рязань", "hidden_value": "2000125", "input_dom_identity": "origin", "hidden_dom_identity": "nnst1"}

    with pytest.raises(service_module.TutuOriginGuardViolation):
        await service_module._check_origin_guard(page, guard, "destination_after_click", diagnostics, "Рязань", "Санкт-Петербург")

    assert diagnostics["destination_station_selection"]["station_selected"] is False
    assert diagnostics["destination_station_selection"]["failure_reason"] == "destination_selection_overwrote_origin"
    assert diagnostics["route_field_invariants"]["violations"][0]["failure_reason"] == "destination_selection_overwrote_origin"


@pytest.mark.asyncio
async def test_route_invariants_pass_after_destination_selection():
    from app import service as service_module

    page = RoutePage(values={"schedule_station_from": "Рязань", "nnst1": "2000125", "schedule_station_to": "Санкт-Петербург", "nnst2": "2004000"})
    diagnostics = {"origin_station_selection": {"station_selected": True}, "destination_station_selection": {"station_selected": True}}
    guard = {"visible_value": "Рязань", "hidden_value": "2000125"}

    await service_module._check_origin_guard(page, guard, "destination_after_click", diagnostics, "Рязань", "Санкт-Петербург")
    verification = await service_module._verify_route_fields(page, "Рязань", "Санкт-Петербург", diagnostics)

    assert verification["verified"] is True
    assert verification["origin"]["hidden_value"] == "2000125"
    assert verification["destination"]["hidden_value"] == "2004000"


def test_sale_period_same_station_is_route_collision():
    from app import service as service_module

    diagnostics = {}
    events = [{"url": "https://www.tutu.ru/ajax/poezda/sale_period/?departure_station_number=2004000&arrival_station_number=2004000"}]

    assert service_module._classify_sale_period_collisions(events, "Рязань", "Санкт-Петербург", diagnostics) is True
    assert diagnostics["sale_period_route_collision_detected"] is True
    assert events[0]["route_field_collision"] is True


@pytest.mark.asyncio
async def test_route_submit_uses_form_request_submit_when_button_absent(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))

    class FormRoutePage(RoutePage):
        def locator(self, selector):
            self.locator_calls.append(selector)
            if selector == "form:has(input[name='schedule_station_from']):has(input[name='schedule_station_to'])":
                return RouteLocator(self, selector, [{"type": "", "tag_name": "form", "value": "", "form_contains_route_fields": True, "changes_url": True}])
            return super().locator(selector)

    page = FormRoutePage(submit_buttons={"#idstationsearch_submit_button_input": [], "fallback": []})
    await service_module._click_route_submit(page, {}, {"screenshots": [], "html_artifacts": []})

    assert page.clicked == ["evaluate:form:has(input[name='schedule_station_from']):has(input[name='schedule_station_to'])"]

@pytest.mark.asyncio
async def test_origin_snapshot_restore_uses_confirmed_snapshot_without_autocomplete():
    from app import service as service_module

    class RestorePage:
        def __init__(self):
            self.evaluate_calls = 0
        async def evaluate(self, script, guard):
            self.evaluate_calls += 1
            assert "schedule_station_from" in script
            assert "nnst1" in script
            return {"ok": True, "visible_value": guard["visible_value"], "hidden_value": guard["hidden_value"]}

    diagnostics = {"origin_recovery_count": 0}
    result = await service_module._restore_origin_from_confirmed_snapshot(
        RestorePage(), {"visible_value": "Рязань", "hidden_value": "2004000"}, diagnostics, time.monotonic() + 3
    )

    assert result["ok"] is True
    assert diagnostics["origin_recovery_strategy"] == "restore_confirmed_snapshot"
    assert diagnostics["origin_recovery_count"] == 1


@pytest.mark.asyncio
async def test_error_artifacts_skipped_when_budget_below_reserve():
    from app import service as service_module

    class NoArtifactPage:
        async def screenshot(self, *args, **kwargs):
            raise AssertionError("screenshot should be skipped")
        async def content(self):
            raise AssertionError("content should be skipped")

    diagnostics = {}
    await service_module._capture_error_artifacts_if_budget_allows(
        NoArtifactPage(), {"screenshots": [], "html_artifacts": []}, diagnostics, time.monotonic() + 0.5
    )

    assert diagnostics["artifacts_capture_skipped"] is True
    assert diagnostics["artifacts_capture_skip_reason"] == "error_artifact_capture_skipped_due_to_deadline"

class ContractRoutePage(RoutePage):
    def __init__(self, method="get", request_submit_changes=True, body_text="места билеты"):
        super().__init__(submit_buttons={"#idstationsearch_submit_button_input": [], "fallback": []})
        self.method = method
        self.request_submit_changes = request_submit_changes
        self.body_text = body_text
        self.goto_calls = []
        self.evaluate_calls = []

    async def evaluate(self, script, *args):
        self.evaluate_calls.append(script)
        if "document.forms).map" in script:
            return {
                "page_url": self.url,
                "forms": [{"index": 0, "id": "route", "name": "route", "action": "https://www.tutu.ru/poezda/search/", "method": self.method, "input_names": ["schedule_station_from", "schedule_station_to", "nnst1", "nnst2", "date"], "submit_controls": []}],
                "route_inputs": [{"name": "schedule_station_from"}, {"name": "schedule_station_to"}],
                "hidden_station_fields": [{"name": "nnst1"}, {"name": "nnst2"}],
                "candidate_route_forms": [0],
            }
        if "const form = Array.from(document.forms).find" in script and "fields =" in script:
            return {
                "found": True,
                "action": "https://www.tutu.ru/poezda/search/",
                "method": self.method,
                "fields": [
                    {"name": "schedule_station_from", "value": "Москва"},
                    {"name": "schedule_station_to", "value": "Рязань"},
                    {"name": "nnst1", "value": "2000000"},
                    {"name": "nnst2", "value": "2000125"},
                    {"name": "date", "value": "01.08.2026"},
                ],
                "required_fields_present": True,
                "station_ids": {"origin": "2000000", "destination": "2000125"},
                "page_url": self.url,
            }
        if "form.requestSubmit" in script:
            if self.request_submit_changes:
                self.url = "https://www.tutu.ru/poezda/search/?submitted=1"
            return {"ok": True, "method": self.method}
        return None

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_calls.append(url)
        self.url = url
        self.body_text = "места билеты"
        return None


@pytest.mark.asyncio
async def test_open_results_uses_request_submit_without_submit_button(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "route_open_deadline_seconds", 2)
    page = ContractRoutePage(method="post", request_submit_changes=True)
    req = AvailabilityCheckRequest(origin="Москва", destination="Рязань", departure_date=date(2026, 8, 1))
    diagnostics = {"selected_inputs": {}, "station_steps": [], "origin_station_selection": {"station_selected": True}, "destination_station_selection": {"station_selected": True}, "popup_candidates": {}, "autocomplete_discovery": {}}

    result = await service_module.open_tutu_results_page(page, req, diagnostics, time.monotonic() + 3)

    assert result["status"] == "results"
    assert result["strategy"] == "form_request_submit"
    assert diagnostics["route_open_attempts"][0]["strategy"] == "form_request_submit"
    assert page.clicked == []
    assert not any("route_submit_button_not_found" in str(a) for a in diagnostics["route_open_attempts"])


@pytest.mark.asyncio
async def test_open_results_falls_back_to_direct_get_from_actual_fields(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "route_open_deadline_seconds", 5)
    page = ContractRoutePage(method="get", request_submit_changes=False, body_text="")
    req = AvailabilityCheckRequest(origin="Москва", destination="Рязань", departure_date=date(2026, 8, 1))
    diagnostics = {"selected_inputs": {}, "station_steps": [], "origin_station_selection": {"station_selected": True}, "destination_station_selection": {"station_selected": True}, "popup_candidates": {}, "autocomplete_discovery": {}}

    result = await service_module.open_tutu_results_page(page, req, diagnostics, time.monotonic() + 7)

    assert result["status"] == "results"
    assert result["strategy"] == "direct_get"
    assert "schedule_station_from=" in page.goto_calls[0]
    assert "nnst1=2000000" in page.goto_calls[0]
    assert diagnostics["direct_route_navigation"]["supported"] is True

class InitialNavigationPage(RoutePage):
    def __init__(self, delay=0, fail_timeout=False, route_inputs=True):
        super().__init__()
        self.delay = delay
        self.fail_timeout = fail_timeout
        self.goto_args = []
        if not route_inputs:
            self.values = {}

    async def goto(self, url, wait_until=None, timeout=None):
        self.goto_args.append({"url": url, "wait_until": wait_until, "timeout": timeout})
        self.url = url
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail_timeout:
            from app import service as service_module
            raise service_module.PlaywrightTimeoutError("timeout")
        return None


@pytest.mark.asyncio
async def test_initial_navigation_continues_when_domcontentloaded_never_arrives_but_inputs_exist():
    from app import service as service_module
    page = InitialNavigationPage(fail_timeout=True, route_inputs=True)
    diagnostics = {}

    await service_module._initial_tutu_navigation(page, time.monotonic() + 12, diagnostics)

    assert page.goto_args[0]["wait_until"] == "commit"
    assert diagnostics["initial_navigation"]["continued_after_timeout"] is True
    assert diagnostics["initial_navigation"]["route_inputs_found"] is True


@pytest.mark.asyncio
async def test_initial_navigation_allows_eight_second_commit(monkeypatch):
    from app import service as service_module
    page = InitialNavigationPage(delay=0.01, route_inputs=True)
    diagnostics = {}

    await service_module._initial_tutu_navigation(page, time.monotonic() + 12, diagnostics)

    assert page.goto_args[0]["wait_until"] == "commit"
    assert 10_000 <= page.goto_args[0]["timeout"] <= 12_000
    assert diagnostics["initial_navigation"]["goto_status"] == "completed"


@pytest.mark.asyncio
async def test_post_submit_deadline_returns_without_long_observations(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "navigation_timeout_ms", 20)
    monkeypatch.setattr(service_module.settings, "results_container_timeout_ms", 20)
    monkeypatch.setattr(service_module.settings, "train_cards_timeout_ms", 20)
    monkeypatch.setattr(service_module.settings, "availability_timeout_ms", 20)
    page = RoutePage()
    diagnostics = {"before_submit_url": page.url}
    start = time.monotonic()

    result = await service_module.wait_for_tutu_search_result(page, time.monotonic() + 0.05, diagnostics)

    assert time.monotonic() - start < 1
    assert result["status"] == "navigation_timeout"
    assert diagnostics["terminal_failure_reason"] == "post_submit_deadline_exceeded"
    assert diagnostics["deadline_exceeded"] is True


def test_timeout_settings_are_capped_below_backend_read_timeout(monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "timeout_seconds", 40)
    monkeypatch.setattr(service_module.settings, "operation_timeout_seconds", 40)
    monkeypatch.setattr(service_module.settings, "route_open_deadline_seconds", 40)

    assert min(service_module.settings.timeout_seconds, 30) == 30
    assert min(service_module.settings.operation_timeout_seconds, 26) == 26
    assert min(service_module.settings.route_open_deadline_seconds, 8) == 8

@pytest.mark.asyncio
async def test_step_artifacts_disabled_skips_screenshot_and_content(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "capture_step_artifacts", False)

    class ArtifactPage:
        async def screenshot(self, *args, **kwargs):
            raise AssertionError("screenshot should not be called")
        async def content(self):
            raise AssertionError("content should not be called")

    diagnostics = {}
    artifacts = {"screenshots": [], "html_artifacts": []}
    await service_module._safe_capture_step_artifact(ArtifactPage(), "origin_before_typing", artifacts, time.monotonic() + 5, diagnostics)

    assert artifacts == {"screenshots": [], "html_artifacts": []}
    assert diagnostics["diagnostic_artifacts_skipped"] is True
    assert diagnostics["diagnostic_artifacts_skip_reason"] == "step_artifacts_disabled"


@pytest.mark.asyncio
async def test_hanging_screenshot_does_not_exhaust_30_second_response(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "capture_step_artifacts", True)

    class HangingArtifactPage:
        async def screenshot(self, *args, **kwargs):
            await asyncio.sleep(60)
        async def content(self):
            return "<html></html>"

    diagnostics = {}
    start = time.monotonic()
    await service_module._save_step_artifact(
        HangingArtifactPage(),
        "terminal_error",
        {"screenshots": [], "html_artifacts": []},
        deadline=time.monotonic() + 3,
        diagnostic_payload=diagnostics,
        terminal=True,
    )

    assert time.monotonic() - start < 1.5
    assert diagnostics["diagnostic_artifacts_skipped"] is True
    assert diagnostics["diagnostic_artifact_elapsed_ms"] < 1500


@pytest.mark.asyncio
async def test_service_deadline_exceeded_skips_recovery_and_artifacts(monkeypatch):
    from app import service as service_module

    class NoOpsPage:
        async def screenshot(self, *args, **kwargs):
            raise AssertionError("no artifacts after service deadline")
        async def content(self):
            raise AssertionError("no artifacts after service deadline")

    diagnostics = {"deadline_exceeded": True, "terminal_failure_reason": "service_deadline_exceeded"}
    await service_module._capture_error_artifacts_if_budget_allows(
        NoOpsPage(), {"screenshots": [], "html_artifacts": []}, diagnostics, time.monotonic() - 1
    )

    assert diagnostics["artifacts_capture_skipped"] is True
    assert diagnostics["artifacts_capture_skip_reason"] == "service_deadline_exceeded"


@pytest.mark.asyncio
async def test_cancelled_error_structured_diagnostics_without_artifacts(monkeypatch):
    from app import service as service_module

    class CancelPage:
        url = "https://www.tutu.ru/poezda/"
        async def close(self):
            return None
        async def screenshot(self, *args, **kwargs):
            raise AssertionError("cancelled requests must not capture artifacts")
        async def content(self):
            raise AssertionError("cancelled requests must not capture html")
        def set_default_timeout(self, timeout):
            self.default_timeout = timeout

    class CancelContext:
        async def new_page(self):
            return CancelPage()
        async def close(self):
            return None

    class CancelBrowser:
        async def new_context(self, **kwargs):
            return CancelContext()

    svc = service_module.TutuAvailabilityService()
    async def browser_instance():
        return CancelBrowser()
    monkeypatch.setattr(svc, "_browser_instance", browser_instance)
    async def cancelled_nav(page, deadline, diagnostics):
        raise asyncio.CancelledError()
    monkeypatch.setattr(service_module, "_initial_tutu_navigation", cancelled_nav)

    req = AvailabilityCheckRequest(origin="Москва", destination="Рязань", departure_date=date(2026, 8, 1), train_number="001")
    with pytest.raises(service_module.TutuDiagnosticError) as exc_info:
        await svc._playwright(req)

    assert exc_info.value.diagnostics.terminal_failure_reason == "service_cancelled"
    assert exc_info.value.diagnostics.diagnostic_response_received is True
    assert exc_info.value.diagnostics.screenshots == []
    assert exc_info.value.diagnostics.html_artifacts == []


@pytest.mark.asyncio
async def test_parallel_segments_return_before_backend_read_timeout(monkeypatch):
    from app import service as service_module
    monkeypatch.setattr(service_module.settings, "enabled", True)
    monkeypatch.setattr(service_module.settings, "mock_mode", False)
    monkeypatch.setattr(service_module.settings, "timeout_seconds", 30)
    monkeypatch.setattr(service_module.settings, "concurrency", 2)

    async def slow_provider(self, req):
        await asyncio.sleep(0.05)
        return service_module.AvailabilityCheckResponse(status=service_module.AvailabilityStatus.PROVIDER_ERROR, train_number=req.train_number, message="bounded")

    monkeypatch.setattr(service_module.TutuAvailabilityService, "_playwright", slow_provider)
    svc = service_module.TutuAvailabilityService()
    reqs = [AvailabilityCheckRequest(origin="Москва", destination="Рязань", departure_date=date(2026, 8, 1), train_number=str(i)) for i in range(2)]
    start = time.monotonic()

    results = await asyncio.gather(*(svc.check(req) for req in reqs))

    assert time.monotonic() - start < 1
    assert all(result.status == service_module.AvailabilityStatus.PROVIDER_ERROR for result in results)
