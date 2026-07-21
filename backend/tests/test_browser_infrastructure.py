import sys
import types

import pytest

httpx_stub = types.SimpleNamespace(Client=object, TimeoutException=TimeoutError)
sys.modules.setdefault("httpx", httpx_stub)

from app.browser import BrowserAutomationProvider, BrowserConfiguration, BrowserManager, BrowserMetrics, BrowserPool, BrowserStatus
from app.browser.exceptions import BrowserPoolExhaustedError
from app.providers.unified import build_default_registry


def test_browser_configuration_defaults_disabled(monkeypatch):
    for key in ["PLAYWRIGHT_ENABLED", "BROWSER_HEADLESS", "BROWSER_POOL_SIZE", "BROWSER_TIMEOUT", "USER_AGENT", "PROXY"]:
        monkeypatch.delenv(key, raising=False)
    config = BrowserConfiguration.from_env()
    assert config.playwright_enabled is False
    assert config.headless is True
    assert config.pool_size == 2
    assert config.timeout == 30
    assert config.user_agent == ""
    assert config.proxy == ""


def test_browser_configuration_from_env(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_ENABLED", "true")
    monkeypatch.setenv("BROWSER_HEADLESS", "false")
    monkeypatch.setenv("BROWSER_POOL_SIZE", "4")
    monkeypatch.setenv("BROWSER_TIMEOUT", "45")
    monkeypatch.setenv("USER_AGENT", "planner-test")
    monkeypatch.setenv("PROXY", "http://proxy.local")
    config = BrowserConfiguration.from_env()
    assert config.playwright_enabled is True
    assert config.headless is False
    assert config.pool_size == 4
    assert config.timeout == 45
    assert config.user_agent == "planner-test"
    assert config.proxy == "http://proxy.local"


def test_browser_manager_disabled_does_not_start_real_browser():
    metrics = BrowserMetrics()
    manager = BrowserManager(BrowserConfiguration(playwright_enabled=False), metrics)
    manager.start()
    health = manager.health()
    assert health.status == BrowserStatus.DISABLED
    assert health.healthy is True
    assert metrics.active_browsers == 0
    assert manager.version() in {"playwright-not-running", "playwright-not-installed"}


def test_browser_manager_restart_updates_metrics_when_enabled():
    metrics = BrowserMetrics()
    manager = BrowserManager(BrowserConfiguration(playwright_enabled=True), metrics)
    manager._installed = True
    manager._running = True
    manager.started_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    metrics.active_browsers = 1
    manager.stop()
    assert metrics.active_browsers == 0
    assert metrics.average_lifetime >= 0


def test_browser_pool_reuses_sessions_and_enforces_limit():
    from test_browser_playwright import FakeManager
    manager = FakeManager()
    pool = BrowserPool(manager)
    first = pool.acquire()
    with pytest.raises(BrowserPoolExhaustedError):
        pool.acquire()
    pool.release(first)
    second = pool.acquire()
    assert second.id == first.id
    pool.release(second)
    assert manager.metrics.active_sessions == 0


def test_browser_pool_context_releases_session_and_tracks_pages():
    from test_browser_playwright import FakeManager
    pool = BrowserPool(FakeManager())
    with pool.session() as session:
        assert session.is_open
        assert session.new_page() is not None
    assert pool.metrics.active_sessions == 0
    assert pool.metrics.pages_opened == 1


def test_browser_provider_status_boundary_is_safe():
    provider = BrowserAutomationProvider(BrowserManager(BrowserConfiguration(playwright_enabled=False)))
    status = provider.status()
    assert status["enabled"] is False
    assert status["configured"] is False
    assert status["healthy"] is True
    assert provider.get_segments() == []


def test_provider_registry_exposes_browser_infrastructure():
    registration = build_default_registry().get("browser_automation")
    assert registration is not None
    assert registration.name == "Browser Automation"
    assert registration.enabled is False
    assert registration.metadata["status_label"] == "Browser diagnostics"
    assert registration.metadata["infrastructure"] == "Инфраструктура готова"
    assert "playwright_installed" in registration.metadata
    assert registration.capabilities.browser_automation["javascript"] is True
