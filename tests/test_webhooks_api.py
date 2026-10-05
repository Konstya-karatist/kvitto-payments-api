import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

import app.routes.webhooks as webhook_routes
from app.config import settings
from app.main import app
from app.models import Payment

STATUSES = ("pending", "succeeded", "failed", "refunded")
ALLOWED_TRANSITIONS = {
    ("pending", "succeeded"),
    ("pending", "failed"),
    ("succeeded", "refunded"),
}
FORBIDDEN_TRANSITIONS = [
    (current, new)
    for current in STATUSES
    for new in STATUSES
    if (current, new) not in ALLOWED_TRANSITIONS
]


def webhook_signature(secret: str, body: bytes) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def create_payment(
    client: TestClient,
    *,
    idempotency_key: str | None = None,
) -> dict[str, object]:
    headers = (
        {"Idempotency-Key": idempotency_key} if idempotency_key is not None else None
    )
    response = client.post(
        "/payments",
        json={
            "tariff_id": 1,
            "email": "webhook@example.com",
            "method": "card",
        },
        headers=headers,
    )
    assert response.status_code == 201
    return response.json()


def set_payment_status(
    session_factory: sessionmaker[Session],
    payment_id: int,
    status: str,
) -> None:
    with session_factory() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        payment.status = status
        session.commit()


def read_payment_status(
    session_factory: sessionmaker[Session],
    payment_id: int,
) -> str:
    with session_factory() as session:
        payment = session.get(Payment, payment_id)
        assert payment is not None
        return payment.status


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    sorted(ALLOWED_TRANSITIONS),
)
def test_allowed_transition_is_saved(
    current_status: str,
    new_status: str,
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        payment = create_payment(client)
        payment_id = int(payment["id"])
        set_payment_status(test_database, payment_id, current_status)

        response = client.post(
            "/webhooks/bank",
            json={"payment_id": payment_id, "status": new_status},
        )

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert read_payment_status(test_database, payment_id) == new_status


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    FORBIDDEN_TRANSITIONS,
)
def test_forbidden_transition_returns_409_and_preserves_status(
    current_status: str,
    new_status: str,
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        payment = create_payment(client)
        payment_id = int(payment["id"])
        set_payment_status(test_database, payment_id, current_status)

        response = client.post(
            "/webhooks/bank",
            json={"payment_id": payment_id, "status": new_status},
        )

    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    assert read_payment_status(test_database, payment_id) == current_status


def test_webhook_for_unknown_payment_returns_404(
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/bank",
            json={"payment_id": 999_999, "status": "succeeded"},
        )

    assert response.status_code == 404


def test_webhook_openapi_documents_404_and_409() -> None:
    responses = app.openapi()["paths"]["/webhooks/bank"]["post"]["responses"]

    assert "404" in responses
    assert "409" in responses
    assert responses["409"]["content"]["application/json"]["example"] == {
        "error": "invalid_transition"
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"payment_id": 1, "status": "unknown"},
        {"status": "succeeded"},
        {"payment_id": 1},
        {"payment_id": 0, "status": "succeeded"},
        {"payment_id": -1, "status": "succeeded"},
    ],
)
def test_webhook_validation_returns_standard_422(
    payload: dict[str, object],
    test_database: sessionmaker[Session],
) -> None:
    with TestClient(app) as client:
        response = client.post("/webhooks/bank", json=payload)

    assert response.status_code == 422
    assert isinstance(response.json().get("detail"), list)


def test_idempotent_payment_response_contains_status_changed_by_webhook(
    test_database: sessionmaker[Session],
) -> None:
    headers = {"Idempotency-Key": "webhook-idempotency"}
    payload = {
        "tariff_id": 1,
        "email": "webhook@example.com",
        "method": "card",
    }

    with TestClient(app) as client:
        created = client.post("/payments", json=payload, headers=headers)
        payment_id = created.json()["id"]

        webhook = client.post(
            "/webhooks/bank",
            json={"payment_id": payment_id, "status": "succeeded"},
        )
        repeated = client.post("/payments", json=payload, headers=headers)

    assert created.status_code == 201
    assert webhook.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["id"] == payment_id
    assert repeated.json()["status"] == "succeeded"


