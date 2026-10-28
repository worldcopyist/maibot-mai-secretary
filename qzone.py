"""Optional QQ Space posts through NapCat's native send_qzone_msg action."""

from __future__ import annotations

import asyncio
import base64
import logging
import random
from datetime import UTC, datetime, time
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

import httpx
from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator

from .anti_bullying import normalize_admin_account
from .daily_report import _message_text
from .mood import MOODS
from .prompts import PERSONA_PRIORITY_PROMPT
from .stream_router import resolve_stream

LOG = logging.getLogger(__name__)


class QZoneSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "QQ Space"

    enabled: bool = Field(default=False, json_schema_extra={"label": "Enable QQ Space posting", "hint": "Requires a NapCat version with the native send_qzone_msg action. No separate QQ Space login is needed."})
    automatic_enabled: bool = Field(default=False, json_schema_extra={"label": "Automatically post every day", "hint": "When enabled, post at the configured local time. NapCat must support QQ Space posts."})
    automatic_time: str = Field(default="20:30", json_schema_extra={"label": "Daily post time", "hint": "HH:MM in the plugin timezone."})
    automatic_source: str = Field(default="life", json_schema_extra={"label": "Legacy source setting", "choices": ["life", "daily"], "hint": "Retained for older configurations; automatic posts now use the source probability below."})
    post_probability: int = Field(default=70, ge=0, le=100, json_schema_extra={"label": "Daily posting probability (%)", "hint": "One random draw at the scheduled time; 0 never posts, 100 always posts."})
    life_probability: int = Field(default=90, ge=0, le=100, json_schema_extra={"label": "Simulated life source probability (%)", "hint": "Otherwise use allowed chat highlights; if no streams are allowed, use simulated life."})
    image_probability: int = Field(default=30, ge=0, le=100, json_schema_extra={"label": "Automatic photo probability (%)", "hint": "Applied when automatic photos are enabled; explicit manual photo requests are unaffected."})
    allowed_streams: list[str] = Field(default_factory=list, json_schema_extra={"label": "Chat streams allowed for daily highlights", "hint": "Only these exact stream IDs may be summarized for a QQ Space post. Empty means no chat records may be used."})
    include_image: bool = Field(default=False, json_schema_extra={"label": "Include a life photo", "hint": "Uses the life-photo provider and its daily image budget. The photo is first-person unless selfie mode is requested separately."})
    visibility: str = Field(default="friends", json_schema_extra={"label": "Post visibility", "choices": ["private", "friends", "public"]})
    max_posts_per_day: int = Field(default=1, ge=1, le=10, json_schema_extra={"label": "Maximum QQ Space posts per day"})
    text_model: str = Field(default="", json_schema_extra={"label": "Optional text model", "hint": "Blank uses MaiBot's utils model."})

    @field_validator("automatic_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        try:
            parsed = time.fromisoformat(value)
        except ValueError as exc:
            raise ValueError("QQ 空间时间必须为 HH:MM") from exc
        if parsed.second or parsed.microsecond:
            raise ValueError("QQ 空间时间只精确到分钟")
        return parsed.strftime("%H:%M")

class QZoneModule:
    name = "qzone"
    state_keys = frozenset({"qzone_state"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.state: dict[str, Any] = {"posts": [], "automatic_day": ""}
        self._jobs: set[asyncio.Task[None]] = set()
        self._streams: dict[str, str] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        value = data.get("qzone_state", {})
        if not isinstance(value, dict):
            raise TypeError("QQ 空间状态格式无效")
        posts = value.get("posts", [])
        if not isinstance(posts, list):
            raise TypeError("QQ 空间记录格式无效")
        self.state = {"posts": [row for row in posts[-50:] if isinstance(row, dict)],
                      "automatic_day": str(value.get("automatic_day") or "")}

    def dump_state(self, payload: dict[str, Any]) -> None:
        if self.state["posts"] or self.state["automatic_day"]:
            payload["qzone_state"] = self.state

    def on_config_update(self) -> None:
        pass

    async def stop(self) -> None:
        jobs = list(self._jobs)
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    async def tick(self, now: datetime) -> None:
        settings = self.plugin.config.qzone
        if not settings.enabled or not settings.automatic_enabled:
            return
        local = now.astimezone(ZoneInfo(self.plugin.config.plugin.timezone))
        day = local.date().isoformat()
        if self.state["automatic_day"] == day or local.strftime("%H:%M") < settings.automatic_time:
            return
        due = datetime.combine(local.date(), time.fromisoformat(settings.automatic_time), local.tzinfo)
        if (local - due).total_seconds() > self.plugin.config.plugin.misfire_grace_seconds:
            self.state["automatic_day"] = day
            self.plugin._save_state()
            return
        self.state["automatic_day"] = day  # Claim before network I/O; never duplicate an uncertain publish.
        self.plugin._save_state()
        if random.random() * 100 >= settings.post_probability:
            return
        source = "life" if random.random() * 100 < settings.life_probability or not settings.allowed_streams else "daily"
        include_image = settings.include_image and random.random() * 100 < settings.image_probability
        await self._queue(source, "", include_image, "", "automatic")

    async def _verified_admin(self, kwargs: dict[str, Any]) -> tuple[str, str]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        user_id = str(kwargs.get("user_id") or "").strip()
        if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip() or not user_id:
            raise ValueError("无法核验当前聊天流和请求者")
        response = await self.plugin.ctx.chat.get_all_streams(platform="all_platforms")
        streams = response if isinstance(response, list) else response.get("streams") if isinstance(response, dict) and response.get("success") is not False else None
        if not isinstance(streams, list):
            raise TypeError("无法读取聊天流")
        matches = [row for row in streams if isinstance(row, dict) and str(row.get("stream_id") or row.get("session_id") or "") == stream_id]
        platforms = {str(row.get("platform") or "").lower() for row in matches}
        types = {str(row.get("chat_type") or "").lower() for row in matches}
        if len(platforms) != 1 or platforms != {"qq"} or len(types) != 1:
            raise ValueError("只能在已核验的 QQ 聊天中操作空间")
        if "group" in types:
            account = self.plugin.role_recognition.consume_planner_speaker(stream_id)
            if account is None or account != normalize_admin_account(f"qq:{user_id}"):
                raise ValueError("群聊发送者身份不一致")
        else:
            if any(str(row.get("user_id") or "") != user_id for row in matches):
                raise ValueError("私聊发送者身份不一致")
            account = normalize_admin_account(f"qq:{user_id}")
        if account not in await self.plugin.role_recognition.admin_accounts(force_refresh=True):
            raise ValueError("只有管理员能发布 QQ 空间")
        return stream_id, account

    async def tool(self, action: str, source: str = "life", topic: str = "", include_image: bool | None = None, **kwargs: Any) -> dict[str, Any]:
        try:
            stream_id, _account = await self._verified_admin(kwargs)
            if action == "status":
                return {"success": True, "posts": self.state["posts"][-10:]}
            if action != "publish":
                raise ValueError("QQ 空间操作只能是 publish 或 status")
            if not self.plugin.config.plugin.enabled or not self.plugin.config.qzone.enabled:
                raise ValueError("QQ 空间模块尚未启用")
            if include_image is None:
                settings = self.plugin.config.qzone
                include_image = settings.include_image and random.random() * 100 < settings.image_probability
            return await self._queue(source, topic, include_image, stream_id, "manual")
        except (ValueError, OSError, TypeError) as exc:
            return {"success": False, "error": str(exc)}

    async def _queue(self, source: str, topic: str, include_image: bool, stream_id: str, mode: str) -> dict[str, Any]:
        if source not in {"life", "daily"}:
            return {"success": False, "error": "内容来源只能是 life 或 daily"}
        if len(topic) > 200:
            return {"success": False, "error": "话题太长"}
        settings = self.plugin.config.qzone
        if source == "daily" and not settings.allowed_streams:
            return {"success": False, "error": "尚未设置允许提取聊天记录的聊天流"}
        local_day = datetime.now(UTC).astimezone(ZoneInfo(self.plugin.config.plugin.timezone)).date().isoformat()
        posts = [row for row in self.state["posts"] if row.get("day") == local_day and row.get("status") in {"queued", "publishing", "published", "unknown"}]
        if len(posts) >= settings.max_posts_per_day:
            return {"success": False, "error": "今天 QQ 空间发文已达上限"}
        record: dict[str, Any] = {"id": f"{local_day}-{len(self.state['posts']) + 1}", "day": local_day, "status": "queued", "source": source, "mode": mode, "created_at": datetime.now(UTC).isoformat()}
        self.state["posts"].append(record)
        self.state["posts"] = self.state["posts"][-50:]
        self.plugin._save_state()
        job = asyncio.create_task(self._publish(record, topic, include_image, stream_id), name="secretary-qzone-post")
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)
        return {"success": True, "content": "已开始准备 QQ 空间内容；发布结果稍后返回，当前还不能声称已发出。", "post_id": record["id"]}

    async def _publish(self, record: dict[str, Any], topic: str, include_image: bool, stream_id: str) -> None:
        try:
            record["status"] = "publishing"
            self.plugin._save_state()
            text, activity = await self._compose(record["source"], topic)
            image = await self._image(activity) if include_image else None
            result = await self._napcat_publish(text, image)
            record.update(status="published", tid=result["tid"], image=bool(image))
        except asyncio.CancelledError:
            record["status"] = "unknown"
            raise
        except Exception as exc:
            record.update(status="unknown" if isinstance(exc, (httpx.ReadTimeout, httpx.ReadError)) else "failed", error=str(exc)[:200])
            LOG.exception("QQ 空间发布未确认：%s", record["id"])
        finally:
            self.plugin._save_state()
            if stream_id:
                status = record["status"]
                detail = f"发布成功，空间说说编号 {record.get('tid')}" if status == "published" else f"发布未确认，原因：{record.get('error', '任务中断')}；不要声称已发出，也不要自动重试"
                try:
                    await self.plugin._trigger(stream_id, f"{PERSONA_PRIORITY_PROMPT}\n这是刚才管理员要求发布 QQ 空间的后台结果：{detail}。请按当前人设简短告诉管理员，不要再次调用 `secretary_qzone_post`。", "QQ 空间发布结果", record["id"])
                except Exception:
                    LOG.exception("QQ 空间结果无法回传到聊天流")

    async def _compose(self, source: str, topic: str) -> tuple[str, str]:
        if source == "life":
            now = datetime.now(UTC)
            scene = self.plugin.virtual_life.scene_at(now)
            if not scene or not scene.get("activity"):
                raise ValueError("当前没有可分享的模拟生活事件")
            activity = str(scene["activity"])
            if "睡觉" in activity or "睡" in activity and "准备" not in activity:
                raise ValueError("当前在睡觉，不能发布生活动态")
            day = now.astimezone(ZoneInfo(self.plugin.config.plugin.timezone)).date().isoformat()
            history = [row for row in self.plugin.virtual_life.history if str(row.get("key", "")).startswith(day + ":")]
            if not any(row.get("key") == scene.get("key") for row in history):
                history.append(scene)
            material = "今天已记录的模拟生活活动（只根据这些记录总结，不补造未记录的时段）：\n" + "\n".join(f"{row.get('period', '')}：{row.get('activity', '')}" for row in history)
        else:
            now = datetime.now(UTC).astimezone(ZoneInfo(self.plugin.config.plugin.timezone))
            rows: list[str] = []
            for target in self.plugin.config.qzone.allowed_streams:
                stream_id = await resolve_stream(self.plugin.ctx, target, self._streams) if ":" in target else target
                messages = await self.plugin.daily_report._read_day(stream_id, now.date(), now)
                rows.extend(_message_text(row)[:300] for row in messages if _message_text(row))
            if not rows:
                raise ValueError("今天允许的聊天流没有可总结的文字")
            material = "今天聊天摘要素材（仅提取适合公开分享的轻松内容，勿泄露账号、隐私或逐字引用）：\n" + "\n".join(rows[-60:])[-8000:]
            activity = str((self.plugin.virtual_life.scene_at(datetime.now(UTC)) or {}).get("activity") or "")
        mood = self.plugin.mood.current(datetime.now(UTC))
        mood_text = MOODS.get(str(mood.get("mood")), ("", ""))[0] if mood else ""
        prompt = (f"{PERSONA_PRIORITY_PROMPT}\n请为麦麦自己的 QQ 空间写一条简短自然的说说。只返回说说正文，40–180 字，不要标题、引号、话题标签或解释。"
                  "必须基于下面素材；不要捏造真实经历或把别人的私事公开。遵循 MaiBot 当前人设与语气。"
                  f"\n当前心情：{mood_text or '未启用心情模块，按人设自然表达'}；让语气自然反映当前心情。\n话题建议：{topic[:200]}\n{material}")
        model_name = self.plugin.config.qzone.text_model.strip()
        options: dict[str, Any] = {"model_name": model_name} if model_name else {}
        result = await self.plugin.ctx.llm.generate(
            prompt=prompt, task_name="utils", temperature=0.5, max_tokens=500,
            rpc_timeout_ms=90000, **options,
        )
        if not isinstance(result, dict) or result.get("success") is False:
            raise RuntimeError("空间文案模型调用失败")
        text = str(result.get("response") or result.get("content") or "").strip().strip('"“”')
        if not 10 <= len(text) <= 500:
            raise ValueError("空间文案长度异常")
        return text, activity

    async def _image(self, activity: str) -> bytes:
        if not activity or "睡觉" in activity or "安稳睡" in activity:
            raise ValueError("当前没有适合拍照的模拟生活事件，不能为这条空间动态配图")
        settings = self.plugin.config.life_photo
        if not settings.enabled or settings.provider != "qwen" or not settings.api_key.strip():
            raise ValueError("生活照片模块未启用或没有千问生图密钥")
        now = datetime.now(UTC)
        local_day = now.astimezone(ZoneInfo(self.plugin.config.plugin.timezone)).date().isoformat()
        async with self.plugin._lock:
            usage = self.plugin.life_photo.usage
            count = int(usage.get("count", 0)) if usage.get("day") == local_day else 0
            if count >= settings.max_images_per_day or now.timestamp() - float(usage.get("last_attempt_at", 0)) < settings.cooldown_minutes * 60:
                raise ValueError("生活照片仍在冷却或已达到今日张数上限")
            prompt, refs = self.plugin.life_photo._prompt_and_refs(activity, "QQ 空间生活随拍", "scene")
            self.plugin.life_photo.usage = {"day": local_day, "count": count + 1, "last_attempt_at": now.timestamp(), "status": "qzone_attempt"}
            self.plugin._save_state()
        async with httpx.AsyncClient(timeout=httpx.Timeout(240.0), follow_redirects=False) as client:
            return await self.plugin.life_photo._request_image(client, prompt, refs, settings)

    async def _napcat_publish(self, text: str, image: bytes | None) -> dict[str, str]:
        settings = self.plugin.config.qzone
        params = {
            "content": text,
            "images": ["base64://" + base64.b64encode(image).decode("ascii")] if image else [],
            "ugc_right": {"public": 1, "friends": 4, "private": 64}[settings.visibility],
            "target_uins": [],
        }
        response = await self.plugin.ctx.api.call(
            "adapter.napcat.action.call", action_name="send_qzone_msg", params=params,
        )
        if not isinstance(response, dict) or response.get("success") is not True:
            raise RuntimeError(f"NapCat 适配器调用失败：{str(response.get('error') if isinstance(response, dict) else '无响应')[:150]}")
        data = response.get("result")
        if not isinstance(data, dict) or str(data.get("status") or "").lower() != "ok" or data.get("retcode") != 0:
            raise RuntimeError(f"NapCat 未确认 QQ 空间发布：{str(data.get('message') or data.get('wording') or data.get('retcode') if isinstance(data, dict) else '无有效回执')[:150]}")
        tid = str((data.get("data") or {}).get("tid") or "")
        if not tid:
            raise RuntimeError("NapCat 未返回说说编号，发布状态不确定")
        return {"tid": tid}
