from app.api.browser import router as browser_router
from app.api.decision import router as decision_router
from app.api.locations import router as locations_router
from app.api.monitoring import router as monitoring_router
from app.api.notifications import router as notifications_router
from app.api.providers import router as providers_router
from app.api.routes import router as routes_router
from app.api.saved_searches import router as saved_searches_router

api_routers = (
    routes_router,
    saved_searches_router,
    monitoring_router,
    notifications_router,
    decision_router,
    providers_router,
    locations_router,
    browser_router,
)
