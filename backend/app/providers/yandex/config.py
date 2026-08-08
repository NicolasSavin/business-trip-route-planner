from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


CANONICAL_YANDEX_RASP_BASE_URL = "https://api.rasp.yandex-net.ru/v3.0/"
LEGACY_YANDEX_RASP_HOST = "api.rasp.yandex.net"


def normalize_yandex_rasp_base_url(value: str) -> str:
    """Return a versioned base URL, transparently migrating the legacy host."""
    candidate = value.strip()
    parsed = urlparse(candidate if "://" in candidate else f"https://{candidate}")
    if (parsed.hostname or "").lower() == LEGACY_YANDEX_RASP_HOST:
        return CANONICAL_YANDEX_RASP_BASE_URL
    return candidate.rstrip("/") + "/"


@dataclass(frozen=True)
class YandexRaspConfiguration:
    api_key: str | None
    enabled: bool = False
    timeout_seconds: float = 10.0
    base_url: str = CANONICAL_YANDEX_RASP_BASE_URL

    def __post_init__(self) -> None:
        object.__setattr__(self, "base_url", normalize_yandex_rasp_base_url(self.base_url))

    @classmethod
    def from_env(cls) -> "YandexRaspConfiguration":
        return cls(
            api_key=os.getenv("YANDEX_RASP_API_KEY") or None,
            enabled=(os.getenv("YANDEX_RASP_ENABLED", "").lower() in {"1", "true", "yes", "on"}) or bool(os.getenv("YANDEX_RASP_API_KEY")),
            timeout_seconds=float(os.getenv("YANDEX_RASP_TIMEOUT_SECONDS", "10")),
            base_url=os.getenv("YANDEX_RASP_BASE_URL", CANONICAL_YANDEX_RASP_BASE_URL),
        )
