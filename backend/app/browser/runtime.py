from __future__ import annotations

from app.browser.browser_pool import BrowserPool
from app.browser.config import BrowserConfiguration
from app.browser.manager import BrowserManager

browser_config = BrowserConfiguration.from_env()
browser_manager = BrowserManager(config=browser_config)
browser_pool = BrowserPool(manager=browser_manager)
