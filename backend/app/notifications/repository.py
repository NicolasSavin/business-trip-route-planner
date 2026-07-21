from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.notifications.models import Notification

DEFAULT_NOTIFICATIONS_FILE = "data/notifications.json"


class NotificationRepository(ABC):
    @abstractmethod
    def add(self, item: Notification) -> Notification: ...

    @abstractmethod
    def list(self) -> list[Notification]: ...

    @abstractmethod
    def unread(self) -> list[Notification]: ...

    @abstractmethod
    def get(self, item_id: str) -> Notification | None: ...

    @abstractmethod
    def mark_read(self, item_id: str) -> Notification | None: ...

    @abstractmethod
    def mark_all_read(self) -> list[Notification]: ...

    @abstractmethod
    def delete(self, item_id: str) -> bool: ...


class FileNotificationRepository(NotificationRepository):
    def __init__(self, file_path: str | Path | None = None):
        self.file_path = Path(file_path or os.getenv("NOTIFICATIONS_FILE", DEFAULT_NOTIFICATIONS_FILE))
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists() or not self.file_path.read_text(encoding="utf-8").strip():
            self._write_all([])

    def _read_all(self) -> list[Notification]:
        if not self.file_path.exists() or not self.file_path.read_text(encoding="utf-8").strip():
            return []
        with self.file_path.open(encoding="utf-8") as source:
            payload = json.load(source)
        return [Notification.model_validate(item) for item in payload]

    def _write_all(self, items: list[Notification]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in items]
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.file_path.parent, delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.file_path)

    def add(self, item: Notification) -> Notification:
        items = self._read_all()
        items.append(item)
        self._write_all(items)
        return item

    def list(self) -> list[Notification]:
        return sorted(self._read_all(), key=lambda item: item.created_at, reverse=True)

    def unread(self) -> list[Notification]:
        return [item for item in self.list() if not item.is_read]

    def get(self, item_id: str) -> Notification | None:
        return next((item for item in self._read_all() if item.id == item_id), None)

    def mark_read(self, item_id: str) -> Notification | None:
        items = self._read_all()
        for index, item in enumerate(items):
            if item.id == item_id:
                updated = item.model_copy(update={"is_read": True})
                items[index] = updated
                self._write_all(items)
                return updated
        return None

    def mark_all_read(self) -> list[Notification]:
        items = [item.model_copy(update={"is_read": True}) for item in self._read_all()]
        self._write_all(items)
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def delete(self, item_id: str) -> bool:
        items = self._read_all()
        filtered = [item for item in items if item.id != item_id]
        if len(filtered) == len(items):
            return False
        self._write_all(filtered)
        return True
