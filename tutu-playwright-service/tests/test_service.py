import pytest
from httpx import ASGITransport, AsyncClient
from app.main import app
from app.service import service

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

class MockKeyboardTextbox:
    def __init__(self, page):
        self.page = page
        self.value = ""
        self.pressed = []

    async def fill(self, value):
        self.value = value
        self.page.autocomplete_open = True

    async def press(self, key):
        self.pressed.append(key)
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
    assert step["typing_strategy"] in {"press_sequentially", "keyboard_insert_text_with_keyup_fallback"}
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
