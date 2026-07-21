from __future__ import annotations

from app.notifications.models import Notification
from app.notifications.repository import NotificationRepository


class NotificationService:
    def __init__(self, repository: NotificationRepository):
        self.repository = repository

    def create(self, notification: Notification) -> Notification:
        return self.repository.add(notification)

    def list(self) -> list[Notification]:
        return self.repository.list()

    def unread(self) -> list[Notification]:
        return self.repository.unread()

    def mark_read(self, item_id: str) -> Notification | None:
        return self.repository.mark_read(item_id)

    def mark_all_read(self) -> list[Notification]:
        return self.repository.mark_all_read()

    def delete(self, item_id: str) -> bool:
        return self.repository.delete(item_id)
