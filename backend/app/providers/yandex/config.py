from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class YandexRaspConfiguration:
    api_key: str | None
    enabled: bool = False
    timeout_seconds: float = 10.0
    base_url: str = "https://api.rasp.yandex-net.ru/v3.0/"

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", self.base_url.rstrip("/") + "/")

    @classmethod
    def from_env(cls) -> "YandexRaspConfiguration":
        return cls(
            api_key=os.getenv("YANDEX_RASP_API_KEY") or None,
            enabled=(os.getenv("YANDEX_RASP_ENABLED", "").lower() in {"1", "true", "yes", "on"}) or bool(os.getenv("YANDEX_RASP_API_KEY")),
            timeout_seconds=float(os.getenv("YANDEX_RASP_TIMEOUT_SECONDS", "10")),
            base_url=os.getenv("YANDEX_RASP_BASE_URL", "https://api.rasp.yandex-net.ru/v3.0/").rstrip("/") + "/",
        )
