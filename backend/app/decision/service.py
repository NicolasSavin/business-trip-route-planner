from .engine import DecisionEngine
from .models import AnalyzeRequest, AnalyzeResponse, CompareRequest, CompareResponse

class DecisionService:
    def __init__(self, engine: DecisionEngine | None = None):
        self.engine = engine or DecisionEngine()

    def analyze(self, request: AnalyzeRequest) -> AnalyzeResponse:
        summaries = self.engine.analyze(request.routes, passengers=request.passengers)
        return AnalyzeResponse(summaries=summaries, best_route_id=summaries[0].route_id if summaries else None)

    def compare(self, request: CompareRequest) -> CompareResponse:
        return self.engine.compare(request.left, request.right, passengers=request.passengers)
