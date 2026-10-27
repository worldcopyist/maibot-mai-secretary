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
ENDPOINTS = {
    "beijing": "https://dashscope.aliyuncs.com/compatible-mode/v1/images/generations",
    "singapore": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/images/generations",
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
    "The first reference image is the character identity reference. Preserve the same face, "
    "hair, distinctive accessories, color palette and art style. Use a medium or closer shot "
    "so these features stay recognizable. Do not invent a different person. "
    "Keep the subject's apparent age and identity consistent with that reference and the bot persona."
)
DEFAULT_SCENE_PROMPT = (
    "Make one casual illustrated snapshot of the character naturally doing the stated current activity. "
    "If a location reference sheet is provided, choose one physically plausible camera view of that "
    "same place and preserve its recognizable layout and furnishings. Render ONE continuous scene, "
    "never a triptych, collage, split panel or contact sheet. Natural light, candid composition, "
    "no captions, text, logos, watermark or extra people."
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
        "label": "Image model", "hint": "Qwen Image 2.1 Turbo accepts character and location references."
    })
    minimax_api_key: str = Field(default="", json_schema_extra={
        "label": "MiniMax API key", "hint": "A standard image-generation API key for the selected MiniMax region. Keep it in the installed plugin config.", "x-widget": "password"
    })
    minimax_region: str = Field(default="china", json_schema_extra={
        "label": "MiniMax API region", "hint": "Use china for api.minimax.cn or global for api.minimax.io; the key must match the region.", "choices": ["china", "global"]
    })
    character_reference: str = Field(default="builtin:icon", json_schema_extra={
        "label": "Character reference", "hint": "builtin:icon uses the plugin avatar. To replace it, put a PNG/JPEG/WebP file in plugin data/life-photo-references and enter its filename."
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
        "label": "Character consistency prompt", "hint": "Describe the bot's appearance generically or customize it for your own character. MaiBot's persona remains authoritative.", "x-widget": "textarea"
    })
    scene_prompt: str = Field(default=DEFAULT_SCENE_PROMPT, max_length=1500, json_schema_extra={
        "label": "Scene consistency prompt", "hint": "Image-only instructions. The activity comes from the current simulated-life scene.", "x-widget": "textarea"
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

    def _prompt_and_refs(self, activity: str, detail: str) -> tuple[str, list[str]]:
        settings = self.plugin.config.life_photo
        refs = [self._reference_data(settings.character_reference)]
        if not refs[0]:
            raise ValueError("需先配置角色参考图")
        location = self._location(activity)
        choice = getattr(settings, REFERENCE_FIELDS[location])
        location_ref = self._reference_data(choice)
        if location_ref:
            refs.append(location_ref)
        anchor = SCENE_ANCHORS.get(location, "")
        prompt = (
            f"{settings.character_prompt.strip()}\n{settings.scene_prompt.strip()}\n"
            f"Current activity: {activity.strip()[:180]}\n"
            f"Optional moment detail: {detail.strip()[:160]}\n"
            f"Location continuity: {anchor}\n"
            "Image 1 is the character reference. Image 2, if present, is only the location reference sheet; "
            "its separate panels show camera angles of ONE place and must never appear as panels in the result. "
            "The current MaiBot persona takes priority; do not add facts or identity traits absent from it."
        )
        return prompt, [ref for ref in refs if ref]

    async def share(self, detail: str = "", activity: str = "", **kwargs: Any) -> dict[str, Any]:
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
        now = datetime.now(UTC)
        local_day = now.astimezone(ZoneInfo(self.plugin.config.plugin.timezone)).date().isoformat()
        async with self.plugin._lock:
            count = int(self.usage.get("count", 0)) if self.usage.get("day") == local_day else 0
            last = float(self.usage.get("last_attempt_at", 0))
            wait = settings.cooldown_minutes * 60 - (now.timestamp() - last)
            if count >= settings.max_images_per_day:
                return {"success": False, "error": "今天的生活照片张数已达上限"}
            if wait > 0:
                return {"success": False, "error": f"生活照片还在冷却，约 {int(wait // 60) + 1} 分钟后可再次生成"}
            try:
                prompt, refs = self._prompt_and_refs(activity, detail)
            except (ValueError, OSError, UnidentifiedImageError) as exc:
                return {"success": False, "error": str(exc)}
            if settings.provider == "minimax" and len(prompt) > 1500:
                return {"success": False, "error": "MiniMax 提示词最多 1500 字符，请缩短角色或场景提示词"}
            self.usage = {"day": local_day, "count": count + 1, "last_attempt_at": now.timestamp(), "status": "queued", "stream_id": stream_id}
            self.plugin._save_state()
        job = asyncio.create_task(self._produce(stream_id, prompt, refs), name="secretary-life-photo")
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)
        return {"success": True, "content": "已开始生成这张生活照片。图片发送是异步的，请先不要说已经发出；生成成功后会发到当前聊天流。"}

    async def _produce(self, stream_id: str, prompt: str, refs: list[str]) -> None:
        try:
            settings = self.plugin.config.life_photo
            async with httpx.AsyncClient(timeout=httpx.Timeout(240.0), follow_redirects=False) as client:
                raw = await self._request_image(client, prompt, refs, settings)
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

    async def _request_image(self, client: httpx.AsyncClient, prompt: str, refs: list[str], settings: LifePhotoSettings) -> bytes:
        if settings.provider == "minimax":
            response = await client.post(
                MINIMAX_ENDPOINTS[settings.minimax_region],
                headers={"Authorization": f"Bearer {settings.minimax_api_key.strip()}"},
                json={
                    "model": "image-01", "prompt": prompt, "subject_reference": [{"type": "character", "image_file": refs[0]}],
                    "aspect_ratio": "2:3", "response_format": "base64", "n": 1, "prompt_optimizer": False,
                },
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
        response = await client.post(
            ENDPOINTS[settings.region],
            headers={"Authorization": f"Bearer {settings.api_key.strip()}"},
            json={"model": settings.model, "prompt": prompt, "image": refs, "n": 1, "size": "1024x1536"},
        )
        response.raise_for_status()
        result = response.json()
        image_url = str((result.get("data") or [{}])[0].get("url") or "")
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
