from fastapi import APIRouter, HTTPException, status

from app.models.saved_searches import SavedSearch, SavedSearchCheckResponse, SavedSearchCreate, SavedSearchUpdate
from app.providers.mock import MockTransportProvider
from app.services.route_search import RouteSearchService
from app.services.saved_searches import FileSavedSearchRepository, SavedSearchService

router = APIRouter(prefix="/api/v1/saved-searches", tags=["saved-searches"])
service = SavedSearchService(FileSavedSearchRepository(), RouteSearchService(MockTransportProvider()))


def not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Заявка на командировку не найдена")


@router.post("", response_model=SavedSearch, status_code=status.HTTP_201_CREATED)
def create_saved_search(request: SavedSearchCreate) -> SavedSearch:
    return service.create(request)


@router.get("", response_model=list[SavedSearch])
def list_saved_searches() -> list[SavedSearch]:
    return service.list()


@router.get("/{saved_search_id}", response_model=SavedSearch)
def get_saved_search(saved_search_id: str) -> SavedSearch:
    item = service.get(saved_search_id)
    if item is None:
        raise not_found()
    return item


@router.patch("/{saved_search_id}", response_model=SavedSearch)
def update_saved_search(saved_search_id: str, request: SavedSearchUpdate) -> SavedSearch:
    item = service.update(saved_search_id, request)
    if item is None:
        raise not_found()
    return item


@router.delete("/{saved_search_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_search(saved_search_id: str) -> None:
    if not service.delete(saved_search_id):
        raise not_found()


@router.post("/{saved_search_id}/check", response_model=SavedSearchCheckResponse)
def check_saved_search(saved_search_id: str) -> SavedSearchCheckResponse:
    result = service.check(saved_search_id)
    if result is None:
        raise not_found()
    saved_search, routes = result
    return SavedSearchCheckResponse(saved_search=saved_search, routes=routes)
