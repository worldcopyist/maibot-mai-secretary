from __future__ import annotations

import asyncio
import json
import types
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from test_secretary import make_plugin, module

ZONE = ZoneInfo("Asia/Shanghai")


def test_mood_probabilities_are_editable_and_must_total_100():
    settings = module.MoodSettings()
    assert sum(settings.weights().values()) == 100
    assert sum(settings.bullying_weights().values()) == 100
    fields = module.MaiSecretaryPlugin.build_config_schema()["sections"]["mood"]["fields"]
    assert {"enabled", *settings.weights()} <= set(fields)
    assert {"bullying_mood_enabled", *(f"bullying_{key}" for key in settings.weights())} <= set(fields)
    with pytest.raises(ValueError, match="总和必须为 100"):
        module.MoodSettings.model_validate({"happy": 99})
    with pytest.raises(ValueError, match="反霸凌心情概率总和必须为 100"):
        module.MoodSettings.model_validate({"bullying_wronged": 39})


def test_confirmed_bullying_uses_independent_distribution_and_persists(tmp_path):
    settings = {
        "mood": {
            "enabled": True, "bullying_wronged": 0, "bullying_sad": 0,
            "bullying_irritable": 0, "bullying_angry": 100,
        },
    }
    plugin, _ = make_plugin(tmp_path, settings)
    at = datetime(2026, 10, 25, 13, 0, tzinfo=ZONE)
    assert plugin.mood.react_to_bullying("stream-a", "message-a", now=at) == "angry"
    state = dict(plugin.mood.state)
    assert state["bullying_event_id"] == "stream-a:message-a"
    assert plugin.mood.react_to_bullying("stream-a", "message-a", now=at) == "angry"
    assert plugin.mood.state == state
    restored, _ = make_plugin(tmp_path, settings)
    restored._load_state()
    assert restored.mood.current(at)["mood"] == "angry"
    assert "当前心情为愤怒" in restored.mood.prompt_for("陌生人", now=at)


def test_shared_mood_follows_life_activity_and_survives_restart(tmp_path):
    config = {"virtual_life": {"enabled": True}, "mood": {"enabled": True}}
    plugin, _ = make_plugin(tmp_path, config)
    at = datetime(2026, 10, 22, 15, 0, tzinfo=ZONE)
    state = plugin.mood.current(at)
    assert state["activity"] == plugin.virtual_life.scene_at(at)["activity"]
    assert "疯狂星期四" in state["activity"]
    assert plugin.mood.effective_weights(state["activity"], "afternoon")["satisfied"] > plugin.config.mood.satisfied
    assert plugin.mood.current(at) == state

    restored, _ = make_plugin(tmp_path, config)
    restored._load_state()
    assert restored.mood.current(at) == state
    later = restored.mood.current(datetime(2026, 10, 22, 18, 0, tzinfo=ZONE))
    assert later["key"] != state["key"]


def test_zero_probability_stays_zero_after_activity_bias(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"mood": {
        "enabled": True, "calm": 50, "happy": 0,
    }})
    assert plugin.mood.effective_weights("去 KFC 吃炸鸡", "afternoon")["happy"] == 0


@pytest.mark.asyncio
async def test_one_mood_has_distinct_owner_familiar_and_stranger_expression(tmp_path):
    plugin, _ = make_plugin(tmp_path, {
        "plugin": {"admin_accounts": ["qq:111"]},
        "role_recognition": {"familiar_accounts": ["qq:222"]},
        "virtual_life": {"enabled": True},
        "mood": {"enabled": True},
    })
    notes = {}
    for account in ("111", "222", "333"):
        message_id = f"msg-{account}"
        stream_id = f"stream-{account}"
        plugin.role_recognition.remember({
            "message_id": message_id, "session_id": stream_id, "platform": "qq",
            "account_id": "bot", "message_info": {"user_info": {"user_id": account}},
        })
        request = {"session_id": stream_id, "reply_message_id": message_id, "items": [
            {"item_type": "SystemMessageItem", "parts": [{"type": "text", "text": "MaiBot 人设"}]},
        ]}
        result = await plugin.role_recognition.inject(request)
        notes[account] = "\n".join(
            part["text"] for item in result["modified_kwargs"]["items"]
            for part in item.get("parts", []) if part.get("type") == "text"
        )
    assert "当前关系级别为主人" in notes["111"]
    assert "自然撒娇" in notes["111"] or "坦诚说出感受" in notes["111"]
    assert "当前关系级别为熟人" in notes["222"]
    assert "当前关系级别为陌生人" in notes["333"]
    assert "当前关系级别为主人" not in notes["333"]
    assert plugin.mood.state["mood"] in module.MoodSettings().weights()
    mood_name = notes["111"].split("当前心情为", 1)[1].split("（", 1)[0]
    assert all(f"当前心情为{mood_name}" in note for note in notes.values())


@pytest.mark.asyncio
async def test_mood_injects_without_role_recognition_using_stranger_style(tmp_path):
    plugin, _ = make_plugin(tmp_path, {
        "role_recognition": {"enabled": False},
        "mood": {"enabled": True},
    })
    result = await plugin.role_recognition.inject({
        "session_id": "unverified-stream", "items": [
            {"item_type": "SystemMessageItem", "parts": [{"type": "text", "text": "MaiBot 人设"}]},
        ],
    })
    rendered = str(result["modified_kwargs"]["items"])
    assert "当前关系级别为陌生人" in rendered
    assert "MaiBot 人设" in rendered


