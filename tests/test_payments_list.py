from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.main import app
from app.models import Payment


def seed_payments(
    client: TestClient,
    session_factory: sessionmaker[Session],
) -> list[int]:
    payloads = [
        {"tariff_id": 1, "email": "first@example.com", "method": "card"},
        {"tariff_id": 2, "email": "first@example.com", "method": "sbp"},
        {"tariff_id": 3, "email": "second@example.com", "method": "card"},
    ]
    responses = [client.post("/payments", json=payload) for payload in payloads]
    assert all(response.status_code == 201 for response in responses)
    payment_ids = [response.json()["id"] for response in responses]

    with session_factory() as session:
        second = session.get(Payment, payment_ids[1])
        third = session.get(Payment, payment_ids[2])
        assert second is not None
        assert third is not None
        second.status = "succeeded"
        third.status = "failed"
        session.commit()

    return payment_ids


def test_list_payments_without_filters(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        payment_ids = seed_payments(client, test_database)
        response = client.get("/payments")

    assert response.status_code == 200
    assert [payment["id"] for payment in response.json()] == payment_ids


def test_list_payments_filtered_by_email(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        payment_ids = seed_payments(client, test_database)
        response = client.get("/payments", params={"email": "first@example.com"})

    assert response.status_code == 200
    assert [payment["id"] for payment in response.json()] == payment_ids[:2]


def test_list_payments_filtered_by_status(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        payment_ids = seed_payments(client, test_database)
        response = client.get("/payments", params={"status": "succeeded"})

    assert response.status_code == 200
    assert [payment["id"] for payment in response.json()] == [payment_ids[1]]


def test_list_payments_filtered_by_email_and_status(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        payment_ids = seed_payments(client, test_database)
        response = client.get(
            "/payments",
            params={"email": "second@example.com", "status": "failed"},
        )

    assert response.status_code == 200
    assert [payment["id"] for payment in response.json()] == [payment_ids[2]]


def test_list_payments_returns_empty_list_when_nothing_matches(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        seed_payments(client, test_database)
        response = client.get("/payments", params={"email": "none@example.com"})

    assert response.status_code == 200
    assert response.json() == []


def test_list_payments_rejects_unknown_status(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.get("/payments", params={"status": "unknown"})

    assert response.status_code == 422
    assert isinstance(response.json().get("detail"), list)
