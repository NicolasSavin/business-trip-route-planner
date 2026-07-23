from __future__ import annotations

from dataclasses import dataclass

from app.domain import Route


@dataclass(frozen=True)
class ExplanationService:
    def explain(self, route: Route, score: float, rank: int, best_score: float | None = None) -> tuple[str, tuple[str, ...], tuple[str, ...]]:
        warnings: list[str] = []
        advantages: list[str] = []
        for transfer in route.transfers:
            warnings.extend(transfer.warnings)
        if route.transfers_count == 0:
            advantages.append("Без пересадок")
        known_seats = [segment.available_seats for segment in route.segments if segment.available_seats is not None]
        if known_seats and min(known_seats) >= 10:
            advantages.append("Максимум свободных мест")
        elif known_seats and min(known_seats) < 2:
            warnings.append("Недостаточно мест")
        if rank == 1:
            advantages.append("Лучший маршрут по score")
        elif best_score is not None:
            warnings.append("Маршрут проиграл другому по score")
        if route.total_duration_minutes <= 6 * 60:
            advantages.append("Самый быстрый")
        explanation = "Маршрут найден и ранжирован по времени, пересадкам, запасу времени и свободным местам."
        return explanation, tuple(dict.fromkeys(warnings)), tuple(dict.fromkeys(advantages))

    def excluded(self, reason: str) -> str:
        return reason