def _inbound(*, message_id: str, stream: str = "private-stream", group: str = "", addressed: bool = False):
    return {
        "message_id": message_id, "session_id": stream, "account_id": "bot",
        "platform": "qq", "processed_plain_text": "谢谢你陪我聊天，你真可爱！",
        "is_mentioned": addressed,
        "message_info": {"user_info": {"user_id": "user"}, "group_info": {"group_id": group}},
    }


@pytest.mark.asyncio
async def test_chat_updates_shared_mood_without_blocking_current_reply(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"mood": {"enabled": True}})
    release = asyncio.Event()
    started = asyncio.Event()
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        started.set()
        await release.wait()
        return {"success": True, "response": '{"mood":"happy","confidence":0.95}'}

    async def recent(_stream_id, *, limit):
        assert limit == 4
        return []

    plugin._ctx.llm = types.SimpleNamespace(generate=generate)
    plugin._ctx.message = types.SimpleNamespace(get_recent=recent)
    await plugin.mood.start()
    try:
        await plugin.capture_mood_inbound(_inbound(message_id="msg-1"))
        await asyncio.wait_for(started.wait(), timeout=1)
        assert not release.is_set()
        release.set()
        await asyncio.wait_for(plugin.mood.queue.join(), timeout=1)
        assert plugin.mood.state["mood"] == "happy"
        assert "当前心情为开心" in plugin.mood.prompt_for("陌生人")
        assert "当前心情为开心" in plugin.mood.prompt_for("主人")
        saved = json.loads(plugin._state_path.read_text(encoding="utf-8"))
        assert "谢谢你" not in json.dumps(saved, ensure_ascii=False)
        assert len(calls) == 1
    finally:
        await plugin.mood.stop()


@pytest.mark.asyncio
async def test_chat_mood_filters_unaddressed_groups_and_duplicate_messages(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"mood": {"enabled": True}})
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return {"response": '{"mood":"wronged","confidence":0.9}'}

    async def recent(_stream_id, *, limit):
        return []

    plugin._ctx.llm = types.SimpleNamespace(generate=generate)
    plugin._ctx.message = types.SimpleNamespace(get_recent=recent)
    await plugin.mood.start()
    try:
        plugin.mood.on_inbound(_inbound(message_id="off-topic", stream="group-stream", group="123"))
        assert plugin.mood.queue.empty()
        addressed = _inbound(message_id="direct", stream="group-stream", group="123", addressed=True)
        plugin.mood.on_inbound(addressed)
        plugin.mood.on_inbound(addressed)
        await asyncio.wait_for(plugin.mood.queue.join(), timeout=1)
        assert len(calls) == 1
        assert plugin.mood.state["mood"] == "wronged"
    finally:
        await plugin.mood.stop()


def test_chat_verdict_requires_allowed_mood_and_confidence():
    parse = module.MoodModule._parse_verdict
    assert parse({"response": '{"mood":"none","confidence":1}'}) is None
    assert parse({"response": '{"mood":"angry","confidence":0.8}'}) == ("angry", 0.8)
    assert parse({"response": '{"mood":"angry","confidence":1.5}'}) is None
    assert parse({"response": '{"mood":["angry"],"confidence":0.9}'}) is None
    assert parse({"response": "not json"}) is None


@pytest.mark.asyncio
async def test_group_reply_to_someone_else_does_not_change_mood(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"mood": {"enabled": True}})
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return {"response": '{"mood":"happy","confidence":0.99}'}

    async def recent(_stream_id, *, limit):
        return [{
            "message_id": "other-message", "message_info": {"user_info": {"user_id": "other"}},
            "processed_plain_text": "你好",
        }]

    plugin._ctx.llm = types.SimpleNamespace(generate=generate)
    plugin._ctx.message = types.SimpleNamespace(get_recent=recent)
    message = _inbound(message_id="reply", stream="group-stream", group="123")
    message["reply_to"] = "other-message"
    await plugin.mood.start()
    try:
        plugin.mood.on_inbound(message)
        await asyncio.wait_for(plugin.mood.queue.join(), timeout=1)
        assert calls == []
    finally:
        await plugin.mood.stop()


@pytest.mark.asyncio
async def test_confirmed_bullying_wins_over_pending_chat_analysis(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"mood": {
        "enabled": True, "bullying_wronged": 0, "bullying_sad": 0,
        "bullying_irritable": 0, "bullying_angry": 100,
    }})
    started = asyncio.Event()
    release = asyncio.Event()

    async def generate(**kwargs):
        started.set()
        await release.wait()
        return {"response": '{"mood":"happy","confidence":0.99}'}

    async def recent(_stream_id, *, limit):
        return []

    plugin._ctx.llm = types.SimpleNamespace(generate=generate)
    plugin._ctx.message = types.SimpleNamespace(get_recent=recent)
    await plugin.mood.start()
    try:
        plugin.mood.on_inbound(_inbound(message_id="abuse-1"))
        await asyncio.wait_for(started.wait(), timeout=1)
        assert plugin.mood.react_to_bullying("private-stream", "abuse-1", now=datetime.now(UTC)) == "angry"
        release.set()
        await asyncio.wait_for(plugin.mood.queue.join(), timeout=1)
        assert plugin.mood.state["mood"] == "angry"
    finally:
        await plugin.mood.stop()
