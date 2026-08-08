import json
import os
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class HotelRepository(ABC):
    @abstractmethod
    def list(self) -> list[dict[str, Any]]: ...
    @abstractmethod
    def create(self, hotel: dict[str, Any]) -> dict[str, Any]: ...
    @abstractmethod
    def update(self, hotel_id: int, hotel: dict[str, Any]) -> dict[str, Any] | None: ...
    @abstractmethod
    def delete(self, hotel_id: int) -> bool: ...


class JsonHotelRepository(HotelRepository):
    """File-backed repository. Configure HOTELS_DATA_PATH on a durable volume."""

    def __init__(self, path: Path, seed_path: Path):
        self.path, self.seed_path, self.lock = path, seed_path, threading.Lock()
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(seed_path.read_text(encoding="utf-8"), encoding="utf-8")

    def _read(self):
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, rows):
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def list(self):
        with self.lock: return self._read()

    def create(self, hotel):
        with self.lock:
            rows = self._read(); hotel = {**hotel, "id": max((r["id"] for r in rows), default=0) + 1}
            rows.append(hotel); self._write(rows); return hotel

    def update(self, hotel_id, hotel):
        with self.lock:
            rows = self._read()
            for index, row in enumerate(rows):
                if row["id"] == hotel_id:
                    rows[index] = {**hotel, "id": hotel_id}; self._write(rows); return rows[index]
        return None

    def delete(self, hotel_id):
        with self.lock:
            rows = self._read(); updated = [row for row in rows if row["id"] != hotel_id]
            if len(updated) == len(rows): return False
            self._write(updated); return True


def default_repository() -> JsonHotelRepository:
    seed = Path(__file__).with_name("seed.json")
    path = Path(os.getenv("HOTELS_DATA_PATH", "/tmp/business-trip-hotels.json"))
    return JsonHotelRepository(path, seed)
