"""Optional, budget-limited snapshots of the current simulated life scene."""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from maibot_sdk import Field, PluginConfigBase
from PIL import Image, UnidentifiedImageError

LOG = logging.getLogger(__name__)
ASSETS = Path(__file__).parent / "assets"
BUILTIN_REFERENCES = {
    "icon": ASSETS / "icon.png",
    "home": ASSETS / "life_photo_home.png",
    "park": ASSETS / "life_photo_park.png",
    "living_room_views": ASSETS / "life_photo_scenes/living_room_views.png",
    "kitchen_dining_views": ASSETS / "life_photo_scenes/kitchen_dining_views.png",
    "bedroom_views": ASSETS / "life_photo_scenes/bedroom_views.png",
    "hobby_desk_views": ASSETS / "life_photo_scenes/hobby_desk_views.png",
    "balcony_views": ASSETS / "life_photo_scenes/balcony_views.png",
    "bathroom_views": ASSETS / "life_photo_scenes/bathroom_views.png",
    "neighborhood_views": ASSETS / "life_photo_scenes/neighborhood_views.png",
    "fried_chicken_restaurant_views": ASSETS / "life_photo_scenes/fried_chicken_restaurant_views.png",
    "wetland_park_views": ASSETS / "life_photo_scenes/wetland_park_views.png",
}
LIGHTING_PERIODS = {
    "predawn": "night", "morning": "morning", "late_morning": "day",
    "noon": "day", "afternoon": "day", "dusk": "dusk",
    "night": "night", "late_night": "night",
}
LIGHTING_DESCRIPTIONS = {
    "morning": "early morning light and sky",
    "day": "bright daytime light and sky",
    "dusk": "evening twilight and fading sunset light",
    "night": "nighttime darkness outside with appropriate artificial lighting",
}
TIMED_SCENE_NAMES = frozenset({
    "living_room_views", "kitchen_dining_views", "bedroom_views", "hobby_desk_views",
    "balcony_views", "bathroom_views", "neighborhood_views", "fried_chicken_restaurant_views",
    "wetland_park_views",
})
BUILTIN_REFERENCES.update({
    f"{scene}_{period}": ASSETS / "life_photo_scenes" / "lighting" / f"{scene}_{period}.png"
    for scene in TIMED_SCENE_NAMES for period in LIGHTING_DESCRIPTIONS
})
ENDPOINTS = {
    "beijing": "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
    "singapore": "https://dashscope-intl.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation",
}
MINIMAX_ENDPOINTS = {
    "china": "https://api.minimax.cn/v1/image_generation",
    "global": "https://api.minimax.io/v1/image_generation",
}
SCENE_ANCHORS = {
    "home": "One fixed living room: moss-green sofa on the left, television on an oak cabinet on the right, coffee table and navy floor cushion in the center, sliding balcony doors at the back.",
    "kitchen": "One compact adjoining kitchen: oak lower cabinets, cream upper cabinets, sink under the window, stove and a two-seat wooden dining table.",
    "bedroom": "One cozy bedroom: bed along the left wall, oak wardrobe on the right, window on the far wall and a few soft toys.",
    "hobby": "One craft desk near the living room: the same wood desk, storage shelves, building blocks, fuse beads and drawing supplies.",
    "balcony": "One narrow apartment balcony: sliding doors, cream parapet, small plant stand, familiar potted plants and the same city skyline.",
    "bathroom": "One compact bathroom: oval sink and oak vanity on the left, glass shower on the right, frosted window and blue towels.",
    "neighborhood": "One neighborhood block: cream apartment building, green-awning corner grocery, a large ginkgo tree, bike racks and a crosswalk.",
    "restaurant": "One familiar fried-chicken restaurant: red-framed street entrance, counter at the back, red booth on the right and pale wood tables in the center.",
    "park": "One wetland park: curving gravel path on the left of the lake, low wooden fence, tall reeds, large tree at the entrance and distant hills.",
}
REFERENCE_FIELDS = {
    "home": "home_reference",
    "kitchen": "kitchen_reference",
    "bedroom": "bedroom_reference",
    "hobby": "hobby_reference",
    "balcony": "balcony_reference",
    "bathroom": "bathroom_reference",
    "neighborhood": "neighborhood_reference",
    "restaurant": "restaurant_reference",
    "park": "park_reference",
}
DEFAULT_CHARACTER_PROMPT = (
    "For an explicitly requested front-camera selfie only, use the first reference image as "
    "the photographer's identity reference. Preserve the same face, hair and distinctive "
    "accessories without inventing a different person. The current bot persona remains authoritative."
)
DEFAULT_SCENE_PROMPT = (
    "Create one realistic handheld smartphone photo at eye level of what the bot sees during "
    "its activity. The photographer stays BEHIND the camera: no face, body, hand or reflection. "
    "Use natural light, believable optics and photographic textures. Location references define "
    "layout only, not illustration style. No collage, panels, caption, watermark or extra people."
)
SELFIE_PROMPT = (
    "This is explicitly a FRONT-CAMERA SELFIE taken by the bot. Show the same person as the "
    "character reference in a natural close phone photo. Frame from the head and shoulders "
    "down to at most the waist; do not show hips, legs, feet or a full body. The phone and "
    "camera-holding arm stay outside the frame; no arm reaches towards the lens, no long arm, "
    "giant hand, wide-angle distortion or stretched anatomy. Use natural eye-level perspective. "
    "Keep the recognizable location visible behind the subject and preserve its layout from "
    "the second reference. Render subject and environment as a single coherent scene with "
    "matching visual style, light direction, color temperature, exposure and shadows. Let "
    "ambient light, bounce light and soft contact shadows fall naturally on the face, hair "
    "and clothing; match edge softness, depth of field and grain to the background. "
    "Preserve the character's face, hair, ears and distinctive accessories, and adapt the "
    "background to the character's illustration style so neither looks pasted on. "
    "Show one coherent front-camera selfie, not a three-view sheet, collage, third-person "
    "portrait or additional people."
)


