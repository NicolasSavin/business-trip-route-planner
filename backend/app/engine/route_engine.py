from datetime import date
from app.algorithms.search import GraphRouteSearch
from app.domain import RouteOption, TransportProvider, TransportSegment, TransportType
from app.graph.builder import GraphBuilder
from app.scoring.service import ScoringService
from app.validators.validation import ValidationService


class RouteEngine:
    def __init__(self, provider: TransportProvider, graph_builder: GraphBuilder | None = None, scorer: ScoringService | None = None, validator: ValidationService | None = None):
        self.provider = provider
        self.graph_builder = graph_builder or GraphBuilder()
        self.scorer = scorer or ScoringService()
        self.validator = validator or ValidationService()
        self.search_algorithm = GraphRouteSearch()

    def search(self, departure_date: date, origin: str, destination: str, passengers: int, allowed_transport: list[TransportType], max_transfers: int, minimum_transfer_minutes: int) -> list[RouteOption]:
        segments = self.provider.get_segments(departure_date, allowed_transport)
        self.validator.validate_segments(segments)
        graph = self.graph_builder.build(segments)
        routes = self.search_algorithm.find_routes(graph, origin, destination, passengers, max_transfers, minimum_transfer_minutes)
        options = [RouteOption(route=route, score=self.scorer.score(route)) for route in routes]
        return sorted(options, key=lambda option: option.score)
