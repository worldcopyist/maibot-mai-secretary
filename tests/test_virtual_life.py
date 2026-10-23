from __future__ import annotations

import importlib
import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from test_secretary import make_plugin, module

life_module = importlib.import_module("mai_secretary.virtual_life")
DAY_NAMES = life_module.DAY_NAMES
DEFAULT_WEEK = life_module.DEFAULT_WEEK
PERIODS = life_module.PERIODS
VirtualLifeSettings = life_module.VirtualLifeSettings

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("Asia/Shanghai")


def test_full_week_defaults_and_public_config_match():
    settings = VirtualLifeSettings()
    source = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    assert len(DAY_NAMES) == 7 and len(PERIODS) == 8
    for day in DAY_NAMES:
        for period, *_ in PERIODS:
            field = f"{day}_{period}"
            assert getattr(settings, field) == DEFAULT_WEEK[day][period]
            assert source["virtual_life"][field] == DEFAULT_WEEK[day][period]
        assert "00:00" in getattr(settings, f"{day}_late_night")
        assert "07:00" in getattr(settings, f"{day}_predawn")
    assert "清理蓝天小窝" in settings.wednesday_afternoon
    assert "疯狂星期四" in settings.thursday_afternoon
    assert "KFC" in settings.thursday_afternoon
    assert "湿地公园散步吹风" in settings.friday_dusk
    assert module.SecretaryConfig.model_validate(source).virtual_life.enabled is False
    schema = module.MaiSecretaryPlugin.build_config_schema()
    fields = schema["sections"]["virtual_life"]["fields"]
    assert len(fields) == 57
    assert fields["wednesday_afternoon"]["ui_type"] == "textarea"
    assert fields["wednesday_afternoon"]["label"].startswith("周三 · 下午")


@pytest.mark.parametrize(("hour", "minute", "expected"), [
    (0, 0, "凌晨"), (6, 59, "凌晨"), (7, 0, "早晨"), (8, 59, "早晨"),
    (9, 0, "上午"), (11, 29, "上午"), (11, 30, "中午"),
    (13, 29, "中午"), (13, 30, "下午"), (17, 29, "下午"),
    (17, 30, "傍晚"), (19, 29, "傍晚"), (19, 30, "夜晚"),
    (22, 29, "夜晚"), (22, 30, "深夜"), (23, 59, "深夜"),
])
def test_period_boundaries(hour, minute, expected):
    label, _ = VirtualLifeSettings().activity_at(datetime(2026, 10, 21, hour, minute, tzinfo=ZONE))
    assert label.startswith("周三" + expected)


def test_one_field_edits_keep_other_daily_defaults():
    settings = VirtualLifeSettings.model_validate({
        "enabled": True,
        "wednesday_afternoon": "给蓝天小窝换一张软毯子",
    })
    assert settings.wednesday_afternoon == "给蓝天小窝换一张软毯子"
    assert settings.wednesday_morning == DEFAULT_WEEK["wednesday"]["morning"]
    assert settings.thursday_afternoon == DEFAULT_WEEK["thursday"]["afternoon"]
    with pytest.raises(ValueError):
        VirtualLifeSettings.model_validate({"wednesday_afternoon": "  "})


@pytest.mark.asyncio
async def test_proactive_uses_current_weekly_activity_and_previous_chat(tmp_path):
    target = "qq:private:123"
    plugin, proactive = make_plugin(tmp_path, {
        "proactive": {"target_chats": [target], "messages_per_window": 1},
        "virtual_life": {"enabled": True},
    })
    start = datetime(2026, 10, 21, 14, 0, tzinfo=ZONE)
    await plugin.proactive.tick(start)
    due = datetime(2026, 10, 21, 15, 0, tzinfo=ZONE)
    plugin.proactive.plans[target]["slots"] = [due.timestamp() - 1]
    plugin.proactive.continuity[target] = {
        "last_message": "我昨天在烤饼干",
        "last_sent_at": datetime(2026, 10, 20, 16, 0, tzinfo=ZONE).timestamp(),
    }
    await plugin.proactive.tick(due)
    assert len(proactive.calls) == 1
    intent = proactive.calls[0]["intent"]
    assert "周三下午" in intent and "清理蓝天小窝" in intent
    assert "我昨天在烤饼干" in intent
    assert "自然转到此刻的安排" in intent
    assert "以 MaiBot 人设为准" in intent


def test_thursday_friday_and_predawn_select_correct_activity(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"virtual_life": {"enabled": True}})
    cases = [
        (datetime(2026, 10, 22, 16, 0, tzinfo=ZONE), "疯狂星期四"),
        (datetime(2026, 10, 23, 18, 0, tzinfo=ZONE), "湿地公园散步吹风"),
        (datetime(2026, 10, 24, 1, 0, tzinfo=ZONE), "安稳睡觉"),
    ]
    for at, phrase in cases:
        assert phrase in plugin.proactive._proactive_intent("qq:private:123", "自然闲聊", at)
