"""One shared mood, influenced by the shared simulated-life activity."""

from __future__ import annotations

import hashlib
import json
import random
import re
from datetime import datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from maibot_sdk import Field, PluginConfigBase
from pydantic import model_validator

MOODS: dict[str, tuple[str, str]] = {
    "calm": ("平静", "正面"),
    "happy": ("开心", "正面"),
    "satisfied": ("满足", "正面"),
    "excited": ("激动", "正面"),
    "wronged": ("委屈", "负面"),
    "sad": ("伤心", "负面"),
    "irritable": ("烦躁", "负面"),
    "angry": ("愤怒", "负面"),
    "grief": ("悲伤", "负面"),
}
DEFAULT_WEIGHTS = {
    "calm": 25, "happy": 25, "satisfied": 15, "excited": 10,
    "wronged": 8, "sad": 6, "irritable": 6, "angry": 3, "grief": 2,
}
_ACTIVITY_BIASES: tuple[tuple[re.Pattern[str], dict[str, float]], ...] = (
    (re.compile(r"吃|餐|饭|零食|饼干|烤箱|KFC|炸鸡", re.IGNORECASE),
     {"happy": 1.5, "satisfied": 2.0, "excited": 1.3}),
    (re.compile(r"游戏|动漫|电视|电影|乐高|拼豆|拼图|画画|手工"),
     {"happy": 1.4, "excited": 1.6, "irritable": 1.2}),
    (re.compile(r"清理|打扫|收拾|整理|洗餐具|家务"),
     {"satisfied": 1.8, "irritable": 1.5, "wronged": 1.2}),
    (re.compile(r"散步|公园|晚霞|吹风|植物|窗边"),
     {"calm": 2.0, "satisfied": 1.3, "sad": 1.2}),
    (re.compile(r"睡觉|洗漱|上床|熄灯|休息"),
     {"calm": 3.0, "excited": 0.3, "angry": 0.4}),
)
_RELATION_STYLE = {
    "主人": {
        "正面": "可以明显分享喜悦、自然撒娇或邀请对方一起聊；仍以 MaiBot 原有人设为准。",
        "负面": "可以坦诚说出感受和生活中的小波折，适度寻求安慰；不要要挟、迁怒或把照顾情绪变成对方的责任。",
    },
    "熟人": {
        "正面": "亲切地分享一两处具体细节，情绪明显但有分寸。",
        "负面": "可以简短倾诉或说自己有点不顺，给对方回应和转移话题的空间。",
    },
    "陌生人": {
        "正面": "保持友好，让好心情轻微体现在语气里，不主动过度亲近。",
        "负面": "保持礼貌克制；仅在相关时略提心情，不宣泄、不迁怒、不要求安慰。",
    },
}


class MoodSettings(PluginConfigBase):
    """Editable base percentages; life activity and continuity bias the draw."""

    __ui_label__: ClassVar[str] = "心情模块"

    enabled: bool = Field(
        default=False,
        json_schema_extra={"label": "启用心情模块", "hint": "所有聊天流共享当前心情；普通聊天也会继承，表现强弱由角色识别决定。"},
    )
    calm: int = Field(default=25, ge=0, le=100, json_schema_extra={"label": "平静 · 基础概率（%）"})
    happy: int = Field(default=25, ge=0, le=100, json_schema_extra={"label": "开心 · 基础概率（%）"})
    satisfied: int = Field(default=15, ge=0, le=100, json_schema_extra={"label": "满足 · 基础概率（%）"})
    excited: int = Field(default=10, ge=0, le=100, json_schema_extra={"label": "激动 · 基础概率（%）"})
    wronged: int = Field(default=8, ge=0, le=100, json_schema_extra={"label": "委屈 · 基础概率（%）"})
    sad: int = Field(default=6, ge=0, le=100, json_schema_extra={"label": "伤心 · 基础概率（%）"})
    irritable: int = Field(default=6, ge=0, le=100, json_schema_extra={"label": "烦躁 · 基础概率（%）"})
    angry: int = Field(default=3, ge=0, le=100, json_schema_extra={"label": "愤怒 · 基础概率（%）"})
    grief: int = Field(default=2, ge=0, le=100, json_schema_extra={"label": "悲伤 · 基础概率（%）"})

    @model_validator(mode="after")
    def validate_probabilities(self) -> MoodSettings:
        if sum(getattr(self, key) for key in MOODS) != 100:
            raise ValueError("心情基础概率总和必须为 100%；模拟生活会进一步调整实际抽取概率")
        return self

    def weights(self) -> dict[str, float]:
        return {key: float(getattr(self, key)) for key in MOODS}


