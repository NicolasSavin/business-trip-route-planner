import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_routers

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


for router in api_routers:
    app.include_router(router)
