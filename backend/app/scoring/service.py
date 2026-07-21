from datetime import time
from app.domain import Route


class ScoringService:
    def score(self, route: Route) -> float:
        transfer_wait = sum(transfer.duration_minutes for transfer in route.transfers)
        night_transfers = sum(1 for transfer in route.transfers if transfer.is_night)
        station_changes = sum(1 for transfer in route.transfers if transfer.station_change)
        city_changes = sum(1 for transfer in route.transfers if transfer.city_change)
        transfer_type_penalty = sum({"walk": 50, "metro": 350, "bus": 700, "unknown": 500}.get(transfer.transfer_type, 500) for transfer in route.transfers)
        buffer_penalty = sum(max(0, (transfer.estimated_transfer_minutes or 0) - transfer.duration_minutes) * 60 for transfer in route.transfers)
        return (
            route.transfers_count * 8_000
            + route.total_duration_minutes * 2
            + transfer_wait * 0.6
            + transfer_type_penalty
            + station_changes * 900
            + city_changes * 1_500
            + buffer_penalty
            + night_transfers * 750
            - route.min_available_seats * 4
        )


def is_night_transfer_start(hour: int) -> bool:
    return hour >= 23 or hour < 6
