from __future__ import annotations

import base64
import io
import types
from datetime import UTC, date, datetime

import pytest
from PIL import Image
from test_secretary import make_plugin


def test_azure_theme_renders_all_text():
    from mai_secretary.daily_report_renderer import render_azure_report

    image = Image.open(io.BytesIO(render_azure_report(date(2026, 10, 23), "今日概览：聊了蓝莓和小鱼。\n重要约定：明天见。")))
    assert image.format == "PNG"
    assert image.width >= 900
    assert image.height >= 1600
    assert image.width * 16 == image.height * 9
    dense = Image.open(io.BytesIO(render_azure_report(date(2026, 10, 23), "蓝莓小鱼。" * 110)))
    assert dense.size == image.size


@pytest.mark.asyncio
async def test_daily_report_reads_whole_day_and_sends_only_once(tmp_path):
    target = "qq:private:2767263382"
    plugin, _ = make_plugin(tmp_path, {
        "daily_report": {
            "enabled": True, "target_chats": [target], "summary_time": "10:00",
            "text_model": "mimo-v2.6-flash",
        },
    })
    plugin.ctx.chat.streams = [{
        "stream_id": "user-stream", "platform": "qq", "chat_type": "private",
        "user_id": "2767263382", "account_id": "bot-1", "scope": "",
    }]
    times = [
        datetime(2026, 10, 22, 16, 10, tzinfo=UTC).timestamp(),
        datetime(2026, 10, 22, 20, 10, tzinfo=UTC).timestamp(),
        datetime(2026, 10, 23, 1, 10, tzinfo=UTC).timestamp(),
    ]
    messages = [
        {
            "message_id": str(index), "timestamp": stamp,
            "processed_plain_text": f"第 {index} 条话题",
            "message_info": {"user_info": {"user_nickname": "世界猫"}},
        }
        for index, stamp in enumerate(times)
    ]
    requested: list[tuple[float, float]] = []
    prompts: list[dict] = []
    sent: list[tuple[bytes, str]] = []

    async def get_by_time_in_chat(**kwargs):
        start, end = float(kwargs["start_time"]), float(kwargs["end_time"])
        requested.append((start, end))
        assert kwargs["limit"] == 0
        return [row for row in messages if start <= row["timestamp"] <= end]

    async def generate(**kwargs):
        prompts.append(kwargs)
        if "固定使用以下四个小标题" in kwargs["prompt"]:
            return {"response": "今日概览：聊了蓝莓。\n聊了什么：小鱼。\n重要约定：无。\n暖心片段：大家说晚安。"}
        return {"response": "提到了蓝莓、小鱼和晚安。"}

    async def send_image(encoded, stream_id, return_details=False):
        assert return_details is True
        sent.append((base64.b64decode(encoded), stream_id))
        return {"sent": True}

    plugin.ctx.message = types.SimpleNamespace(get_by_time_in_chat=get_by_time_in_chat)
    plugin.ctx.llm = types.SimpleNamespace(generate=generate)
    plugin.ctx.send = types.SimpleNamespace(image=send_image)
    now = datetime(2026, 10, 23, 2, 0, tzinfo=UTC)
    await plugin.daily_report.tick(now)
    await next(iter(plugin.daily_report.jobs.values()))
    assert len(requested) == 10
    assert len(sent) == 1
    assert sent[0][1] == "user-stream"
    assert Image.open(io.BytesIO(sent[0][0])).format == "PNG"
    assert all(any(f"第 {index} 条话题" in call["prompt"] for call in prompts) for index in range(3))
    assert all(call["model_name"] == "mimo-v2.6-flash" for call in prompts)
    assert all(call["max_tokens"] >= 4096 and call["rpc_timeout_ms"] == 130000 for call in prompts)
    assert all("只返回总结文字，不生成图片" in call["prompt"] for call in prompts)
    assert plugin.daily_report.records[f"2026-10-23|{target}"]["message_count"] == 3
    await plugin.daily_report.tick(now)
    assert len(sent) == 1


