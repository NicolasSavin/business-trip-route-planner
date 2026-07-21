from fastapi import HTTPException

from app.api import notifications as api_module
from app.monitoring.models import MonitoringHistory, MonitoringResult, MonitoringStatus
from app.notifications import FileNotificationRepository, Notification, NotificationEngine, NotificationService, NotificationSeverity, NotificationType


def test_notification_repository_read_all_delete_and_unread_counter(tmp_path):
    repo = FileNotificationRepository(tmp_path / "notifications.json")
    first = repo.add(Notification(saved_search_id="s1", type=NotificationType.NEW_ROUTE, title="Новый", message="Маршрут"))
    second = repo.add(Notification(saved_search_id="s1", type=NotificationType.SEATS_AVAILABLE, title="Места", message="Есть места"))

    assert len(repo.unread()) == 2
    assert repo.mark_read(first.id).is_read is True
    assert [item.id for item in repo.unread()] == [second.id]
    assert all(item.is_read for item in repo.mark_all_read())
    assert repo.unread() == []
    assert repo.delete(second.id) is True
    assert repo.delete("missing") is False


def test_notification_engine_creates_only_when_monitoring_changed(tmp_path):
    service = NotificationService(FileNotificationRepository(tmp_path / "notifications.json"))
    engine = NotificationEngine(service)
    history = MonitoringHistory(saved_search_id="s1", duration_ms=10, routes_found=2, available_routes=1, status=MonitoringStatus.SUCCESS, change_detected=True, summary="Появились места для группы", changes=["Появились места для группы"])
    result = MonitoringResult(saved_search_id="s1", is_changed=True, changes=history.changes, summary=history.summary, history=history)

    notification = engine.notify_monitoring_result(result)

    assert notification is not None
    assert notification.type == NotificationType.SEATS_AVAILABLE
    assert notification.severity == NotificationSeverity.SUCCESS
    unchanged = history.model_copy(update={"change_detected": False, "changes": [], "summary": "Без изменений"})
    assert engine.notify_monitoring_result(MonitoringResult(saved_search_id="s1", is_changed=False, changes=[], summary="Без изменений", history=unchanged)) is None


def test_notification_engine_failed_and_resumed(tmp_path):
    service = NotificationService(FileNotificationRepository(tmp_path / "notifications.json"))
    engine = NotificationEngine(service)
    previous = MonitoringHistory(saved_search_id="s1", duration_ms=1, routes_found=0, available_routes=0, status=MonitoringStatus.FAILED, summary="Ошибка")
    failed_result = MonitoringResult(saved_search_id="s1", is_changed=False, summary="Ошибка", history=previous)
    assert engine.notify_monitoring_result(failed_result).type == NotificationType.MONITORING_FAILED

    resumed = MonitoringHistory(saved_search_id="s1", duration_ms=1, routes_found=1, available_routes=1, status=MonitoringStatus.SUCCESS, summary="Без изменений")
    resumed_result = MonitoringResult(saved_search_id="s1", is_changed=False, summary="Без изменений", history=resumed)
    assert engine.notify_monitoring_result(resumed_result, previous).type == NotificationType.MONITORING_RESUMED


def test_notifications_api_read_read_all_delete_and_unread_counter(monkeypatch, tmp_path):
    repo = FileNotificationRepository(tmp_path / "notifications.json")
    service = NotificationService(repo)
    monkeypatch.setattr(api_module, "notification_repository", repo)
    monkeypatch.setattr(api_module, "service", service)
    item = repo.add(Notification(saved_search_id="s1", type=NotificationType.NEW_ROUTE, title="Новый", message="Маршрут"))
    repo.add(Notification(saved_search_id="s2", type=NotificationType.PRICE_CHANGED, title="Цена", message="Изменилась", severity=NotificationSeverity.WARNING))

    assert len(api_module.list_notifications()) == 2
    assert len(api_module.unread_notifications()) == 2
    assert api_module.mark_notification_read(item.id).is_read is True
    assert len(api_module.unread_notifications()) == 1
    assert len(api_module.mark_all_notifications_read()) == 2
    assert api_module.unread_notifications() == []
    api_module.delete_notification(item.id)
    with pytest_raises_404():
        api_module.delete_notification("missing")


class pytest_raises_404:
    def __enter__(self):
        import pytest
        self.ctx = pytest.raises(HTTPException)
        self.exc = self.ctx.__enter__()
        return self.exc

    def __exit__(self, *args):
        result = self.ctx.__exit__(*args)
        assert self.exc.value.status_code == 404
        return result
