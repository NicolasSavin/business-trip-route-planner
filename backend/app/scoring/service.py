from datetime import time
from app.domain import Route


class ScoringService:
    def score(self, route: Route) -> float:
        transfer_wait = sum(transfer.duration_minutes for transfer in route.transfers)
        night_transfers = sum(1 for transfer in route.transfers if transfer.is_night)
        return (
            route.transfers_count * 10_000
            + route.total_duration_minutes * 2
            + transfer_wait * 0.6
            + night_transfers * 750
            - route.min_available_seats * 4
        )


def is_night_transfer_start(hour: int) -> bool:
    return hour >= 23 or hour < 6
