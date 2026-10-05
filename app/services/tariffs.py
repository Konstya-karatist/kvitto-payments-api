"""Создание обязательных тарифов при запуске приложения."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Tariff

DEFAULT_TARIFFS = (
    ("basic", 990_000),
    ("standard", 1_990_000),
    ("premium", 2_990_000),
)


def seed_tariffs(db: Session) -> None:
    existing_tariffs = {
        tariff.title: tariff for tariff in db.scalars(select(Tariff)).all()
    }

    for title, price in DEFAULT_TARIFFS:
        tariff = existing_tariffs.get(title)
        if tariff is None:
            db.add(Tariff(title=title, price=price))
        else:
            tariff.price = price

    db.commit()
