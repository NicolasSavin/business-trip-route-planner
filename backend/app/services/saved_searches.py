from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from tempfile import NamedTemporaryFile

from app.models.saved_searches import LastCheckStatus, SavedSearch, SavedSearchCreate, SavedSearchUpdate, utc_now
from app.services.route_search import RouteSearchService

DEFAULT_SAVED_SEARCHES_FILE = "data/saved-searches.json"


class SavedSearchRepository(ABC):
    @abstractmethod
    def create(self, item: SavedSearch) -> SavedSearch: ...

    @abstractmethod
    def list(self) -> list[SavedSearch]: ...

    @abstractmethod
    def get(self, item_id: str) -> SavedSearch | None: ...

    @abstractmethod
    def update(self, item: SavedSearch) -> SavedSearch: ...

    @abstractmethod
    def delete(self, item_id: str) -> bool: ...


class FileSavedSearchRepository(SavedSearchRepository):
    def __init__(self, file_path: str | Path | None = None):
        self.file_path = Path(file_path or os.getenv("SAVED_SEARCHES_FILE", DEFAULT_SAVED_SEARCHES_FILE))
        self._ensure_file()

    def _ensure_file(self) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.file_path.exists() or not self.file_path.read_text(encoding="utf-8").strip():
            self._write_all([])

    def _read_all(self) -> list[SavedSearch]:
        if not self.file_path.exists() or not self.file_path.read_text(encoding="utf-8").strip():
            return []
        with self.file_path.open(encoding="utf-8") as source:
            payload = json.load(source)
        return [SavedSearch.model_validate(item) for item in payload]

    def _write_all(self, items: list[SavedSearch]) -> None:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        payload = [item.model_dump(mode="json") for item in items]
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.file_path.parent, delete=False) as tmp:
            json.dump(payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        tmp_path.replace(self.file_path)

    def create(self, item: SavedSearch) -> SavedSearch:
        items = self._read_all()
        items.append(item)
        self._write_all(items)
        return item

    def list(self) -> list[SavedSearch]:
        return sorted(self._read_all(), key=lambda item: item.created_at, reverse=True)

    def get(self, item_id: str) -> SavedSearch | None:
        return next((item for item in self._read_all() if item.id == item_id), None)

    def update(self, item: SavedSearch) -> SavedSearch:
        items = self._read_all()
        for index, existing in enumerate(items):
            if existing.id == item.id:
                items[index] = item
                self._write_all(items)
                return item
        raise KeyError(item.id)

    def delete(self, item_id: str) -> bool:
        items = self._read_all()
        filtered = [item for item in items if item.id != item_id]
        if len(filtered) == len(items):
            return False
        self._write_all(filtered)
        return True


class SavedSearchService:
    def __init__(self, repository: SavedSearchRepository, route_search: RouteSearchService):
        self.repository = repository
        self.route_search = route_search

    def create(self, request: SavedSearchCreate) -> SavedSearch:
        title = request.title or f"{request.origin} → {request.destination}, {request.departure_date.isoformat()}"
        now = utc_now()
        return self.repository.create(SavedSearch(**request.model_dump(exclude={"title"}), title=title, created_at=now, updated_at=now))

    def list(self) -> list[SavedSearch]:
        return self.repository.list()

    def get(self, item_id: str) -> SavedSearch | None:
        return self.repository.get(item_id)

    def update(self, item_id: str, patch: SavedSearchUpdate) -> SavedSearch | None:
        item = self.repository.get(item_id)
        if item is None:
            return None
        changes = patch.model_dump(exclude_unset=True)
        return self.repository.update(item.model_copy(update={**changes, "updated_at": utc_now()}))

    def delete(self, item_id: str) -> bool:
        return self.repository.delete(item_id)

    def check(self, item_id: str):
        item = self.repository.get(item_id)
        if item is None:
            return None
        checking = item.model_copy(update={"last_check_status": LastCheckStatus.CHECKING, "updated_at": utc_now(), "last_error": None})
        self.repository.update(checking)
        try:
            routes = self.route_search.search(checking.to_search_request(), include_unavailable=True)
            available = [route for route in routes if route.is_available_for_group]
            status = LastCheckStatus.ROUTES_FOUND if available else LastCheckStatus.NO_AVAILABLE_ROUTES
            updated = checking.model_copy(update={
                "last_checked_at": utc_now(), "last_check_status": status, "last_routes_count": len(routes),
                "last_available_routes_count": len(available), "last_error": None, "updated_at": utc_now(),
            })
            self.repository.update(updated)
            return updated, routes
        except Exception as exc:
            updated = checking.model_copy(update={
                "last_checked_at": utc_now(), "last_check_status": LastCheckStatus.FAILED,
                "last_error": str(exc) or "Проверка не выполнена", "updated_at": utc_now(),
            })
            self.repository.update(updated)
            raise
