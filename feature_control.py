"""Persisted natural-language switches layered over the WebUI configuration."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, ClassVar


class FeatureControlModule:
    name = "feature_control"
    state_keys = frozenset({"feature_overrides"})

    # Each switch is intentionally explicit. No model-provided config path is evaluated.
    SWITCHES: ClassVar[dict[str, tuple[str, str, str, tuple[str, ...]]]] = {
        "scheduled_tasks": ("scheduled_tasks", "enabled", "定时任务", ("定时提醒", "任务")),
        "timetable": ("timetable", "enabled", "课表模块", ("上课提醒", "课表提醒")),
        "task_receipts": ("task_receipts", "enabled", "任务回执", ("发送回执", "回执中心")),
        "daily_report": ("daily_report", "enabled", "定时日报", ("日报定时发送",)),
        "manual_report": ("daily_report", "manual_enabled", "即时日报", ("手动日报",)),
        "proactive": ("proactive", "enabled", "主动发言", ("随机发言", "主动聊天")),
        "virtual_life": ("virtual_life", "enabled", "模拟生活", ("虚拟生活",)),
        "life_photo": ("life_photo", "enabled", "生活照片", ("主动发图", "生图分享", "拍照分享")),
        "mood": ("mood", "enabled", "心情模块", ("心情", "情绪模块")),
        "mood_chat": ("mood", "chat_influence_enabled", "聊天影响心情", ("对话影响心情",)),
        "mood_bullying": ("mood", "bullying_mood_enabled", "反霸凌影响心情", ("被辱骂后改变心情",)),
        "role_recognition": ("role_recognition", "enabled", "角色识别", ("身份识别",)),
        "relationships": ("relationships", "enabled", "关系管理", ("关系档案",)),
        "followups": ("followups", "enabled", "约定回访", ("回访",)),
        "followups_auto": ("followups", "auto_capture", "自动发现回访", ("自动回访",)),
        "poke": ("poke", "enabled", "戳一戳", ("戳人",)),
        "poke_reaction": ("poke", "respond_to_poke", "被戳回应", ("戳一戳回应",)),
        "poke_bystander": ("poke", "bystander_enabled", "跟风戳人", ("跟风戳",)),
        "poke_tool": ("poke", "allow_model_poke", "麦麦主动戳人", ("主动戳人",)),
        "poke_group": ("poke", "group_enabled", "群聊戳一戳", ("群戳",)),
        "poke_private": ("poke", "private_enabled", "私聊戳一戳", ("私聊戳",)),
        "group_admin": ("group_admin", "enabled", "QQ群管", ("群管", "群管理")),
        "group_moderation": ("group_admin", "moderation_enabled", "群消息审核", ("自动撤回禁言", "敏感词审核")),
        "group_recall": ("group_admin", "moderation_recall", "群审核自动撤回", ("审核撤回",)),
        "group_mute": ("group_admin", "moderation_mute", "群审核自动禁言", ("审核禁言",)),
        "group_welcome": ("group_admin", "welcome_enabled", "入群欢迎", ("欢迎新成员",)),
        "voice": ("voice_synthesis", "enabled", "语音模块", ("语音回复", "语音", "文字转语音")),
        "singing": ("voice_synthesis", "singing_enabled", "唱歌", ("唱歌功能",)),
        "anti_bullying": ("anti_bullying", "enabled", "AI反霸凌", ("反霸凌", "辱骂告状")),
        "knowledge_base": ("knowledge_base", "enabled", "知识库", ("文档检索",)),
        "knowledge_semantic": ("knowledge_base", "semantic_search", "知识库语义检索", ("语义检索",)),
        "deepseek_web": ("deepseek_web", "enabled", "DeepSeek联网", ("联网模块",)),
        "web_search": ("deepseek_web", "search_enabled", "联网搜索", ("搜索", "网页抓取")),
        "balance_query": ("deepseek_web", "balance_enabled", "蓝莓余额查询", ("余额查询",)),
        "auto_balance": ("deepseek_web", "auto_balance_enabled", "自动查询蓝莓", ("自动余额查询",)),
        "balance_sharing": ("deepseek_web", "balance_context_all_chats", "余额全聊天可见", ("蓝莓共享",)),
        "blueberry_budget": ("deepseek_web", "budget_alert_enabled", "DeepSeek 低余额提醒", ("蓝莓预算提醒", "预算提醒", "余额预警")),
        "message_debounce": ("message_debounce", "enabled", "消息防抖", ("防抖",)),
        "debounce_private": ("message_debounce", "enable_private", "私聊防抖", ("私聊消息防抖",)),
        "debounce_group": ("message_debounce", "enable_group", "群聊防抖", ("群聊消息防抖",)),
        "debounce_ignore_commands": ("message_debounce", "ignore_commands", "命令跳过防抖", ("命令防抖豁免",)),
        "stale_reply": ("message_debounce", "suppress_stale_private_replies", "取消过时私聊回复", ("取消旧回复",)),
    }
    PARENTS: ClassVar[dict[str, tuple[str, ...]]] = {
        "timetable": ("scheduled_tasks",),
        "virtual_life": ("proactive",), "mood_chat": ("mood",),
        "mood_bullying": ("mood", "anti_bullying"),
        "relationships": ("role_recognition",),
        "followups_auto": ("followups",), "poke_reaction": ("poke",),
        "poke_bystander": ("poke",), "poke_tool": ("poke",),
        "poke_group": ("poke",), "poke_private": ("poke",),
        "group_moderation": ("group_admin",), "group_recall": ("group_admin", "group_moderation"),
        "group_mute": ("group_admin", "group_moderation"), "group_welcome": ("group_admin",),
        "singing": ("voice",), "knowledge_semantic": ("knowledge_base",),
        "web_search": ("deepseek_web",), "balance_query": ("deepseek_web",),
        "auto_balance": ("deepseek_web", "balance_query"),
        "balance_sharing": ("deepseek_web", "balance_query"),
        "blueberry_budget": ("deepseek_web",),
        "debounce_private": ("message_debounce",), "debounce_group": ("message_debounce",),
        "debounce_ignore_commands": ("message_debounce",), "stale_reply": ("message_debounce", "debounce_private"),
    }

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.overrides: dict[str, bool] = {}
        self.base: dict[str, bool] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        raw = data.get("feature_overrides", {})
        if not isinstance(raw, dict):
            raise TypeError("功能开关状态格式错误")
        self.overrides = {
            key: value for key, value in raw.items()
            if key in self.SWITCHES and type(value) is bool
        }

    def dump_state(self, payload: dict[str, Any]) -> None:
        if self.overrides:
            payload["feature_overrides"] = self.overrides

    def on_config_update(self) -> None:
        pass

    async def tick(self, now: datetime) -> None:
        del now

    def apply(self, config_data: dict[str, Any] | None = None) -> None:
        """Apply the saved chat switches after initial load or a WebUI config reload."""
        for key, (section, field, _label, _aliases) in self.SWITCHES.items():
            section_obj = getattr(self.plugin.config, section)
            source = config_data.get(section) if isinstance(config_data, dict) else None
            if isinstance(source, dict) and type(source.get(field)) is bool:
                baseline = source[field]
            elif key not in self.base:
                baseline = bool(getattr(section_obj, field))
            else:
                baseline = self.base[key]
            self.base[key] = baseline
            setattr(section_obj, field, self.overrides.get(key, baseline))

    @classmethod
    def resolve(cls, value: str) -> str | None:
        needle = re.sub(r"\s+", "", str(value or "").casefold())
        for key, (_section, _field, label, aliases) in cls.SWITCHES.items():
            if needle in {key.casefold(), label.casefold(), *(name.casefold() for name in aliases)}:
                return key
        return None

    def rows(self) -> list[dict[str, Any]]:
        values = {
            key: bool(getattr(getattr(self.plugin.config, section), field))
            for key, (section, field, _label, _aliases) in self.SWITCHES.items()
        }
        return [
            {
                "key": key, "label": label,
                "enabled": values[key],
                "effective": bool(self.plugin.config.plugin.enabled and values[key]
                                  and all(values[parent] for parent in self.PARENTS.get(key, ()))),
                "requires": list(self.PARENTS.get(key, ())),
                "configured": self.base.get(key, bool(getattr(getattr(self.plugin.config, section), field))),
                "chat_override": key in self.overrides,
            }
            for key, (section, field, label, _aliases) in self.SWITCHES.items()
        ]

    async def set_switches(self, action: str, feature: str) -> dict[str, Any]:
        action = str(action or "").strip().lower()
        if action not in {"enable", "disable", "reset"}:
            return {"success": False, "error": "action 只能为 enable、disable 或 reset"}
        names = [part.strip() for part in re.split(r"[,，、；;]", str(feature or "")) if part.strip()]
        keys = [self.resolve(name) for name in names]
        if not names or any(key is None for key in keys):
            return {"success": False, "error": "功能名称不明确；请先查看功能列表，并使用准确名称"}
        async with self.plugin._lock:
            for key in keys:
                assert key is not None
                if action == "reset":
                    self.overrides.pop(key, None)
                else:
                    self.overrides[key] = action == "enable"
            self.apply()
            self.plugin._save_state()
            self.plugin._wake.set()
        names = [self.SWITCHES[key][2] for key in keys if key]
        return {"success": True, "content": f"已{'恢复页面配置' if action == 'reset' else '开启' if action == 'enable' else '关闭'}：{'、'.join(names)}", "switches": self.rows()}

    async def tool(self, action: str, feature: str = "", **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip():
            return {"success": False, "error": "无法核验当前聊天流"}
        actor = self.plugin.role_recognition.peek_planner_speaker(stream_id)
        if not actor or actor not in await self.plugin.role_recognition.admin_accounts(force_refresh=True):
            return {"success": False, "error": "只有已核验的小秘书管理员能管理功能开关"}
        if action == "list":
            rows = self.rows()
            return {"success": True, "content": "；".join(f"{row['label']}：{'生效' if row['effective'] else '未生效'}（开关{'开' if row['enabled'] else '关'}）" for row in rows), "switches": rows}
        return await self.set_switches(action, feature)
