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
async def test_select_location_arrow_down_enter_fallback():
    from app.service import select_location

    page = MockPage(["Тула"])
    value = await select_location(page, page.textbox, "Рязань", "origin")

    assert value == "Рязань"
    assert page.textbox.pressed == ["ArrowDown", "Enter"]


@pytest.mark.asyncio
async def test_select_location_no_suggestion_saves_artifacts(tmp_path, monkeypatch):
    from app import service as service_module

    monkeypatch.setattr(service_module.settings, "artifact_dir", str(tmp_path))
    monkeypatch.setattr(service_module, "LOCATION_AUTOCOMPLETE_TIMEOUT_MS", 1)
    page = MockPage([])

    with pytest.raises(ValueError, match="Location suggestion not found: Рязань"):
        await service_module.select_location(page, page.textbox, "Рязань", "origin")

    assert page.screenshots
    assert list(tmp_path.glob("location-origin-*.html"))
