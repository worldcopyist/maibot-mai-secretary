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
DEFAULT_CHOICES = life_module.DEFAULT_CHOICES
PERIODS = life_module.PERIODS
VirtualLifeSettings = life_module.VirtualLifeSettings

ROOT = Path(__file__).resolve().parents[1]
ZONE = ZoneInfo("Asia/Shanghai")


def test_random_pools_and_fixed_list_schema():
    settings = VirtualLifeSettings()
    source = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    assert len(DAY_NAMES) == 7 and len(PERIODS) == 8
    for period, *_ in PERIODS:
        assert getattr(settings, f"{period}_choices").splitlines() == list(DEFAULT_CHOICES[period])
        assert source["virtual_life"][f"{period}_choices"].strip().splitlines() == list(DEFAULT_CHOICES[period])
    assert len(settings.fixed_activities) == 3
    assert [item.model_dump() for item in settings.fixed_activities] == source["virtual_life"]["fixed_activities"]
    assert "清理蓝天小窝" in settings.fixed_activities[0].activity
    assert "疯狂星期四" in settings.fixed_activities[1].activity
    assert "湿地公园散步吹风" in settings.fixed_activities[2].activity
    assert not {"fixed_slots", "wednesday_afternoon", "sunday_predawn"} & VirtualLifeSettings.model_fields.keys()
    assert set(source["virtual_life"]) == {"enabled", "fixed_activities", *[f"{period}_choices" for period, *_ in PERIODS]}
    assert module.SecretaryConfig.model_validate(source).virtual_life.enabled is False
    schema = module.MaiSecretaryPlugin.build_config_schema()
    fields = schema["sections"]["virtual_life"]["fields"]
    assert len(fields) == 10
    assert fields["afternoon_choices"]["ui_type"] == "textarea"
    fixed = fields["fixed_activities"]
    assert fixed["ui_type"] == "list" and fixed["item_type"] == "object"
    assert fixed["item_fields"]["day"]["type"] == "select"
    assert fixed["item_fields"]["day"]["choices"] == list(life_module.DAY_LABELS)
    assert fixed["item_fields"]["period"]["type"] == "select"
    assert fixed["item_fields"]["period"]["choices"] == [part[1] for part in PERIODS]
    assert fixed["item_fields"]["activity"]["type"] == "string"


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


def test_fixed_activity_can_be_added_removed_and_legacy_fields_migrate():
    settings = VirtualLifeSettings.model_validate({
        "enabled": True,
        "fixed_activities": [
            {"day": "周六", "period": "下午", "activity": " 拼乐高 "},
        ],
    })
    assert settings.fixed_activities[0].activity == "拼乐高"
    assert VirtualLifeSettings.model_validate({"fixed_activities": []}).fixed_activities == []
    legacy = VirtualLifeSettings.model_validate({
        "enabled": True,
        "fixed_slots": "周三下午，周六夜晚",
        "wednesday_afternoon": "给小窝换一张软毯子",
        "saturday_night": "看一部电影",
        "monday_morning": "旧版非固定内容",
    })
    assert [(item.day, item.period, item.activity) for item in legacy.fixed_activities] == [
        ("周三", "下午", "给小窝换一张软毯子"),
        ("周六", "夜晚", "看一部电影"),
    ]
    assert "fixed_slots" not in legacy.model_dump()
    assert "monday_morning" not in legacy.model_dump()
    assert VirtualLifeSettings.model_validate({"fixed_slots": ""}).fixed_activities == []
    assert VirtualLifeSettings.model_validate({
        "fixed_activities": [], "fixed_slots": "周三下午", "wednesday_afternoon": "旧内容",
    }).fixed_activities == []


def test_sdk_default_merge_preserves_legacy_fixed_content():
    raw = tomllib.loads((ROOT / "config.toml").read_text(encoding="utf-8"))
    raw["virtual_life"] = {
        "enabled": True,
        "fixed_slots": "周三下午,周四下午,周六夜晚",
        "wednesday_afternoon": "旧版自定义打扫内容",
        "thursday_afternoon": "旧版自定义晚餐内容",
        "saturday_night": "旧版自定义看剧内容",
    }
    normalized, changed = module.MaiSecretaryPlugin().normalize_plugin_config(raw)
    assert changed
    fixed = normalized["virtual_life"]["fixed_activities"]
    assert [(item["day"], item["period"], item["activity"]) for item in fixed] == [
        ("周三", "下午", "旧版自定义打扫内容"),
        ("周四", "下午", "旧版自定义晚餐内容"),
        ("周六", "夜晚", "旧版自定义看剧内容"),
    ]
    assert "fixed_slots" not in normalized["virtual_life"]
    assert "wednesday_afternoon" not in normalized["virtual_life"]

    raw["virtual_life"]["fixed_activities"] = []
    normalized, _ = module.MaiSecretaryPlugin().normalize_plugin_config(raw)
    assert normalized["virtual_life"]["fixed_activities"] == []


