import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import close, connect, ensure_indexes
from app.core.logging import configure_logging, get_logger
from app.api.routes import (
    auth,
    dashboard,
    defontana,
    dispatch,
    inventory,
    locations,
    order_import,
    orders,
    packing,
    picking,
    products,
    public,
    seed,
    sync_jobs,
    users,
    warehouses,
)

configure_logging(logging.INFO)
logger = get_logger("app.main")

API_PREFIX = "/api/v1"

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="WMS SaaS — Warehouse Management System con integración Defontana.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def on_startup() -> None:
    connect()
    try:
        await ensure_indexes()
    except Exception as exc:  # noqa: BLE001 - never block startup on index creation
        logger.warning("Could not ensure indexes at startup: %s", exc)
    logger.info("%s started (mock=%s)", settings.app_name, settings.defontana_mock)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close()


@app.get("/health", tags=["health"])
async def health():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


# Register routers under /api/v1
for module in (
    auth,
    dashboard,
    users,
    products,
    warehouses,
    locations,
    inventory,
    orders,
    order_import,
    picking,
    packing,
    dispatch,
    defontana,
    sync_jobs,
    seed,
    public,
):
    app.include_router(module.router, prefix=API_PREFIX)
