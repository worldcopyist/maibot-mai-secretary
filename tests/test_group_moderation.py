from __future__ import annotations

import json
import types

import pytest
from test_secretary import make_plugin


async def setup_moderation(tmp_path, *, sensitivity=50, bot_role="admin", verdict=None):
    plugin, _ = make_plugin(tmp_path, {
        "plugin": {"admin_accounts": ["qq:2767263382"]},
        "group_admin": {
            "enabled": True, "managed_group_ids": ["745564579"],
            "moderation_enabled": True, "moderation_sensitivity": sensitivity,
        },
    })
    calls = []
    contexts = []

    async def call(name, **kwargs):
        calls.append((name, kwargs))
        if name.endswith("get_group_member_info"):
            user = str(kwargs["user_id"])
            return {"success": True, "result": {"user_id": int(user), "role": bot_role if user == "2966970067" else "member"}}
        return {"success": True, "result": {"status": "ok", "retcode": 0, "data": {}}}

    async def generate(**kwargs):
        return {"success": True, "response": json.dumps(verdict or {"violation": False, "benign": True, "risk": 0.0, "reason": "正常用法"}, ensure_ascii=False)}

    async def recent(*args, **kwargs):
        return []

    async def append(**kwargs):
        contexts.append(kwargs)

    plugin.ctx.api = types.SimpleNamespace(call=call)
    plugin.ctx.llm = types.SimpleNamespace(generate=generate)
    plugin.ctx.message = types.SimpleNamespace(get_recent=recent)
    plugin.ctx.maisaka.context = types.SimpleNamespace(append=append)
    await plugin.knowledge_base.start()
    await plugin.knowledge_base.add_moderation_text("745564579", "词库", "你妈")
    return plugin, calls, contexts


def inbound(text: str, message_id: int = 12345, user_id: int = 345678901):
    return {
        "platform": "qq", "account_id": "2966970067", "session_id": "group-stream",
        "message_id": message_id, "processed_plain_text": text,
        "message_info": {"group_info": {"group_id": "745564579"}, "user_info": {"user_id": str(user_id)}},
    }


@pytest.mark.asyncio
async def test_benign_term_only_queues_and_ai_does_not_punish(tmp_path):
    plugin, calls, _ = await setup_moderation(tmp_path)
    await plugin.group_moderation.on_inbound(inbound("你妈身体怎么样了"))
    candidate = plugin.group_moderation.queue.get_nowait()
    assert candidate.matches == ("你妈",)
    await plugin.group_moderation._process(candidate)
    assert not calls
    assert "未判违规" in plugin.group_moderation.audit[-1]["result"]
    await plugin.knowledge_base.stop()


@pytest.mark.asyncio
async def test_confirmed_violation_recalls_exact_message_and_mutes(tmp_path):
    plugin, calls, contexts = await setup_moderation(tmp_path, verdict={"violation": True, "benign": False, "risk": 0.95, "reason": "针对成员辱骂"})
    await plugin.group_moderation.on_inbound(inbound("你妈滚开", 99881))
    await plugin.group_moderation.on_inbound(inbound("你妈滚开", 99881))
    assert plugin.group_moderation.queue.qsize() == 1
    await plugin.group_moderation._process(plugin.group_moderation.queue.get_nowait())
    assert any(name.endswith("delete_msg") and args["message_id"] == 99881 for name, args in calls)
    assert any(name.endswith("set_group_ban") and args["duration"] == 600 and args["user_id"] == 345678901 for name, args in calls)
    assert "你妈" in contexts[0]["visible_text"]
    await plugin.knowledge_base.stop()


@pytest.mark.asyncio
async def test_sensitivity_and_permission_gates(tmp_path):
    verdict = {"violation": True, "benign": False, "risk": 0.8, "reason": "可能违规"}
    low, calls, _ = await setup_moderation(tmp_path / "low", sensitivity=0, verdict=verdict)
    await low.group_moderation.on_inbound(inbound("你妈真行"))
    await low.group_moderation._process(low.group_moderation.queue.get_nowait())
    assert not calls
    await low.knowledge_base.stop()

    high, calls, _ = await setup_moderation(tmp_path / "high", sensitivity=100, verdict=verdict)
    await high.group_moderation.on_inbound(inbound("你妈真行"))
    await high.group_moderation._process(high.group_moderation.queue.get_nowait())
    assert any(name.endswith("delete_msg") for name, _ in calls)
    await high.knowledge_base.stop()

    no_rights, calls, _ = await setup_moderation(tmp_path / "member", bot_role="member", verdict=verdict)
    await no_rights.group_moderation.on_inbound(inbound("你妈真行"))
    await no_rights.group_moderation._process(no_rights.group_moderation.queue.get_nowait())
    assert not any(name.endswith(("delete_msg", "set_group_ban")) for name, _ in calls)
    await no_rights.knowledge_base.stop()


@pytest.mark.asyncio
async def test_invalid_ai_result_and_admin_message_never_punish(tmp_path):
    plugin, calls, _ = await setup_moderation(tmp_path)

    async def invalid(**kwargs):
        return {"success": True, "response": "无法判断"}

    plugin.ctx.llm.generate = invalid
    await plugin.group_moderation.on_inbound(inbound("你妈", 12345))
    await plugin.group_moderation._process(plugin.group_moderation.queue.get_nowait())
    assert not calls
    assert "未处罚" in plugin.group_moderation.audit[-1]["result"]
    await plugin.group_moderation.on_inbound(inbound("你妈", 12346, 2767263382))
    await plugin.group_moderation._process(plugin.group_moderation.queue.get_nowait())
    assert not calls
    assert "管理员发言" in plugin.group_moderation.audit[-1]["result"]
    await plugin.knowledge_base.stop()
