from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.monitoring.models import MonitoringHistory

DEFAULT_MONITORING_HISTORY_FILE = "data/monitoring-history.json"


class MonitoringHistoryRepository(ABC):
    @abstractmethod
    def add(self, item: MonitoringHistory) -> MonitoringHistory: ...

    @abstractmethod
    def list(self, saved_search_id: str | None = None) -> list[MonitoringHistory]: ...

    def latest(self, saved_search_id: str) -> MonitoringHistory | None:
        items = self.list(saved_search_id)
        return items[0] if items else None


class FileMonitoringHistoryRepository(MonitoringHistoryRepository):
    def __init__(self, file_path: str | Path | None = None):
        self.file_path = Path(file_path or os.getenv("MONITORING_HISTORY_FILE", DEFAULT_MONITORING_HISTORY_FILE))
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists() or not self.file_path.read_text(encoding="utf-8").strip():
            self._write_all([])

    def _read_all(self) -> list[MonitoringHistory]:
        if not self.file_path.exists() or not self.file_path.read_text(encoding="utf-8").strip():
            return []
        with self.file_path.open(encoding="utf-8") as source:
            return [MonitoringHistory.model_validate(item) for item in json.load(source)]

    def _write_all(self, items: list[MonitoringHistory]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.file_path.parent, delete=False) as tmp:
            json.dump([item.model_dump(mode="json") for item in items], tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.file_path)

    def add(self, item: MonitoringHistory) -> MonitoringHistory:
        items = self._read_all()
        items.append(item)
        self._write_all(items)
        return item

    def list(self, saved_search_id: str | None = None) -> list[MonitoringHistory]:
        items = self._read_all()
        if saved_search_id is not None:
            items = [item for item in items if item.saved_search_id == saved_search_id]
        return sorted(items, key=lambda item: item.checked_at, reverse=True)
