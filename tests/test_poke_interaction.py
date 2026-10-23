from __future__ import annotations

import asyncio
import types

import pytest
from test_secretary import make_plugin


def _notice(*, poker: str = "123456789", target: str = "2966970067", group: str = "765926623") -> dict:
    payload = {
        "self_id": "2966970067", "user_id": poker, "target_id": target,
        "group_id": group,
    }
    return {
        "message_id": "poke-1", "session_id": "group-stream" if group else "private-stream",
        "platform": "qq", "account_id": "2966970067", "is_notify": True,
        "message_info": {
            "user_info": {"user_id": poker, "user_nickname": "小鱼"},
            "additional_config": {
                "napcat_notice_type": "notify", "napcat_notice_sub_type": "poke",
                "napcat_notice_payload": payload,
            },
        },
    }


@pytest.mark.asyncio
async def test_poked_bot_uses_maibot_persona_and_emoji_tool_without_duplicate(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"poke": {
        "reaction_probability": 1, "back_poke_probability": 0, "bystander_probability": 0,
        "received_action_description": "摸摸头",
    }})
    events = []

    async def append(**kwargs):
        events.append(kwargs["visible_text"])
        return {"success": True}

    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    result = await plugin.handle_poke_notice(_notice())
    assert result == {"action": "abort"}
    await asyncio.gather(*plugin.poke.jobs)
    assert len(proactive.calls) == 1
    call = proactive.calls[0]
    assert call["stream_id"] == "group-stream"
    assert call["reason"] == "收到互动"
    assert "当前配置的人物身份" in call["intent"]
    assert "`send_emoji`" in call["intent"]
    assert '对你做了 "摸摸头" 这个动作' in call["intent"]
    assert "不要调用 `secretary_poke`" in call["intent"]
    assert plugin.role_recognition._proactive_sessions["group-stream"] == "qq:123456789"
    assert len(events) == 1 and '昵称 "小鱼" 的 QQ 123456789 刚刚对我做了 "摸摸头" 这个动作' in events[0]
    assert await plugin.handle_poke_notice(_notice()) == {"action": "abort"}
    assert await plugin.handle_poke_notice(_notice(target="987654321")) == {"action": "abort"}
    assert await plugin.handle_poke_notice(_notice(poker="2966970067")) == {"action": "abort"}
    await asyncio.gather(*plugin.poke.jobs)
    assert len(proactive.calls) == 1
    assert len(events) == 2


@pytest.mark.asyncio
async def test_poke_tool_resolves_current_group_member_and_enforces_cooldown(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    plugin.ctx.chat.streams = [{
        "stream_id": "group-stream", "platform": "qq", "chat_type": "group",
        "group_id": "765926623", "account_id": "2966970067",
    }]
    calls: list[tuple[str, dict]] = []
    events = []

    async def append(**kwargs):
        events.append(kwargs["visible_text"])
        return {"success": True}

    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)

    async def call(name: str, **kwargs):
        calls.append((name, kwargs))
        if name.endswith("get_group_member_list"):
            return {"success": True, "result": [
                {"user_id": 123456789, "card": "小鱼", "nickname": "鱼鱼"},
                {"user_id": 987654321, "card": "蓝莓", "nickname": "蓝莓"},
            ]}
        if name.endswith("get_group_member_info"):
            return {"success": True, "result": {"user_id": kwargs["user_id"]}}
        return {"success": True, "result": {"status": "ok", "retcode": 0}}

    plugin.ctx.api = types.SimpleNamespace(call=call)
    sent = await plugin.secretary_poke("小鱼", stream_id="group-stream", chat_id="group-stream")
    assert sent["success"] is True
    assert calls[-1] == ("adapter.napcat.message.send_poke", {
        "user_id": 123456789, "group_id": 765926623, "target_id": 123456789,
    })
    assert len(events) == 1 and '我刚刚戳了戳 "小鱼（QQ 123456789）"' in events[0]
    repeat = await plugin.secretary_poke("123456789", stream_id="group-stream", chat_id="group-stream")
    assert repeat["success"] is False and "刚戳过" in repeat["error"]
    wrong_stream = await plugin.secretary_poke("蓝莓", stream_id="other", chat_id="group-stream")
    assert wrong_stream["success"] is False
    assert sum(name.endswith("send_poke") for name, _ in calls) == 1


