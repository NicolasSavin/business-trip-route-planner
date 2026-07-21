from __future__ import annotations

from dataclasses import dataclass, field

from app.domain import Route, RouteOption
from app.intelligence.explanations import ExplanationService
from app.scoring.service import ScoringService


@dataclass
class RouteComparator:
    scorer: ScoringService = field(default_factory=ScoringService)
    explanations: ExplanationService = field(default_factory=ExplanationService)

    def rank(self, routes: list[Route]) -> list[RouteOption]:
        scored = sorted(((route, self.scorer.score(route)) for route in routes), key=lambda item: item[1])
        best = scored[0][1] if scored else None
        options: list[RouteOption] = []
        for index, (route, score) in enumerate(scored, start=1):
            explanation, warnings, advantages = self.explanations.explain(route, score, index, best)
            options.append(RouteOption(route, score, index, explanation, warnings, advantages))
        return options
