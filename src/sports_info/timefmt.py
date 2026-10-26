"""Converting stored UTC times into the user's timezone and friendly labels."""

from datetime import date, datetime, timedelta, timezone
from functools import cache
from zoneinfo import ZoneInfo, available_timezones


def default_timezone() -> str:
    try:
        from tzlocal import get_localzone_name

        name = get_localzone_name()
        if name in available_timezones():
            return name
    except Exception:  # tzlocal can fail on unusual system configs
        pass
    return "UTC"


@cache
def all_timezones() -> list[str]:
    return sorted(available_timezones())


def to_local(dt_utc: datetime, tz_name: str) -> datetime:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    return dt_utc.astimezone(ZoneInfo(tz_name))


def day_label(day: date, today: date) -> str:
    if day == today:
        return "Today"
    if day == today + timedelta(days=1):
        return "Tomorrow"
    if day == today - timedelta(days=1):
        return "Yesterday"
    return f"{day:%A} {day.day} {day:%B}"


def short_time(dt_utc: datetime, tz_name: str) -> str:
    return to_local(dt_utc, tz_name).strftime("%H:%M")


def short_datetime(dt_utc: datetime, tz_name: str) -> str:
    local = to_local(dt_utc, tz_name)
    return f"{local:%a} {local.day} {local:%b}, {local:%H:%M}"


def relative(dt_utc: datetime, now_utc: datetime) -> str:
    seconds = (dt_utc - now_utc).total_seconds()
    future = seconds >= 0
    seconds = abs(seconds)
    if seconds < 60:
        return "now"
    if seconds < 3600:
        amount = f"{int(seconds // 60)} min"
    elif seconds < 86400:
        amount = f"{int(seconds // 3600)} h"
    else:
        days = int(seconds // 86400)
        amount = f"{days} day{'s' if days != 1 else ''}"
    return f"in {amount}" if future else f"{amount} ago"
