from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from app.browser.metrics import BrowserMetrics


@dataclass
class BrowserSession:
    metrics: BrowserMetrics
    id: str = field(default_factory=lambda: str(uuid4()))
    is_open: bool = False
    destroyed: bool = False

    def open(self) -> "BrowserSession":
        self.is_open = True
        return self

    def close(self) -> None:
        self.is_open = False

    def new_page(self) -> dict[str, str]:
        self.metrics.record_page_opened()
        return {"status": "mock", "session_id": self.id}

    def navigate(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("Browser navigation is not implemented until a real automation driver is enabled.")

    def wait_ready(self, *_args: Any, **_kwargs: Any) -> bool:
        return True

    def capture_html(self) -> str:
        return ""

    def capture_screenshot(self) -> bytes:
        return b""

    def capture_pdf(self) -> bytes:
        return b""

    def evaluate(self, *_args: Any, **_kwargs: Any) -> Any:
        raise NotImplementedError("JavaScript evaluation is not implemented in mock browser sessions.")

    def click(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("Click actions are not implemented in mock browser sessions.")

    def fill(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("Fill actions are not implemented in mock browser sessions.")

    def select(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("Select actions are not implemented in mock browser sessions.")

    def wait_for(self, *_args: Any, **_kwargs: Any) -> bool:
        return True

    def cookies(self) -> list[dict[str, Any]]:
        return []

    def headers(self) -> dict[str, str]:
        return {}

    def destroy(self) -> None:
        self.close()
        self.destroyed = True
