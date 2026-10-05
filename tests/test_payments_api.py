from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

import app.routes.payments as payment_routes
from app.main import app
from app.models import Payment, Tariff


def payment_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "tariff_id": 2,
        "email": "student@example.com",
        "method": "card",
    }
    payload.update(changes)
    return payload


def test_create_payment_without_discount(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post("/payments", json=payment_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["tariff_id"] == 2
    assert body["amount"] == 1_990_000
    assert body["discount"] == 0
    assert body["method"] == "card"
    assert body["installment_months"] is None
    assert body["schedule"] is None
    assert body["email"] == "student@example.com"
    assert "idempotency_key" not in body

    created_at = datetime.fromisoformat(body["created_at"].replace("Z", "+00:00"))
    assert created_at.utcoffset() == timedelta(0)


def test_create_payment_with_lowercase_promo(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/payments",
            json=payment_payload(method="sbp", promo_code="kvitto10"),
        )

    assert response.status_code == 201
    assert response.json()["discount"] == 199_000
    assert response.json()["amount"] == 1_791_000


@pytest.mark.parametrize("months", [3, 6, 12])
def test_create_installment_payment(
    months: int,
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/payments",
            json=payment_payload(method="installment", installment_months=months),
        )

    assert response.status_code == 201
    body = response.json()
    schedule = body["schedule"]
    assert body["installment_months"] == months
    assert len(schedule) == months
    assert sum(schedule) == body["amount"] == 1_990_000
    assert schedule == sorted(schedule, reverse=True)
    if months == 3:
        assert schedule == [663_334, 663_333, 663_333]


@pytest.mark.parametrize("method", ["card", "sbp"])
def test_non_installment_payment_has_no_schedule(
    method: str,
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post("/payments", json=payment_payload(method=method))

    assert response.status_code == 201
    assert response.json()["installment_months"] is None
    assert response.json()["schedule"] is None


@pytest.mark.parametrize(
    "payload",
    [
        payment_payload(email="not-an-email"),
        payment_payload(method="cash"),
        payment_payload(promo_code="UNKNOWN"),
        payment_payload(promo_code=""),
        payment_payload(method="installment"),
        payment_payload(method="installment", installment_months=4),
        payment_payload(method="card", installment_months=3),
        payment_payload(method="sbp", installment_months=12),
    ],
)
def test_create_payment_validation_error(
    payload: dict[str, object],
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post("/payments", json=payload)

    assert response.status_code == 422
    assert "detail" in response.json()


def test_create_payment_for_unknown_tariff(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/payments",
            json=payment_payload(tariff_id=999_999),
        )

    assert response.status_code == 404


def test_idempotency_key_returns_existing_payment(
    test_database: sessionmaker[Session],
) -> None:
    headers = {"Idempotency-Key": "same-request"}
    with TestClient(app) as client:
        first = client.post("/payments", json=payment_payload(), headers=headers)
        second = client.post("/payments", json=payment_payload(), headers=headers)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()

    with test_database() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.idempotency_key == "same-request")
        )
    assert count == 1


def test_idempotency_key_ignores_changed_valid_body(
    test_database: sessionmaker[Session],
) -> None:
    headers = {"Idempotency-Key": "changed-request"}
    with TestClient(app) as client:
        first = client.post("/payments", json=payment_payload(), headers=headers)
        second = client.post(
            "/payments",
            json=payment_payload(
                tariff_id=999_999,
                email="other@example.com",
                method="installment",
                installment_months=3,
                promo_code="kvitto10",
            ),
            headers=headers,
        )

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()


def test_requests_without_idempotency_key_create_two_payments(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        first = client.post("/payments", json=payment_payload())
        second = client.post("/payments", json=payment_payload())

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]

    with test_database() as session:
        count = session.scalar(select(func.count()).select_from(Payment))
    assert count == 2


def test_get_payment_and_not_found(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        created = client.post("/payments", json=payment_payload())
        found = client.get(f"/payments/{created.json()['id']}")
        missing = client.get("/payments/999999")

    assert found.status_code == 200
    assert found.json() == created.json()
    assert missing.status_code == 404


def test_saved_amount_does_not_change_with_tariff_price(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        created = client.post(
            "/payments",
            json=payment_payload(promo_code="KVITTO10"),
        )

        with test_database() as session:
            tariff = session.get(Tariff, 2)
            assert tariff is not None
            tariff.price = 5_000_000
            session.commit()

        found = client.get(f"/payments/{created.json()['id']}")

    assert found.status_code == 200
    assert found.json()["amount"] == 1_791_000
    assert found.json()["discount"] == 199_000


def test_concurrent_requests_with_same_key_create_one_payment(
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    calculation_barrier = Barrier(2, timeout=10)
    original_calculate_discount = payment_routes.calculate_discount

    def synchronized_calculate_discount(
        price_kopecks: int,
        promo_code: str | None,
    ) -> int:
        calculation_barrier.wait()
        return original_calculate_discount(price_kopecks, promo_code)

    monkeypatch.setattr(
        payment_routes,
        "calculate_discount",
        synchronized_calculate_discount,
    )

    headers = {"Idempotency-Key": "concurrent-request"}
    with TestClient(app) as client:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    client.post,
                    "/payments",
                    json=payment_payload(),
                    headers=headers,
                )
                for _ in range(2)
            ]
            responses = [future.result(timeout=15) for future in futures]

    assert sorted(response.status_code for response in responses) == [200, 201]
    assert responses[0].json()["id"] == responses[1].json()["id"]

    with test_database() as session:
        count = session.scalar(
            select(func.count())
            .select_from(Payment)
            .where(Payment.idempotency_key == "concurrent-request")
        )
    assert count == 1
