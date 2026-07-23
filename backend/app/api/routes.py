import logging
from time import monotonic
from uuid import uuid4

from fastapi import APIRouter, Request
from app.models.routes import RouteSearchRequest, RouteSearchResponse
from app.providers.unified import unified_provider
from app.services.route_search import RouteSearchService

router = APIRouter(prefix="/api/v1/routes", tags=["routes"])
service = RouteSearchService(unified_provider)
logger = logging.getLogger(__name__)


@router.post("/search", response_model=RouteSearchResponse)
async def search_routes(request: RouteSearchRequest, raw_request: Request) -> RouteSearchResponse:
    started_at = monotonic()
    request_id = raw_request.headers.get("x-request-id") or raw_request.headers.get("x-correlation-id") or str(uuid4())
    provider = service.planner.provider
    selected_providers = [
        registration.id
        for registration, _ in provider.registry.enabled(request.allowed_transport, schedule_only=True)
    ] if hasattr(provider, "registry") else [getattr(provider, "provider_name", provider.__class__.__name__)]
    try:
        return await service.search_response_async(request)
    except Exception:
        logger.exception(
            "Unhandled exception in /api/v1/routes/search",
            extra={
                "request_body": request.model_dump(mode="json"),
                "selected_providers": selected_providers,
                "request_id": request_id,
                "elapsed_ms": int((monotonic() - started_at) * 1000),
            },
        )
        raise
