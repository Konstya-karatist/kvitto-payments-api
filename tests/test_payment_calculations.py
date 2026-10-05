import pytest

from app.services.payments import (
    calculate_discount,
    calculate_schedule,
    is_transition_allowed,
)

STATUSES = ("pending", "succeeded", "failed", "refunded")
ALLOWED_TRANSITIONS = {
    ("pending", "succeeded"),
    ("pending", "failed"),
    ("succeeded", "refunded"),
}


@pytest.mark.parametrize(
    ("promo_code", "expected_discount"),
    [
        (None, 0),
        ("KVITTO10", 199_000),
        ("kvitto10", 199_000),
        ("KvItTo10", 199_000),
    ],
)
def test_calculate_discount(
    promo_code: str | None,
    expected_discount: int,
) -> None:
    discount = calculate_discount(1_990_000, promo_code)

    assert discount == expected_discount
    assert isinstance(discount, int)


@pytest.mark.parametrize("promo_code", ["UNKNOWN", ""])
def test_calculate_discount_rejects_unknown_code(promo_code: str) -> None:
    with pytest.raises(ValueError):
        calculate_discount(1_990_000, promo_code)


@pytest.mark.parametrize(
    ("amount", "months", "expected_schedule"),
    [
        (1_990_000, 3, [663_334, 663_333, 663_333]),
        (1_990_000, 6, [331_667, 331_667, 331_667, 331_667, 331_666, 331_666]),
        (
            1_990_000,
            12,
            [
                165_834,
                165_834,
                165_834,
                165_834,
                165_833,
                165_833,
                165_833,
                165_833,
                165_833,
                165_833,
                165_833,
                165_833,
            ],
        ),
        (10, 3, [4, 3, 3]),
        (11, 3, [4, 4, 3]),
    ],
)
def test_calculate_schedule(
    amount: int,
    months: int,
    expected_schedule: list[int],
) -> None:
    schedule = calculate_schedule(amount, months)

    assert schedule == expected_schedule
    assert len(schedule) == months
    assert sum(schedule) == amount
    assert all(isinstance(payment, int) for payment in schedule)


@pytest.mark.parametrize("months", [3, 6, 12])
def test_schedule_puts_extra_kopecks_first(months: int) -> None:
    amount = 100
    schedule = calculate_schedule(amount, months)
    base, remainder = divmod(amount, months)

    assert schedule[:remainder] == [base + 1] * remainder
    assert schedule[remainder:] == [base] * (months - remainder)


@pytest.mark.parametrize(
    ("current_status", "new_status"),
    [(current, new) for current in STATUSES for new in STATUSES],
)
def test_is_transition_allowed(current_status: str, new_status: str) -> None:
    result = is_transition_allowed(current_status, new_status)

    assert result is ((current_status, new_status) in ALLOWED_TRANSITIONS)
