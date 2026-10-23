"""Admin-managed relationship decisions, separate from automatic familiarity counts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from .anti_bullying import normalize_admin_account


class RelationshipManagementModule:
    name = "relationships"
    state_keys = frozenset({"relationship_overrides"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.overrides: dict[str, str] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        raw = data.get("relationship_overrides", {})
        if not isinstance(raw, dict):
            raise TypeError("关系管理状态格式错误")
        self.overrides = {}
        for account, level in raw.items():
            if not isinstance(account, str) or level not in {"familiar", "stranger"}:
                continue
            try:
                self.overrides[normalize_admin_account(account)] = level
            except ValueError:
                continue

    def dump_state(self, payload: dict[str, Any]) -> None:
        if self.overrides:
            payload["relationship_overrides"] = self.overrides

    def on_config_update(self) -> None:
        pass

    async def tick(self, now: datetime) -> None:
        del now

    def level_for(self, account: str) -> str | None:
        if not self.plugin.config.relationships.enabled:
            return None
        return self.overrides.get(account)

    async def describe(self, account: str) -> dict[str, Any]:
        owners = await self.plugin.role_recognition.admin_accounts()
        role = self.plugin.role_recognition
        if account in owners:
            level = "主人"
        elif self.plugin.config.relationships.enabled and account in self.overrides:
            level = "熟人" if self.overrides[account] == "familiar" else "陌生人"
        elif account in self.plugin.config.role_recognition.familiar_accounts or account in role.auto_familiar_accounts:
            level = "熟人"
        else:
            level = "陌生人"
        return {
            "account": account, "level": level,
            "interactions": role.interaction_counts.get(account, 0),
            "threshold": self.plugin.config.role_recognition.auto_upgrade_threshold,
            "manual_override": self.overrides.get(account, ""),
            "auto_familiar": account in role.auto_familiar_accounts,
        }

    async def list_rows(self) -> list[dict[str, Any]]:
        role = self.plugin.role_recognition
        accounts = set(role.interaction_counts) | role.auto_familiar_accounts | set(self.overrides) | set(self.plugin.config.role_recognition.familiar_accounts)
        return [await self.describe(account) for account in sorted(accounts)][:1000]

    async def change(self, action: str, account: str) -> dict[str, Any]:
        if not self.plugin.config.relationships.enabled:
            return {"success": False, "error": "关系管理模块尚未启用"}
        try:
            account = normalize_admin_account(account)
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        if account in await self.plugin.role_recognition.admin_accounts(force_refresh=True):
            return {"success": False, "error": "主人身份由管理员权限决定，不能在关系管理中改成其他级别"}
        if action not in {"familiar", "stranger", "reset"}:
            return {"success": False, "error": "action 只能为 familiar、stranger 或 reset"}
        async with self.plugin._lock:
            if action == "reset":
                self.overrides.pop(account, None)
                self.plugin.role_recognition.interaction_counts.pop(account, None)
                self.plugin.role_recognition.auto_familiar_accounts.discard(account)
            else:
                self.overrides[account] = action
            self.plugin._save_state()
        result = await self.describe(account)
        return {"success": True, "content": f"{account} 现在是{result['level']}；互动记录 {result['interactions']} 次。", "relationship": result}

    async def tool(self, action: str = "show", target: str = "", **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip():
            return {"success": False, "error": "无法核验当前聊天流"}
        actor = self.plugin.role_recognition.peek_planner_speaker(stream_id)
        if not actor:
            return {"success": False, "error": "无法核验本轮真实发言者"}
        admins = await self.plugin.role_recognition.admin_accounts(force_refresh=True)
        is_admin = actor in admins
        if action == "list":
            if not is_admin:
                return {"success": False, "error": "只有管理员能查看全部关系"}
            rows = await self.list_rows()
            return {"success": True, "content": f"已记录 {len(rows)} 个账号的关系。", "relationships": rows}
        account = actor if target.strip() in {"", "我", "自己", "当前用户"} else target.strip()
        try:
            account = normalize_admin_account(account)
        except ValueError:
            return {"success": False, "error": "请提供准确账号，例如 qq:123456789；也可说‘我’"}
        if action == "show":
            if not is_admin and account != actor:
                return {"success": False, "error": "只能查看自己的关系"}
            row = await self.describe(account)
            return {"success": True, "content": f"{row['account']}：{row['level']}，已计 {row['interactions']} 次互动；超过 {row['threshold']} 次自动成为熟人。", "relationship": row}
        if not is_admin:
            return {"success": False, "error": "只有管理员能修改关系"}
        return await self.change(action, account)

    async def webui_list(self) -> dict[str, Any]:
        return {"relationships": await self.list_rows()}