class LifePhotoSettings(PluginConfigBase):
    __ui_label__: ClassVar[str] = "Life Photos"

    enabled: bool = Field(default=False, json_schema_extra={
        "label": "Enable life photos", "hint": "MaiBot may choose to share a generated image while talking about its current simulated activity. Requires an image API key; each image may cost money."
    })
    provider: str = Field(default="qwen", json_schema_extra={
        "label": "Image API provider", "hint": "Choose Qwen Image or MiniMax. Both use the same life-photo tool, cooldown and daily cap.", "choices": ["qwen", "minimax"]
    })
    api_key: str = Field(default="", json_schema_extra={
        "label": "Qwen Image API key", "hint": "Keep this key in the installed plugin configuration; never put it in source control or prompts.", "x-widget": "password"
    })
    region: str = Field(default="beijing", json_schema_extra={
        "label": "API region", "hint": "Choose the region in which your Qwen Image API key is valid.", "choices": ["beijing", "singapore"]
    })
    model: str = Field(default="qwen-image-2.1-turbo", json_schema_extra={
        "label": "Image model", "hint": "Qwen Image 2.1 Turbo uses the DashScope image API. Ordinary photos send the location sheet only."
    })
    minimax_api_key: str = Field(default="", json_schema_extra={
        "label": "MiniMax API key", "hint": "A standard image-generation API key for the selected MiniMax region. Keep it in the installed plugin config.", "x-widget": "password"
    })
    minimax_region: str = Field(default="china", json_schema_extra={
        "label": "MiniMax API region", "hint": "Use china for api.minimax.cn or global for api.minimax.io; the key must match the region.", "choices": ["china", "global"]
    })
    character_reference: str = Field(default="builtin:icon", json_schema_extra={
        "label": "Selfie character reference", "hint": "Used only for front-camera selfies. builtin:icon uses the plugin avatar; replace it with a PNG/JPEG/WebP character sheet in plugin data/life-photo-references."
    })
    home_reference: str = Field(default="builtin:living_room_views", json_schema_extra={
        "label": "Living room reference", "hint": "Three views of one living room. Use builtin:home for the original single view, or a filename in plugin data/life-photo-references."
    })
    kitchen_reference: str = Field(default="builtin:kitchen_dining_views", json_schema_extra={
        "label": "Kitchen and dining reference", "hint": "Three views of one kitchen and dining area, or a custom reference filename."
    })
    bedroom_reference: str = Field(default="builtin:bedroom_views", json_schema_extra={
        "label": "Bedroom reference", "hint": "Three views of one bedroom, or a custom reference filename."
    })
    hobby_reference: str = Field(default="builtin:hobby_desk_views", json_schema_extra={
        "label": "Craft and game desk reference", "hint": "Three views of one craft desk, or a custom reference filename."
    })
    balcony_reference: str = Field(default="builtin:balcony_views", json_schema_extra={
        "label": "Balcony reference", "hint": "Three views of one balcony and plant corner, or a custom reference filename."
    })
    bathroom_reference: str = Field(default="builtin:bathroom_views", json_schema_extra={
        "label": "Bathroom reference", "hint": "Three views of one wash area, or a custom reference filename."
    })
    neighborhood_reference: str = Field(default="builtin:neighborhood_views", json_schema_extra={
        "label": "Neighborhood reference", "hint": "Three views of one nearby street and grocery, or a custom reference filename."
    })
    restaurant_reference: str = Field(default="builtin:fried_chicken_restaurant_views", json_schema_extra={
        "label": "Fried-chicken restaurant reference", "hint": "Three views of one restaurant, or a custom reference filename."
    })
    park_reference: str = Field(default="builtin:wetland_park_views", json_schema_extra={
        "label": "Wetland park reference", "hint": "Three views of one wetland park. Use builtin:park for the original single view, or a custom reference filename."
    })
    character_prompt: str = Field(default=DEFAULT_CHARACTER_PROMPT, max_length=1500, json_schema_extra={
        "label": "Selfie identity prompt", "hint": "Used only when selfie mode is selected. MaiBot's current persona remains authoritative.", "x-widget": "textarea"
    })
    scene_prompt: str = Field(default=DEFAULT_SCENE_PROMPT, max_length=1500, json_schema_extra={
        "label": "First-person scene prompt", "hint": "Ordinary life photos are taken from the bot's point of view, with the bot out of frame.", "x-widget": "textarea"
    })
    cooldown_minutes: int = Field(default=120, ge=10, le=1440, json_schema_extra={
        "label": "Minimum minutes between images", "hint": "Global cooldown across all chat streams, counted from the moment an API request is accepted."
    })
    max_images_per_day: int = Field(default=3, ge=1, le=50, json_schema_extra={
        "label": "Maximum images per day", "hint": "Global daily cap on attempted image generations in the plugin timezone. Failed requests may still cost money."
    })


