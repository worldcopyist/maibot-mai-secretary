"""Merge a user's quick consecutive messages before MaiBot processes them.

Adapted from Blackwindy2333/Message_Debouncing_Refactored (MIT); see
THIRD_PARTY_NOTICES.md. This module keeps message identity tied to the final
real inbound message so the secretary's role checks remain valid.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict, deque
from dataclasses import dataclass, field
from datetime import datetime
from time import monotonic
from typing import Any


@dataclass
class _Window:
    started: float
    event: asyncio.Event = field(default_factory=asyncio.Event)
    messages: list[dict[str, Any]] = field(default_factory=list)
    timer: asyncio.Task[None] | None = None
    generation: int = 0


class MessageDebounceModule:
    name = "message_debounce"
    state_keys: frozenset[str] = frozenset()

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self._windows: dict[tuple[str, str, str, str], _Window] = {}
        self._recent_private: OrderedDict[tuple[str, str, str], deque[tuple[str, float]]] = OrderedDict()
        self._lock = asyncio.Lock()

    def load_state(self, data: dict[str, Any]) -> None:
        del data

    def dump_state(self, payload: dict[str, Any]) -> None:
        del payload

    def on_config_update(self) -> None:
        # Existing short windows finish with the current configuration.
        pass

    async def tick(self, now: datetime) -> None:
        del now

    async def stop(self) -> None:
        async with self._lock:
            windows = list(self._windows.values())
            self._windows.clear()
            for window in windows:
                if window.timer is not None:
                    window.timer.cancel()
                window.event.set()
            self._recent_private.clear()

    async def on_inbound(self, message: dict[str, Any] | None) -> dict[str, Any] | None:
        cfg = self.plugin.config.message_debounce
        if not self.plugin.config.plugin.enabled or not cfg.enabled or not isinstance(message, dict):
            return None
        key = self._key(message)
        if key is None or not self._eligible(message, cfg):
            return None
        if cfg.suppress_stale_private_replies and not message["message_info"].get("group_info"):
            self._remember_private(key[:3], str(message["message_id"]))

        async with self._lock:
            window = self._windows.get(key)
            if window is not None:
                message_id = str(message.get("message_id") or "")
                if any(str(item.get("message_id") or "") == message_id for item in window.messages):
                    return {"action": "abort"}
                window.messages.append(message)
                if len(window.messages) >= 100:
                    self._windows.pop(key, None)
                    if window.timer is not None:
                        window.timer.cancel()
                    window.event.set()
                else:
                    self._schedule_locked(key, window, cfg)
                return {"action": "abort"}

            window = _Window(started=monotonic(), messages=[message])
            self._windows[key] = window
            self._schedule_locked(key, window, cfg)

        try:
            await window.event.wait()
        except asyncio.CancelledError:
            async with self._lock:
                if self._windows.get(key) is window:
                    self._windows.pop(key, None)
                    if window.timer is not None:
                        window.timer.cancel()
            raise

        if len(window.messages) == 1:
            return None
        merged = self._merge(window.messages, cfg.merge_separator)
        self.plugin.ctx.logger.info(
            "消息防抖合并：聊天流 %s、用户 %s、%d 条消息",
            key[2], key[3], len(window.messages),
        )
        return {"action": "continue", "modified_kwargs": {"message": merged}}

    def before_send(self, message: dict[str, Any] | None) -> dict[str, str] | None:
        """Cancel a private reply if a newer user message arrived while it was generated."""
        cfg = self.plugin.config.message_debounce
        if not (
            self.plugin.config.plugin.enabled
            and cfg.enabled
            and cfg.enable_private
            and cfg.suppress_stale_private_replies
        ):
            return None
        if not isinstance(message, dict):
            return None
        info = message.get("message_info")
        user = info.get("user_info") if isinstance(info, dict) else None
        if not isinstance(user, dict) or info.get("group_info"):
            return None
        if str(user.get("user_id") or "") != str(message.get("account_id") or ""):
            return None
        reply_to = str(message.get("reply_to") or "").strip()
        if not reply_to:
            return None
        key = tuple(str(message.get(part) or "").strip() for part in ("platform", "account_id", "session_id"))
        if not all(key):
            return None
        recent = self._recent_private.get(key)
        if not recent:
            return None
        now = monotonic()
        while recent and now - recent[0][1] > 120:
            recent.popleft()
        if len(recent) < 2 or reply_to == recent[-1][0]:
            return None
        if any(message_id == reply_to for message_id, _ in recent):
            self.plugin.ctx.logger.info("取消过时私聊回复：聊天流 %s、旧消息 %s", key[2], reply_to)
            return {"action": "abort"}
        return None

    def _remember_private(self, key: tuple[str, str, str], message_id: str) -> None:
        recent = self._recent_private.setdefault(key, deque(maxlen=32))
        if not recent or recent[-1][0] != message_id:
            recent.append((message_id, monotonic()))
        self._recent_private.move_to_end(key)
        if len(self._recent_private) > 1024:
            self._recent_private.popitem(last=False)

    def _schedule_locked(self, key: tuple[str, str, str, str], window: _Window, cfg: Any) -> None:
        if window.timer is not None:
            window.timer.cancel()
        window.generation += 1
        delay = min(cfg.debounce_seconds, max(0.0, cfg.max_wait_seconds - (monotonic() - window.started)))
        window.timer = asyncio.create_task(self._flush_later(key, window, window.generation, delay))

    async def _flush_later(
        self, key: tuple[str, str, str, str], window: _Window, generation: int, delay: float,
    ) -> None:
        try:
            await asyncio.sleep(delay)
            async with self._lock:
                if self._windows.get(key) is window and window.generation == generation:
                    self._windows.pop(key, None)
                    window.event.set()
        except asyncio.CancelledError:
            pass

    @staticmethod
    def _key(message: dict[str, Any]) -> tuple[str, str, str, str] | None:
        info = message.get("message_info")
        user = info.get("user_info") if isinstance(info, dict) else None
        if not isinstance(user, dict):
            return None
        key = tuple(str(value or "").strip() for value in (
            message.get("platform"), message.get("account_id"),
            message.get("session_id"), user.get("user_id"),
        ))
        if not all(key) or not str(message.get("message_id") or "").strip():
            return None
        return key  # type: ignore[return-value]

    @staticmethod
    def _text(message: dict[str, Any]) -> str:
        processed = message.get("processed_plain_text")
        if isinstance(processed, str) and processed.strip():
            return processed.strip()
        raw = message.get("raw_message")
        if not isinstance(raw, list):
            return ""
        return "".join(
            str(part.get("data")) for part in raw
            if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("data"), str)
        ).strip()

    def _eligible(self, message: dict[str, Any], cfg: Any) -> bool:
        if message.get("is_notify") or message.get("is_command"):
            return False
        info = message.get("message_info")
        group = info.get("group_info") if isinstance(info, dict) else None
        if (bool(group) and not cfg.enable_group) or (not group and not cfg.enable_private):
            return False
        text = self._text(message)
        if cfg.ignore_commands and any(text.startswith(prefix) for prefix in cfg.command_prefixes):
            return False
        raw = message.get("raw_message")
        return bool(text) or (
            isinstance(raw, list) and any(
                isinstance(part, dict) and part.get("type") in {"image", "emoji", "voice", "forward", "file"}
                for part in raw
            )
        )

    def _merge(self, messages: list[dict[str, Any]], separator: str) -> dict[str, Any]:
        # The final actual message supplies the ID and verified sender. A fresh
        # dictionary prevents mutation of an SDK payload held by another hook.
        merged = dict(messages[-1])
        merged_raw: list[dict[str, Any]] = []
        texts: list[str] = []
        for index, message in enumerate(messages):
            if index and separator:
                merged_raw.append({"type": "text", "data": separator})
            raw = message.get("raw_message")
            if isinstance(raw, list) and raw:
                merged_raw.extend(part for part in raw if isinstance(part, dict))
            elif text := self._text(message):
                merged_raw.append({"type": "text", "data": text})
            if text := self._text(message):
                texts.append(text)
        merged["raw_message"] = merged_raw
        merged["processed_plain_text"] = separator.join(texts)
        merged["is_emoji"] = all(bool(item.get("is_emoji")) for item in messages)
        merged["is_picture"] = any(bool(item.get("is_picture")) for item in messages)
        merged["is_at"] = any(bool(item.get("is_at")) for item in messages)
        merged["is_mentioned"] = any(bool(item.get("is_mentioned")) for item in messages)
        merged["is_command"] = False
        return merged
