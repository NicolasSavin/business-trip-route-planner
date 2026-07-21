from datetime import date

import pytest
from fastapi import HTTPException

from app.api import monitoring as api_module
from app.models.saved_searches import SavedSearch, SavedSearchCreate
from app.monitoring import MonitoringEngine, MonitoringScheduler, MonitoringService
from app.monitoring.history import FileMonitoringHistoryRepository
from app.monitoring.models import MonitoringHistory, MonitoringStatus
from app.providers.mock import MockTransportProvider
from app.services.route_search import RouteSearchService
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
def monitoring(tmp_path):
    saved_repo = FileSavedSearchRepository(tmp_path / "saved.json")
    history_repo = FileMonitoringHistoryRepository(tmp_path / "history.json")
    saved_service = SavedSearchService(saved_repo, RouteSearchService(MockTransportProvider()))
    engine = MonitoringEngine(RouteSearchService(MockTransportProvider()), history_repo)
    service = MonitoringService(saved_repo, engine, history_repo)
    return saved_service, history_repo, engine, service, MonitoringScheduler(service)


def test_monitoring_engine_records_history_without_changing_saved_search(monitoring):
    saved_service, history_repo, _engine, service, _scheduler = monitoring
    item = saved_service.create(SavedSearchCreate(**payload(title="Мониторинг")))
    before = saved_service.get(item.id)
    result = service.run_one(item.id)
    after = saved_service.get(item.id)

    assert result.is_changed is True
    assert result.history.routes_found > 0
    assert result.history.available_routes > 0
    assert history_repo.list(item.id)[0].id == result.history.id
    assert after == before


def test_change_detection_finds_new_routes_available_routes_score_and_seats(monitoring):
    _saved_service, history_repo, engine, _service, _scheduler = monitoring
    saved = SavedSearch(**payload(title="Сравнение"))
    previous = MonitoringHistory(
        saved_search_id=saved.id,
        duration_ms=1,
        routes_found=0,
        available_routes=0,
        best_score=0.1,
        status=MonitoringStatus.SUCCESS,
        summary="old",
        route_ids=[],
        free_seats=0,
    )
    history_repo.add(previous)
    routes = RouteSearchService(MockTransportProvider()).search(saved.to_search_request(), include_unavailable=True)

    changes = engine.detect_changes(previous, routes)

    assert any("новые маршруты" in change for change in changes)
    assert any("Доступных маршрутов стало больше" in change for change in changes)
    assert any("Появились места" in change for change in changes)
    assert any("score" in change for change in changes)
    assert any("Свободных мест" in change for change in changes)


def test_monitoring_history_repository_persists_records(tmp_path):
    path = tmp_path / "history.json"
    repo = FileMonitoringHistoryRepository(path)
    record = repo.add(MonitoringHistory(saved_search_id="s1", duration_ms=12, routes_found=3, available_routes=2, status=MonitoringStatus.SUCCESS, summary="ok"))

    restored = FileMonitoringHistoryRepository(path)

    assert restored.latest("s1").id == record.id
    assert restored.list("missing") == []


def test_scheduler_run_one_and_prevents_parallel_run(monitoring):
    saved_service, _history_repo, _engine, service, scheduler = monitoring
    item = saved_service.create(SavedSearchCreate(**payload()))
    lock = scheduler._lock_for(item.id)
    assert lock.acquire(blocking=False) is True
    try:
        assert scheduler.run_one(item.id) is None
        assert scheduler.run_log[-1].status == MonitoringStatus.SKIPPED
    finally:
        lock.release()

    result = scheduler.run_one(item.id)
    assert result.saved_search_id == item.id
    assert scheduler.run_log[-1].status == MonitoringStatus.SUCCESS


def test_scheduler_run_all_checks_only_active_searches(monitoring):
    saved_service, _history_repo, _engine, _service, scheduler = monitoring
    active = saved_service.create(SavedSearchCreate(**payload(title="active")))
    saved_service.create(SavedSearchCreate(**payload(title="paused", monitoring_enabled=False)))

    results = scheduler.run_all()

    assert [result.saved_search_id for result in results] == [active.id]
    assert scheduler.run_log[-1].summary == "Проверено заявок: 1"


def test_monitoring_api_run_and_history(monkeypatch, monitoring):
    saved_service, history_repo, engine, service, scheduler = monitoring
    item = saved_service.create(SavedSearchCreate(**payload()))
    monkeypatch.setattr(api_module, "saved_search_repository", saved_service.repository)
    monkeypatch.setattr(api_module, "history_repository", history_repo)
    monkeypatch.setattr(api_module, "monitoring_engine", engine)
    monkeypatch.setattr(api_module, "service", service)
    monkeypatch.setattr(api_module, "scheduler", scheduler)

    result = api_module.run_monitoring(item.id)

    assert result.saved_search_id == item.id
    assert api_module.monitoring_history(item.id)
    with pytest.raises(HTTPException) as exc:
        api_module.run_monitoring("missing")
    assert exc.value.status_code == 404
