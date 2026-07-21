from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RzdConfiguration:
    enabled: bool = False
    priority: int = 10
    timeout: float = 5.0
    base_url: str = "https://example.invalid/rzd-placeholder"
    retry_count: int = 0

    @classmethod
    def from_env(cls) -> "RzdConfiguration":
        return cls(
            enabled=os.getenv("RZD_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            priority=int(os.getenv("RZD_PRIORITY", "10")),
            timeout=float(os.getenv("RZD_TIMEOUT", "5.0")),
            base_url=os.getenv("RZD_BASE_URL", cls.base_url),
            retry_count=int(os.getenv("RZD_RETRY_COUNT", "0")),
        )
