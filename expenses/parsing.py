"""Parsing and formatting helpers for expense forms and templates."""

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo


class FormError(ValueError):
    pass


def parse_money(value: str, field: str, allow_zero: bool = False,
                allow_negative: bool = False) -> int:
    """'$1,234.56' → 123456 cents; '-$24.99' → -2499 when negatives are allowed."""
    cleaned = value.strip().replace("$", "").replace(",", "")
    if not cleaned:
        if allow_zero:
            return 0
        raise FormError(f"{field} is required.")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise FormError(f"{field} must be an amount like 12.34.")
    if amount != amount.quantize(Decimal("0.01")):
        raise FormError(f"{field} can't have more than two decimal places.")
    if amount == 0 and not allow_zero:
        raise FormError(f"{field} can't be zero." if allow_negative
                        else f"{field} must be more than zero.")
    if amount < 0 and not allow_negative:
        raise FormError(f"{field} must be more than zero.")
    return int(amount * 100)


def parse_date(value: str, field: str, required: bool = True) -> date | None:
    value = value.strip()
    if not value:
        if required:
            raise FormError(f"{field} is required.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise FormError(f"{field} must be a date.")


def money(cents: int | None) -> str:
    """Jinja filter: 123456 → '$1,234.56'."""
    cents = cents or 0
    sign = "-" if cents < 0 else ""
    return f"{sign}${abs(cents) / 100:,.2f}"


LOCAL_TZ = ZoneInfo("America/Toronto")


def local_time(value: datetime | None) -> str:
    """Jinja filter: stored UTC timestamp → 'Sep 23, 2026 2:05 PM' in Toronto time."""
    if value is None:
        return ""
    if value.tzinfo is None:            # SQLite returns naive UTC
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(LOCAL_TZ).strftime("%b %-d, %Y %-I:%M %p")
