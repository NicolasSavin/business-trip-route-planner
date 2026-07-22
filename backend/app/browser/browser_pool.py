from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.browser.exceptions import BrowserPoolExhaustedError
from app.browser.manager import BrowserManager
from app.browser.metrics import BrowserMetrics
from app.browser.session import BrowserSession


class BrowserPool:
    def __init__(self, manager: BrowserManager | None = None, max_size: int | None = None) -> None:
        self.manager = manager or BrowserManager()
        self.max_size = max_size or self.manager.config.pool_size
        self.metrics: BrowserMetrics = self.manager.metrics
        self._available: list[BrowserSession] = []
        self._leased: set[str] = set()

    async def acquire(self) -> BrowserSession:
        browser = await self.manager.ensure_browser()
        if self._available:
            session = self._available.pop()
        elif len(self._leased) < self.max_size:
            session = BrowserSession(browser=browser, metrics=self.metrics, timeout_seconds=self.manager.config.timeout, user_agent=self.manager.config.user_agent)
        else:
            raise BrowserPoolExhaustedError("Browser pool size limit reached")
        await session.open()
        self._leased.add(session.id)
        self.metrics.active_sessions = len(self._leased)
        return session

    async def release(self, session: BrowserSession) -> None:
        if session.id not in self._leased:
            return
        self._leased.remove(session.id)
        await session.close()
        if not session.destroyed:
            self._available.append(session)
        self.metrics.active_sessions = len(self._leased)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[BrowserSession]:
        acquired = await self.acquire()
        try:
            yield acquired
        finally:
            await self.release(acquired)

    async def shutdown(self) -> None:
        for session in self._available:
            await session.destroy()
        self._available.clear()
        self._leased.clear()
        self.metrics.active_sessions = 0
        await self.manager.graceful_shutdown()
