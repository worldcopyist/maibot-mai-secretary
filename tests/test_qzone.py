from __future__ import annotations

import asyncio
import types
from datetime import UTC, datetime

import pytest
from test_secretary import make_plugin, module


def test_napcat_module_auto_post_stays_off(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    assert plugin.config.qzone.enabled is False
    assert plugin.config.qzone.automatic_enabled is False
    with pytest.raises(ValueError):
        module.QZoneSettings(automatic_time="25:00")


@pytest.mark.asyncio
async def test_publish_uses_native_napcat_action_and_waits_for_confirmed_tid(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"qzone": {"enabled": True}, "virtual_life": {"enabled": True}})
    plugin._ctx.chat.streams = [{"stream_id": "real-stream-1", "platform": "qq", "chat_type": "private", "user_id": "123", "account_id": "bot-1"}]
    plugin.role_recognition.admin_accounts = lambda **kwargs: asyncio.sleep(0, result={"qq:123"})
    plugin.virtual_life.scene_at = lambda now: {"activity": "在桌边拼乐高"}
    model_calls = []
    def generate(**kwargs):
        model_calls.append(kwargs)
        return asyncio.sleep(0, result={"success": True, "response": "今天终于把小房子拼好了，最后一块积木找了好久！"})
    plugin._ctx.llm = types.SimpleNamespace(generate=generate)
    plugin._trigger = lambda *args, **kwargs: asyncio.sleep(0, result=True)
    requests = []
    async def call(name, **kwargs):
        requests.append((name, kwargs))
        return {"success": True, "result": {"status": "ok", "retcode": 0, "data": {"tid": "321"}}}
    plugin._ctx.api = types.SimpleNamespace(call=call)
    result = await plugin.qzone.tool("publish", "life", "今天的手工", False, stream_id="real-stream-1", chat_id="real-stream-1", user_id="123")
    assert result["success"] is True
    await asyncio.gather(*plugin.qzone._jobs)
    assert plugin.qzone.state["posts"][-1]["status"] == "published"
    assert plugin.qzone.state["posts"][-1]["tid"] == "321"
    assert "model_name" not in model_calls[0]
    assert len(requests) == 1 and requests[0][0] == "adapter.napcat.action.call"
    assert requests[0][1]["action_name"] == "send_qzone_msg"
    body = requests[0][1]["params"]
    assert body["ugc_right"] == 4 and body["images"] == []
    assert "最后一块" in body["content"]
    duplicate = await plugin.qzone.tool("publish", "life", "", False, stream_id="real-stream-1", chat_id="real-stream-1", user_id="123")
    assert duplicate["success"] is False
    outsider = await plugin.qzone.tool("status", stream_id="real-stream-1", chat_id="real-stream-1", user_id="other")
    assert outsider["success"] is False


@pytest.mark.asyncio
async def test_automatic_daily_post_is_claimed_once(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"qzone": {"enabled": True, "automatic_enabled": True, "automatic_time": "20:30", "post_probability": 100}})
    calls = []
    plugin.qzone._queue = lambda *args: asyncio.sleep(0, result=calls.append(args))
    due = datetime(2026, 10, 28, 12, 30, tzinfo=UTC)
    await plugin.qzone.tick(due)
    await plugin.qzone.tick(due)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_probability_boundaries_and_empty_allowlist(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"qzone": {"enabled": True, "automatic_enabled": True, "post_probability": 0}})
    calls = []
    plugin.qzone._queue = lambda *args: asyncio.sleep(0, result=calls.append(args))
    due = datetime(2026, 10, 28, 12, 30, tzinfo=UTC)
    await plugin.qzone.tick(due)
    assert not calls
    plugin.qzone.state["automatic_day"] = ""
    plugin.config.qzone.post_probability = 100
    plugin.config.qzone.life_probability = 0
    plugin.config.qzone.include_image = True
    plugin.config.qzone.image_probability = 100
    await plugin.qzone.tick(due)
    assert calls[0][0] == "life" and calls[0][2] is True


@pytest.mark.asyncio
async def test_life_summary_uses_recorded_today_and_current_mood(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"virtual_life": {"enabled": True}, "mood": {"enabled": True}})
    now = datetime.now(UTC)
    plugin.virtual_life.scene_at(now)
    prompts = []
    async def generate(**kwargs):
        prompts.append(kwargs["prompt"])
        return {"success": True, "response": "今天过得很充实，做了喜欢的事情，心情也很不错。"}
    plugin._ctx.llm = types.SimpleNamespace(generate=generate)
    plugin.mood.current = lambda _now: {"mood": "happy"}
    await plugin.qzone._compose("life", "")
    assert plugin.virtual_life.history[0]["activity"] in prompts[0]
    assert "开心" in prompts[0]
