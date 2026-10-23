"""Read saved DeepSeek balance snapshots and alert verified administrators."""

from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from .deepseek_web import WebSearchError
from .prompts import PERSONA_PRIORITY_PROMPT
from .stream_router import resolve_stream


class BlueberryBudgetModule:
    name = "blueberry_budget"
    state_keys = frozenset({"blueberry_budget_state"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.alerted: dict[str, float] = {}
        self.pending: dict[str, dict[str, Any]] = {}
        self.threshold_override: float | None = None
        self.streams: dict[str, str] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        raw = data.get("blueberry_budget_state", {})
        if not isinstance(raw, dict):
            raise TypeError("蓝莓预算状态格式错误")
        alerted = raw.get("alerted", {})
        pending = raw.get("pending", {})
        self.alerted = {str(key): float(stamp) for key, stamp in alerted.items() if isinstance(stamp, (int, float))} if isinstance(alerted, dict) else {}
        self.pending = {str(key): value for key, value in pending.items() if isinstance(value, dict)} if isinstance(pending, dict) else {}
        override = raw.get("threshold_override")
        self.threshold_override = float(override) if isinstance(override, (int, float)) and 0 <= float(override) <= 1000000 else None

    def dump_state(self, payload: dict[str, Any]) -> None:
        if self.alerted or self.pending or self.threshold_override is not None:
            payload["blueberry_budget_state"] = {
                "alerted": self.alerted, "pending": self.pending,
                "threshold_override": self.threshold_override,
            }

    def on_config_update(self) -> None:
        self.streams.clear()

    @property
    def threshold(self) -> Decimal:
        value = self.threshold_override if self.threshold_override is not None else self.plugin.config.blueberry_budget.low_balance_threshold
        return Decimal(str(value))

    def on_snapshot(self, snapshot: dict[str, Any]) -> None:
        if not self.plugin.config.blueberry_budget.enabled:
            return
        fingerprint = str(snapshot.get("account_fingerprint") or "")
        if not fingerprint:
            return
        changed = False
        for item in snapshot.get("balance_infos") or []:
            if not isinstance(item, dict):
                continue
            currency = str(item.get("currency") or "")
            try:
                amount = Decimal(str(item.get("total_balance")))
            except InvalidOperation:
                continue
            key = f"{fingerprint}:{currency}"
            if amount > self.threshold:
                changed = bool(self.alerted.pop(key, None) is not None or self.pending.pop(key, None) is not None) or changed
                continue
            if snapshot.get("source") != "automatic":
                continue  # The manual balance answer already tells the administrator.
            cooldown = self.plugin.config.blueberry_budget.alert_cooldown_hours * 3600
            if time.time() - self.alerted.get(key, 0) < cooldown or key in self.pending:
                continue
            self.pending[key] = {
                "currency": currency, "amount": str(amount), "queried_at": snapshot.get("queried_at"),
                "alias": snapshot.get("alias") or "API 余额", "created_at": time.time(),
            }
            changed = True
        if changed:
            self.plugin._save_state()
            self.plugin._wake.set()

    async def tick(self, now: datetime) -> None:
        del now
        if not self.plugin.config.blueberry_budget.enabled or not self.plugin.config.deepseek_web.enabled:
            return
        if not self.pending:
            return
        try:
            current_fingerprint = self.plugin.deepseek_web._account_fingerprint()
        except WebSearchError:
            return
        admins = await self.plugin.role_recognition.admin_accounts()
        targets = sorted(account for account in admins if account.startswith("qq:"))
        if not targets:
            return
        for key, item in list(self.pending.items()):
            if not key.startswith(f"{current_fingerprint}:"):
                self.pending.pop(key, None)
                self.plugin._save_state()
                continue
            if time.time() - float(item.get("created_at", 0)) > 86400:
                self.pending.pop(key, None)
                self.plugin._save_state()
                continue
            sent_any = False
            for account in targets:
                target = f"qq:private:{account.split(':', 1)[1]}"
                try:
                    stream_id = await resolve_stream(self.plugin.ctx, target, self.streams)
                    intent = (
                        f"{PERSONA_PRIORITY_PROMPT}\n"
                        f"小秘书自动查询发现你珍惜的{item['alias']}余额较低："
                        f"{item['currency']} {item['amount']}，查询时间 {item['queried_at']}。"
                        f"管理员设定的提醒线是 {self.threshold}。请在这个私聊中按麦麦现有人设自然提醒主人，"
                        "说明这是上次查询时的数字，不要猜测现在余额，也不要公开到群聊。"
                    )
                    await self.plugin._trigger(stream_id, intent, "蓝莓预算低余额提醒", key, requester_account=account)
                    sent_any = True
                except Exception:
                    self.plugin.ctx.logger.exception("蓝莓预算提醒未能送达管理员")
            if sent_any:
                self.alerted[key] = time.time()
                self.pending.pop(key, None)
                self.plugin._save_state()

    def status(self) -> dict[str, Any]:
        web = self.plugin.deepseek_web
        snapshot = web._latest_balance
        recent: list[dict[str, Any]] = []
        if snapshot is not None and web._balance_store is not None:
            recent = web._balance_store.recent(str(snapshot["account_fingerprint"]), limit=10)
        trend: list[dict[str, str]] = []
        if len(recent) >= 2:
            previous = {row.get("currency"): row for row in recent[1].get("balance_infos") or [] if isinstance(row, dict)}
            for current in recent[0].get("balance_infos") or []:
                if not isinstance(current, dict) or current.get("currency") not in previous:
                    continue
                try:
                    difference = Decimal(str(current["total_balance"])) - Decimal(str(previous[current["currency"]]["total_balance"]))
                except (InvalidOperation, KeyError):
                    continue
                trend.append({"currency": str(current["currency"]), "change_since_previous": str(difference)})
        return {
            "enabled": self.plugin.config.blueberry_budget.enabled,
            "threshold": str(self.threshold), "snapshot": snapshot,
            "recent": recent, "trend": trend,
            "pending_alerts": len(self.pending),
        }

    async def set_threshold(self, amount: float) -> dict[str, Any]:
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not 0 <= amount <= 1000000:
            return {"success": False, "error": "提醒线须为 0 到 1000000 之间的数字"}
        async with self.plugin._lock:
            self.threshold_override = float(amount)
            self.plugin._save_state()
        return {"success": True, "content": f"已把蓝莓低余额提醒线设为 {self.threshold}（按余额币种分别比较）"}

    async def tool(self, action: str = "status", amount: float = 0, **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip():
            return {"success": False, "error": "无法核验当前聊天流"}
        actor = self.plugin.role_recognition.peek_planner_speaker(stream_id)
        if not actor or actor not in await self.plugin.role_recognition.admin_accounts(force_refresh=True):
            return {"success": False, "error": "只有已核验管理员能查看和设置蓝莓预算"}
        if action == "set_threshold":
            return await self.set_threshold(amount)
        if action == "status":
            data = self.status()
            snapshot = data["snapshot"]
            return {"success": True, "content": f"提醒线 {data['threshold']}；最近余额查询：{snapshot['queried_at'] if snapshot else '暂无'}。差额仅比较两次记录，不等于准确消耗。", "budget": data}
        return {"success": False, "error": "action 只能为 status 或 set_threshold"}
