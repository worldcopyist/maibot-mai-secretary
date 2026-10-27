from __future__ import annotations

import asyncio
import base64
import io
import json
import types

import httpx
import pytest
from mai_secretary.virtual_life import DEFAULT_CHOICES, DEFAULT_FIXED_TEXT
from PIL import Image
from test_secretary import make_plugin


@pytest.mark.asyncio
async def test_current_life_photo_uses_two_refs_and_sends_to_verified_stream(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, {
        "virtual_life": {"enabled": True},
        "life_photo": {"enabled": True, "api_key": "test-only", "cooldown_minutes": 120},
    })
    sent = []

    async def send_image(encoded, stream_id, **kwargs):
        sent.append((stream_id, base64.b64decode(encoded), kwargs))
        return {"sent": True}

    plugin._ctx.send = types.SimpleNamespace(image=send_image)
    plugin.virtual_life.scene_at = lambda now: {"activity": "在家玩游戏"}
    request_bodies = []
    png = io.BytesIO()
    Image.new("RGB", (4, 4), "blue").save(png, format="PNG")

    def handler(request):
        if request.method == "POST":
            assert request.headers["Authorization"] == "Bearer test-only"
            body = json.loads(request.content)
            request_bodies.append(body)
            return httpx.Response(200, json={"data": [{"url": "https://result.aliyuncs.com/photo.png"}]})
        assert request.url.host == "result.aliyuncs.com"
        return httpx.Response(200, content=png.getvalue(), headers={"content-type": "image/png"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    result = await plugin.life_photo.share(detail="一张很随意的生活照", stream_id="real-stream-1", chat_id="real-stream-1")
    assert result["success"] is True
    await asyncio.gather(*list(plugin.life_photo._jobs))
    assert plugin.life_photo.usage["status"] == "sent"
    assert len(sent) == 1 and sent[0][0] == "real-stream-1"
    assert sent[0][1].startswith(b"\x89PNG")
    assert len(request_bodies) == 1
    assert request_bodies[0]["model"] == "qwen-image-2.1-turbo"
    assert len(request_bodies[0]["image"]) == 2  # character plus selected location sheet
    assert "Current activity:" in request_bodies[0]["prompt"]
    assert (await plugin.life_photo.share(stream_id="real-stream-1", chat_id="wrong"))["success"] is False
    assert (await plugin.life_photo.share(stream_id="real-stream-1", chat_id="real-stream-1"))["success"] is False


def test_references_cannot_escape_plugin_data_directory(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    with pytest.raises(ValueError):
        plugin.life_photo._reference_path("../secret.png")
    assert plugin.life_photo._reference_path("builtin:icon").is_file()


@pytest.mark.parametrize(("activity", "location"), [
    ("窝在沙发上看动漫", "home"),
    ("烤吐司和煎蛋当早餐", "kitchen"),
    ("整理床铺，准备睡觉", "bedroom"),
    ("在桌边拼乐高", "hobby"),
    ("给窗边植物浇水", "balcony"),
    ("起床洗漱", "bathroom"),
    ("出门散一小会儿步，顺路买晚饭食材", "neighborhood"),
    ("去 KFC 吃炸鸡和薯条", "restaurant"),
    ("去湿地公园散步", "park"),
])
def test_activity_selects_matching_multiview_reference(tmp_path, activity, location):
    plugin, _ = make_plugin(tmp_path)
    assert plugin.life_photo._location(activity) == location
    prompt, refs = plugin.life_photo._prompt_and_refs(activity, "")
    assert len(refs) == 2
    assert "ONE place" in prompt
    assert all(ref.startswith("data:image/png;base64,") for ref in refs)


def test_every_default_simulated_activity_has_a_location(tmp_path):
    plugin, _ = make_plugin(tmp_path)
    choices = [item for period in DEFAULT_CHOICES.values() for item in period]
    choices.extend(DEFAULT_FIXED_TEXT.values())
    for activity in choices:
        location = plugin.life_photo._location(activity)
        assert location in {"home", "kitchen", "bedroom", "hobby", "balcony", "bathroom", "neighborhood", "restaurant", "park"}
        prompt, refs = plugin.life_photo._prompt_and_refs(activity, "")
        assert prompt and len(refs) == 2


@pytest.mark.asyncio
async def test_minimax_uses_character_only_and_scene_text(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path, {
        "virtual_life": {"enabled": True},
        "life_photo": {"enabled": True, "provider": "minimax", "minimax_api_key": "mini-test"},
    })
    plugin.virtual_life.scene_at = lambda now: {"activity": "在湿地公园散步"}
    sent = []

    async def send_image(encoded, stream_id, **kwargs):
        sent.append(stream_id)
        return {"sent": True}

    plugin._ctx.send = types.SimpleNamespace(image=send_image)
    png = io.BytesIO()
    Image.new("RGB", (4, 4), "pink").save(png, format="PNG")
    bodies = []

    def handler(request):
        assert request.url.host == "api.minimax.cn"
        assert request.headers["Authorization"] == "Bearer mini-test"
        body = json.loads(request.content)
        bodies.append(body)
        return httpx.Response(200, json={
            "base_resp": {"status_code": 0, "status_msg": "success"},
            "data": {"image_base64": [base64.b64encode(png.getvalue()).decode()]},
        })

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    result = await plugin.life_photo.share(stream_id="real-stream-1", chat_id="real-stream-1")
    assert result["success"] is True
    await asyncio.gather(*list(plugin.life_photo._jobs))
    assert sent == ["real-stream-1"]
    assert bodies[0]["model"] == "image-01" and bodies[0]["n"] == 1
    assert len(bodies[0]["subject_reference"]) == 1
    assert bodies[0]["subject_reference"][0]["image_file"].startswith("data:image/")
    assert "wetland park" in bodies[0]["prompt"]
    assert "image" not in bodies[0]
