"""Создание и получение платежей."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status
from pydantic import EmailStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Payment, Tariff
from app.schemas import PaymentCreate, PaymentRead, PaymentStatus
from app.services.payments import calculate_discount, calculate_schedule

router = APIRouter(prefix="/payments", tags=["payments"])


def find_payment_by_key(db: Session, idempotency_key: str) -> Payment | None:
    return db.scalar(select(Payment).where(Payment.idempotency_key == idempotency_key))


@router.get("", response_model=list[PaymentRead])
def list_payments(
    db: Annotated[Session, Depends(get_db)],
    email: Annotated[EmailStr | None, Query()] = None,
    payment_status: Annotated[
        PaymentStatus | None,
        Query(alias="status"),
    ] = None,
) -> list[Payment]:
    statement = select(Payment)
    if email is not None:
        statement = statement.where(Payment.email == str(email))
    if payment_status is not None:
        statement = statement.where(Payment.status == payment_status)

    statement = statement.order_by(Payment.id)
    return list(db.scalars(statement).all())


@router.post("", response_model=PaymentRead, status_code=status.HTTP_201_CREATED)
def create_payment(
    payment_data: PaymentCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", max_length=255),
    ] = None,
) -> Payment:
    if idempotency_key is not None:
        existing_payment = find_payment_by_key(db, idempotency_key)
        if existing_payment is not None:
            response.status_code = status.HTTP_200_OK
            return existing_payment

    tariff = db.get(Tariff, payment_data.tariff_id)
    if tariff is None:
        raise HTTPException(status_code=404, detail="Tariff not found")

    discount = calculate_discount(tariff.price, payment_data.promo_code)
    amount = tariff.price - discount
    installment_months = payment_data.installment_months
    schedule = (
        calculate_schedule(amount, installment_months)
        if payment_data.method == "installment" and installment_months is not None
        else None
    )

    payment = Payment(
        tariff_id=tariff.id,
        email=str(payment_data.email),
        method=payment_data.method,
        installment_months=installment_months,
        amount=amount,
        discount=discount,
        schedule=schedule,
        status="pending",
        idempotency_key=idempotency_key,
    )
    db.add(payment)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if idempotency_key is not None:
            existing_payment = find_payment_by_key(db, idempotency_key)
            if existing_payment is not None:
                response.status_code = status.HTTP_200_OK
                return existing_payment
        raise

    db.refresh(payment)
    return payment


@router.get("/{payment_id}", response_model=PaymentRead)
def get_payment(
    payment_id: int,
    db: Annotated[Session, Depends(get_db)],
) -> Payment:
    payment = db.get(Payment, payment_id)
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    return payment
