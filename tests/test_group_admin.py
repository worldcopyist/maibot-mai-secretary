from __future__ import annotations

import time
import types

import pytest
from test_secretary import make_plugin


def setup_group(tmp_path, *, role="admin", config=None):
    base = {"plugin": {"admin_accounts": ["qq:123456789"]}, "group_admin": {"enabled": True, "managed_group_ids": ["765926623"]}}
    if config:
        base["group_admin"].update(config)
    plugin, _ = make_plugin(tmp_path, base)
    plugin.ctx.chat.streams = [{"stream_id": "group-stream", "platform": "qq", "chat_type": "group", "group_id": "765926623", "account_id": "2966970067"}]
    calls = []

    async def call(name, **kwargs):
        calls.append((name, kwargs))
        if name.endswith("get_group_member_info"):
            user = str(kwargs["user_id"])
            return {"success": True, "result": {"user_id": int(user), "role": role if user == "2966970067" else "member"}}
        if name.endswith("get_group_system_msg"):
            return {"success": True, "result": {"status": "ok", "retcode": 0, "data": {"join_requests": [{"group_id": 765926623, "request_id": "r-1", "requester_uin": 345678901, "comment": "蓝莓", "checked": False}, {"group_id": 999, "request_id": "r-other", "checked": False}]}}}
        return {"success": True, "result": {"status": "ok", "retcode": 0, "data": {}}}

    plugin.ctx.api = types.SimpleNamespace(call=call)
    kwargs = {"stream_id": "group-stream", "chat_id": "group-stream"}
    return plugin, calls, kwargs


def authorize(plugin, account="qq:123456789"):
    stamp = time.time()
    plugin.role_recognition.records["group-stream:m1"] = {"session_id": "group-stream", "message_id": "m1", "account": account, "seen_at": stamp}
    plugin.role_recognition._planner_speakers["group-stream"] = {"account": account, "message_id": "m1", "verified_at": stamp}


@pytest.mark.asyncio
async def test_permission_and_mute_confirm_inner_result(tmp_path):
    plugin, calls, kwargs = setup_group(tmp_path)
    permission = await plugin.secretary_group_permission(**kwargs)
    assert permission["can_manage"] is True and permission["role"] == "admin"
    authorize(plugin)
    result = await plugin.secretary_group_member("mute", "345678901", 15, **kwargs)
    assert result["success"] is True
    assert any(name.endswith("set_group_ban") and args["duration"] == 900 for name, args in calls)
    assert plugin.role_recognition.peek_planner_speaker("group-stream") is None


@pytest.mark.asyncio
async def test_denies_nonadmin_or_unlisted_group_and_bot_without_permission(tmp_path):
    plugin, calls, kwargs = setup_group(tmp_path)
    authorize(plugin, "qq:987654321")
    denied = await plugin.secretary_group_member("mute", "345678901", 10, **kwargs)
    assert denied["success"] is False
    assert not any(name.endswith("set_group_ban") for name, _ in calls)
    authorize(plugin)
    plugin.ctx.chat.streams[0]["group_id"] = "999"
    denied = await plugin.secretary_group_member("mute", "345678901", 10, **kwargs)
    assert denied["success"] is False
    plugin.ctx.chat.streams[0]["group_id"] = "765926623"
    denied_bot, _, denied_kwargs = setup_group(tmp_path, role="member")
    authorize(denied_bot)
    permission = await denied_bot.secretary_group_permission(**denied_kwargs)
    assert permission["success"] is True and permission["can_manage"] is False
    denied = await denied_bot.secretary_group_member("mute", "345678901", 10, **denied_kwargs)
    assert denied["success"] is False and "没有" in denied["error"]


