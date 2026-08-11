"""Duration → expiry helpers shared by key generation and first-use activation."""

from datetime import datetime, timedelta


def add_calendar_months(dt: datetime, months: int) -> datetime:
    """Add whole calendar months, clamping the day to the target month's end."""
    idx = dt.month - 1 + months
    year = dt.year + idx // 12
    month = idx % 12 + 1
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    days_in_month = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1]
    return dt.replace(year=year, month=month, day=min(dt.day, days_in_month))


def expiry_from_duration(value: int, unit: str, now: datetime) -> datetime | None:
    """Return the expiry for a stored validity, or None for lifetime."""
    unit = (unit or "").lower()
    if not unit or unit == "lifetime":
        return None
    if value <= 0:
        return None
    if unit == "minutes":
        return now + timedelta(minutes=value)
    if unit == "hours":
        return now + timedelta(hours=value)
    if unit == "days":
        return now + timedelta(days=value)
    if unit == "weeks":
        return now + timedelta(weeks=value)
    if unit == "months":
        return add_calendar_months(now, value)
    if unit == "years":
        return add_calendar_months(now, value * 12)
    raise ValueError(f"unknown duration unit: {unit}")


def validity_from_duration(days: int, duration: int, unit: str) -> tuple[int, str]:
    """Normalize a license-create payload into (value, unit).

    Returns ("", 0) for lifetime. ``days`` is the legacy field; when ``unit`` is
    set it takes precedence. Raises ValueError on invalid input.
    """
    unit = (unit or "").lower()
    if unit == "lifetime":
        return 0, ""
    if unit:
        if unit not in {"minutes", "hours", "days", "weeks", "months", "years"}:
            raise ValueError("unit must be minutes|hours|days|weeks|months|years|lifetime")
        if duration <= 0:
            raise ValueError("duration must be greater than 0")
        return duration, unit
    if days and days > 0:
        return days, "days"
    return 0, ""
