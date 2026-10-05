from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models import Tariff


def test_get_tariffs(test_database: sessionmaker[Session]) -> None:
    with TestClient(app) as client:
        response = client.get("/tariffs")

    assert response.status_code == 200
    assert response.json() == [
        {"id": 1, "title": "basic", "price": 990_000},
        {"id": 2, "title": "standard", "price": 1_990_000},
        {"id": 3, "title": "premium", "price": 2_990_000},
    ]


def test_repeated_startup_does_not_duplicate_tariffs(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app):
        pass
    with TestClient(app):
        pass

    with test_database() as session:
        tariff_count = session.scalar(select(func.count()).select_from(Tariff))

    assert tariff_count == 3
