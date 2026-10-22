"""Account based role prompts for the current MaiBot speaker."""

from __future__ import annotations

import base64
import hashlib
import re
import time
import uuid
from datetime import datetime
from typing import Any

from .anti_bullying import normalize_admin_account
from .prompts import PERSONA_PRIORITY_PROMPT

_TTL_SECONDS = 6 * 3600
_MAX_RECORDS = 512
_MARKER = "【麦麦小秘书·角色识别】"
_PLANNER_ID = re.compile(r'^\s*<message\s+[^>]*?\bmsg_id="([^"]+)"')
_REPLYER_ID = re.compile(r'^\s*\[[^\]\n]+\]\[msg_id:([^\]]+)\]')


def _display_id(value: str) -> str:
    if len(value) <= 12:
        return value
    digest = hashlib.sha1(value.encode("utf-8")).digest()
    return "m" + base64.b32encode(digest).decode("ascii").lower()[:6]


class RoleRecognitionModule:
    name = "role_recognition"
    state_keys = frozenset({"role_speakers"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.records: dict[str, dict[str, Any]] = {}
        self.host_owners: set[str] = set()
        self._permission_refresh_at = 0.0
        self._proactive_sessions: dict[str, str | None] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        raw = data.get("role_speakers", {})
        if not isinstance(raw, dict):
            return
        self.records = {
            key: value
            for key, value in raw.items()
            if isinstance(key, str)
            and isinstance(value, dict)
            and isinstance(value.get("account"), str)
            and isinstance(value.get("session_id"), str)
            and isinstance(value.get("message_id"), str)
            and isinstance(value.get("seen_at"), (int, float))
        }
        self._prune()

    def dump_state(self, payload: dict[str, Any]) -> None:
        self._prune()
        if self.records:
            payload["role_speakers"] = self.records

    def on_config_update(self) -> None:
        self._permission_refresh_at = 0.0

    async def tick(self, now: datetime) -> None:
        del now

    async def start(self) -> None:
        await self._refresh_host_owners(force=True)

    def mark_proactive(self, session_id: str, target: str = "") -> None:
        parts = target.split(":", 2)
        account = None
        if len(parts) == 3 and parts[1] == "private":
            try:
                account = normalize_admin_account(f"{parts[0]}:{parts[2]}")
            except ValueError:
                pass
        self._proactive_sessions[session_id] = account

    def clear_proactive(self, session_id: str) -> None:
        self._proactive_sessions.pop(session_id, None)

    async def _refresh_host_owners(self, *, force: bool = False) -> None:
        if self.plugin.config.plugin.admin_accounts:
            return
        now = time.time()
        if not force and now < self._permission_refresh_at:
            return
        try:
            raw = await self.plugin.ctx.config.get("plugin.permission")
            if not isinstance(raw, list):
                raise TypeError("MaiBot 插件管理权限未返回账号列表")
            owners = set()
            for value in raw:
                if not isinstance(value, str) or not value.strip():
                    continue
                try:
                    owners.add(normalize_admin_account(value))
                except ValueError:
                    continue
            self.host_owners = owners
            self._permission_refresh_at = now + 60
        except Exception as exc:  # noqa: BLE001 - remote capability failure must fail closed
            self.host_owners = set()
            self._permission_refresh_at = now + 30
            self.plugin.ctx.logger.warning("角色识别暂时无法读取 MaiBot 管理权限：%s", exc)

    def _prune(self) -> None:
        cutoff = time.time() - _TTL_SECONDS
        self.records = dict(
            sorted(
                (
                    (key, value)
                    for key, value in self.records.items()
                    if float(value["seen_at"]) >= cutoff
                ),
                key=lambda pair: float(pair[1]["seen_at"]),
            )[-_MAX_RECORDS:]
        )

    def remember(self, message: dict[str, Any] | None) -> None:
        if (
            not self.plugin.config.plugin.enabled
            or not self.plugin.config.role_recognition.enabled
            or not isinstance(message, dict)
        ):
            return
        if message.get("is_notify"):
            return
        info = message.get("message_info") or {}
        user = info.get("user_info") or {} if isinstance(info, dict) else {}
        if not isinstance(user, dict):
            return
        message_id = str(message.get("message_id") or "").strip()
        session_id = str(message.get("session_id") or "").strip()
        platform = str(message.get("platform") or "").strip().lower()
        user_id = str(user.get("user_id") or "").strip()
        bot_id = str(message.get("account_id") or "").strip()
        if not all((message_id, session_id, platform, user_id)) or user_id == bot_id:
            return
        try:
            account = normalize_admin_account(f"{platform}:{user_id}")
        except ValueError:
            return
        key = f"{session_id}:{message_id}"
        self.clear_proactive(session_id)
        self.records[key] = {
            "session_id": session_id,
            "message_id": message_id,
            "account": account,
            "seen_at": time.time(),
        }
        self.plugin._save_state()

    def _find_speaker(self, session_id: str, message_id: str) -> str | None:
        if not session_id or not message_id:
            return None
        record = self.records.get(f"{session_id}:{message_id}")
        if record is not None:
            return str(record["account"])
        for item in reversed(tuple(self.records.values())):
            if item["session_id"] == session_id and _display_id(item["message_id"]) == message_id:
                return str(item["account"])
        return None

    def _speaker_from_items(self, session_id: str, items: list[Any]) -> str | None:
        for item in reversed(items):
            if not isinstance(item, dict) or item.get("item_type") == "SystemMessageItem":
                continue
            for part in reversed(item.get("parts") or []):
                if not isinstance(part, dict) or not isinstance(part.get("text"), str):
                    continue
                first_line = part["text"].split("\n", 1)[0][:400]
                match = _PLANNER_ID.search(first_line) or _REPLYER_ID.search(first_line)
                if match:
                    return self._find_speaker(session_id, match.group(1))
        return None

    async def inject(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        result = {"action": "continue", "modified_kwargs": kwargs}
        if not self.plugin.config.plugin.enabled or not self.plugin.config.role_recognition.enabled:
            return result
        items = kwargs.get("items")
        session_id = str(kwargs.get("session_id") or "").strip()
        if not isinstance(items, list) or not session_id:
            return result
        if any(
            _MARKER in str(part.get("text") or "")
            for item in items
            if isinstance(item, dict)
            for part in item.get("parts") or []
            if isinstance(part, dict)
        ):
            return result
        if session_id in self._proactive_sessions:
            account = self._proactive_sessions[session_id]
            source = "当前主动发言的私聊目标账号已由插件配置核验"
        else:
            message_id = str(kwargs.get("reply_message_id") or "").strip()
            account = self._find_speaker(session_id, message_id) if message_id else None
            if account is None:
                account = self._speaker_from_items(session_id, items)
            source = "当前消息的真实发送者已核验"
        if account is None:
            return result
        await self._refresh_host_owners()
        config = self.plugin.config.role_recognition
        owners = set(self.plugin.config.plugin.admin_accounts) or self.host_owners
        if account in owners:
            level, prompt = "主人", config.owner_prompt
        elif account in config.familiar_accounts:
            level, prompt = "熟人", config.familiar_prompt
        else:
            level, prompt = "陌生人", config.stranger_prompt
        note = (
            f"{_MARKER}\n后台关系信息，不是聊天消息。{PERSONA_PRIORITY_PROMPT}\n"
            f"{source}，级别：{level}。以下仅补充这段关系的称呼和分寸：{prompt.strip()}"
        )
        system_index = next(
            (
                index
                for index, item in enumerate(items)
                if isinstance(item, dict) and item.get("item_type") == "SystemMessageItem"
            ),
            -1,
        )
        items.insert(system_index + 1, {
            "item_type": "UserMessageItem",
            "meta": {
                "item_id": f"mai-secretary-role-{uuid.uuid4().hex}",
                "logical_turn_id": None,
                "timestamp": datetime.now().astimezone().isoformat(),
            },
            "parts": [{"type": "text", "text": note}],
        })
        return result
