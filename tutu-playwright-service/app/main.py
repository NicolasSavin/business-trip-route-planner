import logging

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from .models import AvailabilityCheckRequest, JourneyAvailabilityRequest
from .connectivity import run_connectivity_diagnostics
from .service import service
from .settings import settings

logger = logging.getLogger(__name__)

app = FastAPI(title="Tutu Playwright Availability Service", version="0.1.0")

@app.middleware("http")
async def log_availability_check_request(request: Request, call_next):
    if request.url.path == "/api/v1/availability/check":
        logger.info("request received", extra={"endpoint": request.url.path, "method": request.method})
    return await call_next(request)

def require_token(x_service_token: str | None = Header(default=None)):
    if settings.service_api_token and x_service_token != settings.service_api_token:
        logger.info("token validation failed", extra={"reason": "invalid_service_token"})
        raise HTTPException(status_code=401, detail="Invalid service token")
    logger.info("token validated", extra={"token_required": bool(settings.service_api_token)})
    return True

@app.get("/health")
def health():
    return {"status":"ok", "enabled": settings.enabled, "mock_mode": settings.mock_mode, "concurrency": settings.concurrency}

@app.post("/api/v1/availability/check", dependencies=[Depends(require_token)])
async def check(req: AvailabilityCheckRequest):
    logger.info("request parsed", extra={"origin": req.origin, "destination": req.destination, "departure_date": req.departure_date.isoformat(), "train_number_present": bool(req.train_number)})
    response = await service.check(req)
    logger.info("response returned", extra={"status": response.status.value, "matched_train": response.matched_train, "train_number": response.train_number})
    return response

@app.post("/api/v1/availability/check-journey", dependencies=[Depends(require_token)])
async def check_journey(req: JourneyAvailabilityRequest):
    return await service.check_journey(req.segments)

@app.post("/api/v1/debug/test-search", dependencies=[Depends(require_token)])
async def debug_test_search(req: AvailabilityCheckRequest):
    return await service.check(req)

@app.get("/api/v1/debug/connectivity", dependencies=[Depends(require_token)])
async def debug_connectivity():
    return await run_connectivity_diagnostics()
