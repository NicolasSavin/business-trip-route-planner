from fastapi import APIRouter
from app.models.routes import RouteSearchRequest, RouteSearchResponse
from app.providers.unified import unified_provider
from app.services.route_search import RouteSearchService

router = APIRouter(prefix="/api/v1/routes", tags=["routes"])
service = RouteSearchService(unified_provider)


@router.post("/search", response_model=RouteSearchResponse)
def search_routes(request: RouteSearchRequest) -> RouteSearchResponse:
    return RouteSearchResponse(routes=service.search(request))