def test_concurrent_transitions_allow_only_one_winner(
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    after_read_barrier = Barrier(2, timeout=10)
    original_is_transition_allowed = webhook_routes.is_transition_allowed

    def synchronized_transition_check(
        current_status: str,
        new_status: str,
    ) -> bool:
        after_read_barrier.wait()
        return original_is_transition_allowed(current_status, new_status)

    monkeypatch.setattr(
        webhook_routes,
        "is_transition_allowed",
        synchronized_transition_check,
    )

    with TestClient(app) as client:
        payment = create_payment(client)
        payment_id = int(payment["id"])

        def send_webhook(new_status: str):
            response = client.post(
                "/webhooks/bank",
                json={"payment_id": payment_id, "status": new_status},
            )
            return new_status, response

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(send_webhook, "succeeded"),
                executor.submit(send_webhook, "failed"),
            ]
            results = [future.result(timeout=15) for future in futures]

    assert sorted(response.status_code for _, response in results) == [200, 409]

    winning_status = next(
        status for status, response in results if response.status_code == 200
    )
    losing_response = next(
        response for _, response in results if response.status_code == 409
    )
    assert losing_response.json() == {"error": "invalid_transition"}
    assert read_payment_status(test_database, payment_id) == winning_status


def test_webhook_accepts_correct_signature(
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "webhook_secret", secret)

    with TestClient(app) as client:
        payment = create_payment(client)
        body = f'{{"payment_id":{payment["id"]},"status":"succeeded"}}'.encode()
        response = client.post(
            "/webhooks/bank",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": webhook_signature(secret, body),
            },
        )

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert read_payment_status(test_database, int(payment["id"])) == "succeeded"


@pytest.mark.parametrize("signature", [None, "incorrect-signature"])
def test_webhook_rejects_missing_or_invalid_signature_without_changes(
    signature: str | None,
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "webhook_secret", secret)

    with TestClient(app) as client:
        payment = create_payment(client)
        payment_id = int(payment["id"])
        body = f'{{"payment_id":{payment_id},"status":"succeeded"}}'.encode()
        headers = {"Content-Type": "application/json"}
        if signature is not None:
            headers["X-Signature"] = signature

        response = client.post("/webhooks/bank", content=body, headers=headers)

    assert response.status_code == 401
    assert read_payment_status(test_database, payment_id) == "pending"


def test_webhook_rejects_changed_body_with_old_signature(
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "webhook_secret", secret)

    with TestClient(app) as client:
        payment = create_payment(client)
        payment_id = int(payment["id"])
        signed_body = f'{{"payment_id":{payment_id},"status":"failed"}}'.encode()
        changed_body = f'{{"payment_id":{payment_id},"status":"succeeded"}}'.encode()
        response = client.post(
            "/webhooks/bank",
            content=changed_body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": webhook_signature(secret, signed_body),
            },
        )

    assert response.status_code == 401
    assert read_payment_status(test_database, payment_id) == "pending"


def test_webhook_signature_uses_exact_raw_body_bytes(
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "webhook_secret", secret)

    with TestClient(app) as client:
        payment = create_payment(client)
        payment_id = int(payment["id"])
        body = f'{{ "payment_id": {payment_id}, "status": "succeeded" }}'.encode()
        response = client.post(
            "/webhooks/bank",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": webhook_signature(secret, body),
            },
        )

    assert response.status_code == 200


def test_webhook_validation_remains_422_with_valid_signature(
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    secret = "test-webhook-secret"
    monkeypatch.setattr(settings, "webhook_secret", secret)
    body = b'{"payment_id":1,"status":"unknown"}'

    with TestClient(app) as client:
        response = client.post(
            "/webhooks/bank",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Signature": webhook_signature(secret, body),
            },
        )

    assert response.status_code == 422
    assert isinstance(response.json().get("detail"), list)


def test_webhook_signature_check_is_disabled_without_secret(
    test_database: sessionmaker[Session],
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "webhook_secret", None)

    with TestClient(app) as client:
        payment = create_payment(client)
        response = client.post(
            "/webhooks/bank",
            json={"payment_id": payment["id"], "status": "succeeded"},
        )

    assert response.status_code == 200
