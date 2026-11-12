from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from test_secretary import make_plugin


def message(stamp, *, sender="123", text="你好", message_id="m1"):
    return {"session_id": "real-stream-1", "message_id": message_id, "timestamp": str(stamp),
            "account_id": "bot-1", "message_info": {"user_info": {"user_id": sender}},
            "raw_message": [{"type": "text", "data": text}]}


def settings():
    return {"proactive": {"target_chats": ["qq:private:123"], "window_start": "08:00",
                           "window_end": "23:59", "scheduling_mode": "interval",
                           "average_interval_hours": 2, "offset_minutes": 0}}


@pytest.mark.asyncio
async def test_recent_user_and_bot_messages_restart_interval(tmp_path):
    plugin, calls = make_plugin(tmp_path, settings())
    start = datetime(2026, 11, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    target = "qq:private:123"
    await plugin._tick(start)
    assert plugin.proactive.plans[target]["slots"][0] == start.timestamp() + 7200
    incoming = start.timestamp() + 3600
    await plugin.cancel_pending_on_inbound(message(incoming))
    await plugin._tick(datetime.fromtimestamp(incoming + 1, UTC))
    assert plugin.proactive.plans[target]["slots"][0] == incoming + 7200
    outgoing = incoming + 60
    await plugin.capture_proactive_reply(message(outgoing, sender="bot-1", message_id="bot"), sent=True)
    await plugin._tick(datetime.fromtimestamp(outgoing + 1, UTC))
    assert plugin.proactive.plans[target]["slots"][0] == outgoing + 7200
    assert calls.calls == []


@pytest.mark.asyncio
async def test_recent_history_is_included_and_old_activity_is_respected(tmp_path):
    config = settings()
    config["proactive"]["average_interval_hours"] = 0.5
    plugin, calls = make_plugin(tmp_path, config)
    now = datetime(2026, 11, 12, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    rows = [message(now.timestamp() - 1800, text="我已经吃过饭了")]
    async def recent(chat_id, limit):
        assert chat_id == "real-stream-1" and limit == 200
        return rows
    plugin._ctx.message.get_recent = recent
    await plugin._tick(now)
    assert len(calls.calls) == 1
    assert "我已经吃过饭了" in calls.calls[0]["intent"]
    assert "不要再问是否吃饭" in calls.calls[0]["intent"]


@pytest.mark.asyncio
async def test_unanswered_silences_after_three_sent_and_user_message_resets(tmp_path):
    plugin, calls = make_plugin(tmp_path, settings())
    plugin.proactive.rng.random = lambda: 0.0
    target = "qq:private:123"
    start = datetime(2026, 11, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    await plugin._tick(start)
    for index in range(3):
        due = plugin.proactive.plans[target]["slots"][0]
        await plugin._tick(datetime.fromtimestamp(due + 1, UTC))
        await plugin.capture_proactive_reply(message(due + 2, sender="bot-1", message_id=f"bot{index}"), sent=True)
        assert plugin.proactive.continuity[target]["unanswered_count"] == index + 1
        await plugin._tick(datetime.fromtimestamp(due + 3, UTC))
    assert len(calls.calls) == 3
    due = plugin.proactive.plans[target]["slots"][0]
    await plugin._tick(datetime.fromtimestamp(due + 1, UTC))
    assert len(calls.calls) == 3
    await plugin.cancel_pending_on_inbound(message(due + 10, message_id="reply"))
    assert plugin.proactive.continuity[target]["unanswered_count"] == 0
    await plugin._tick(datetime.fromtimestamp(due + 11, UTC))
    assert plugin.proactive.plans[target]["slots"][0] == due + 10 + 7200


@pytest.mark.asyncio
async def test_history_after_restart_replans_and_reactivates_without_cross_chat_leak(tmp_path):
    config = settings()
    plugin, _ = make_plugin(tmp_path, config)
    now = datetime(2026, 11, 12, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    target = "qq:private:123"
    await plugin._tick(now)
    old_due = plugin.proactive.plans[target]["slots"][0]
    plugin.proactive.continuity[target] = {"last_chat_at": now.timestamp(), "last_sent_at": now.timestamp(), "unanswered_count": 3}
    plugin._save_state()
    restored, calls = make_plugin(tmp_path, config)
    restored._load_state()
    recent_time = old_due - 300
    async def recent(_chat_id, limit):
        return [message(recent_time, text="我已经吃过饭"), {**message(recent_time + 20, text="其他聊天的内容"), "session_id": "other"}]
    restored._ctx.message.get_recent = recent
    await restored._tick(datetime.fromtimestamp(old_due + 1, UTC))
    assert calls.calls == []
    assert restored.proactive.continuity[target]["unanswered_count"] == 0
    assert restored.proactive.plans[target]["slots"][0] == recent_time + 7200
    rows = await restored.proactive._recent_messages("real-stream-1")
    assert len(rows) == 1 and "其他聊天的内容" not in restored.proactive._context_note(rows, datetime.fromtimestamp(old_due + 1, UTC))


@pytest.mark.asyncio
async def test_history_lookup_failure_does_not_send_without_context(tmp_path):
    plugin, calls = make_plugin(tmp_path, settings())
    async def fail(*_args, **_kwargs):
        raise RuntimeError("unavailable")
    plugin._ctx.message.get_recent = fail
    await plugin._tick(datetime(2026, 11, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
    assert calls.calls == []


@pytest.mark.asyncio
async def test_user_reply_cancels_only_matching_queued_proactive_send(tmp_path):
    plugin, _ = make_plugin(tmp_path, settings())
    target = "qq:private:123"
    now = datetime(2026, 11, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
    await plugin._tick(datetime.fromtimestamp(now, UTC))
    plugin.proactive.continuity[target]["pending"] = {"stream_id": "real-stream-1", "since": now,
        "until": now + 180, "host_task_id": "proactive:secretary:1"}
    await plugin.cancel_pending_on_inbound(message(now + 2))
    reply = {**message(now + 3, sender="bot-1"), "reply_to": "proactive:secretary:1"}
    assert plugin.proactive.suppress_cancelled_send(reply) == {"action": "abort"}
    assert plugin.proactive.suppress_cancelled_send({**reply, "reply_to": "other-task"}) is None
    assert plugin.proactive.suppress_cancelled_send({**reply, "session_id": "other"}) is None


@pytest.mark.asyncio
async def test_probability_skip_does_not_increment_unanswered_count(tmp_path):
    plugin, calls = make_plugin(tmp_path, settings())
    now = datetime(2026, 11, 12, 8, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    target = "qq:private:123"
    plugin.proactive.rng.random = lambda: 0.99
    await plugin._tick(now)
    plugin.proactive.continuity[target]["unanswered_count"] = 1
    due = plugin.proactive.plans[target]["slots"][0]
    await plugin._tick(datetime.fromtimestamp(due + 1, UTC))
    assert calls.calls == []
    assert plugin.proactive.continuity[target]["unanswered_count"] == 1


@pytest.mark.asyncio
async def test_elapsed_interval_before_window_can_send_at_window_start(tmp_path):
    config = settings()
    config["proactive"].update(window_start="10:00", window_end="02:00")
    plugin, calls = make_plugin(tmp_path, config)
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime(2026, 11, 12, 9, 0, tzinfo=zone)
    last = datetime(2026, 11, 12, 7, 0, tzinfo=zone).timestamp()
    async def recent(_chat_id, limit):
        return [message(last)]
    plugin._ctx.message.get_recent = recent
    await plugin._tick(now)
    due = plugin.proactive.plans["qq:private:123"]["slots"][0]
    assert due == datetime(2026, 11, 12, 10, 0, tzinfo=zone).timestamp()
    await plugin._tick(datetime.fromtimestamp(due + 1, UTC))
    assert len(calls.calls) == 1


@pytest.mark.asyncio
async def test_count_mode_does_not_reset_window_quota_after_sending(tmp_path):
    config = settings()
    config["proactive"].update(scheduling_mode="count", messages_per_window=1)
    plugin, calls = make_plugin(tmp_path, config)
    plugin.proactive.rng.seed(7)
    target = "qq:private:123"
    await plugin._tick(datetime(2026, 11, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai")))
    due = plugin.proactive.plans[target]["slots"][0]
    await plugin._tick(datetime.fromtimestamp(due + 1, UTC))
    await plugin.capture_proactive_reply(message(due + 2, sender="bot-1", message_id="sent"), sent=True)
    await plugin._tick(datetime.fromtimestamp(due + 3, UTC))
    assert len(calls.calls) == 1
    assert plugin.proactive.plans[target]["slots"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["interval", "count"])
async def test_affection_once_after_silence_and_reset_on_reply(tmp_path, mode):
    config = settings()
    config["mood"] = {"enabled": True}
    config["proactive"].update(scheduling_mode=mode, messages_per_window=1)
    plugin, calls = make_plugin(tmp_path, config)
    start = datetime(2026, 11, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    target = "qq:private:123"
    plugin.proactive.continuity[target] = {"last_chat_at": start.timestamp(), "last_sent_at": start.timestamp(),
                                          "unanswered_count": 3, "count_window_key": "2026-11-12", "count_sent": 1}
    await plugin._tick(start)
    due = plugin.proactive.plans[target]["slots"][0]
    await plugin._tick(datetime.fromtimestamp(due + 1, UTC))
    assert len(calls.calls) == 1 and "自然撒娇" in calls.calls[0]["intent"]
    assert plugin.proactive.continuity[target]["affection_attempted"] is True
    await plugin.capture_proactive_reply(message(due + 2, sender="bot-1", message_id="affection"), sent=True)
    await plugin._tick(datetime.fromtimestamp(due + 3, UTC))
    restored, restored_calls = make_plugin(tmp_path, config)
    restored._load_state()
    await restored._tick(datetime.fromtimestamp(due + 7205, UTC))
    assert restored_calls.calls == []
    await restored.cancel_pending_on_inbound(message(due + 7210, message_id="reply"))
    assert restored.proactive.continuity[target]["unanswered_count"] == 0
    assert "affection_attempted" not in restored.proactive.continuity[target]


@pytest.mark.asyncio
async def test_affection_disabled_with_mood_or_feature(tmp_path):
    for mood in ({"enabled": False}, {"enabled": True, "affection_after_silence_enabled": False}):
        config = settings()
        config["mood"] = mood
        plugin, calls = make_plugin(tmp_path, config)
        now = datetime(2026, 11, 12, 9, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        target = "qq:private:123"
        plugin.proactive.continuity[target] = {"last_chat_at": now.timestamp(), "last_sent_at": now.timestamp(), "unanswered_count": 3}
        await plugin._tick(now)
        due = plugin.proactive.plans[target]["slots"][0]
        await plugin._tick(datetime.fromtimestamp(due + 1, UTC))
        assert calls.calls == []
