from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TutuConfiguration:
    enabled: bool = False
    base_url: str = ""
    api_key: str = field(default="", repr=False)
    login: str = field(default="", repr=False)
    password: str = field(default="", repr=False)
    timeout_seconds: int = 20

    @property
    def configured(self) -> bool:
        return bool(self.base_url and (self.api_key or (self.login and self.password)))

    @classmethod
    def from_env(cls) -> "TutuConfiguration":
        return cls(
            enabled=os.getenv("TUTU_ENABLED", "false").lower() in {"1", "true", "yes", "on"},
            base_url=os.getenv("TUTU_BASE_URL", ""),
            api_key=os.getenv("TUTU_API_KEY", ""),
            login=os.getenv("TUTU_LOGIN", ""),
            password=os.getenv("TUTU_PASSWORD", ""),
            timeout_seconds=int(os.getenv("TUTU_TIMEOUT_SECONDS", "20")),
        )