@pytest.mark.asyncio
async def test_poke_tool_rejects_unknown_or_ambiguous_group_target(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    plugin.ctx.chat.streams = [{
        "stream_id": "group-stream", "platform": "qq", "chat_type": "group",
        "group_id": "765926623", "account_id": "2966970067",
    }]
    calls: list[str] = []

    async def call(name: str, **kwargs):
        calls.append(name)
        if name.endswith("get_group_member_list"):
            return {"success": True, "result": [
                {"user_id": 123456789, "card": "同名"},
                {"user_id": 987654321, "card": "同名"},
            ]}
        if name.endswith("get_group_member_info"):
            return {"success": True, "result": None}
        raise AssertionError("未核实目标不能调用发送接口")

    plugin.ctx.api = types.SimpleNamespace(call=call)
    ambiguous = await plugin.secretary_poke("同名", stream_id="group-stream", chat_id="group-stream")
    unknown = await plugin.secretary_poke("111111111", stream_id="group-stream", chat_id="group-stream")
    assert ambiguous["success"] is False and "唯一匹配" in ambiguous["error"]
    assert unknown["success"] is False and "不在当前群" in unknown["error"]
    assert not any(name.endswith("send_poke") for name in calls)


@pytest.mark.asyncio
async def test_private_poke_only_current_peer_and_failed_send_not_counted(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    plugin.ctx.chat.streams = [{
        "stream_id": "private-stream", "platform": "qq", "chat_type": "private",
        "user_id": "123456789", "user_nickname": "世界猫", "account_id": "2966970067",
    }]
    calls = []

    async def call(name: str, **kwargs):
        calls.append((name, kwargs))
        return {"success": True, "result": {"status": "failed", "retcode": 100}}

    plugin.ctx.api = types.SimpleNamespace(call=call)
    denied = await plugin.secretary_poke("987654321", stream_id="private-stream", chat_id="private-stream")
    failed = await plugin.secretary_poke(stream_id="private-stream", chat_id="private-stream")
    assert denied["success"] is False
    assert failed["success"] is False
    assert calls == [("adapter.napcat.message.send_poke", {"user_id": 123456789})]
    assert plugin.poke.last_sent == {}


@pytest.mark.asyncio
async def test_many_people_poking_one_group_stays_within_reaction_limit(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"poke": {
        "max_reactions_per_minute": 1, "reaction_probability": 1,
        "back_poke_probability": 0,
    }})

    events = []

    async def append(**kwargs):
        events.append(kwargs["visible_text"])
        return {"success": True}

    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    assert await plugin.handle_poke_notice(_notice(poker="123456789")) == {"action": "abort"}
    assert await plugin.handle_poke_notice(_notice(poker="987654321")) == {"action": "abort"}
    await asyncio.gather(*plugin.poke.jobs)
    assert len(proactive.calls) == 1
    assert len(events) == 2


@pytest.mark.asyncio
async def test_back_poke_records_both_events_and_optional_persona_reply(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"poke": {
        "reaction_probability": 1, "back_poke_probability": 1,
        "reply_after_back_poke_probability": 1,
    }})
    events = []
    sent = []

    async def append(**kwargs):
        events.append(kwargs["visible_text"])
        return {"success": True}

    async def call(name: str, **kwargs):
        sent.append((name, kwargs))
        return {"success": True, "result": {"status": "ok", "retcode": 0}}

    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    plugin.ctx.api = types.SimpleNamespace(call=call)
    assert await plugin.handle_poke_notice(_notice()) == {"action": "abort"}
    await asyncio.gather(*plugin.poke.jobs)
    assert len(sent) == 1 and sent[0][1]["user_id"] == 123456789
    assert len(events) == 2
    assert '刚刚对我做了 "戳一戳" 这个动作' in events[0] and "我刚刚戳了戳" in events[1]
    assert len(proactive.calls) == 1
    assert "你已经回戳了对方" in proactive.calls[0]["intent"]


