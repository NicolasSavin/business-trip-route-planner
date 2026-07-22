import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_routers
from app.browser.runtime import browser_manager

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


@app.on_event("startup")
async def log_browser_startup_diagnostics() -> None:
    try:
        diagnostics = await browser_manager.startup_diagnostics()
        await browser_manager.start()
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
