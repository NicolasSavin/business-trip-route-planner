from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class YandexRaspConfiguration:
    api_key: str | None
    enabled: bool = False
    timeout_seconds: float = 10.0
    base_url: str = "https://api.rasp.yandex.net/v3.0"

    @classmethod
    def from_env(cls) -> "YandexRaspConfiguration":
        return cls(
            api_key=os.getenv("YANDEX_RASP_API_KEY") or None,
            enabled=os.getenv("YANDEX_RASP_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            timeout_seconds=float(os.getenv("YANDEX_RASP_TIMEOUT_SECONDS", "10")),
        )