class MoodModule:
    name = "mood"
    state_keys = frozenset({"mood_state"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.state: dict[str, Any] = {}
        self.rng = random.Random()

    def load_state(self, data: dict[str, Any]) -> None:
        raw = data.get("mood_state", {})
        self.state = raw if isinstance(raw, dict) and (
            isinstance(raw.get("key"), str)
            and isinstance(raw.get("signature"), str)
            and raw.get("mood") in MOODS
        ) else {}

    def dump_state(self, payload: dict[str, Any]) -> None:
        if self.state:
            payload["mood_state"] = self.state

    def on_config_update(self) -> None:
        pass  # The config signature invalidates the current draw on the next read.

    async def tick(self, now: datetime) -> None:
        self.current(now)

    def effective_weights(self, activity: str, period_key: str, previous: str = "") -> dict[str, float]:
        weights = self.plugin.config.mood.weights()
        for pattern, biases in _ACTIVITY_BIASES:
            if pattern.search(activity):
                for key, multiplier in biases.items():
                    weights[key] *= multiplier
        if period_key in {"late_night", "predawn"}:
            weights["calm"] *= 1.8
            weights["excited"] *= 0.5
        if previous in MOODS:
            weights[previous] *= 1.5
        return weights

    def current(self, now: datetime) -> dict[str, Any] | None:
        settings = self.plugin.config.mood
        if not settings.enabled:
            return None
        local_time = now.astimezone(ZoneInfo(self.plugin.config.plugin.timezone))
        scene = self.plugin.virtual_life.scene_at(now)
        period_key, period = self.plugin.config.virtual_life.period_at(local_time)
        activity = str(scene.get("activity") or "") if scene else ""
        key = (
            f"{scene['key']}:{scene['signature']}" if scene
            else f"no-life:{local_time.date().isoformat()}:{period_key}"
        )
        signature = hashlib.sha256(settings.model_dump_json().encode("utf-8")).hexdigest()[:16]
        if self.state.get("key") == key and self.state.get("signature") == signature:
            return self.state
        weights = self.effective_weights(activity, period_key, str(self.state.get("mood") or ""))
        mood = self.rng.choices(list(weights), weights=list(weights.values()), k=1)[0]
        self.state = {
            "key": key, "signature": signature, "mood": mood,
            "period": str(scene.get("period") or period) if scene else period,
            "activity": activity, "selected_at": local_time.isoformat(timespec="seconds"),
        }
        self.plugin._save_state()
        return self.state

    def prompt_for(self, level: str, *, now: datetime | None = None) -> str:
        state = self.current(now or datetime.now().astimezone())
        if state is None:
            return ""
        label, polarity = MOODS[state["mood"]]
        style = _RELATION_STYLE.get(level, _RELATION_STYLE["陌生人"])[polarity]
        activity = str(state.get("activity") or "")[:200]
        source = (
            f"当前所有聊天流共享的模拟生活活动是 {json.dumps(activity, ensure_ascii=False)}；"
            if activity else "当前未启用模拟生活活动；"
        )
        return (
            f"【麦麦小秘书·心情】{source}当前心情为{label}（{polarity}）。"
            "心情是短期背景，不覆盖 MaiBot 原有人设、当前用户的需要或真实聊天内容。"
            "情绪由当前生活活动与上次心情共同影响；只有相关时才自然提及活动，不要每轮报告心情。"
            "即使心情正面，遇到对方的难过或严肃问题也应先认真回应。"
            "若当前活动是睡觉或休息，收到消息时不要声称自己一边睡着一边回复；可按人设说刚醒来或准备休息。"
            "负面心情不得编造重大创伤、死亡等经历，也不得攻击用户。"
            f"当前关系级别为{level if level in _RELATION_STYLE else '陌生人'}；{style}"
        )