@pytest.mark.asyncio
async def test_join_request_bound_to_current_group_and_napcat_failure(tmp_path):
    plugin, calls, kwargs = setup_group(tmp_path)
    authorize(plugin)
    listed = await plugin.secretary_group_join("list", **kwargs)
    assert listed["success"] is True and [row["request_id"] for row in listed["requests"]] == ["r-1"]
    assert plugin.role_recognition.peek_planner_speaker("group-stream") == "qq:123456789"
    denied = await plugin.secretary_group_join("approve", "r-other", **kwargs)
    assert denied["success"] is False
    authorize(plugin)
    original = plugin.ctx.api.call

    async def reject_inner(name, **args):
        if name.endswith("set_group_add_request"):
            return {"success": True, "result": {"status": "failed", "retcode": 100, "wording": "权限不足"}}
        return await original(name, **args)

    plugin.ctx.api.call = reject_inner
    rejected = await plugin.secretary_group_join("approve", "r-1", **kwargs)
    assert rejected["success"] is False and "权限不足" in rejected["error"]
    assert not any(name.endswith("set_group_add_request") for name, _ in calls)


@pytest.mark.asyncio
async def test_welcome_only_configured_group_and_deduplicated(tmp_path):
    plugin, calls, _ = setup_group(tmp_path, config={"welcome_enabled": True, "welcome_template": "欢迎 {name}（{qq}）"})
    message = {"platform": "qq", "account_id": "2966970067", "is_notify": True, "message_id": "join-1", "message_info": {"user_info": {"user_nickname": "小鱼"}, "additional_config": {"napcat_notice_type": "group_increase", "napcat_notice_payload": {"group_id": 765926623, "user_id": 345678901, "self_id": 2966970067}}}}
    await plugin.handle_group_join_notice(message)
    await plugin.handle_group_join_notice(message)
    assert len([name for name, _ in calls if name.endswith("send_group_msg")]) == 1
    message["message_info"]["additional_config"]["napcat_notice_payload"]["group_id"] = 999
    await plugin.handle_group_join_notice(message)
    assert len([name for name, _ in calls if name.endswith("send_group_msg")]) == 1


@pytest.mark.asyncio
async def test_admin_can_set_welcome_for_this_group(tmp_path):
    plugin, _, kwargs = setup_group(tmp_path)
    authorize(plugin)
    changed = await plugin.secretary_group_welcome("set", "欢迎 {name}！", **kwargs)
    assert changed["success"] is True and changed["text"] == "欢迎 {name}！"
    authorize(plugin)
    enabled = await plugin.secretary_group_welcome("enable", **kwargs)
    assert enabled["enabled"] is True
    assert plugin.group_admin.welcome_overrides["765926623"]["enabled"] is True


@pytest.mark.asyncio
async def test_keyword_review_only_with_permission_and_match(tmp_path):
    plugin, calls, _ = setup_group(tmp_path, config={"review_mode": "keyword", "review_accept_words": ["蓝莓"]})
    await plugin.group_admin.tick(None)
    assert len([name for name, _ in calls if name.endswith("set_group_add_request")]) == 1
    await plugin.group_admin.tick(None)
    assert len([name for name, _ in calls if name.endswith("set_group_add_request")]) == 1
    denied, denied_calls, _ = setup_group(tmp_path, role="member", config={"review_mode": "keyword", "review_accept_words": ["蓝莓"]})
    await denied.group_admin.tick(None)
    assert not any(name.endswith("set_group_add_request") for name, _ in denied_calls)


@pytest.mark.asyncio
async def test_title_requires_bot_owner_and_notice_checks_inner_ack(tmp_path):
    plugin, calls, kwargs = setup_group(tmp_path)
    authorize(plugin)
    title = await plugin.secretary_group_member("title", "345678901", text="蓝莓", **kwargs)
    assert title["success"] is False and "没有" in title["error"]
    authorize(plugin)
    original = plugin.ctx.api.call

    async def failed_notice(name, **args):
        if name.endswith("send_group_notice"):
            return {"success": True, "result": {"status": "failed", "retcode": 1404, "wording": "无权限发布公告"}}
        return await original(name, **args)

    plugin.ctx.api.call = failed_notice
    result = await plugin.secretary_group_notice("create", text="测试公告", **kwargs)
    assert result["success"] is False and "无权限发布公告" in result["error"]
    assert not any(name.endswith("send_group_notice") for name, _ in calls)
