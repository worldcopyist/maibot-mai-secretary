from __future__ import annotations

import base64
import json
import types
from pathlib import Path

import httpx
import pytest
from mai_secretary import voice_synthesis
from test_secretary import make_plugin


def test_reads_existing_mimo_provider_without_exposing_key(tmp_path: Path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "model_config.toml").write_text(
        '[[api_providers]]\nname = "mimo"\nbase_url = "https://api.xiaomimimo.com/v1"\napi_key = "test-secret"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(voice_synthesis, "__file__", str(tmp_path / "plugins" / "secretary" / "voice_synthesis.py"))
    assert voice_synthesis.VoiceSynthesisModule._provider() == (
        "test-secret", "https://api.xiaomimimo.com/v1",
    )


@pytest.mark.asyncio
async def test_sends_voice_to_current_qq_chat_only_and_cools_down(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path)
    plugin.ctx.chat.streams = [{"stream_id": "s1", "platform": "qq", "chat_type": "private"}]
    sent = []

    async def custom(kind, data, stream_id, **kwargs):
        sent.append((kind, data, stream_id, kwargs))
        return {"success": True, "sent": True}

    async def synthesize(text, mode):
        assert text == "你好，主人喵。"
        assert mode == "speech"
        return "audio-base64"

    plugin.ctx.send = types.SimpleNamespace(custom=custom)
    monkeypatch.setattr(plugin.voice_synthesis, "_synthesize", synthesize)
    assert (await plugin.secretary_speak("你好，主人喵。", stream_id="s1", chat_id="other"))["success"] is False
    assert (await plugin.secretary_speak("你好，主人喵。", stream_id="s1", chat_id="s1"))["success"] is True
    assert sent == [("voice", "audio-base64", "s1", {"return_details": True})]
    assert (await plugin.secretary_speak("你好，主人喵。", stream_id="s1", chat_id="s1"))["success"] is False


@pytest.mark.asyncio
async def test_mimo_request_uses_voice_design_and_preset_singing(tmp_path, monkeypatch):
    plugin, _ = make_plugin(tmp_path)
    requests = []
    raw = b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40
    encoded = base64.b64encode(raw).decode()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        assert request.url == "https://api.xiaomimimo.com/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-secret"
        return httpx.Response(200, json={"choices": [{"message": {"audio": {"data": encoded}}}]})

    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        return real_client(transport=transport, **kwargs)

    monkeypatch.setattr(voice_synthesis.VoiceSynthesisModule, "_provider", staticmethod(lambda: ("test-secret", "https://api.xiaomimimo.com/v1")))
    monkeypatch.setattr(voice_synthesis.httpx, "AsyncClient", client_factory)
    assert await plugin.voice_synthesis._synthesize("你好", "speech") == encoded
    assert await plugin.voice_synthesis._synthesize("(唱歌)蓝莓真甜", "sing") == encoded
    assert requests[0]["model"] == voice_synthesis.VOICE_DESIGN_MODEL
    assert "软糯" in requests[0]["messages"][0]["content"]
    assert "voice" not in requests[0]["audio"]
    assert requests[1]["model"] == voice_synthesis.SINGING_MODEL
    assert requests[1]["audio"]["voice"] == "冰糖"
