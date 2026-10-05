"""Получение доступных тарифов."""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Tariff
from app.schemas import TariffRead

router = APIRouter(prefix="/tariffs", tags=["tariffs"])


@router.get("", response_model=list[TariffRead])
def list_tariffs(db: Annotated[Session, Depends(get_db)]) -> list[Tariff]:
    return list(db.scalars(select(Tariff).order_by(Tariff.id)).all())
