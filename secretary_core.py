"""Time calculations and persisted task records for 麦麦小秘书."""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_clock(value: str) -> time:
    try:
        hour, minute = (int(part) for part in value.split(":"))
        return time(hour, minute)
    except (TypeError, ValueError) as exc:
        raise ValueError("时间须为 HH:MM，例如 08:00") from exc


def parse_weekdays(value: str) -> tuple[int, ...]:
    try:
        days = tuple(sorted({int(part.strip()) for part in value.split(",")}))
    except (TypeError, ValueError) as exc:
        raise ValueError("星期须用 1 到 7 的数字，逗号分隔；1 是周一") from exc
    if not days or any(day < 1 or day > 7 for day in days):
        raise ValueError("星期须用 1 到 7 的数字，逗号分隔；1 是周一")
    return days


def parse_once(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(
            "单次任务时间须为带时区的 ISO 时间，例如 2026-10-21T08:00:00+08:00"
        ) from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("单次任务时间必须带时区，例如 +08:00")
    return result


@dataclass
class ScheduledTask:
    id: str
    stream_id: str
    owner_user_id: str
    instruction: str
    schedule: str
    at: str
    timezone: str
    weekdays: str
    next_run: float
    status: str = "active"
    last_error: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ScheduledTask:
        return cls(
            id=str(data["id"]),
            stream_id=str(data["stream_id"]),
            owner_user_id=str(data["owner_user_id"]),
            instruction=str(data["instruction"]),
            schedule=str(data["schedule"]),
            at=str(data["at"]),
            timezone=str(data["timezone"]),
            weekdays=str(data.get("weekdays", "")),
            next_run=float(data["next_run"]),
            status=str(data.get("status", "active")),
            last_error=str(data.get("last_error", "")),
        )


def next_occurrence(
    schedule: str,
    at: str,
    timezone_name: str,
    weekdays: str,
    after: datetime,
) -> float:
    """Return the first occurrence strictly after ``after`` as a UTC timestamp."""
    if after.tzinfo is None:
        raise ValueError("内部时间必须带时区")
    if schedule == "once":
        candidate = parse_once(at)
        if candidate <= after:
            raise ValueError("单次任务时间必须在未来")
        return candidate.timestamp()
    if schedule not in {"daily", "weekly"}:
        raise ValueError("周期只支持 once、daily 或 weekly")

    zone = ZoneInfo(timezone_name)
    clock = parse_clock(at)
    days = parse_weekdays(weekdays) if schedule == "weekly" else ()
    local_today = after.astimezone(zone).date()
    for offset in range(8):
        day = local_today + timedelta(days=offset)
        if days and day.isoweekday() not in days:
            continue
        candidate = datetime.combine(day, clock, zone)
        if candidate > after:
            return candidate.timestamp()
    raise ValueError("无法计算下次执行时间")


def window_bounds(
    anchor: date, start: time, end: time, zone: ZoneInfo
) -> tuple[datetime, datetime]:
    if start == end:
        raise ValueError("主动发言窗口的开始和结束时间不能相同")
    first = datetime.combine(anchor, start, zone)
    last = datetime.combine(anchor + timedelta(days=1 if end < start else 0), end, zone)
    return first, last


def next_window(
    now: datetime, start: time, end: time, zone: ZoneInfo
) -> tuple[str, datetime, datetime]:
    """Find the current or next window; overnight windows retain their start date."""
    today = now.astimezone(zone).date()
    for offset in (-1, 0, 1):
        anchor = today + timedelta(days=offset)
        first, last = window_bounds(anchor, start, end, zone)
        if last > now:
            return anchor.isoformat(), first, last
    raise RuntimeError("无法确定主动发言时间窗口")


def random_slots(
    now: datetime,
    first: datetime,
    last: datetime,
    count: int,
    rng: random.Random,
) -> list[float]:
    """Spread random slots across the remaining window instead of bunching them."""
    lower = max(now.timestamp() + 1, first.timestamp())
    upper = last.timestamp()
    if upper <= lower:
        return []
    count = min(count, max(1, int((upper - lower) // 300) + 1))
    width = (upper - lower) / count
    return [
        rng.uniform(lower + index * width, lower + (index + 1) * width)
        for index in range(count)
    ]


def interval_slots(
    now: datetime,
    first: datetime,
    last: datetime,
    average_interval_hours: float,
    offset_minutes: int,
    rng: random.Random,
) -> list[float]:
    """Schedule gaps uniformly around the requested average, inside one window."""
    interval = average_interval_hours * 3600
    offset = offset_minutes * 60
    if interval <= 0 or offset < 0 or offset >= interval:
        raise ValueError("随机发言偏移分钟数须小于平均间隔")

    cursor = max(now.timestamp(), first.timestamp())
    upper = last.timestamp()
    slots: list[float] = []
    while cursor < upper:
        cursor += rng.uniform(interval - offset, interval + offset)
        if cursor >= upper:
            break
        slots.append(cursor)
    return slots
