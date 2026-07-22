from fastapi import Depends, FastAPI, Header, HTTPException
from .models import AvailabilityCheckRequest, JourneyAvailabilityRequest
from .service import service
from .settings import settings

app = FastAPI(title="Tutu Playwright Availability Service", version="0.1.0")

def require_token(x_service_token: str | None = Header(default=None)):
    if settings.service_api_token and x_service_token != settings.service_api_token:
        raise HTTPException(status_code=401, detail="Invalid service token")
    return True

@app.get("/health")
def health():
    return {"status":"ok", "enabled": settings.enabled, "mock_mode": settings.mock_mode, "concurrency": settings.concurrency}

@app.post("/api/v1/availability/check", dependencies=[Depends(require_token)])
async def check(req: AvailabilityCheckRequest):
    return await service.check(req)

@app.post("/api/v1/availability/check-journey", dependencies=[Depends(require_token)])
async def check_journey(req: JourneyAvailabilityRequest):
    return await service.check_journey(req.segments)

@app.post("/api/v1/debug/test-search", dependencies=[Depends(require_token)])
async def debug_test_search(req: AvailabilityCheckRequest):
    return await service.check(req)
