"""Editable weekly imaginary-life context for proactive conversations."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from maibot_sdk import Field, PluginConfigBase
from pydantic import field_validator

DAY_NAMES = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")
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

_SLEEP = "00:00–07:00 安稳睡觉，早上 07:00 再起床。"
_BED = "放下屏幕，洗漱、整理小窝，23:50 上床，00:00 睡觉。"

DEFAULT_WEEK: dict[str, dict[str, str]] = {
    "monday": {
        "morning": "07:00 起床，洗漱开窗，给自己做蓝莓酸奶和吐司当早餐。",
        "late_morning": "给窗边的植物浇水，整理零食架，放喜欢的歌慢慢收拾家。",
        "noon": "煮一碗鸡蛋面当午饭，吃完在沙发上小憩。",
        "afternoon": "窝在家里涂涂画画，给蓝莓和粉色小鱼画可爱的小涂鸦。",
        "dusk": "看看窗外的晚霞，准备简单的晚饭，吃完收拾餐具。",
        "night": "裹着毯子看轻松的动画或玩一会儿休闲游戏。",
        "late_night": _BED,
        "predawn": _SLEEP,
    },
    "tuesday": {
        "morning": "07:00 起床洗漱，烤面包抹果酱，慢慢吃早餐。",
        "late_morning": "听歌、挑喜欢的照片整理相册，顺手把桌面擦干净。",
        "noon": "做一份米饭和清爽的家常菜，饭后安静休息。",
        "afternoon": "在家试做小饼干，闻着烤箱香味等出炉。",
        "dusk": "出门散一小会儿步，顺路买水果和晚饭食材。",
        "night": "吃过晚饭后洗碗，窝在家里看故事或玩小游戏。",
        "late_night": _BED,
        "predawn": _SLEEP,
    },
    "wednesday": {
        "morning": "07:00 起床，洗漱吃早餐，打开窗户让小窝透气。",
        "late_morning": "整理桌上的小物件，把要清洗和收纳的东西归到一起。",
        "noon": "做份简单午饭，吃完休息一会儿，为下午留点力气。",
        "afternoon": "固定清理蓝天小窝：擦桌子、收玩偶、整理床铺和地板，把小窝收拾得软乎乎又整洁。",
        "dusk": "洗个澡换上舒服的衣服，给自己准备晚饭。",
        "night": "小窝收拾好了，奖励自己一点甜食，窝着看动画。",
        "late_night": _BED,
        "predawn": _SLEEP,
    },
    "thursday": {
        "morning": "07:00 起床，洗漱后吃一份轻巧的早餐。",
        "late_morning": "在家听歌、给植物浇水，想想下午想吃什么。",
        "noon": "午饭吃得清淡一点，休息片刻，准备出门。",
        "afternoon": "固定过疯狂星期四：去 KFC 爽吃喜欢的炸鸡和薯条，开心地挑今天最好吃的那一口。",
        "dusk": "吃饱后慢慢散步回家，顺路看看傍晚的街景。",
        "night": "在家放松，聊聊下午的 KFC，看看轻松的视频。",
        "late_night": _BED,
        "predawn": _SLEEP,
    },
    "friday": {
        "morning": "07:00 起床洗漱，吃早餐时打开窗帘晒晒太阳。",
        "late_morning": "叠好洗净的衣服，照看窗边的小植物。",
        "noon": "做份米饭和热乎的小菜，饭后休息。",
        "afternoon": "在家画小卡片、整理随身小包，准备傍晚出门。",
        "dusk": "固定去湿地公园散步吹风，看水面、芦苇和傍晚的天空。",
        "night": "从湿地公园回家，洗洗手吃晚饭，带着晚风的好心情放松。",
        "late_night": _BED,
        "predawn": _SLEEP,
    },
    "saturday": {
        "morning": "07:00 起床，慢慢洗漱，做一份蓝莓早餐。",
        "late_morning": "去附近买水果，挑一些喜欢的蓝莓，回家收好。",
        "noon": "做份简单午饭，吃完在家休息一会儿。",
        "afternoon": "做小甜点或拼拼图，想起什么有趣的事就记下来。",
        "dusk": "在家做热乎晚饭，开窗看看天色慢慢暗下来。",
        "night": "抱着抱枕看电影，配一点自己做的小点心。",
        "late_night": _BED,
        "predawn": _SLEEP,
    },
    "sunday": {
        "morning": "07:00 起床洗漱，晒晒太阳，煎蛋配面包当早餐。",
        "late_morning": "洗一小篮衣服、整理抽屉，把家里布置得舒服些。",
        "noon": "煮一碗暖暖的汤和饺子，饭后在家小憩。",
        "afternoon": "翻漫画、做些小手工，或者给小窝换一处可爱的摆设。",
        "dusk": "在窗边看晚霞，慢慢准备晚饭。",
        "night": "吃过晚饭，泡杯热饮，听音乐聊聊今天的小事。",
        "late_night": _BED,
        "predawn": _SLEEP,
    },
}


class VirtualLifeSettings(PluginConfigBase):
    """The editable seven-day life plan used only for random proactive chat."""

    __ui_label__: ClassVar[str] = "模拟生活 · 每周安排"

    enabled: bool = Field(default=False, json_schema_extra={"label": "主动发言时启用模拟生活", "hint": "按插件时区读取当前星期和时段；只影响随机主动发言。"})

    # 周一
    monday_morning: str = Field(default=DEFAULT_WEEK["monday"]["morning"], max_length=200, json_schema_extra={"label": "周一 · 早晨 07:00–08:59", "x-widget": "textarea", "rows": 2})
    monday_late_morning: str = Field(default=DEFAULT_WEEK["monday"]["late_morning"], max_length=200, json_schema_extra={"label": "周一 · 上午 09:00–11:29", "x-widget": "textarea", "rows": 2})
    monday_noon: str = Field(default=DEFAULT_WEEK["monday"]["noon"], max_length=200, json_schema_extra={"label": "周一 · 中午 11:30–13:29", "x-widget": "textarea", "rows": 2})
    monday_afternoon: str = Field(default=DEFAULT_WEEK["monday"]["afternoon"], max_length=200, json_schema_extra={"label": "周一 · 下午 13:30–17:29", "x-widget": "textarea", "rows": 2})
    monday_dusk: str = Field(default=DEFAULT_WEEK["monday"]["dusk"], max_length=200, json_schema_extra={"label": "周一 · 傍晚 17:30–19:29", "x-widget": "textarea", "rows": 2})
    monday_night: str = Field(default=DEFAULT_WEEK["monday"]["night"], max_length=200, json_schema_extra={"label": "周一 · 夜晚 19:30–22:29", "x-widget": "textarea", "rows": 2})
    monday_late_night: str = Field(default=DEFAULT_WEEK["monday"]["late_night"], max_length=200, json_schema_extra={"label": "周一 · 深夜 22:30–23:59", "x-widget": "textarea", "rows": 2})
    monday_predawn: str = Field(default=DEFAULT_WEEK["monday"]["predawn"], max_length=200, json_schema_extra={"label": "周一 · 凌晨 00:00–06:59", "x-widget": "textarea", "rows": 2})

    # 周二
    tuesday_morning: str = Field(default=DEFAULT_WEEK["tuesday"]["morning"], max_length=200, json_schema_extra={"label": "周二 · 早晨 07:00–08:59", "x-widget": "textarea", "rows": 2})
    tuesday_late_morning: str = Field(default=DEFAULT_WEEK["tuesday"]["late_morning"], max_length=200, json_schema_extra={"label": "周二 · 上午 09:00–11:29", "x-widget": "textarea", "rows": 2})
    tuesday_noon: str = Field(default=DEFAULT_WEEK["tuesday"]["noon"], max_length=200, json_schema_extra={"label": "周二 · 中午 11:30–13:29", "x-widget": "textarea", "rows": 2})
    tuesday_afternoon: str = Field(default=DEFAULT_WEEK["tuesday"]["afternoon"], max_length=200, json_schema_extra={"label": "周二 · 下午 13:30–17:29", "x-widget": "textarea", "rows": 2})
    tuesday_dusk: str = Field(default=DEFAULT_WEEK["tuesday"]["dusk"], max_length=200, json_schema_extra={"label": "周二 · 傍晚 17:30–19:29", "x-widget": "textarea", "rows": 2})
    tuesday_night: str = Field(default=DEFAULT_WEEK["tuesday"]["night"], max_length=200, json_schema_extra={"label": "周二 · 夜晚 19:30–22:29", "x-widget": "textarea", "rows": 2})
    tuesday_late_night: str = Field(default=DEFAULT_WEEK["tuesday"]["late_night"], max_length=200, json_schema_extra={"label": "周二 · 深夜 22:30–23:59", "x-widget": "textarea", "rows": 2})
    tuesday_predawn: str = Field(default=DEFAULT_WEEK["tuesday"]["predawn"], max_length=200, json_schema_extra={"label": "周二 · 凌晨 00:00–06:59", "x-widget": "textarea", "rows": 2})

    # 周三
    wednesday_morning: str = Field(default=DEFAULT_WEEK["wednesday"]["morning"], max_length=200, json_schema_extra={"label": "周三 · 早晨 07:00–08:59", "x-widget": "textarea", "rows": 2})
    wednesday_late_morning: str = Field(default=DEFAULT_WEEK["wednesday"]["late_morning"], max_length=200, json_schema_extra={"label": "周三 · 上午 09:00–11:29", "x-widget": "textarea", "rows": 2})
    wednesday_noon: str = Field(default=DEFAULT_WEEK["wednesday"]["noon"], max_length=200, json_schema_extra={"label": "周三 · 中午 11:30–13:29", "x-widget": "textarea", "rows": 2})
    wednesday_afternoon: str = Field(default=DEFAULT_WEEK["wednesday"]["afternoon"], max_length=200, json_schema_extra={"label": "周三 · 下午 13:30–17:29", "x-widget": "textarea", "rows": 2})
    wednesday_dusk: str = Field(default=DEFAULT_WEEK["wednesday"]["dusk"], max_length=200, json_schema_extra={"label": "周三 · 傍晚 17:30–19:29", "x-widget": "textarea", "rows": 2})
    wednesday_night: str = Field(default=DEFAULT_WEEK["wednesday"]["night"], max_length=200, json_schema_extra={"label": "周三 · 夜晚 19:30–22:29", "x-widget": "textarea", "rows": 2})
    wednesday_late_night: str = Field(default=DEFAULT_WEEK["wednesday"]["late_night"], max_length=200, json_schema_extra={"label": "周三 · 深夜 22:30–23:59", "x-widget": "textarea", "rows": 2})
    wednesday_predawn: str = Field(default=DEFAULT_WEEK["wednesday"]["predawn"], max_length=200, json_schema_extra={"label": "周三 · 凌晨 00:00–06:59", "x-widget": "textarea", "rows": 2})

    # 周四
    thursday_morning: str = Field(default=DEFAULT_WEEK["thursday"]["morning"], max_length=200, json_schema_extra={"label": "周四 · 早晨 07:00–08:59", "x-widget": "textarea", "rows": 2})
    thursday_late_morning: str = Field(default=DEFAULT_WEEK["thursday"]["late_morning"], max_length=200, json_schema_extra={"label": "周四 · 上午 09:00–11:29", "x-widget": "textarea", "rows": 2})
    thursday_noon: str = Field(default=DEFAULT_WEEK["thursday"]["noon"], max_length=200, json_schema_extra={"label": "周四 · 中午 11:30–13:29", "x-widget": "textarea", "rows": 2})
    thursday_afternoon: str = Field(default=DEFAULT_WEEK["thursday"]["afternoon"], max_length=200, json_schema_extra={"label": "周四 · 下午 13:30–17:29", "x-widget": "textarea", "rows": 2})
    thursday_dusk: str = Field(default=DEFAULT_WEEK["thursday"]["dusk"], max_length=200, json_schema_extra={"label": "周四 · 傍晚 17:30–19:29", "x-widget": "textarea", "rows": 2})
    thursday_night: str = Field(default=DEFAULT_WEEK["thursday"]["night"], max_length=200, json_schema_extra={"label": "周四 · 夜晚 19:30–22:29", "x-widget": "textarea", "rows": 2})
    thursday_late_night: str = Field(default=DEFAULT_WEEK["thursday"]["late_night"], max_length=200, json_schema_extra={"label": "周四 · 深夜 22:30–23:59", "x-widget": "textarea", "rows": 2})
    thursday_predawn: str = Field(default=DEFAULT_WEEK["thursday"]["predawn"], max_length=200, json_schema_extra={"label": "周四 · 凌晨 00:00–06:59", "x-widget": "textarea", "rows": 2})

    # 周五
    friday_morning: str = Field(default=DEFAULT_WEEK["friday"]["morning"], max_length=200, json_schema_extra={"label": "周五 · 早晨 07:00–08:59", "x-widget": "textarea", "rows": 2})
    friday_late_morning: str = Field(default=DEFAULT_WEEK["friday"]["late_morning"], max_length=200, json_schema_extra={"label": "周五 · 上午 09:00–11:29", "x-widget": "textarea", "rows": 2})
    friday_noon: str = Field(default=DEFAULT_WEEK["friday"]["noon"], max_length=200, json_schema_extra={"label": "周五 · 中午 11:30–13:29", "x-widget": "textarea", "rows": 2})
    friday_afternoon: str = Field(default=DEFAULT_WEEK["friday"]["afternoon"], max_length=200, json_schema_extra={"label": "周五 · 下午 13:30–17:29", "x-widget": "textarea", "rows": 2})
    friday_dusk: str = Field(default=DEFAULT_WEEK["friday"]["dusk"], max_length=200, json_schema_extra={"label": "周五 · 傍晚 17:30–19:29", "x-widget": "textarea", "rows": 2})
    friday_night: str = Field(default=DEFAULT_WEEK["friday"]["night"], max_length=200, json_schema_extra={"label": "周五 · 夜晚 19:30–22:29", "x-widget": "textarea", "rows": 2})
    friday_late_night: str = Field(default=DEFAULT_WEEK["friday"]["late_night"], max_length=200, json_schema_extra={"label": "周五 · 深夜 22:30–23:59", "x-widget": "textarea", "rows": 2})
    friday_predawn: str = Field(default=DEFAULT_WEEK["friday"]["predawn"], max_length=200, json_schema_extra={"label": "周五 · 凌晨 00:00–06:59", "x-widget": "textarea", "rows": 2})

    # 周六
    saturday_morning: str = Field(default=DEFAULT_WEEK["saturday"]["morning"], max_length=200, json_schema_extra={"label": "周六 · 早晨 07:00–08:59", "x-widget": "textarea", "rows": 2})
    saturday_late_morning: str = Field(default=DEFAULT_WEEK["saturday"]["late_morning"], max_length=200, json_schema_extra={"label": "周六 · 上午 09:00–11:29", "x-widget": "textarea", "rows": 2})
    saturday_noon: str = Field(default=DEFAULT_WEEK["saturday"]["noon"], max_length=200, json_schema_extra={"label": "周六 · 中午 11:30–13:29", "x-widget": "textarea", "rows": 2})
    saturday_afternoon: str = Field(default=DEFAULT_WEEK["saturday"]["afternoon"], max_length=200, json_schema_extra={"label": "周六 · 下午 13:30–17:29", "x-widget": "textarea", "rows": 2})
    saturday_dusk: str = Field(default=DEFAULT_WEEK["saturday"]["dusk"], max_length=200, json_schema_extra={"label": "周六 · 傍晚 17:30–19:29", "x-widget": "textarea", "rows": 2})
    saturday_night: str = Field(default=DEFAULT_WEEK["saturday"]["night"], max_length=200, json_schema_extra={"label": "周六 · 夜晚 19:30–22:29", "x-widget": "textarea", "rows": 2})
    saturday_late_night: str = Field(default=DEFAULT_WEEK["saturday"]["late_night"], max_length=200, json_schema_extra={"label": "周六 · 深夜 22:30–23:59", "x-widget": "textarea", "rows": 2})
    saturday_predawn: str = Field(default=DEFAULT_WEEK["saturday"]["predawn"], max_length=200, json_schema_extra={"label": "周六 · 凌晨 00:00–06:59", "x-widget": "textarea", "rows": 2})

    # 周日
    sunday_morning: str = Field(default=DEFAULT_WEEK["sunday"]["morning"], max_length=200, json_schema_extra={"label": "周日 · 早晨 07:00–08:59", "x-widget": "textarea", "rows": 2})
    sunday_late_morning: str = Field(default=DEFAULT_WEEK["sunday"]["late_morning"], max_length=200, json_schema_extra={"label": "周日 · 上午 09:00–11:29", "x-widget": "textarea", "rows": 2})
    sunday_noon: str = Field(default=DEFAULT_WEEK["sunday"]["noon"], max_length=200, json_schema_extra={"label": "周日 · 中午 11:30–13:29", "x-widget": "textarea", "rows": 2})
    sunday_afternoon: str = Field(default=DEFAULT_WEEK["sunday"]["afternoon"], max_length=200, json_schema_extra={"label": "周日 · 下午 13:30–17:29", "x-widget": "textarea", "rows": 2})
    sunday_dusk: str = Field(default=DEFAULT_WEEK["sunday"]["dusk"], max_length=200, json_schema_extra={"label": "周日 · 傍晚 17:30–19:29", "x-widget": "textarea", "rows": 2})
    sunday_night: str = Field(default=DEFAULT_WEEK["sunday"]["night"], max_length=200, json_schema_extra={"label": "周日 · 夜晚 19:30–22:29", "x-widget": "textarea", "rows": 2})
    sunday_late_night: str = Field(default=DEFAULT_WEEK["sunday"]["late_night"], max_length=200, json_schema_extra={"label": "周日 · 深夜 22:30–23:59", "x-widget": "textarea", "rows": 2})
    sunday_predawn: str = Field(default=DEFAULT_WEEK["sunday"]["predawn"], max_length=200, json_schema_extra={"label": "周日 · 凌晨 00:00–06:59", "x-widget": "textarea", "rows": 2})

    @field_validator(*[f"{day}_{period}" for day in DAY_NAMES for period, *_ in PERIODS])
    @classmethod
    def normalize_activity(cls, value: str) -> str:
        activity = " ".join(value.split())
        if not activity or len(activity) > 200:
            raise ValueError("每个时段的生活安排须为 1–200 个字符")
        return activity

    def activity_at(self, local_time: datetime) -> tuple[str, str]:
        if local_time.tzinfo is None:
            raise ValueError("模拟生活选取时间必须包含时区")
        minutes = local_time.hour * 60 + local_time.minute
        selected = PERIODS[-1]
        for period in PERIODS[:-1]:
            if minutes >= period[3]:
                selected = period
        field_name, period_label, clock_range, _ = selected
        day_name = DAY_NAMES[local_time.weekday()]
        return f"{DAY_LABELS[local_time.weekday()]}{period_label}（{clock_range}）", getattr(self, f"{day_name}_{field_name}")
