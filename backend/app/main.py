import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router as routes_router
from app.api.saved_searches import router as saved_searches_router
from app.api.monitoring import router as monitoring_router
from app.api.notifications import router as notifications_router
from app.api.decision import router as decision_router

app = FastAPI(title="Business Trip Route Planner API")

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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


app.include_router(routes_router)
app.include_router(saved_searches_router)
app.include_router(monitoring_router)
app.include_router(notifications_router)
app.include_router(decision_router)
