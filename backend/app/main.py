import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_routers
from app.browser.runtime import browser_manager
from app.providers.unified import registry as provider_registry
from app.providers.yandex.location_service import yandex_location_resolver
from app.memory import log_memory

app = FastAPI(title="Business Trip Route Planner API")
logger = logging.getLogger("uvicorn.error")

frontend_hostname = os.getenv("FRONTEND_HOSTNAME")
allowed_origins = ["http://localhost:3000"]
if frontend_hostname:
    allowed_origins.append(f"https://{frontend_hostname}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)



def log_transport_provider_startup_diagnostics() -> None:
    lines = ["=== Transport Providers Startup Diagnostics ==="]
    for provider in provider_registry.list():
        caps = provider.capabilities
        configured = provider.metadata.get("configured", True)
        lines.extend([
            f"provider: {provider.id}",
            f"enabled: {str(provider.enabled).lower()}",
            f"configured: {str(bool(configured)).lower()}",
            f"supports_schedule: {str(caps.supports_schedule).lower()}",
            f"supports_availability: {str(caps.supports_availability).lower()}",
            f"supports_train: {str('train' in [t.value for t in caps.supported_transport]).lower()}",
            f"supports_bus: {str('bus' in [t.value for t in caps.supported_transport]).lower()}",
            f"status: {provider.health.value if hasattr(provider.health, 'value') else provider.health}",
            "",
        ])
    logger.info("\n" + "\n".join(lines))

@app.on_event("startup")
async def log_browser_startup_diagnostics() -> None:
    log_memory("before provider diagnostics")
    log_transport_provider_startup_diagnostics()
    yandex_location_resolver.warm_from_existing_cache()
    log_memory("after Yandex directory metadata")
    logger.info("Yandex locations cache ready: %s", yandex_location_resolver.stats())
    log_memory("after Yandex indexes")
    yandex_location_resolver.startup_refresh_background()
    try:
        log_memory("before Playwright probe")
        diagnostics = await browser_manager.startup_diagnostics()
        log_memory("after Chromium probe (not launched)")
    except Exception as exc:
        diagnostics = {
            "playwright_version": "unavailable",
            "playwright_browsers_path": os.getenv("PLAYWRIGHT_BROWSERS_PATH", "not-set"),
            "browser_executable_path": "unavailable",
            "browser_exists": False,
            "browser_manager_status": "diagnostics-failed",
            "browser_launch_message": "Browser launch unavailable",
            "startup_exception": str(exc) or exc.__class__.__name__,
        }

    log_memory("after startup")
    logger.info(
        "\n"
        "==================================================\n"
        "Playwright Startup Diagnostics\n\n"
        "Playwright version: %s\n\n"
        "PLAYWRIGHT_BROWSERS_PATH:\n%s\n\n"
        "Executable:\n%s\n\n"
        "Exists: %s\n\n"
        "%s\n\n"
        "BrowserManager status: %s\n\n"
        "Startup exception: %s\n\n"
        "==================================================",
        diagnostics["playwright_version"],
        diagnostics["playwright_browsers_path"],
        diagnostics["browser_executable_path"],
        str(diagnostics["browser_exists"]).lower(),
        diagnostics.get("browser_launch_message", "Browser launch unavailable"),
        diagnostics["browser_manager_status"],
        diagnostics["startup_exception"],
    )


@app.on_event("shutdown")
async def shutdown_browser_manager() -> None:
    await browser_manager.graceful_shutdown()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


for router in api_routers:
    app.include_router(router)
