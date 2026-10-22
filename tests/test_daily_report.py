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
        "daily_report": {"enabled": True, "target_chats": [target], "summary_time": "10:00"},
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
    prompts: list[str] = []
    sent: list[tuple[bytes, str]] = []

    async def get_by_time_in_chat(**kwargs):
        start, end = float(kwargs["start_time"]), float(kwargs["end_time"])
        requested.append((start, end))
        assert kwargs["limit"] == 0
        return [row for row in messages if start <= row["timestamp"] <= end]

    async def generate(**kwargs):
        prompts.append(kwargs["prompt"])
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
    assert all(any(f"第 {index} 条话题" in prompt for prompt in prompts) for index in range(3))
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
