from __future__ import annotations

from app.monitoring.engine import MonitoringEngine
from app.monitoring.history import MonitoringHistoryRepository
from app.monitoring.models import MonitoringHistory, MonitoringResult
from app.services.saved_searches import SavedSearchRepository


class MonitoringService:
    def __init__(self, saved_searches: SavedSearchRepository, engine: MonitoringEngine, history: MonitoringHistoryRepository):
        self.saved_searches = saved_searches
        self.engine = engine
        self.history = history

    def run_one(self, saved_search_id: str) -> MonitoringResult | None:
        saved_search = self.saved_searches.get(saved_search_id)
        if saved_search is None:
            return None
        return self.engine.check(saved_search)

    def run_all(self) -> list[MonitoringResult]:
        results: list[MonitoringResult] = []
        for saved_search in self.saved_searches.list():
            if saved_search.monitoring_enabled:
                results.append(self.engine.check(saved_search))
        return results

    def list_history(self, saved_search_id: str) -> list[MonitoringHistory] | None:
        if self.saved_searches.get(saved_search_id) is None:
            return None
        return self.history.list(saved_search_id)
