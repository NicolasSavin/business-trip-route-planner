from __future__ import annotations

from app.monitoring.models import MonitoringHistory, MonitoringResult, MonitoringStatus
from app.notifications.models import Notification, NotificationSeverity, NotificationType
from app.notifications.service import NotificationService


class NotificationEngine:
    def __init__(self, service: NotificationService):
        self.service = service

    def notify_monitoring_result(self, result: MonitoringResult, previous: MonitoringHistory | None = None) -> Notification | None:
        if result.history.status == MonitoringStatus.FAILED:
            return self._create(result.saved_search_id, NotificationType.MONITORING_FAILED, "Мониторинг не выполнен", result.summary, NotificationSeverity.CRITICAL, result)
        if previous is not None and previous.status == MonitoringStatus.FAILED and result.history.status == MonitoringStatus.SUCCESS:
            return self._create(result.saved_search_id, NotificationType.MONITORING_RESUMED, "Мониторинг восстановлен", "Проверка заявки снова выполняется успешно.", NotificationSeverity.SUCCESS, result)
        if not result.is_changed:
            return None
        notification_type, severity, title = self._classify(result.changes)
        return self._create(result.saved_search_id, notification_type, title, result.summary, severity, result)

    def _classify(self, changes: list[str]) -> tuple[NotificationType, NotificationSeverity, str]:
        text = " ".join(changes).lower()
        if "места для группы" in text or "доступных маршрутов стало больше" in text:
            return NotificationType.SEATS_AVAILABLE, NotificationSeverity.SUCCESS, "Появились места"
        if "новые маршруты" in text or "маршрутов стало больше" in text or "первичная проверка" in text:
            return NotificationType.NEW_ROUTE, NotificationSeverity.INFO, "Найдены изменения маршрутов"
        if "score" in text or "лучшего маршрута" in text:
            return NotificationType.BETTER_ROUTE, NotificationSeverity.SUCCESS, "Найден более выгодный маршрут"
        if "цен" in text or "price" in text:
            return NotificationType.PRICE_CHANGED, NotificationSeverity.WARNING, "Изменилась цена"
        return NotificationType.NEW_ROUTE, NotificationSeverity.INFO, "Есть изменения в мониторинге"

    def _create(self, saved_search_id: str, notification_type: NotificationType, title: str, message: str, severity: NotificationSeverity, result: MonitoringResult) -> Notification:
        provider_suffix = f" Источник: {', '.join(result.history.provider_ids)}." if result.history.provider_ids else ""
        return self.service.create(Notification(saved_search_id=saved_search_id, type=notification_type, title=title, message=message + provider_suffix, severity=severity, metadata={"history_id": result.history.id, "changes": result.changes, "checked_at": result.timestamp.isoformat(), "providers": result.history.provider_ids}))
