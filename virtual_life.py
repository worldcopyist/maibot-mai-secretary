"""Time-bound random activities and editable weekly fixed activities."""

from __future__ import annotations

import random
import re
from datetime import datetime
from typing import ClassVar, Literal

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator, model_validator

DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
DayLabel = Literal["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
PeriodLabel = Literal["早晨", "上午", "中午", "下午", "傍晚", "夜晚", "深夜", "凌晨"]
PERIODS = (
    ("morning", "早晨", "07:00–08:59", 420),
    ("late_morning", "上午", "09:00–11:29", 540),
    ("noon", "中午", "11:30–13:29", 690),
    ("afternoon", "下午", "13:30–17:29", 810),
    ("dusk", "傍晚", "17:30–19:29", 1050),
    ("night", "夜晚", "19:30–22:29", 1170),
    ("late_night", "深夜", "22:30–23:59", 1350),
    ("predawn", "凌晨", "00:00–06:59", 0),
)
SLOT_NAMES = frozenset(f"{day}_{period}" for day in DAY_NAMES for period, *_ in PERIODS)
SLOT_LABELS = {
    f"{DAY_LABELS[index]}{label}": f"{day}_{period}"
    for index, day in enumerate(DAY_NAMES)
    for period, label, *_ in PERIODS
}
DEFAULT_LEGACY_FIXED_SLOTS = "wednesday_afternoon,thursday_afternoon,friday_dusk"
DEFAULT_FIXED_TEXT = {
    "wednesday_afternoon": "固定清理蓝天小窝：擦桌子、收玩偶、整理床铺和地板，把小窝收拾得软乎乎又整洁。",
    "thursday_afternoon": "固定过疯狂星期四：去 KFC 爽吃喜欢的炸鸡和薯条，开心地挑今天最好吃的那一口。",
    "friday_dusk": "固定去湿地公园散步吹风，看水面、芦苇和傍晚的天空。",
}
DEFAULT_CHOICES: dict[str, tuple[str, ...]] = {
    "morning": (
        "07:00 起床洗漱，烤吐司和煎蛋当早餐。",
        "起床后开窗透气，做一碗酸奶水果当早餐。",
        "洗漱后煮点热粥，慢慢吃早餐、听早晨的音乐。",
        "起床叠被子，泡一杯热饮，配面包吃早餐。",
    ),
    "late_morning": (
        "给窗边植物浇水，顺手整理小窝。",
        "整理照片相册，挑出几张喜欢的照片。",
        "坐在桌边拼乐高，琢磨下一块积木放哪里。",
        "拿出拼豆板，慢慢拼一幅小图案。",
        "听歌并收拾书架和零食架。",
        "看一集轻松的动漫，边看边记住喜欢的情节。",
    ),
    "noon": (
        "做一碗鸡蛋面当午饭，吃完休息片刻。",
        "煮米饭配一份家常菜，慢慢吃午饭。",
        "准备简单的午餐，饭后在沙发上小憩。",
        "吃完热乎的午饭，洗好餐具再晒晒太阳。",
    ),
    "afternoon": (
        "玩一会儿喜欢的游戏，刚好碰上有趣的关卡。",
        "在桌边拼乐高，试着搭一座小房子。",
        "挑几种颜色做拼豆，等图案一点点成形。",
        "窝在沙发上看动漫，猜下一集会发生什么。",
        "追一集电视剧，记住今天最有趣的剧情。",
        "画画或做小手工，桌上摆满彩笔和材料。",
        "拼拼图，找那块一直没找到的边角。",
        "试做小饼干，等烤箱里飘出香味。",
    ),
    "dusk": (
        "看看晚霞，给自己准备晚饭。",
        "出门散一小会儿步，顺路买晚饭食材。",
        "做一份热乎的晚饭，吃完收拾餐具。",
        "在窗边吹吹傍晚的风，再回屋吃晚饭。",
    ),
    "night": (
        "裹着毯子看动漫，想起一段喜欢的剧情。",
        "追一集电视剧，边看边吃点小零食。",
        "玩一会儿休闲游戏，和喜欢的角色一起冒险。",
        "在桌边拼一会儿乐高，慢慢搭出喜欢的造型。",
        "做一点拼豆手工，试着搭配几种颜色。",
        "抱着抱枕看电影，喝一杯热饮。",
    ),
    "late_night": (
        "关掉游戏和屏幕，洗漱、整理小窝，准备 00:00 睡觉。",
        "收好拼豆和积木，洗漱上床，00:00 准时睡觉。",
        "听一点轻音乐、整理床铺，00:00 熄灯睡觉。",
    ),
    "predawn": ("00:00–07:00 安稳睡觉，早上 07:00 再起床。",),
}


def _legacy_slot_keys(value: str) -> list[str]:
    if not isinstance(value, str):
        raise TypeError("旧版固定时段列表格式无效")
    slots = list(dict.fromkeys(
        SLOT_LABELS.get(clean, clean)
        for item in re.split(r"[,，;；\n]+", value)
        if (clean := re.sub(r"[\s·•]", "", item).lower())
    ))
    invalid = [slot for slot in slots if slot not in SLOT_NAMES]
    if invalid:
        raise ValueError(f"未知的旧版固定时段：{', '.join(invalid)}")
    return slots


class FixedActivity(PluginConfigBase):
    """One fixed weekly override rendered as two selects and a text input."""

    day: DayLabel = Field(default="周一", json_schema_extra={"label": "星期"})
    period: PeriodLabel = Field(default="下午", json_schema_extra={"label": "时间段"})
    activity: str = Field(
        default="",
        max_length=200,
        json_schema_extra={"label": "固定做什么", "placeholder": "填写麦麦在这个时段做的事"},
    )

    @field_validator("activity")
    @classmethod
    def normalize_activity(cls, value: str) -> str:
        activity = " ".join(value.split())
        if not activity or len(activity) > 200:
            raise ValueError("固定活动须为 1–200 个字符")
        return activity


def _default_fixed_activities() -> list[FixedActivity]:
    return [
        FixedActivity(day="周三", period="下午", activity=DEFAULT_FIXED_TEXT["wednesday_afternoon"]),
        FixedActivity(day="周四", period="下午", activity=DEFAULT_FIXED_TEXT["thursday_afternoon"]),
        FixedActivity(day="周五", period="傍晚", activity=DEFAULT_FIXED_TEXT["friday_dusk"]),
    ]


class VirtualLifeSettings(PluginConfigBase):
    """Editable period pools with optional day-and-period fixed overrides."""

    __ui_label__: ClassVar[str] = "模拟生活"

    enabled: bool = Field(default=False, json_schema_extra={"label": "主动发言时启用模拟生活", "hint": "按插件时区读取当前星期和时段；只影响随机主动发言。"})
    morning_choices: str = Field(default="\n".join(DEFAULT_CHOICES["morning"]), max_length=4000, json_schema_extra={"label": "早晨随机活动 · 07:00–08:59", "hint": "每行一个可能正在做的事；仅在早晨随机选一行。", "x-widget": "textarea", "rows": 5})
    late_morning_choices: str = Field(default="\n".join(DEFAULT_CHOICES["late_morning"]), max_length=4000, json_schema_extra={"label": "上午随机活动 · 09:00–11:29", "hint": "每行一个可能正在做的事；仅在上午随机选一行。", "x-widget": "textarea", "rows": 7})
    noon_choices: str = Field(default="\n".join(DEFAULT_CHOICES["noon"]), max_length=4000, json_schema_extra={"label": "中午随机活动 · 11:30–13:29", "hint": "每行一个可能正在做的事；仅在中午随机选一行。", "x-widget": "textarea", "rows": 5})
    afternoon_choices: str = Field(default="\n".join(DEFAULT_CHOICES["afternoon"]), max_length=4000, json_schema_extra={"label": "下午随机活动 · 13:30–17:29", "hint": "每行一个可能正在做的事；仅在下午随机选一行。", "x-widget": "textarea", "rows": 9})
    dusk_choices: str = Field(default="\n".join(DEFAULT_CHOICES["dusk"]), max_length=4000, json_schema_extra={"label": "傍晚随机活动 · 17:30–19:29", "hint": "每行一个可能正在做的事；仅在傍晚随机选一行。", "x-widget": "textarea", "rows": 5})
    night_choices: str = Field(default="\n".join(DEFAULT_CHOICES["night"]), max_length=4000, json_schema_extra={"label": "夜晚随机活动 · 19:30–22:29", "hint": "每行一个可能正在做的事；仅在夜晚随机选一行。", "x-widget": "textarea", "rows": 7})
    late_night_choices: str = Field(default="\n".join(DEFAULT_CHOICES["late_night"]), max_length=4000, json_schema_extra={"label": "深夜随机活动 · 22:30–23:59", "hint": "每行一个睡前活动，仍保持 00:00 睡觉。", "x-widget": "textarea", "rows": 4})
    predawn_choices: str = Field(default="\n".join(DEFAULT_CHOICES["predawn"]), max_length=4000, json_schema_extra={"label": "凌晨随机活动 · 00:00–06:59", "hint": "默认睡觉到 07:00；若主动发言窗口覆盖凌晨，也会按这里的内容生成背景。", "x-widget": "textarea", "rows": 3})
    fixed_activities: list[FixedActivity] = Field(
        default_factory=_default_fixed_activities,
        max_length=56,
        json_schema_extra={
            "label": "每周固定活动",
            "hint": "点击添加，分别选择星期和时间段，再填写活动；固定活动优先于该时段的随机候选。可删除或拖动排序。",
            "max_items": 56,
        },
    )

    @model_validator(mode="before")
    @classmethod
    def migrate_legacy_week(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        if "fixed_slots" not in value and not SLOT_NAMES.intersection(value):
            return value
        current = value.get("fixed_activities")
        defaults = [item.model_dump() for item in _default_fixed_activities()]
        # The SDK fills missing fields before validation. Its inserted default list
        # must not hide the old fixed-slot values during an upgrade.
        if current is not None and current != defaults:
            return value
        slots = _legacy_slot_keys(value.get("fixed_slots", DEFAULT_LEGACY_FIXED_SLOTS))
        rules: list[dict[str, str]] = []
        for slot in slots:
            activity = value.get(slot, DEFAULT_FIXED_TEXT.get(slot))
            if not isinstance(activity, str) or not activity.strip():
                raise ValueError(f"旧版固定活动缺少内容：{slot}")
            day_name, period_name = slot.split("_", 1)
            day_label = DAY_LABELS[DAY_NAMES.index(day_name)]
            period_label = next(label for name, label, *_ in PERIODS if name == period_name)
            rules.append({"day": day_label, "period": period_label, "activity": activity})
        return {**value, "fixed_activities": rules}

    @field_validator(*[f"{period}_choices" for period, *_ in PERIODS])
    @classmethod
    def normalize_choices(cls, value: str) -> str:
        choices = list(dict.fromkeys(line.strip() for line in value.splitlines() if line.strip()))
        if not choices or len(choices) > 30 or any(len(choice) > 200 for choice in choices):
            raise ValueError("随机活动须每行一项，保留 1–30 项，每项不超过 200 字")
        return "\n".join(choices)

    @field_validator("fixed_activities")
    @classmethod
    def unique_fixed_activities(cls, value: list[FixedActivity]) -> list[FixedActivity]:
        slots = [(item.day, item.period) for item in value]
        if len(slots) != len(set(slots)):
            raise ValueError("同一星期和时间段只能设置一条固定活动")
        return value

    def activity_at(self, local_time: datetime, *, previous: str = "",
                    rng: random.Random | None = None) -> tuple[str, str]:
        if local_time.tzinfo is None:
            raise ValueError("模拟生活选取时间必须包含时区")
        minutes = local_time.hour * 60 + local_time.minute
        selected = PERIODS[-1]
        for period in PERIODS[:-1]:
            if minutes >= period[3]:
                selected = period
        field_name, period_label, clock_range, _ = selected
        day_label = DAY_LABELS[local_time.weekday()]
        fixed = next(
            (item.activity for item in self.fixed_activities
             if item.day == day_label and item.period == period_label),
            None,
        )
        if fixed is not None:
            activity = fixed
        else:
            choices = getattr(self, f"{field_name}_choices").splitlines()
            fresh = [choice for choice in choices if choice != previous]
            activity = (rng or random).choice(fresh or choices)
        return f"{day_label}{period_label}（{clock_range}）", activity
