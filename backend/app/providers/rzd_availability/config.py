from __future__ import annotations

import os
from dataclasses import dataclass


def _boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class RZDAvailabilityConfig:
    enabled: bool = False
    timeout_seconds: float = 20.0
    station_lookup_timeout_seconds: float = 8.0
    ticket_search_timeout_seconds: float = 15.0
    retries: int = 2
    backoff_seconds: float = 0.25
    station_cache_ttl_seconds: int = 86_400
    availability_cache_ttl_seconds: int = 300
    verify_ssl: bool = True

    @classmethod
    def from_env(cls) -> "RZDAvailabilityConfig":
        return cls(
            enabled=_boolean("RZD_AVAILABILITY_ENABLED"),
            timeout_seconds=float(os.getenv("RZD_AVAILABILITY_TIMEOUT_SECONDS", "20")),
            station_lookup_timeout_seconds=float(
                os.getenv("RZD_STATION_LOOKUP_TIMEOUT_SECONDS", "8")
            ),
            ticket_search_timeout_seconds=float(
                os.getenv("RZD_TICKET_SEARCH_TIMEOUT_SECONDS", "15")
            ),
            retries=int(os.getenv("RZD_AVAILABILITY_RETRIES", "2")),
            backoff_seconds=float(
                os.getenv("RZD_AVAILABILITY_BACKOFF_SECONDS", "0.25")
            ),
            station_cache_ttl_seconds=int(
                os.getenv("RZD_STATION_CACHE_TTL_SECONDS", "86400")
            ),
            availability_cache_ttl_seconds=int(
                os.getenv("RZD_AVAILABILITY_CACHE_TTL_SECONDS", "300")
            ),
            verify_ssl=_boolean("RZD_AVAILABILITY_VERIFY_SSL", True),
        )