def test_interrupted_preparation_can_retry_but_uncertain_send_cannot(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    module = plugin.daily_report
    module.load_state({"daily_reports": {
        "2026-10-23|qq:private:1": {"status": "preparing"},
        "2026-10-23|qq:private:2": {"status": "sending"},
    }})
    assert "2026-10-23|qq:private:1" not in module.records
    assert module.records["2026-10-23|qq:private:2"]["status"] == "sending"


@pytest.mark.asyncio
async def test_natural_language_tool_queues_current_chat_only_without_schedule(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"plugin": {"admin_accounts": ["qq:123456789"]}})
    plugin.ctx.chat.streams = [{
        "stream_id": "my-chat", "platform": "qq", "chat_type": "private",
        "user_id": "123456789", "account_id": "bot-1",
    }, {
        "stream_id": "group-chat", "platform": "qq", "chat_type": "group",
        "group_id": "10001", "account_id": "bot-1",
    }]
    assert plugin.config.daily_report.enabled is False
    assert plugin.config.daily_report.manual_enabled is True
    sender = {"stream_id": "my-chat", "chat_id": "my-chat", "user_id": "123456789"}
    wrong = await plugin.secretary_generate_daily_report(
        stream_id="another-chat", chat_id="my-chat", user_id="123456789",
    )
    assert wrong["success"] is False
    stranger = await plugin.secretary_generate_daily_report(
        stream_id="group-chat", chat_id="group-chat", user_id="987654321",
    )
    assert stranger["success"] is False
    assert "只有插件管理员" in stranger["error"]
    assert not plugin.daily_report.jobs

    stamp = datetime.now(UTC).timestamp() - 60
    fetched: list[tuple[str, float]] = []
    sent: list[str] = []

    async def get_by_time_in_chat(**kwargs):
        fetched.append((kwargs["chat_id"], float(kwargs["end_time"])))
        if float(kwargs["start_time"]) <= stamp < float(kwargs["end_time"]):
            return [{
                "message_id": "one", "timestamp": stamp,
                "processed_plain_text": "今天聊了蓝莓",
                "message_info": {"user_info": {"user_nickname": "世界猫"}},
            }]
        return []

    async def generate(**kwargs):
        if "固定使用以下四个小标题" in kwargs["prompt"]:
            return {"response": "今日概览：聊了蓝莓。\n聊了什么：蓝莓。\n重要约定：无。\n暖心片段：暂无。"}
        return {"response": "聊了蓝莓。"}

    async def send_image(encoded, stream_id, return_details=False):
        assert Image.open(io.BytesIO(base64.b64decode(encoded))).format == "PNG"
        sent.append(stream_id)
        return {"sent": True}

    plugin.ctx.message = types.SimpleNamespace(get_by_time_in_chat=get_by_time_in_chat)
    plugin.ctx.llm = types.SimpleNamespace(generate=generate)
    plugin.ctx.send = types.SimpleNamespace(image=send_image)
    result = await plugin.secretary_generate_daily_report(**sender, target_chat="another-chat")
    assert result["status"] == "queued"
    assert "尚未生成或发送完成" in result["content"]
    duplicate = await plugin.secretary_generate_daily_report(**sender)
    assert duplicate["success"] is False
    await next(iter(plugin.daily_report.jobs.values()))
    assert sent == ["my-chat"]
    assert fetched and {item[0] for item in fetched} == {"my-chat"}
    assert max(end for _, end in fetched) <= datetime.now(UTC).timestamp()
    assert any(row["mode"] == "manual" and row["status"] == "sent" for row in plugin.daily_report.records.values())
    cooled = await plugin.secretary_generate_daily_report(**sender)
    assert cooled["success"] is False


@pytest.mark.asyncio
async def test_manual_report_failure_notifies_same_chat_and_allows_retry(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"plugin": {"admin_accounts": ["qq:123456789"]}})
    plugin.ctx.chat.streams = [{
        "stream_id": "my-chat", "platform": "qq", "chat_type": "private",
        "user_id": "123456789", "account_id": "bot-1",
    }]
    sender = {"stream_id": "my-chat", "chat_id": "my-chat", "user_id": "123456789"}
    notices: list[tuple[str, str]] = []

    async def get_by_time_in_chat(**kwargs):
        stamp = float(kwargs["end_time"]) - 1
        return [{"message_id": "one", "timestamp": stamp, "processed_plain_text": "今天的事"}]

    async def generate(**kwargs):
        raise RuntimeError("模型暂时不可用")

    async def send_text(message, stream_id):
        notices.append((message, stream_id))
        return True

    plugin.ctx.message = types.SimpleNamespace(get_by_time_in_chat=get_by_time_in_chat)
    plugin.ctx.llm = types.SimpleNamespace(generate=generate)
    plugin.ctx.send = types.SimpleNamespace(text=send_text)
    queued = await plugin.secretary_generate_daily_report(**sender)
    assert queued["success"] is True
    await next(iter(plugin.daily_report.jobs.values()))
    assert notices == [("今日日报暂时生成失败了，请稍后再试。", "my-chat")]
    assert any(record["status"] == "failed" for record in plugin.daily_report.records.values())
    retry = await plugin.secretary_generate_daily_report(**sender)
    assert retry["success"] is True
    await plugin.daily_report.stop()


@pytest.mark.asyncio
async def test_manual_report_uses_maibot_permission_when_plugin_admins_empty(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    plugin.ctx.chat.streams = [{
        "stream_id": "my-chat", "platform": "qq", "chat_type": "private",
        "user_id": "123456789", "account_id": "bot-1",
    }]

    permissions = ["qq:123456789"]

    async def get_config(key):
        assert key == "plugin.permission"
        return permissions

    async def get_by_time_in_chat(**kwargs):
        return []

    async def send_image(encoded, stream_id, return_details=False):
        return {"sent": True}

    plugin.ctx.config = types.SimpleNamespace(get=get_config)
    plugin.ctx.message = types.SimpleNamespace(get_by_time_in_chat=get_by_time_in_chat)
    plugin.ctx.send = types.SimpleNamespace(image=send_image)
    result = await plugin.secretary_generate_daily_report(
        stream_id="my-chat", chat_id="my-chat", user_id="123456789",
    )
    assert result["success"] is True
    await next(iter(plugin.daily_report.jobs.values()))
    assert any(row["status"] == "sent" for row in plugin.daily_report.records.values())
    permissions.clear()
    revoked = await plugin.secretary_generate_daily_report(
        stream_id="my-chat", chat_id="my-chat", user_id="123456789",
    )
    assert revoked["success"] is False
    assert "只有插件管理员" in revoked["error"]
