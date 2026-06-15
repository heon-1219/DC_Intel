from datetime import datetime
from typing import Protocol

from app.calendar.models import RawEvent


class CalendarProvider(Protocol):
    name: str

    async def fetch_scheduled(self, start_utc: datetime, end_utc: datetime) -> list[RawEvent]: ...
