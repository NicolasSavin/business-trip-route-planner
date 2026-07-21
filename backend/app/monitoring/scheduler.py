from __future__ import annotations

from threading import Lock

from app.monitoring.models import MonitoringResult, MonitoringRunLog, MonitoringStatus, utc_now
from app.monitoring.service import MonitoringService


class MonitoringScheduler:
    def __init__(self, service: MonitoringService):
        self.service = service
        self._global_lock = Lock()
        self._locks: dict[str, Lock] = {}
        self.run_log: list[MonitoringRunLog] = []

    def run_one(self, saved_search_id: str) -> MonitoringResult | None:
        lock = self._lock_for(saved_search_id)
        log = MonitoringRunLog(saved_search_id=saved_search_id)
        if not lock.acquire(blocking=False):
            log.status = MonitoringStatus.SKIPPED
            log.finished_at = utc_now()
            log.summary = "Проверка этой заявки уже выполняется"
            self.run_log.append(log)
            return None
        try:
            result = self.service.run_one(saved_search_id)
            log.status = MonitoringStatus.SUCCESS if result is not None else MonitoringStatus.FAILED
            log.summary = result.summary if result is not None else "Заявка не найдена"
            return result
        except Exception as exc:
            log.status = MonitoringStatus.FAILED
            log.summary = str(exc) or "Проверка не выполнена"
            raise
        finally:
            log.finished_at = utc_now()
            self.run_log.append(log)
            lock.release()

    def run_all(self) -> list[MonitoringResult]:
        log = MonitoringRunLog(summary="Запуск всех активных заявок")
        results: list[MonitoringResult] = []
        try:
            for saved_search in self.service.saved_searches.list():
                if saved_search.monitoring_enabled:
                    result = self.run_one(saved_search.id)
                    if result is not None:
                        results.append(result)
            log.status = MonitoringStatus.SUCCESS
            log.summary = f"Проверено заявок: {len(results)}"
            return results
        except Exception as exc:
            log.status = MonitoringStatus.FAILED
            log.summary = str(exc) or "Запуск всех заявок не выполнен"
            raise
        finally:
            log.finished_at = utc_now()
            self.run_log.append(log)

    def _lock_for(self, saved_search_id: str) -> Lock:
        with self._global_lock:
            if saved_search_id not in self._locks:
                self._locks[saved_search_id] = Lock()
            return self._locks[saved_search_id]