@pytest.mark.asyncio
async def test_bystander_poke_uses_probability_and_records_own_action(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"poke": {"bystander_probability": 1}})
    events = []
    sent = []

    async def append(**kwargs):
        events.append(kwargs["visible_text"])
        return {"success": True}

    async def call(name: str, **kwargs):
        sent.append(kwargs)
        return {"success": True, "result": {"status": "ok", "retcode": 0}}

    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    plugin.ctx.api = types.SimpleNamespace(call=call)
    assert await plugin.handle_poke_notice(_notice(target="987654321")) == {"action": "abort"}
    await asyncio.gather(*plugin.poke.jobs)
    assert sent[0]["target_id"] == 987654321
    assert len(events) == 1 and "QQ 987654321" in events[0]
    assert not proactive.calls


@pytest.mark.asyncio
async def test_silent_reaction_still_tells_maibot_who_poked_it(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"poke": {
        "reaction_probability": 0, "received_action_description": "摸摸头",
    }})
    events = []

    async def append(**kwargs):
        events.append(kwargs["visible_text"])
        return {"success": True}

    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    assert await plugin.handle_poke_notice(_notice()) == {"action": "abort"}
    await asyncio.gather(*plugin.poke.jobs)
    assert len(events) == 1 and '昵称 "小鱼" 的 QQ 123456789 刚刚对我做了 "摸摸头"' in events[0]
    assert not proactive.calls


def test_received_action_description_is_required_and_normalized():
    from mai_secretary.plugin import PokeSettings

    assert PokeSettings.model_validate({"received_action_description": "  摸摸头  "}).received_action_description == "摸摸头"
    with pytest.raises(ValueError):
        PokeSettings.model_validate({"received_action_description": "  "})


@pytest.mark.asyncio
async def test_back_poke_can_end_without_extra_reply(tmp_path):
    plugin, proactive = make_plugin(tmp_path, {"poke": {
        "reaction_probability": 1, "back_poke_probability": 1,
        "reply_after_back_poke_probability": 0,
    }})

    async def append(**kwargs):
        return {"success": True}

    async def call(name: str, **kwargs):
        return {"success": True, "result": {"status": "ok", "retcode": 0}}

    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    plugin.ctx.api = types.SimpleNamespace(call=call)
    assert await plugin.handle_poke_notice(_notice()) == {"action": "abort"}
    await asyncio.gather(*plugin.poke.jobs)
    assert not proactive.calls


@pytest.mark.asyncio
async def test_poke_me_in_group_requires_verified_current_speaker(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    plugin.ctx.chat.streams = [{
        "stream_id": "group-stream", "platform": "qq", "chat_type": "group",
        "group_id": "765926623", "account_id": "2966970067",
    }]
    sent = []

    async def call(name: str, **kwargs):
        sent.append(kwargs)
        return {"success": True, "result": {"status": "ok", "retcode": 0}}

    async def append(**kwargs):
        return {"success": True}

    async def get_config(key):
        return []

    plugin.ctx.api = types.SimpleNamespace(call=call)
    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    plugin.ctx.config = types.SimpleNamespace(get=get_config)
    denied = await plugin.secretary_poke("我", stream_id="group-stream", chat_id="group-stream")
    assert denied["success"] is False
    plugin.role_recognition.remember({
        "message_id": "speaker-1", "session_id": "group-stream", "platform": "qq",
        "account_id": "2966970067", "message_info": {"user_info": {"user_id": "123456789"}},
    })
    await plugin.inject_role_for_planner(
        session_id="group-stream",
        items=[{"item_type": "UserMessageItem", "parts": [{
            "type": "text", "text": '<message msg_id="speaker-1">\n戳我一下',
        }]}],
    )
    success = await plugin.secretary_poke("我", stream_id="group-stream", chat_id="group-stream")
    assert success["success"] is True
    assert len(sent) == 1 and sent[0]["user_id"] == 123456789
