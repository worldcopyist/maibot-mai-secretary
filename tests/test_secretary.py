from __future__ import annotations

import importlib
import json
import logging
import random
import sys
import types
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("mai_secretary")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("mai_secretary", package)
core = importlib.import_module("mai_secretary.secretary_core")
module = importlib.import_module("mai_secretary.plugin")


class FakeProactive:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def trigger(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True}


class FakeChat:
    async def open_session(self, **kwargs):
        return {"stream_id": "real-stream-1"}


def make_plugin(tmp_path: Path, config: dict | None = None):
    plugin = module.MaiSecretaryPlugin()
    plugin._plugin_config_instance = module.SecretaryConfig.model_validate(config or {})
    proactive = FakeProactive()
    plugin._ctx = types.SimpleNamespace(
        maisaka=types.SimpleNamespace(proactive=proactive),
        chat=FakeChat(),
        logger=logging.getLogger("test_secretary"),
        paths=types.SimpleNamespace(data_dir=tmp_path),
    )
    plugin._state_path = tmp_path / "secretary-state.json"
    return plugin, proactive


def test_daily_weekly_and_once_time_calculation():
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 20, 9, 0, tzinfo=zone)  # Tuesday
    daily = core.next_occurrence("daily", "08:00", "Asia/Shanghai", "", now)
    weekly = core.next_occurrence("weekly", "08:00", "Asia/Shanghai", "2,4", now)
    assert datetime.fromtimestamp(daily, zone) == datetime(
        2026, 10, 21, 8, 0, tzinfo=zone
    )
    assert datetime.fromtimestamp(weekly, zone) == datetime(
        2026, 10, 22, 8, 0, tzinfo=zone
    )
    with pytest.raises(ValueError, match="时区"):
        core.next_occurrence("once", "2026-10-21T08:00:00", "Asia/Shanghai", "", now)
    with pytest.raises(ValueError, match="未来"):
        core.next_occurrence(
            "once", "2026-10-19T08:00:00+08:00", "Asia/Shanghai", "", now
        )


def test_overnight_window_uses_previous_start_date():
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 21, 0, 30, tzinfo=zone)
    key, first, last = core.next_window(
        now, core.parse_clock("20:00"), core.parse_clock("01:00"), zone
    )
    assert key == "2026-10-20"
    assert first == datetime(2026, 10, 20, 20, 0, tzinfo=zone)
    assert last == datetime(2026, 10, 21, 1, 0, tzinfo=zone)


def test_interval_slots_keep_each_gap_within_requested_offset():
    zone = ZoneInfo("Asia/Shanghai")
    first = datetime(2026, 10, 20, 10, 0, tzinfo=zone)
    last = datetime(2026, 10, 21, 2, 0, tzinfo=zone)
    slots = core.interval_slots(first, first, last, 2, 15, random.Random(7))
    gaps = [slots[0] - first.timestamp(), *(b - a for a, b in pairwise(slots))]
    assert len(slots) >= 6
    assert all(105 * 60 <= gap <= 135 * 60 for gap in gaps)
    assert all(first.timestamp() < slot < last.timestamp() for slot in slots)
    with pytest.raises(ValueError, match="小于平均间隔"):
        core.interval_slots(first, first, last, 2, 120, random.Random(7))


@pytest.mark.asyncio
async def test_one_time_task_persists_and_does_not_repeat(tmp_path):
    plugin, proactive = make_plugin(tmp_path)
    now = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    plugin._tasks["abc"] = core.ScheduledTask(
        id="abc",
        stream_id="stream-1",
        owner_user_id="user-1",
        instruction="告诉我天气",
        schedule="once",
        at="2026-10-20T15:59:00+08:00",
        timezone="Asia/Shanghai",
        weekdays="",
        next_run=now.timestamp() - 60,
    )
    await plugin._tick(now)
    await plugin._tick(now)
    assert len(proactive.calls) == 1
    assert "可靠的实时数据" in proactive.calls[0]["intent"]
    assert plugin._tasks["abc"].status == "completed"

    restored, restored_proactive = make_plugin(tmp_path)
    restored._load_state()
    await restored._tick(now)
    assert restored_proactive.calls == []
    assert restored._tasks["abc"].status == "completed"


