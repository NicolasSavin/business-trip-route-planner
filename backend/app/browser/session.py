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

    async def open(self) -> "BrowserSession":
        self.is_open = True
        return self

    async def close(self) -> None:
        if self.page is not None:
            await self.page.close()
            self.page = None
            self.metrics.record_page_closed()
        if self.context is not None:
            await self.context.close()
            self.context = None
        self.is_open = False

    async def new_page(self) -> Any:
        if self.context is None:
            options: dict[str, Any] = {}
            if self.user_agent:
                options["user_agent"] = self.user_agent
            self.context = await self.browser.new_context(**options)
        if self.page is not None:
            await self.page.close()
            self.metrics.record_page_closed()
        self.page = await self.context.new_page()
        self.page.set_default_timeout(self.timeout_seconds * 1000)
        self.metrics.record_page_opened()
        return self.page

    async def _require_page(self) -> Any:
        return self.page or await self.new_page()

    async def navigate(self, url: str) -> Any:
        page = await self._require_page()
        started = perf_counter()
        response = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_seconds * 1000)
        self.metrics.record_page_load((perf_counter() - started) * 1000)
        return response

    async def wait_ready(self, *_args: Any, **_kwargs: Any) -> bool:
        page = await self._require_page()
        await page.wait_for_load_state("domcontentloaded")
        return True

    async def capture_html(self) -> str:
        page = await self._require_page()
        return await page.content()

    async def capture_screenshot(self) -> bytes:
        page = await self._require_page()
        return await page.screenshot(type="png", full_page=True)

    async def capture_pdf(self) -> bytes:
        page = await self._require_page()
        return await page.pdf()

    async def evaluate(self, expression: str, arg: Any | None = None) -> Any:
        page = await self._require_page()
        if arg is None:
            return await page.evaluate(expression)
        return await page.evaluate(expression, arg)

    async def click(self, selector: str, **kwargs: Any) -> None:
        page = await self._require_page()
        await page.locator(selector).first.click(**kwargs)

    async def fill(self, selector: str, value: str, **kwargs: Any) -> None:
        page = await self._require_page()
        await page.locator(selector).first.fill(value, **kwargs)

    async def select(self, selector: str, value: str | list[str], **kwargs: Any) -> Any:
        page = await self._require_page()
        return await page.locator(selector).first.select_option(value, **kwargs)

    async def wait_for(self, selector: str | None = None, **kwargs: Any) -> bool:
        if selector is None:
            return await self.wait_ready()
        page = await self._require_page()
        await page.locator(selector).first.wait_for(**kwargs)
        return True

    async def cookies(self) -> list[dict[str, Any]]:
        return await self.context.cookies() if self.context is not None else []

    async def headers(self) -> dict[str, str]:
        return {}

    async def destroy(self) -> None:
        await self.close()
        self.destroyed = True
