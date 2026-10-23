"""MiMo speech synthesis for the current QQ chat stream."""

from __future__ import annotations

import asyncio
import base64
import binascii
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from .plugin import MaiSecretaryPlugin


VOICE_DESIGN_MODEL = "mimo-v2.5-tts-voicedesign"
SINGING_MODEL = "mimo-v2.5-tts"
AZURE_VOICE_PROMPT = (
    "请设计听感约16岁的少女普通话声线：音高偏高但不尖，声音轻盈、软甜，"
    "带一点浅浅的鼻音和自然的嗲感，像和亲近的人轻声撒娇聊天；"
    "不要成熟厚重，也不要夸张夹嗓或幼儿奶声。语速中等稍快，字与字自然连贯，"
    "咬字柔和，不逐字强调、不在每个词后停顿；句尾偶尔软软地轻拖一点并微微上扬。"
    "情绪带一点好奇、黏人和憨憨的笑意，认真说明事情时也保持这条年轻柔软的声线。"
)


class VoiceSynthesisModule:
    name = "voice_synthesis"
    state_keys: frozenset[str] = frozenset()

    def __init__(self, plugin: MaiSecretaryPlugin) -> None:
        self.plugin = plugin
        self._lock = asyncio.Lock()
        self._last_attempt: dict[str, float] = {}

    @property
    def settings(self) -> Any:
        return self.plugin.config.voice_synthesis

    def load_state(self, data: dict[str, Any]) -> None:
        del data

    def dump_state(self, payload: dict[str, Any]) -> None:
        del payload

    def on_config_update(self) -> None:
        self._last_attempt.clear()

    async def tick(self, now: datetime) -> None:
        del now

    async def speak(self, text: str, mode: str = "speech", **kwargs: Any) -> dict[str, Any]:
        """Generate and send one voice message, without exposing the API key."""
        try:
            if not self.plugin.config.plugin.enabled or not self.settings.enabled:
                raise ValueError("小秘书语音模块尚未启用")
            stream_id = str(kwargs.get("stream_id") or "").strip()
            if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip():
                raise ValueError("无法确认当前聊天流，不能发送语音")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("语音内容不能为空")
            content = text.strip()
            if len(content) > self.settings.max_text_chars:
                raise ValueError(f"语音内容不能超过 {self.settings.max_text_chars} 字")
            if mode not in {"speech", "sing"}:
                raise ValueError("mode 只能是 speech 或 sing")
            if mode == "sing" and not self.settings.singing_enabled:
                raise ValueError("唱歌功能未开启")
            if mode == "sing" and not content.startswith("(唱歌)"):
                content = "(唱歌)" + content
            await self._verify_stream(stream_id)
            async with self._lock:
                now = time.monotonic()
                if now - self._last_attempt.get(stream_id, -1e10) < self.settings.cooldown_seconds:
                    raise ValueError("刚尝试生成语音，请稍等一会儿再试")
                self._last_attempt[stream_id] = now
                audio_data = await self._synthesize(content, mode)
                result = await self.plugin.ctx.send.custom(
                    "voice", audio_data, stream_id, return_details=True,
                )
                if result is False or (isinstance(result, dict) and result.get("success") is False):
                    raise RuntimeError("QQ 语音发送接口未确认送达")
            return {"success": True, "content": "语音已发送；不要再重复朗读或声称还未发送。"}
        except (ValueError, RuntimeError, TypeError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception:
            self.plugin.ctx.logger.exception("小秘书语音合成或发送失败")
            return {"success": False, "error": "语音暂时无法生成或发送，请用蓝天的人设向用户说明并改用文字回复。"}

    async def _verify_stream(self, stream_id: str) -> None:
        response = await self.plugin.ctx.chat.get_all_streams(platform="qq")
        streams = response if isinstance(response, list) else response.get("streams") if isinstance(response, dict) else None
        if not isinstance(streams, list):
            raise TypeError("无法核验当前 QQ 聊天流")
        matches = [item for item in streams if isinstance(item, dict) and str(item.get("stream_id") or item.get("session_id") or "") == stream_id]
        if len(matches) != 1 or matches[0].get("platform") != "qq":
            raise ValueError("目前只支持在当前 QQ 聊天流发送语音")

    @staticmethod
    def _provider() -> tuple[str, str]:
        """Read MaiBot's existing MiMo provider; never copy its secret into plugin config."""
        for parent in Path(__file__).resolve().parents:
            path = parent / "config" / "model_config.toml"
            if not path.is_file():
                continue
            data = tomllib.loads(path.read_text(encoding="utf-8"))
            for provider in data.get("api_providers", []):
                if not isinstance(provider, dict) or provider.get("name") != "mimo":
                    continue
                key = str(provider.get("api_key") or "").strip()
                base_url = str(provider.get("base_url") or "").rstrip("/")
                parsed = urlsplit(base_url)
                if parsed.scheme != "https" or parsed.hostname != "api.xiaomimimo.com" or parsed.path != "/v1":
                    raise RuntimeError("麦麦的 MiMo API 地址不是官方地址")
                if not key:
                    raise RuntimeError("麦麦的 MiMo API Key 未配置")
                return key, base_url
            raise RuntimeError("麦麦模型配置里没有 MiMo 提供方")
        raise RuntimeError("找不到麦麦的 model_config.toml")

    async def _synthesize(self, text: str, mode: str) -> str:
        key, base_url = self._provider()
        if mode == "sing":
            model = SINGING_MODEL
            audio = {"format": "wav", "voice": self.settings.singing_voice}
            context = "用亲近、轻快、自然的年轻女声唱出完整歌词，咬字清楚，保持自然节奏。"
        else:
            model = VOICE_DESIGN_MODEL
            audio = {"format": "wav"}
            context = self.settings.voice_prompt.strip()
            if not context:
                raise ValueError("请先填写蓝天的音色描述")
        payload = {
            "model": model,
            "messages": [
                {"role": "user", "content": context},
                {"role": "assistant", "content": text},
            ],
            "audio": audio,
        }
        async with httpx.AsyncClient(timeout=self.settings.timeout_seconds) as client:
            response = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
        if response.status_code != 200:
            raise RuntimeError(f"MiMo 语音接口返回 HTTP {response.status_code}")
        try:
            data = response.json()
            encoded = data["choices"][0]["message"]["audio"]["data"]
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, KeyError, IndexError, TypeError, binascii.Error) as exc:
            raise RuntimeError("MiMo 未返回可读取的音频") from exc
        if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
            raise RuntimeError("MiMo 返回的音频不是 WAV 格式")
        return encoded
