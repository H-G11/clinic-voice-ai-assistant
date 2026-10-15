"""Case/API calendar: fixed GMT+4, independent of Windows/user timezone."""
from datetime import datetime, timedelta, timezone

CLINIC_TZ = timezone(timedelta(hours=4), 'GMT+4')


def clinic_now():
    return datetime.now(CLINIC_TZ).replace(tzinfo=None)
