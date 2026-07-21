from fastapi import APIRouter
from app.decision.models import AnalyzeRequest, AnalyzeResponse, CompareRequest, CompareResponse
from app.decision.service import DecisionService

router = APIRouter(prefix="/api/v1/decision", tags=["decision"])
service = DecisionService()

@router.post("/analyze", response_model=AnalyzeResponse)
def analyze_routes(request: AnalyzeRequest) -> AnalyzeResponse:
    return service.analyze(request)

@router.post("/compare", response_model=CompareResponse)
def compare_routes(request: CompareRequest) -> CompareResponse:
    return service.compare(request)
