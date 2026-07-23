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

    assert page.textbox.pressed == []
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
