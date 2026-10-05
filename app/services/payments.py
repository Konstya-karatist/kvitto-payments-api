def calculate_discount(
    price_kopecks: int,
    promo_code: str | None,
) -> int:
    if promo_code is None:
        return 0
    elif promo_code.upper() == "KVITTO10":
        return price_kopecks // 10
    else:
        raise ValueError("Unknown promo code")


def calculate_schedule(amount_kopecks: int, months: int) -> list[int]:
    base = amount_kopecks // months
    remainder = amount_kopecks % months
    schedule = []

    for i in range(months):
        if i < remainder:
            schedule.append(base + 1)
        else:
            schedule.append(base)

    return schedule


def is_transition_allowed(current_status: str, new_status: str) -> bool:
    if current_status == "pending":
        return new_status == "succeeded" or new_status == "failed"
    elif current_status == "succeeded":
        return new_status == "refunded"
    else:
        return False
