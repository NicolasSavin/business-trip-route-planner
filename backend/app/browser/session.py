from __future__ import annotations

from dataclasses import dataclass, field
from time import perf_counter
from typing import Any
from uuid import uuid4

from app.browser.metrics import BrowserMetrics


@dataclass
class BrowserSession:
    browser: Any
    metrics: BrowserMetrics
    timeout_seconds: int = 30
    user_agent: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    is_open: bool = False
    destroyed: bool = False
    page: Any | None = None
    context: Any | None = None

    def open(self) -> "BrowserSession":
        self.is_open = True
        return self

    def close(self) -> None:
        if self.page is not None:
            self.page.close()
            self.page = None
            self.metrics.record_page_closed()
        if self.context is not None:
            self.context.close()
            self.context = None
        self.is_open = False

    def new_page(self) -> Any:
        if self.context is None:
            options: dict[str, Any] = {}
            if self.user_agent:
                options["user_agent"] = self.user_agent
            self.context = self.browser.new_context(**options)
        if self.page is not None:
            self.page.close()
            self.metrics.record_page_closed()
        self.page = self.context.new_page()
        self.page.set_default_timeout(self.timeout_seconds * 1000)
        self.metrics.record_page_opened()
        return self.page

    def _require_page(self) -> Any:
        return self.page or self.new_page()

    def navigate(self, url: str) -> Any:
        page = self._require_page()
        started = perf_counter()
        response = page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
        self.metrics.record_page_load((perf_counter() - started) * 1000)
        return response

    def wait_ready(self, *_args: Any, **_kwargs: Any) -> bool:
        self._require_page().wait_for_load_state("domcontentloaded")
        return True

    def capture_html(self) -> str:
        return self._require_page().content()

    def capture_screenshot(self) -> bytes:
        return self._require_page().screenshot(type="png", full_page=True)

    def capture_pdf(self) -> bytes:
        return self._require_page().pdf()

    def evaluate(self, expression: str, arg: Any | None = None) -> Any:
        page = self._require_page()
        if arg is None:
            return page.evaluate(expression)
        return page.evaluate(expression, arg)

    def click(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("Click actions are intentionally not connected at this stage.")

    def fill(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("Fill actions are intentionally not connected at this stage.")

    def select(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotImplementedError("Select actions are intentionally not connected at this stage.")

    def wait_for(self, *_args: Any, **_kwargs: Any) -> bool:
        return self.wait_ready()

    def cookies(self) -> list[dict[str, Any]]:
        return self.context.cookies() if self.context is not None else []

    def headers(self) -> dict[str, str]:
        return {}

    def destroy(self) -> None:
        self.close()
        self.destroyed = True
