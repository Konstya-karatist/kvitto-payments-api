import hashlib
import hmac
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import Payment
from app.schemas import BankWebhook, BankWebhookResult
from app.services.payments import is_transition_allowed

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


async def verify_webhook_signature(
    request: Request,
    x_signature: Annotated[str | None, Header(alias="X-Signature")] = None,
) -> None:
    if not settings.webhook_secret:
        return

    body = await request.body()
    expected_signature = hmac.new(
        settings.webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if x_signature is None or not hmac.compare_digest(
        x_signature,
        expected_signature,
    ):
        raise HTTPException(status_code=401, detail="Invalid signature")


@router.post(
    "/bank",
    response_model=BankWebhookResult,
    dependencies=[Depends(verify_webhook_signature)],
    responses={
        401: {"description": "Invalid or missing webhook signature"},
        404: {"description": "Payment not found"},
        409: {
            "description": "Invalid status transition",
            "content": {
                "application/json": {
                    "example": {"error": "invalid_transition"},
                }
            },
        },
    },
)
def bank_webhook(
    webhook_data: BankWebhook,
    db: Annotated[Session, Depends(get_db)],
):

    payment = db.get(Payment, webhook_data.payment_id)

    if payment is None:
        raise HTTPException(404, "Payment not found")

    if not is_transition_allowed(payment.status, webhook_data.status):
        return JSONResponse(status_code=409, content={"error": "invalid_transition"})

    current_status = payment.status

    statement = (
        update(Payment)
        .where(
            Payment.id == webhook_data.payment_id,
            Payment.status == current_status,
        )
        .values(status=webhook_data.status)
    )

    result = db.execute(statement)

    if result.rowcount == 0:
        db.rollback()
        return JSONResponse(
            status_code=409,
            content={"error": "invalid_transition"},
        )

    db.commit()
    return BankWebhookResult(result="ok")
