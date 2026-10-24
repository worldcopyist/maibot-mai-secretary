from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from test_secretary import make_plugin, module

ZONE = ZoneInfo("Asia/Shanghai")


def test_mood_probabilities_are_editable_and_must_total_100():
    settings = module.MoodSettings()
    assert sum(settings.weights().values()) == 100
    fields = module.MaiSecretaryPlugin.build_config_schema()["sections"]["mood"]["fields"]
    assert {"enabled", *settings.weights()} <= set(fields)
    with pytest.raises(ValueError, match="总和必须为 100"):
        module.MoodSettings.model_validate({"happy": 99})


def test_shared_mood_follows_life_activity_and_survives_restart(tmp_path):
    config = {"virtual_life": {"enabled": True}, "mood": {"enabled": True}}
    plugin, _ = make_plugin(tmp_path, config)
    at = datetime(2026, 10, 22, 15, 0, tzinfo=ZONE)
    state = plugin.mood.current(at)
    assert state["activity"] == plugin.virtual_life.scene_at(at)["activity"]
    assert "疯狂星期四" in state["activity"]
    assert plugin.mood.effective_weights(state["activity"], "afternoon")["satisfied"] > plugin.config.mood.satisfied
    assert plugin.mood.current(at) == state

    restored, _ = make_plugin(tmp_path, config)
    restored._load_state()
    assert restored.mood.current(at) == state
    later = restored.mood.current(datetime(2026, 10, 22, 18, 0, tzinfo=ZONE))
    assert later["key"] != state["key"]


def test_zero_probability_stays_zero_after_activity_bias(tmp_path):
    plugin, _ = make_plugin(tmp_path, {"mood": {
        "enabled": True, "calm": 50, "happy": 0,
    }})
    assert plugin.mood.effective_weights("去 KFC 吃炸鸡", "afternoon")["happy"] == 0


@pytest.mark.asyncio
async def test_one_mood_has_distinct_owner_familiar_and_stranger_expression(tmp_path):
    plugin, _ = make_plugin(tmp_path, {
        "plugin": {"admin_accounts": ["qq:111"]},
        "role_recognition": {"familiar_accounts": ["qq:222"]},
        "virtual_life": {"enabled": True},
        "mood": {"enabled": True},
    })
    notes = {}
    for account in ("111", "222", "333"):
        message_id = f"msg-{account}"
        stream_id = f"stream-{account}"
        plugin.role_recognition.remember({
            "message_id": message_id, "session_id": stream_id, "platform": "qq",
            "account_id": "bot", "message_info": {"user_info": {"user_id": account}},
        })
        request = {"session_id": stream_id, "reply_message_id": message_id, "items": [
            {"item_type": "SystemMessageItem", "parts": [{"type": "text", "text": "MaiBot 人设"}]},
        ]}
        result = await plugin.role_recognition.inject(request)
        notes[account] = "\n".join(
            part["text"] for item in result["modified_kwargs"]["items"]
            for part in item.get("parts", []) if part.get("type") == "text"
        )
    assert "当前关系级别为主人" in notes["111"]
    assert "自然撒娇" in notes["111"] or "坦诚说出感受" in notes["111"]
    assert "当前关系级别为熟人" in notes["222"]
    assert "当前关系级别为陌生人" in notes["333"]
    assert "当前关系级别为主人" not in notes["333"]
    assert plugin.mood.state["mood"] in module.MoodSettings().weights()
    mood_name = notes["111"].split("当前心情为", 1)[1].split("（", 1)[0]
    assert all(f"当前心情为{mood_name}" in note for note in notes.values())


@pytest.mark.asyncio
async def test_mood_injects_without_role_recognition_using_stranger_style(tmp_path):
    plugin, _ = make_plugin(tmp_path, {
        "role_recognition": {"enabled": False},
        "mood": {"enabled": True},
    })
    result = await plugin.role_recognition.inject({
        "session_id": "unverified-stream", "items": [
            {"item_type": "SystemMessageItem", "parts": [{"type": "text", "text": "MaiBot 人设"}]},
        ],
    })
    rendered = str(result["modified_kwargs"]["items"])
    assert "当前关系级别为陌生人" in rendered
    assert "MaiBot 人设" in rendered
