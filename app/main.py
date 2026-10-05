"""Точка входа FastAPI."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import db, models  # noqa: F401 — models регистрирует таблицы
from app.routes.payments import router as payments_router
from app.routes.tariffs import router as tariffs_router
from app.routes.webhooks import router as webhooks_router
from app.services.tariffs import seed_tariffs


@asynccontextmanager
async def lifespan(_: FastAPI):
    with db.SessionLocal() as session:
        seed_tariffs(session)
    yield


app = FastAPI(title="Kvitto Payments API", lifespan=lifespan)
app.include_router(tariffs_router)
app.include_router(payments_router)
app.include_router(webhooks_router)
