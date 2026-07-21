from __future__ import annotations

import time

from app.models.routes import RouteOption
from app.models.saved_searches import SavedSearch
from app.monitoring.history import MonitoringHistoryRepository
from app.monitoring.models import MonitoringHistory, MonitoringPolicy, MonitoringResult, MonitoringStatus, utc_now
from app.services.route_search import RouteSearchService


class MonitoringEngine:
    def __init__(self, route_search: RouteSearchService, history: MonitoringHistoryRepository, policy: MonitoringPolicy | None = None):
        self.route_search = route_search
        self.history = history
        self.policy = policy or MonitoringPolicy()

    def check(self, saved_search: SavedSearch) -> MonitoringResult:
        started = time.perf_counter()
        previous = self.history.latest(saved_search.id)
        timestamp = utc_now()
        try:
            routes = self.route_search.search(saved_search.to_search_request(), include_unavailable=self.policy.include_unavailable)
            changes = self.detect_changes(previous, routes)
            summary = self._summary(changes)
            history = MonitoringHistory(
                saved_search_id=saved_search.id,
                checked_at=timestamp,
                duration_ms=round((time.perf_counter() - started) * 1000),
                routes_found=len(routes),
                available_routes=sum(1 for route in routes if route.is_available_for_group),
                best_score=self._best_score(routes),
                status=MonitoringStatus.SUCCESS,
                change_detected=bool(changes),
                summary=summary,
                changes=changes,
                route_ids=[route.id for route in routes],
                free_seats=self._free_seats(routes),
            )
        except Exception as exc:
            history = MonitoringHistory(
                saved_search_id=saved_search.id,
                checked_at=timestamp,
                duration_ms=round((time.perf_counter() - started) * 1000),
                routes_found=0,
                available_routes=0,
                status=MonitoringStatus.FAILED,
                change_detected=False,
                summary=str(exc) or "Проверка не выполнена",
            )
            self.history.add(history)
            raise
        self.history.add(history)
        return MonitoringResult(saved_search_id=saved_search.id, is_changed=bool(changes), changes=changes, summary=summary, timestamp=timestamp, history=history)

    def detect_changes(self, previous: MonitoringHistory | None, routes: list[RouteOption]) -> list[str]:
        if previous is None:
            return ["Первичная проверка: состояние маршрутов зафиксировано"]
        changes: list[str] = []
        route_ids = {route.id for route in routes}
        new_routes = route_ids.difference(previous.route_ids)
        available_routes = sum(1 for route in routes if route.is_available_for_group)
        best_score = self._best_score(routes)
        free_seats = self._free_seats(routes)
        if new_routes:
            changes.append(f"Появились новые маршруты: {len(new_routes)}")
        if len(routes) > previous.routes_found:
            changes.append(f"Маршрутов стало больше: {previous.routes_found} → {len(routes)}")
        if available_routes > previous.available_routes:
            changes.append(f"Доступных маршрутов стало больше: {previous.available_routes} → {available_routes}")
        if previous.available_routes == 0 and available_routes > 0:
            changes.append("Появились места для группы")
        if previous.best_score is not None and best_score is not None and abs(best_score - previous.best_score) > self.policy.score_tolerance:
            changes.append(f"Изменился score лучшего маршрута: {previous.best_score:.2f} → {best_score:.2f}")
        if free_seats != previous.free_seats:
            direction = "больше" if free_seats > previous.free_seats else "меньше"
            changes.append(f"Свободных мест стало {direction}: {previous.free_seats} → {free_seats}")
        return changes

    def _summary(self, changes: list[str]) -> str:
        return "; ".join(changes) if changes else "Без изменений"

    def _best_score(self, routes: list[RouteOption]) -> float | None:
        scores = [route.score for route in routes if route.score is not None]
        return max(scores) if scores else None

    def _free_seats(self, routes: list[RouteOption]) -> int:
        return sum(min((segment.available_seats for segment in route.segments), default=0) for route in routes)
