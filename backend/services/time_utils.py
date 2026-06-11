from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import settings


def business_timezone() -> ZoneInfo:
    return ZoneInfo(settings.apscheduler_timezone)


def business_now() -> datetime:
    """Naive wall-clock time used by business schedules stored in DB."""
    return datetime.now(business_timezone()).replace(tzinfo=None)


def business_now_aware() -> datetime:
    return datetime.now(business_timezone())


def as_business_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=business_timezone())
    return value.astimezone(business_timezone())


def next_business_time(value: datetime) -> datetime:
    run_time = as_business_time(value)
    now = business_now_aware()
    if run_time <= now:
        return now + timedelta(seconds=1)
    return run_time
