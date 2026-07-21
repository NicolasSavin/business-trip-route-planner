from fastapi import APIRouter, HTTPException, status

from app.monitoring import FileMonitoringHistoryRepository, MonitoringEngine, MonitoringHistory, MonitoringResult, MonitoringScheduler, MonitoringService
from app.providers.mock import MockTransportProvider
from app.services.route_search import RouteSearchService
from app.services.saved_searches import FileSavedSearchRepository

router = APIRouter(prefix="/api/v1/monitoring", tags=["monitoring"])

saved_search_repository = FileSavedSearchRepository()
history_repository = FileMonitoringHistoryRepository()
monitoring_engine = MonitoringEngine(RouteSearchService(MockTransportProvider()), history_repository)
service = MonitoringService(saved_search_repository, monitoring_engine, history_repository)
scheduler = MonitoringScheduler(service)


def not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка на командировку не найдена")


@router.get("/history/{saved_search_id}", response_model=list[MonitoringHistory])
def monitoring_history(saved_search_id: str) -> list[MonitoringHistory]:
    history = service.list_history(saved_search_id)
    if history is None:
        raise not_found()
    return history


@router.post("/run/{saved_search_id}", response_model=MonitoringResult)
def run_monitoring(saved_search_id: str) -> MonitoringResult:
    result = scheduler.run_one(saved_search_id)
    if result is None:
        saved = saved_search_repository.get(saved_search_id)
        if saved is None:
            raise not_found()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Проверка этой заявки уже выполняется")
    return result


@router.post("/run-all", response_model=list[MonitoringResult])
def run_all_monitoring() -> list[MonitoringResult]:
    return scheduler.run_all()