class LifePhotoModule:
    name = "life_photo"
    state_keys = frozenset({"life_photo_usage"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.usage: dict[str, Any] = {}
        self._jobs: set[asyncio.Task[None]] = set()

    def load_state(self, data: dict[str, Any]) -> None:
        value = data.get("life_photo_usage", {})
        if not isinstance(value, dict):
            raise TypeError("生活照片用量格式无效")
        self.usage = value

    def dump_state(self, payload: dict[str, Any]) -> None:
        if self.usage:
            payload["life_photo_usage"] = self.usage

    def on_config_update(self) -> None:
        pass

    async def tick(self, now: datetime) -> None:
        del now

    async def stop(self) -> None:
        jobs = list(self._jobs)
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)

    def _reference_path(self, choice: str) -> Path | None:
        choice = choice.strip()
        if not choice:
            return None
        if choice.startswith("builtin:"):
            return BUILTIN_REFERENCES.get(choice.removeprefix("builtin:"))
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}\.(?:png|jpg|jpeg|webp)", choice, re.IGNORECASE):
            raise ValueError("参考图只能是参考图目录内的 PNG、JPEG 或 WebP 文件名")
        return Path(self.plugin.ctx.paths.data_dir) / "life-photo-references" / choice

    def _reference_data(self, choice: str) -> str | None:
        path = self._reference_path(choice)
        if path is None:
            return None
        if not path.is_file():
            raise ValueError(f"参考图不存在：{choice}")
        if path.stat().st_size > 8_000_000:
            raise ValueError(f"参考图超过 8 MB：{choice}")
        with Image.open(path) as image:
            image.verify()
        suffix = path.suffix.lower()
        mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/webp" if suffix == ".webp" else "image/png"
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"

    @staticmethod
    def _location(activity: str) -> str:
        activity = activity.casefold()
        if any(word in activity for word in ("公园", "湿地", "野餐", "park", "wetland", "hike")):
            return "park"
        if any(word in activity for word in ("kfc", "肯德基", "疯狂星期四", "炸鸡", "薯条", "fried chicken")):
            return "restaurant"
        if any(word in activity for word in ("买菜", "买晚饭食材", "杂货店", "便利店", "超市", "出门散", "街道", "散步", "grocery", "street", "walk")):
            return "neighborhood"
        if any(word in activity for word in ("睡觉", "上床", "床铺", "叠被子", "熄灯", "整理小窝", "收玩偶", "卧室", "bedroom", "sleep", "bedtime")) and not any(word in activity for word in ("早餐", "午饭", "晚饭", "烤吐司", "热饮")):
            return "bedroom"
        if any(word in activity for word in ("早餐", "午饭", "午餐", "晚饭", "烤吐司", "煎蛋", "热粥", "煮", "做一碗", "饼干", "烤箱", "餐具", "厨房", "cook", "breakfast", "lunch", "dinner", "bake")):
            return "kitchen"
        if any(word in activity for word in ("拼豆", "乐高", "拼图", "画画", "手工", "照片相册", "彩笔", "游戏", "积木", "craft", "lego", "puzzle", "game")):
            return "hobby"
        if any(word in activity for word in ("洗漱", "刷牙", "洗脸", "洗澡", "bathroom", "wash", "shower")):
            return "bathroom"
        if any(word in activity for word in ("窗边", "开窗", "植物", "浇水", "晚霞", "阳台", "balcony", "plant", "window")):
            return "balcony"
        return "home"

    def _prompt_and_refs(self, activity: str, detail: str, mode: str = "scene", *, now: datetime | None = None) -> tuple[str, list[str]]:
        settings = self.plugin.config.life_photo
        if mode not in {"scene", "selfie"}:
            raise ValueError("照片模式只能是 scene 或 selfie")
        refs: list[str] = []
        if mode == "selfie":
            character_ref = self._reference_data(settings.character_reference)
            if not character_ref:
                raise ValueError("自拍需先配置角色参考图")
            refs.append(character_ref)
        location = self._location(activity)
        choice = getattr(settings, REFERENCE_FIELDS[location])
        local_time = (now or datetime.now(UTC)).astimezone(ZoneInfo(self.plugin.config.plugin.timezone))
        period_key, period_label = self.plugin.config.virtual_life.period_at(local_time)
        lighting = LIGHTING_PERIODS[period_key]
        builtin = choice.removeprefix("builtin:") if choice.startswith("builtin:") else ""
        if builtin in TIMED_SCENE_NAMES:
            choice = f"builtin:{builtin}_{lighting}"
        location_ref = self._reference_data(choice)
        if location_ref:
            refs.append(location_ref)
        anchor = SCENE_ANCHORS.get(location, "")
        composition = (
            f"{settings.character_prompt.strip()}\n{SELFIE_PROMPT}\n"
            "Image 1 is the photographer's identity reference. Image 2, if present, shows the location. "
            if mode == "selfie" else
            f"{settings.scene_prompt.strip()}\n"
            "The photographer is BEHIND the camera and must not appear anywhere in the frame. "
            "Image 1, if present, is a location reference ONLY; it does not depict the photographer. "
        )
        prompt = (
            f"{composition}"
            f"Current activity: {activity.strip()[:180]}\n"
            f"Current local time: {local_time.strftime('%H:%M')} ({period_label}); lighting: {LIGHTING_DESCRIPTIONS[lighting]}. "
            "Use this time of day for the scene, sky, illumination and shadows.\n"
            f"Optional moment detail: {detail.strip()[:160]}\n"
            f"Location continuity: {anchor}\n"
            "Any location reference sheet shows camera angles of ONE place and must never appear as panels in the result. "
            "The current MaiBot persona takes priority; do not add facts or identity traits absent from it."
        )
        return prompt, refs

    async def _can_override_cooldown(self, stream_id: str, user_id: str) -> bool:
        """Require a current verified human speaker and the configured admin account."""
        role = self.plugin.role_recognition
        account = role.peek_planner_speaker(stream_id)
        if not account or account not in await role.admin_accounts(force_refresh=True):
            return False
        response = await self.plugin.ctx.chat.get_all_streams(platform="all_platforms")
        streams = response if isinstance(response, list) else response.get("streams") if isinstance(response, dict) and response.get("success") is not False else None
        if not isinstance(streams, list):
            return False
        matches = [row for row in streams if isinstance(row, dict) and str(row.get("stream_id") or row.get("session_id") or "") == stream_id]
        if len(matches) != 1:
            return False
        stream = matches[0]
        platform = str(stream.get("platform") or "").strip().lower()
        kind = str(stream.get("chat_type") or "").strip().lower()
        if not platform or not account.startswith(platform + ":"):
            return False
        if kind == "private":
            if not user_id or str(stream.get("user_id") or "").strip() != user_id or account != f"{platform}:{user_id}":
                return False
        elif kind == "group":
            if user_id and account != f"{platform}:{user_id}":
                return False
        else:
            return False
        return role.consume_planner_speaker(stream_id) == account

    async def share(self, detail: str = "", activity: str = "", mode: str = "scene", ignore_cooldown: bool = False, **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip():
            return {"success": False, "error": "无法核验当前聊天流"}
        settings = self.plugin.config.life_photo
        if not self.plugin.config.plugin.enabled or not settings.enabled:
            return {"success": False, "error": "生活照片模块未开启"}
        if settings.provider not in {"qwen", "minimax"}:
            return {"success": False, "error": "未知的生图服务商"}
        active_key = settings.api_key if settings.provider == "qwen" else settings.minimax_api_key
        if not active_key.strip():
            return {"success": False, "error": "尚未配置生图 API Key"}
        if settings.provider == "qwen" and (settings.region not in ENDPOINTS or settings.model != "qwen-image-2.1-turbo"):
            return {"success": False, "error": "当前仅支持指定地区的 Qwen Image 2.1 Turbo"}
        if settings.provider == "minimax" and settings.minimax_region not in MINIMAX_ENDPOINTS:
            return {"success": False, "error": "未知的 MiniMax API 地区"}
        scene = self.plugin.virtual_life.scene_at(datetime.now(UTC))
        if scene:
            activity = str(scene["activity"])
        else:
            pending = next((row.get("pending") for row in self.plugin.proactive.continuity.values()
                            if isinstance(row.get("pending"), dict) and row["pending"].get("stream_id") == stream_id), None)
            if not pending or float(pending.get("until", 0)) < datetime.now(UTC).timestamp():
                return {"success": False, "error": "当前没有可分享的模拟生活或主动发言场景"}
            activity = activity.strip()
        if not activity or len(activity) > 200 or len(detail) > 200:
            return {"success": False, "error": "活动或照片细节长度无效"}
        if any(word in activity.casefold() for word in ("睡觉", "安稳睡", "熄灯睡", "asleep", "sleeping")):
            return {"success": False, "error": "当前活动是睡觉，不能在睡着时拍生活照片"}
        now = datetime.now(UTC)
        local_day = now.astimezone(ZoneInfo(self.plugin.config.plugin.timezone)).date().isoformat()
        async with self.plugin._lock:
            count = int(self.usage.get("count", 0)) if self.usage.get("day") == local_day else 0
            last = float(self.usage.get("last_attempt_at", 0))
            wait = settings.cooldown_minutes * 60 - (now.timestamp() - last)
            if count >= settings.max_images_per_day or wait > 0:
                override = False
                if ignore_cooldown:
                    try:
                        override = await self._can_override_cooldown(stream_id, str(kwargs.get("user_id") or "").strip())
                    except Exception:
                        LOG.warning("无法核验照片冷却豁免请求者", exc_info=True)
                if not override:
                    if count >= settings.max_images_per_day:
                        return {"success": False, "error": "今天的生活照片张数已达上限；管理员要求拍照时可跳过限制"}
                    return {"success": False, "error": f"生活照片还在冷却，约 {int(wait // 60) + 1} 分钟后可再次生成；管理员可明确要求忽略冷却"}
            try:
                prompt, refs = self._prompt_and_refs(activity, detail, mode, now=now)
            except (ValueError, OSError, UnidentifiedImageError) as exc:
                return {"success": False, "error": str(exc)}
            if settings.provider == "minimax" and len(prompt) > 1500:
                return {"success": False, "error": "MiniMax 提示词最多 1500 字符，请缩短角色或场景提示词"}
            self.usage = {"day": local_day, "count": count + 1, "last_attempt_at": now.timestamp(), "status": "queued", "stream_id": stream_id}
            self.plugin._save_state()
        job = asyncio.create_task(self._produce(stream_id, prompt, refs, mode), name="secretary-life-photo")
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)
        return {"success": True, "content": "已开始生成这张生活照片。图片发送是异步的，请先不要说已经发出；生成成功后会发到当前聊天流。"}

    async def _produce(self, stream_id: str, prompt: str, refs: list[str], mode: str) -> None:
        try:
            settings = self.plugin.config.life_photo
            async with httpx.AsyncClient(timeout=httpx.Timeout(240.0), follow_redirects=False) as client:
                raw = await self._request_image(client, prompt, refs, settings, mode)
            with Image.open(io.BytesIO(raw)) as image:
                if image.width * image.height > 12_000_000:
                    raise ValueError("生成图片尺寸过大")
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
            if not self.plugin.config.plugin.enabled or not self.plugin.config.life_photo.enabled:
                self.usage["status"] = "cancelled"
                return
            send_result = await self.plugin.ctx.send.image(base64.b64encode(output.getvalue()).decode("ascii"), stream_id, return_details=True)
            sent = send_result.get("sent") if isinstance(send_result, dict) else send_result is True
            self.usage["status"] = "sent" if sent else "send_unknown"
        except asyncio.CancelledError:
            self.usage["status"] = "cancelled"
            raise
        except Exception as exc:
            self.usage["status"] = "failed"
            self.usage["error"] = str(exc)[:300]
            LOG.exception("生活照片生成或发送失败")
        finally:
            self.plugin._save_state()

    async def _request_image(self, client: httpx.AsyncClient, prompt: str, refs: list[str], settings: LifePhotoSettings, mode: str = "scene") -> bytes:
        if settings.provider == "minimax":
            payload: dict[str, Any] = {
                "model": "image-01", "prompt": prompt, "aspect_ratio": "2:3",
                "response_format": "base64", "n": 1, "prompt_optimizer": False,
            }
            if mode == "selfie":
                payload["subject_reference"] = [{"type": "character", "image_file": refs[0]}]
            response = await client.post(
                MINIMAX_ENDPOINTS[settings.minimax_region],
                headers={"Authorization": f"Bearer {settings.minimax_api_key.strip()}"},
                json=payload,
            )
            response.raise_for_status()
            result = response.json()
            base_resp = result.get("base_resp") or {}
            if base_resp.get("status_code") != 0:
                raise ValueError(f"MiniMax 生图失败：{str(base_resp.get('status_msg') or '未知错误')[:160]}")
            images = (result.get("data") or {}).get("image_base64") or []
            if not images or not isinstance(images[0], str) or len(images[0]) > 16_000_000:
                raise ValueError("MiniMax 未返回有效图片")
            raw = base64.b64decode(images[0], validate=True)
            if len(raw) > 12_000_000:
                raise ValueError("生成图片过大")
            return raw
        content = [{"image": ref} for ref in refs]
        content.append({"text": prompt})
        response = await client.post(
            ENDPOINTS[settings.region],
            headers={"Authorization": f"Bearer {settings.api_key.strip()}"},
            json={
                "model": settings.model,
                "input": {"messages": [{"role": "user", "content": content}]},
                "parameters": {"n": 1, "size": "1024*1536", "prompt_extend": False},
            },
        )
        if response.is_error:
            try:
                error = response.json()
            except ValueError:
                response.raise_for_status()
            raise ValueError(f"千问生图失败：{str(error.get('code') or response.status_code)[:50]} "
                             f"{str(error.get('message') or '')[:180]}")
        result = response.json()
        choices = (result.get("output") or {}).get("choices") or []
        image_content = ((choices[0].get("message") or {}).get("content") or []) if choices else []
        image_url = next((item.get("image") for item in image_content if isinstance(item, dict) and item.get("image")), "")
        image_url = str(image_url)
        parsed = urlparse(image_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host.endswith((".aliyuncs.com", ".alicdn.com")) or parsed.username or parsed.password:
            raise ValueError("生图服务返回了不可信的图片地址")
        chunks: list[bytes] = []
        total = 0
        async with client.stream("GET", image_url) as image_response:
            image_response.raise_for_status()
            async for chunk in image_response.aiter_bytes():
                total += len(chunk)
                if total > 12_000_000:
                    raise ValueError("生成图片过大")
                chunks.append(chunk)
        return b"".join(chunks)