@pytest.mark.asyncio
async def test_missed_one_time_task_is_not_sent_late(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"plugin": {"misfire_grace_seconds": 60}})
    now = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    plugin._tasks["late"] = core.ScheduledTask(
        id="late",
        stream_id="stream-1",
        owner_user_id="user-1",
        instruction="过期消息",
        schedule="once",
        at="2026-10-20T15:00:00+08:00",
        timezone="Asia/Shanghai",
        weekdays="",
        next_run=now.timestamp() - 3600,
    )
    await plugin._tick(now)
    assert proactive.calls == []
    assert plugin._tasks["late"].status == "missed"


@pytest.mark.asyncio
async def test_daily_task_moves_to_next_day_after_trigger(tmp_path):
    plugin, proactive = make_plugin(tmp_path)
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 20, 8, 0, 10, tzinfo=zone)
    plugin._tasks["daily"] = core.ScheduledTask(
        id="daily",
        stream_id="stream-1",
        owner_user_id="user-1",
        instruction="给我说天气预报",
        schedule="daily",
        at="08:00",
        timezone="Asia/Shanghai",
        weekdays="",
        next_run=now.timestamp() - 10,
    )
    await plugin._tick(now)
    await plugin._tick(now)
    assert len(proactive.calls) == 1
    assert plugin._tasks["daily"].status == "active"
    assert datetime.fromtimestamp(plugin._tasks["daily"].next_run, zone) == datetime(
        2026, 10, 21, 8, 0, tzinfo=zone
    )


@pytest.mark.asyncio
async def test_random_proactive_plan_survives_reload(tmp_path):
    config = {"proactive": {"target_chats": ["qq:group:123"], "messages_per_window": 1}}
    plugin, proactive = make_plugin(tmp_path, config)
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 20, 10, 0, tzinfo=zone)
    await plugin._tick(now)
    slot = plugin._plans["qq:group:123"]["slots"][0]
    assert (
        now.timestamp() < slot < datetime(2026, 10, 20, 21, 0, tzinfo=zone).timestamp()
    )
    await plugin._tick(datetime.fromtimestamp(slot + 1, UTC))
    assert len(proactive.calls) == 1
    assert proactive.calls[0]["stream_id"] == "real-stream-1"

    restored, restored_proactive = make_plugin(tmp_path, config)
    restored._load_state()
    await restored._tick(datetime.fromtimestamp(slot + 1, UTC))
    assert restored_proactive.calls == []


@pytest.mark.asyncio
async def test_interval_plan_survives_reload_and_replans_on_mode_change(tmp_path):
    target = "qq:private:123"
    config = {
        "proactive": {
            "target_chats": [target],
            "window_start": "10:00",
            "window_end": "02:00",
            "scheduling_mode": "interval",
            "average_interval_hours": 2,
            "offset_minutes": 15,
        }
    }
    plugin, _ = make_plugin(tmp_path, config)
    plugin._rng.seed(7)
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 20, 10, 0, tzinfo=zone)
    await plugin._tick(now)
    planned = plugin._plans[target]["slots"].copy()

    restored, _ = make_plugin(tmp_path, config)
    restored._load_state()
    await restored._tick(datetime(2026, 10, 20, 10, 1, tzinfo=zone))
    assert restored._plans[target]["slots"] == planned

    restored.config.proactive.scheduling_mode = "count"
    await restored._tick(datetime(2026, 10, 20, 10, 2, tzinfo=zone))
    assert len(restored._plans[target]["slots"]) == 1
    assert restored._plans[target]["slots"] != planned


@pytest.mark.asyncio
async def test_tools_restrict_tasks_to_current_user_and_chat(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    identity = {"stream_id": "stream-1", "chat_id": "stream-1", "user_id": "user-1"}
    created = await plugin.secretary_create_task(
        **identity, instruction="每天告诉我天气", schedule="daily", at="08:00"
    )
    assert created["success"] is True
    task_id = created["task_id"]
    other_user = {**identity, "user_id": "user-2"}
    assert (await plugin.secretary_list_tasks(**other_user))["tasks"] == []
    assert (await plugin.secretary_cancel_task(**other_user, task_id=task_id))[
        "success"
    ] is False
    other_chat = {**identity, "chat_id": "stream-2"}
    assert (await plugin.secretary_list_tasks(**other_chat))["success"] is False
    assert (await plugin.secretary_cancel_task(**identity, task_id=task_id))[
        "success"
    ] is True
    assert (
        json.loads((tmp_path / "secretary-state.json").read_text(encoding="utf-8"))[
            "tasks"
        ]
        == []
    )
