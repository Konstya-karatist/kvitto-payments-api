"""Контракты входных данных и ответов API."""

from datetime import UTC, datetime
from typing import Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

PaymentMethod = Literal["card", "sbp", "installment"]
PaymentStatus = Literal["pending", "succeeded", "failed", "refunded"]


class TariffRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    price: int  # копейки


class PaymentCreate(BaseModel):
    tariff_id: int = Field(gt=0)
    email: EmailStr
    method: PaymentMethod
    installment_months: Literal[3, 6, 12] | None = None
    promo_code: str | None = None

    @field_validator("promo_code")
    @classmethod
    def validate_promo_code(cls, promo_code: str | None) -> str | None:
        if promo_code is not None and promo_code.upper() != "KVITTO10":
            raise ValueError("unknown promo code")
        return promo_code

    @model_validator(mode="after")
    def validate_installment_months(self) -> Self:
        if self.method == "installment" and self.installment_months is None:
            raise ValueError("installment_months is required for installment")
        if self.method != "installment" and self.installment_months is not None:
            raise ValueError("installment_months is only allowed for installment")
        return self


class PaymentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: PaymentStatus
    tariff_id: int
    amount: int  # копейки
    discount: int  # копейки
    method: PaymentMethod
    installment_months: int | None
    schedule: list[int] | None  # копейки
    email: EmailStr
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def ensure_utc(cls, created_at: datetime) -> datetime:
        if created_at.tzinfo is None:
            return created_at.replace(tzinfo=UTC)
        return created_at.astimezone(UTC)


class BankWebhook(BaseModel):
    payment_id: int = Field(gt=0)
    status: PaymentStatus


class BankWebhookResult(BaseModel):
    result: Literal["ok"]