def test_random_candidates_are_time_bound_and_fixed_activity_wins():
    class PickFirst:
        @staticmethod
        def choice(choices):
            return choices[0]

    settings = VirtualLifeSettings.model_validate({
        "afternoon_choices": "玩游戏\n拼乐高",
        "morning_choices": "做早餐\n吃早餐",
        "fixed_activities": [{"day": "周三", "period": "下午", "activity": "固定打扫小窝"}],
    })
    monday = datetime(2026, 10, 19, 14, 0, tzinfo=ZONE)
    _, first = settings.activity_at(monday, rng=PickFirst())
    _, second = settings.activity_at(monday, previous=first, rng=PickFirst())
    assert (first, second) == ("玩游戏", "拼乐高")
    assert "早餐" not in first + second
    wednesday = datetime(2026, 10, 21, 14, 0, tzinfo=ZONE)
    assert settings.activity_at(wednesday, rng=PickFirst())[1] == "固定打扫小窝"
    assert settings.activity_at(datetime(2026, 10, 19, 7, 0, tzinfo=ZONE), rng=PickFirst())[1] == "做早餐"


def test_candidate_and_fixed_activity_validation():
    with pytest.raises(ValueError, match="未知的旧版固定时段"):
        VirtualLifeSettings.model_validate({"fixed_slots": "wednesday_breakfast"})
    with pytest.raises(ValueError, match="随机活动"):
        VirtualLifeSettings.model_validate({"afternoon_choices": "  \n "})
    with pytest.raises(ValueError, match="同一星期和时间段"):
        VirtualLifeSettings.model_validate({"fixed_activities": [
            {"day": "周三", "period": "下午", "activity": "打扫"},
            {"day": "周三", "period": "下午", "activity": "画画"},
        ]})
    with pytest.raises(ValueError, match="Input should be"):
        VirtualLifeSettings.model_validate({"fixed_activities": [
            {"day": "周二", "period": "晚上", "activity": "看书"},
        ]})
    with pytest.raises(ValueError, match="固定活动"):
        VirtualLifeSettings.model_validate({"fixed_activities": [
            {"day": "周二", "period": "夜晚", "activity": " "},
        ]})
    settings = VirtualLifeSettings.model_validate({"afternoon_choices": " 玩游戏 \n\n拼乐高\n玩游戏"})
    assert settings.afternoon_choices == "玩游戏\n拼乐高"


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


@pytest.mark.asyncio
async def test_shared_random_activity_and_sent_only_continuity(tmp_path):
    target = "qq:private:123"
    config = {
        "proactive": {"target_chats": [target], "messages_per_window": 1},
        "virtual_life": {
            "enabled": True,
            "afternoon_choices": "玩游戏\n拼乐高",
        },
    }
    plugin, proactive = make_plugin(tmp_path, config)
    start = datetime(2026, 10, 19, 14, 0, tzinfo=ZONE)
    await plugin.proactive.tick(start)
    due = datetime(2026, 10, 19, 15, 0, tzinfo=ZONE)
    plugin.proactive.plans[target]["slots"] = [due.timestamp() - 1]
    await plugin.proactive.tick(due)
    assert len(proactive.calls) == 1
    pending = plugin.proactive.continuity[target]["pending"]
    selected = pending["activity"]
    assert selected in {"玩游戏", "拼乐高"}
    assert "last_activity" not in plugin.proactive.continuity[target]
    await plugin.capture_proactive_reply({
        "session_id": "real-stream-1", "message_id": "sent-1",
        "timestamp": str(due.timestamp() + 1),
        "raw_message": [{"type": "text", "data": "今天有点开心"}],
    }, sent=True)
    assert plugin.proactive.continuity[target]["last_activity"] == selected
    restored, _ = make_plugin(tmp_path, config)
    restored._load_state()
    assert restored.proactive.continuity[target]["last_activity"] == selected
    next_intent = restored.proactive._proactive_intent(target, "自然闲聊", due)
    assert selected in next_intent
    assert restored.virtual_life.scene_at(due)["activity"] == selected


def test_two_chat_streams_share_one_activity_until_period_changes(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"virtual_life": {
        "enabled": True, "afternoon_choices": "玩游戏\n拼乐高",
        "dusk_choices": "吃晚饭\n散步",
        "fixed_activities": [],
    }})
    afternoon = datetime(2026, 10, 19, 14, 0, tzinfo=ZONE)
    first = plugin.proactive._proactive_intent("qq:private:123", "自然闲聊", afternoon)
    second = plugin.proactive._proactive_intent("qq:group:456", "自然闲聊", afternoon)
    activity = plugin.virtual_life.scene_at(afternoon)["activity"]
    assert activity in first and activity in second
    assert plugin.virtual_life.scene_at(datetime(2026, 10, 19, 16, 0, tzinfo=ZONE))["activity"] == activity
    dusk = plugin.virtual_life.scene_at(datetime(2026, 10, 19, 18, 0, tzinfo=ZONE))
    assert dusk["activity"] in {"吃晚饭", "散步"}
    assert dusk["key"] != "2026-10-19:afternoon"


def test_thursday_friday_and_predawn_select_correct_activity(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"virtual_life": {"enabled": True}})
    cases = [
        (datetime(2026, 10, 22, 16, 0, tzinfo=ZONE), "疯狂星期四"),
        (datetime(2026, 10, 23, 18, 0, tzinfo=ZONE), "湿地公园散步吹风"),
        (datetime(2026, 10, 24, 1, 0, tzinfo=ZONE), "安稳睡觉"),
    ]
    for at, phrase in cases:
        assert phrase in plugin.proactive._proactive_intent("qq:private:123", "自然闲聊", at)
