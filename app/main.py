from fastapi import FastAPI

from app.acquisition.api import router as acquisition_router
from app.analytics.api import router as analytics_router
from app.core.api import jobs_router
from app.discovery.api import router as discovery_router
from app.identity.api import admin_router, auth_router, users_router
from app.reporting.api import router as reporting_router
from app.scenario.api import router as scenario_router

app = FastAPI(title="Investment Committee Intelligence Platform", version="0.1.0")

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(admin_router)
app.include_router(jobs_router)
app.include_router(discovery_router)
app.include_router(acquisition_router)
app.include_router(analytics_router)
app.include_router(scenario_router)
app.include_router(reporting_router)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok"}
