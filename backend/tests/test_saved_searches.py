import pytest
from fastapi import HTTPException

from app.api import saved_searches as api_module
from app.models.saved_searches import LastCheckStatus, SavedSearchCreate, SavedSearchUpdate
from app.services.saved_searches import FileSavedSearchRepository, SavedSearchService


def payload(**overrides):
    data = {
        "origin": "Москва",
        "destination": "Екатеринбург",
        "departure_date": "2026-08-10",
        "passengers": 2,
        "allowed_transport": ["train", "bus"],
        "max_transfers": 2,
        "minimum_transfer_minutes": 30,
    }
    data.update(overrides)
    return data


@pytest.fixture()
def service(tmp_path):
    return SavedSearchService(FileSavedSearchRepository(tmp_path / "saved-searches.json"), api_module.service.route_search)


def test_create_list_get_update_toggle_delete(service):
    item = service.create(SavedSearchCreate(**payload(title="Тестовая заявка")))
    assert item.title == "Тестовая заявка"
    assert service.list()[0].id == item.id
    assert service.get(item.id).origin == "Москва"
    assert service.update(item.id, SavedSearchUpdate(title="Новое название")).title == "Новое название"
    assert service.update(item.id, SavedSearchUpdate(monitoring_enabled=False)).monitoring_enabled is False
    assert service.update(item.id, SavedSearchUpdate(monitoring_enabled=True)).monitoring_enabled is True
    assert service.delete(item.id) is True
    assert service.get(item.id) is None


def test_api_functions_return_404_for_missing_saved_search(monkeypatch, service):
    monkeypatch.setattr(api_module, "service", service)
    for call in (
        lambda: api_module.get_saved_search("missing"),
        lambda: api_module.update_saved_search("missing", SavedSearchUpdate(title="Нет")),
        lambda: api_module.delete_saved_search("missing"),
        lambda: api_module.check_saved_search("missing"),
    ):
        with pytest.raises(HTTPException) as exc:
            call()
        assert exc.value.status_code == 404


def test_manual_check_with_found_routes(service):
    item = service.create(SavedSearchCreate(**payload(title="Тестовая заявка")))
    checked, routes = service.check(item.id)
    assert routes
    assert checked.last_check_status == LastCheckStatus.ROUTES_FOUND
    assert checked.last_routes_count >= checked.last_available_routes_count > 0


def test_manual_check_without_available_routes(service):
    item = service.create(SavedSearchCreate(**payload(passengers=100, title="Большая группа")))
    checked, routes = service.check(item.id)
    assert routes
    assert checked.last_check_status == LastCheckStatus.NO_AVAILABLE_ROUTES
    assert checked.last_routes_count >= 1
    assert checked.last_available_routes_count == 0


def test_manual_check_saves_error_and_clears_checking(tmp_path):
    class BrokenSearch:
        def search(self, request, include_unavailable=False):
            raise RuntimeError("Искусственная ошибка")

    service = SavedSearchService(FileSavedSearchRepository(tmp_path / "saved-searches.json"), BrokenSearch())
    item = service.create(SavedSearchCreate(**payload()))
    with pytest.raises(RuntimeError):
        service.check(item.id)
    stored = service.get(item.id)
    assert stored.last_check_status == LastCheckStatus.FAILED
    assert stored.last_error == "Искусственная ошибка"


def test_repository_restores_from_json_and_handles_missing_file(tmp_path, service):
    path = tmp_path / "nested" / "saved-searches.json"
    repository = FileSavedSearchRepository(path)
    assert repository.list() == []
    created = SavedSearchService(repository, service.route_search).create(SavedSearchCreate(**payload(title="Из файла")))
    restored = FileSavedSearchRepository(path)
    assert restored.get(created.id).title == "Из файла"


def test_repository_safe_write_uses_replacement_file(tmp_path, service):
    path = tmp_path / "saved-searches.json"
    repository = FileSavedSearchRepository(path)
    item = SavedSearchService(repository, service.route_search).create(SavedSearchCreate(**payload()))
    assert path.exists()
    assert item.id in path.read_text(encoding="utf-8")
    assert not list(tmp_path.glob("tmp*"))
