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
stream_router = importlib.import_module("mai_secretary.stream_router")


class FakeProactive:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def trigger(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True}


class FakeChat:
    def __init__(self) -> None:
        self.streams = [{"stream_id": "other-stream", "platform": "qq", "chat_type": "private", "user_id": "other", "account_id": "bot-1", "scope": ""}]
        self.open_calls: list[dict] = []

    async def get_all_streams(self, **kwargs):
        return self.streams

    async def open_session(self, **kwargs):
        self.open_calls.append(kwargs)
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


def test_sdk_still_exposes_original_tools_and_hooks(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    assert {(item["type"], item["name"]) for item in plugin.get_components()} == {
        ("TOOL", "secretary_create_task"),
        ("TOOL", "secretary_list_tasks"),
        ("TOOL", "secretary_cancel_task"),
        ("HOOK_HANDLER", "secretary_cancel_pending_on_inbound"),
        ("HOOK_HANDLER", "secretary_capture_proactive_reply"),
        ("HOOK_HANDLER", "secretary_anti_bullying_inspect"),
    }


def test_admin_account_format_and_new_config_defaults():
    settings = module.PluginSettings.model_validate(
        {"admin_accounts": ["qq：123456789", "qq:123456789"]}
    )
    assert settings.admin_accounts == ["qq:123456789"]
    with pytest.raises(ValueError, match="管理员账号"):
        module.PluginSettings.model_validate({"admin_accounts": ["qq:someone"]})
    assert module.SecretaryConfig().anti_bullying.forbidden_words == []


@pytest.mark.asyncio
async def test_anti_bullying_reports_only_confirmed_direct_abuse(tmp_path):
    plugin, _ = make_plugin(
        tmp_path,
        {
            "plugin": {"admin_accounts": ["qq:123456789"]},
            "anti_bullying": {"forbidden_words": ["坏词"]},
        },
    )
    plugin.anti_bullying.bot_names = ("蓝天",)
    plugin.ctx.chat.streams = [
        {
            "stream_id": "admin-stream",
            "platform": "qq",
            "chat_type": "private",
            "user_id": "123456789",
            "account_id": "bot-1",
            "scope": "",
        }
    ]
    llm_calls = []
    sent = []

    async def classify(**kwargs):
        llm_calls.append(kwargs)
        return {
            "success": True,
            "response": json.dumps(
                {
                    "targeted": True,
                    "abusive": True,
                    "confidence": 0.95,
                    "reason": "直接辱骂麦麦",
                }
            ),
        }

    async def get_recent(chat_id, limit):
        assert chat_id == "group-stream"
        assert limit == 6
        return []

    async def send_text(text, stream_id):
        sent.append((text, stream_id))
        return True

    plugin.ctx.llm = types.SimpleNamespace(generate=classify)
    plugin.ctx.message = types.SimpleNamespace(get_recent=get_recent)
    plugin.ctx.send = types.SimpleNamespace(text=send_text)
    inbound = {
        "message_id": "msg-1",
        "session_id": "group-stream",
        "platform": "qq",
        "account_id": "bot-1",
        "processed_plain_text": "蓝天你这个坏词",
        "message_info": {
            "user_info": {"user_id": "user-1", "user_nickname": "甲"},
            "group_info": {"group_id": "group-1", "group_name": "测试群"},
        },
    }
    await plugin.anti_bullying.on_inbound(inbound)
    assert plugin.anti_bullying.queue.qsize() == 1
    await plugin.anti_bullying._process(plugin.anti_bullying.queue.get_nowait())
    assert len(llm_calls) == 1
    assert len(sent) == 1
    assert sent[0][1] == "admin-stream"
    assert "测试群" in sent[0][0]
    assert "msg-1" in sent[0][0]
    assert "anti_bullying_alerts" in json.loads(plugin._state_path.read_text(encoding="utf-8"))
    await plugin.anti_bullying.on_inbound(inbound)
    assert plugin.anti_bullying.queue.empty()
    await plugin.anti_bullying.on_inbound({**inbound, "message_id": "msg-2"})
    await plugin.anti_bullying._process(plugin.anti_bullying.queue.get_nowait())
    assert len(llm_calls) == 1  # Per-sender cooldown also avoids another model call.
    assert len(sent) == 1


@pytest.mark.asyncio
async def test_anti_bullying_skips_unrelated_group_and_rejected_quote(tmp_path):
    plugin, _ = make_plugin(
        tmp_path,
        {
            "plugin": {"admin_accounts": ["qq:123456789"]},
            "anti_bullying": {"forbidden_words": ["坏词"]},
        },
    )
    plugin.anti_bullying.bot_names = ("蓝天",)
    llm_calls = []
    sent = []

    async def classify(**kwargs):
        llm_calls.append(kwargs)
        return {
            "success": True,
            "response": '{"targeted":false,"abusive":false,"confidence":0.99,"reason":"在引用"}',
        }

    async def get_recent(chat_id, limit):
        return []

    async def send_text(text, stream_id):
        sent.append((text, stream_id))
        return True

    plugin.ctx.llm = types.SimpleNamespace(generate=classify)
    plugin.ctx.message = types.SimpleNamespace(get_recent=get_recent)
    plugin.ctx.send = types.SimpleNamespace(text=send_text)
    base = {
        "session_id": "group-stream",
        "platform": "qq",
        "account_id": "bot-1",
        "message_info": {
            "user_info": {"user_id": "user-1", "user_nickname": "甲"},
            "group_info": {"group_id": "group-1", "group_name": "测试群"},
        },
    }
    await plugin.anti_bullying.on_inbound(
        {**base, "message_id": "other", "processed_plain_text": "别人今天很开心"}
    )
    assert plugin.anti_bullying.queue.empty()
    await plugin.anti_bullying.on_inbound(
        {**base, "message_id": "quote", "processed_plain_text": "蓝天，坏词是什么意思？"}
    )
    await plugin.anti_bullying._process(plugin.anti_bullying.queue.get_nowait())
    assert len(llm_calls) == 1
    assert sent == []


@pytest.mark.asyncio
async def test_anti_bullying_without_admin_does_not_queue(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    await plugin.anti_bullying.on_inbound(
        {
            "session_id": "private-stream",
            "platform": "qq",
            "processed_plain_text": "蓝天你真坏",
            "message_info": {"user_info": {"user_id": "user-1"}},
        }
    )
    assert plugin.anti_bullying.queue.empty()


@pytest.mark.asyncio
async def test_admin_route_uses_the_same_bot_account(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    plugin.ctx.chat.streams = [
        {
            "stream_id": "right-admin-stream",
            "platform": "qq",
            "chat_type": "private",
            "user_id": "123456789",
            "account_id": "bot-1",
        },
        {
            "stream_id": "other-bot-admin-stream",
            "platform": "qq",
            "chat_type": "private",
            "user_id": "123456789",
            "account_id": "bot-2",
        },
    ]
    assert await stream_router.resolve_stream(
        plugin.ctx,
        "qq:private:123456789",
        {},
        preferred_account_id="bot-1",
    ) == "right-admin-stream"


@pytest.mark.asyncio
async def test_existing_account_scoped_private_stream_is_reused(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    chat = plugin.ctx.chat
    chat.streams = [
        {"stream_id": "old-real-stream", "platform": "qq", "chat_type": "private", "user_id": "123", "account_id": "bot-1", "scope": ""},
        {"stream_id": "duplicate-stream", "platform": "qq", "chat_type": "private", "user_id": "123", "account_id": "", "scope": ""},
    ]

    assert await plugin.proactive._resolve_stream("qq:private:123") == "old-real-stream"
    assert chat.open_calls == []


@pytest.mark.asyncio
async def test_wrapped_stream_result_is_still_accepted(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    chat = plugin.ctx.chat
    chat.streams = [
        {"stream_id": "old-real-stream", "platform": "qq", "chat_type": "private", "user_id": "123", "account_id": "bot-1", "scope": ""}
    ]

    async def wrapped(**kwargs):
        return {"success": True, "streams": chat.streams}

    chat.get_all_streams = wrapped
    assert await plugin.proactive._resolve_stream("qq:private:123") == "old-real-stream"


@pytest.mark.asyncio
async def test_new_target_uses_known_bot_account_and_never_opens_without_it(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    chat = plugin.ctx.chat

    assert await plugin.proactive._resolve_stream("qq:private:123") == "real-stream-1"
    assert chat.open_calls[0]["account_id"] == "bot-1"

    chat.streams = []
    plugin.proactive.streams.clear()
    with pytest.raises(ValueError, match="无法确定"):
        await plugin.proactive._resolve_stream("qq:private:123")
    assert len(chat.open_calls) == 1


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
    plugin.scheduled.tasks["abc"] = core.ScheduledTask(
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
    task_intent = proactive.calls[0]["intent"]
    assert "可靠的实时数据" in task_intent
    assert "不要调用 `secretary_create_task` 重复设置" in task_intent
    assert all(
        f"`{name}`" in task_intent
        for name in (
            "deepseek_search",
            "deepseek_fetch",
            "secretary_create_task",
            "secretary_list_tasks",
            "secretary_cancel_task",
            "tool_search",
        )
    )
    assert plugin.scheduled.tasks["abc"].status == "completed"

    restored, restored_proactive = make_plugin(tmp_path)
    restored._load_state()
    await restored._tick(now)
    assert restored_proactive.calls == []
    assert restored.scheduled.tasks["abc"].status == "completed"


@pytest.mark.asyncio
async def test_missed_one_time_task_is_not_sent_late(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"plugin": {"misfire_grace_seconds": 60}})
    now = datetime(2026, 10, 20, 8, 0, tzinfo=UTC)
    plugin.scheduled.tasks["late"] = core.ScheduledTask(
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
    assert plugin.scheduled.tasks["late"].status == "missed"


@pytest.mark.asyncio
async def test_daily_task_moves_to_next_day_after_trigger(tmp_path):
    plugin, proactive = make_plugin(tmp_path)
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 20, 8, 0, 10, tzinfo=zone)
    plugin.scheduled.tasks["daily"] = core.ScheduledTask(
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
    assert plugin.scheduled.tasks["daily"].status == "active"
    assert datetime.fromtimestamp(plugin.scheduled.tasks["daily"].next_run, zone) == datetime(
        2026, 10, 21, 8, 0, tzinfo=zone
    )


@pytest.mark.asyncio
async def test_random_proactive_plan_survives_reload(tmp_path):
    config = {"proactive": {"target_chats": ["qq:group:123"], "messages_per_window": 1}}
    plugin, proactive = make_plugin(tmp_path, config)
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 20, 10, 0, tzinfo=zone)
    await plugin._tick(now)
    slot = plugin.proactive.plans["qq:group:123"]["slots"][0]
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
    plugin.proactive.rng.seed(7)
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 10, 20, 10, 0, tzinfo=zone)
    await plugin._tick(now)
    planned = plugin.proactive.plans[target]["slots"].copy()

    restored, _ = make_plugin(tmp_path, config)
    restored._load_state()
    await restored._tick(datetime(2026, 10, 20, 10, 1, tzinfo=zone))
    assert restored.proactive.plans[target]["slots"] == planned

    restored.config.proactive.scheduling_mode = "count"
    await restored._tick(datetime(2026, 10, 20, 10, 2, tzinfo=zone))
    assert len(restored.proactive.plans[target]["slots"]) == 1
    assert restored.proactive.plans[target]["slots"] != planned


@pytest.mark.asyncio
async def test_next_proactive_chat_uses_only_a_successfully_sent_previous_message(tmp_path):
    target = "qq:private:123"
    config = {"proactive": {"target_chats": [target], "messages_per_window": 2}}
    plugin, proactive = make_plugin(tmp_path, config)
    plugin.proactive.rng.seed(7)
    zone = ZoneInfo("Asia/Shanghai")
    await plugin._tick(datetime(2026, 10, 20, 9, 0, tzinfo=zone))
    first, second = plugin.proactive.plans[target]["slots"]
    await plugin._tick(datetime.fromtimestamp(first + 1, UTC))
    assert len(proactive.calls) == 1
    assert "自己决定你此刻在做" in proactive.calls[0]["intent"]
    assert "`deepseek_search`" in proactive.calls[0]["intent"]
    assert "`tool_search`" in proactive.calls[0]["intent"]
    assert "日常闲聊无需联网" in proactive.calls[0]["intent"]
    assert "实际发出的文字" not in proactive.calls[0]["intent"]

    message = {
        "session_id": "real-stream-1",
        "message_id": "sent-1",
        "timestamp": str(first + 2),
        "raw_message": [{"type": "text", "data": "我在吃饭"}],
    }
    await plugin.capture_proactive_reply(message, sent=False)
    await plugin.capture_proactive_reply({**message, "session_id": "other-stream"}, sent=True)
    assert "last_message" not in plugin.proactive.continuity[target]
    await plugin.capture_proactive_reply(message, sent=True)
    await plugin.capture_proactive_reply(message, sent=True)  # Duplicate hook delivery.
    await plugin.capture_proactive_reply(
        {**message, "message_id": "sent-2", "timestamp": str(first + 5),
         "raw_message": [{"type": "text", "data": "这碗面真香"}]},
        sent=True,
    )
    assert plugin.proactive.continuity[target]["last_message"] == "我在吃饭 这碗面真香"

    restored, restored_proactive = make_plugin(tmp_path, config)
    restored._load_state()
    await restored._tick(datetime.fromtimestamp(second + 1, UTC))
    assert len(restored_proactive.calls) == 1
    intent = restored_proactive.calls[0]["intent"]
    assert "我在吃饭 这碗面真香" in intent
    assert "按经过的时间自然接续" in intent


@pytest.mark.asyncio
async def test_queued_without_sent_message_does_not_create_false_continuity(tmp_path):
    target = "qq:private:123"
    config = {"proactive": {"target_chats": [target], "messages_per_window": 2}}
    plugin, proactive = make_plugin(tmp_path, config)
    plugin.proactive.rng.seed(7)
    zone = ZoneInfo("Asia/Shanghai")
    await plugin._tick(datetime(2026, 10, 20, 9, 0, tzinfo=zone))
    first, second = plugin.proactive.plans[target]["slots"]
    await plugin._tick(datetime.fromtimestamp(first + 1, UTC))
    await plugin._tick(datetime.fromtimestamp(second + 1, UTC))
    assert len(proactive.calls) == 2
    assert "实际发出的文字" not in proactive.calls[1]["intent"]


@pytest.mark.asyncio
async def test_inbound_message_prevents_claiming_an_ordinary_reply(tmp_path):
    target = "qq:private:123"
    plugin, proactive = make_plugin(
        tmp_path, {"proactive": {"target_chats": [target], "messages_per_window": 2}}
    )
    plugin.proactive.rng.seed(7)
    zone = ZoneInfo("Asia/Shanghai")
    await plugin._tick(datetime(2026, 10, 20, 9, 0, tzinfo=zone))
    first, second = plugin.proactive.plans[target]["slots"]
    await plugin._tick(datetime.fromtimestamp(first + 1, UTC))
    await plugin.cancel_pending_on_inbound(
        {
            "session_id": "real-stream-1",
            "timestamp": str(first + 2),
            "account_id": "bot-1",
            "message_info": {"user_info": {"user_id": "user-1"}},
        }
    )
    await plugin.capture_proactive_reply(
        {
            "session_id": "real-stream-1",
            "timestamp": str(first + 3),
            "raw_message": [{"type": "text", "data": "这是普通回复"}],
        },
        sent=True,
    )
    assert "last_message" not in plugin.proactive.continuity[target]
    await plugin._tick(datetime.fromtimestamp(second + 1, UTC))
    assert "这是普通回复" not in proactive.calls[1]["intent"]


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


def test_old_state_is_loaded_without_losing_module_data(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    task = core.ScheduledTask(
        id="old-task",
        stream_id="stream-1",
        owner_user_id="user-1",
        instruction="每天说天气",
        schedule="daily",
        at="08:00",
        timezone="Asia/Shanghai",
        weekdays="",
        next_run=1790000000.0,
    )
    original = {
        "schema_version": 1,
        "tasks": [task.to_dict()],
        "proactive_plans": {"qq:private:123": {"window_key": "2026-10-20", "slots": []}},
        "proactive_continuity": {"qq:private:123": {"last_message": "我在吃饭"}},
        "future_module_state": {"kept": True},
    }
    plugin._state_path.write_text(json.dumps(original), encoding="utf-8")

    plugin._load_state()
    assert plugin.scheduled.tasks["old-task"].instruction == "每天说天气"
    assert plugin.proactive.continuity["qq:private:123"]["last_message"] == "我在吃饭"
    plugin._save_state()
    assert json.loads(plugin._state_path.read_text(encoding="utf-8")) == original


@pytest.mark.asyncio
async def test_new_module_can_join_dispatch_and_own_a_state_key(tmp_path):
    class ExampleModule:
        name = "example"
        state_keys = frozenset({"example_state"})

        def __init__(self):
            self.value = 0

        def load_state(self, data):
            self.value = data.get("example_state", 0)

        def dump_state(self, payload):
            payload["example_state"] = self.value

        def on_config_update(self):
            pass

        async def tick(self, now):
            self.value += 1

    plugin, _ = make_plugin(tmp_path)
    example = ExampleModule()
    plugin._register_module(example)
    with pytest.raises(ValueError, match="状态字段重复"):
        plugin._register_module(type("Conflicting", (), {"name": "conflict", "state_keys": frozenset({"tasks"})})())

    await plugin._tick(datetime(2026, 10, 20, 8, 0, tzinfo=UTC))
    assert example.value == 1
    plugin._save_state()
    assert json.loads(plugin._state_path.read_text(encoding="utf-8"))["example_state"] == 1


@pytest.mark.asyncio
async def test_scheduled_tasks_module_can_be_disabled_independently(tmp_path):
    plugin, calls = make_plugin(
        tmp_path,
        {
            "scheduled_tasks": {"enabled": False},
            "proactive": {"target_chats": ["qq:private:123"]},
        },
    )
    now = datetime(2026, 10, 20, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    plugin.scheduled.tasks["due"] = core.ScheduledTask(
        id="due",
        stream_id="stream-1",
        owner_user_id="user-1",
        instruction="说天气",
        schedule="once",
        at="2026-10-20T09:59:00+08:00",
        timezone="Asia/Shanghai",
        weekdays="",
        next_run=now.timestamp() - 60,
    )
    await plugin._tick(now)
    assert plugin.scheduled.tasks["due"].status == "active"
    assert plugin.proactive.plans["qq:private:123"]["slots"]
    assert calls.calls == []
    result = await plugin.secretary_create_task(
        stream_id="stream-1",
        chat_id="stream-1",
        user_id="user-1",
        instruction="明天提醒我",
        schedule="daily",
        at="08:00",
    )
    assert result["success"] is False
