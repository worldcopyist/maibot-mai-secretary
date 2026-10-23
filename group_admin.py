"""QQ group administration through the public NapCat adapter API.

All model tools bind to the current MaiBot stream and a verified human speaker.
NapCat's inner status is checked separately from MaiBot's API wrapper status.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any

LOG = logging.getLogger(__name__)
_API = "adapter.napcat.group."


def _qq(value: Any) -> str:
    value = str(value or "").strip()
    return value if value.isascii() and value.isdecimal() and int(value) > 0 else ""


def _result(response: Any) -> Any:
    if not isinstance(response, dict) or response.get("success") is not True:
        raise RuntimeError(str(response.get("error") if isinstance(response, dict) else "适配器接口未响应"))
    return response.get("result")


def _accepted(response: Any) -> Any:
    result = _result(response)
    if not isinstance(result, dict) or str(result.get("status") or "").lower() != "ok" or result.get("retcode") != 0:
        detail = result.get("message") or result.get("wording") or result.get("retcode") if isinstance(result, dict) else "无有效回执"
        raise RuntimeError(f"QQ 群操作未成功：{detail}")
    return result.get("data")


def _pending_rows(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, dict) and "status" in data:
        if str(data.get("status") or "").lower() != "ok" or data.get("retcode") != 0:
            raise RuntimeError(f"查询加群申请失败：{data.get('wording') or data.get('message') or data.get('retcode')}")
        data = data.get("data")
    if data is None:
        return []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("join_requests") or data.get("joinRequests") or data.get("join_request") or []
    else:
        raise TypeError("NapCat 没有返回可识别的加群申请列表")
    if not isinstance(rows, list):
        raise TypeError("NapCat 加群申请列表格式不正确")
    return [row for row in rows if isinstance(row, dict)]


class GroupAdminModule:
    name = "group_admin"
    state_keys = frozenset({"group_admin_state"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.welcome_seen: dict[str, float] = {}
        self.review_seen: dict[str, float] = {}
        self.welcome_overrides: dict[str, dict[str, Any]] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        raw = data.get("group_admin_state", {})
        if not isinstance(raw, dict):
            raise TypeError("群管状态格式错误")
        for name in ("welcome_seen", "review_seen"):
            rows = raw.get(name, {})
            if not isinstance(rows, dict):
                raise TypeError("群管状态格式错误")
            setattr(self, name, {str(k): float(v) for k, v in rows.items() if isinstance(v, (int, float))})
        overrides = raw.get("welcome_overrides", {})
        if not isinstance(overrides, dict):
            raise TypeError("入群欢迎配置格式错误")
        self.welcome_overrides = {
            str(group): {"enabled": bool(value.get("enabled")), "text": str(value.get("text") or "")}
            for group, value in overrides.items() if _qq(group) and isinstance(value, dict)
        }
        self._prune()

    def dump_state(self, payload: dict[str, Any]) -> None:
        self._prune()
        if self.welcome_seen or self.review_seen or self.welcome_overrides:
            payload["group_admin_state"] = {"welcome_seen": self.welcome_seen, "review_seen": self.review_seen, "welcome_overrides": self.welcome_overrides}

    def on_config_update(self) -> None:
        pass

    def _prune(self) -> None:
        cutoff = time.time() - 7 * 86400
        self.welcome_seen = {k: v for k, v in self.welcome_seen.items() if v >= cutoff}
        self.review_seen = {k: v for k, v in self.review_seen.items() if v >= cutoff}

    async def _call(self, name: str, *, params: dict[str, Any] | None = None, **kwargs: Any) -> Any:
        configured = self.plugin.config.group_admin.adapter_plugin_id.strip()
        api = f"{configured}.{_API}{name}" if configured else f"{_API}{name}"
        if params is not None:
            kwargs["params"] = params
        return await self.plugin.ctx.api.call(api, **kwargs)

    async def _stream(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip():
            raise ValueError("无法核验当前聊天流")
        response = await self.plugin.ctx.chat.get_all_streams(platform="qq")
        streams = response if isinstance(response, list) else response.get("streams") if isinstance(response, dict) and response.get("success") is not False else None
        if not isinstance(streams, list):
            raise TypeError("无法读取当前 QQ 聊天流")
        matches = [row for row in streams if isinstance(row, dict) and str(row.get("stream_id") or row.get("session_id") or "") == stream_id]
        if len(matches) != 1 or matches[0].get("platform") != "qq" or matches[0].get("chat_type") != "group":
            raise ValueError("群管工具仅能用于当前 QQ 群聊")
        stream = matches[0]
        group_id = _qq(stream.get("group_id"))
        if not group_id or not _qq(stream.get("account_id")):
            raise ValueError("当前群聊缺少可靠的群号或麦麦账号")
        if group_id not in self.plugin.config.group_admin.managed_group_ids:
            raise ValueError("这个群没有在小秘书群管模块中启用")
        return stream

    async def _actor(self, stream_id: str, *, consume: bool) -> str:
        role = self.plugin.role_recognition
        account = role.consume_planner_speaker(stream_id) if consume else role.peek_planner_speaker(stream_id)
        if not account or account not in await role.admin_accounts(force_refresh=True):
            raise ValueError("只能由已核验的小秘书管理员在当前群聊请求群管操作")
        return account

    async def _bot_role(self, group_id: str, bot_id: str) -> str:
        result = _result(await self._call("get_group_member_info", group_id=int(group_id), user_id=int(bot_id), no_cache=True))
        if not isinstance(result, dict) or _qq(result.get("user_id")) != bot_id:
            raise RuntimeError("无法核验麦麦在本群的身份")
        role = str(result.get("role") or "").lower()
        if role not in {"owner", "admin", "member"}:
            raise RuntimeError("NapCat 没有返回可识别的群身份")
        return role

    async def _preflight(self, kwargs: dict[str, Any], *, consume: bool, owner_only: bool = False) -> tuple[dict[str, Any], str]:
        settings = self.plugin.config.group_admin
        if not self.plugin.config.plugin.enabled or not settings.enabled:
            raise ValueError("小秘书群管模块未启用")
        stream = await self._stream(kwargs)
        stream_id = str(kwargs["stream_id"])
        await self._actor(stream_id, consume=consume)
        role = await self._bot_role(_qq(stream["group_id"]), _qq(stream["account_id"]))
        if role not in ({"owner"} if owner_only else {"owner", "admin"}):
            raise ValueError("麦麦在当前群没有执行这项群管理操作的权限")
        return stream, role

    async def permission(self, **kwargs: Any) -> dict[str, Any]:
        try:
            if not self.plugin.config.plugin.enabled or not self.plugin.config.group_admin.enabled:
                raise ValueError("小秘书群管模块未启用")
            stream = await self._stream(kwargs)
            role = await self._bot_role(_qq(stream["group_id"]), _qq(stream["account_id"]))
            names = {"owner": "群主", "admin": "管理员", "member": "普通成员"}
            return {"success": True, "content": f"麦麦在群 {_qq(stream['group_id'])} 的身份是{names[role]}；{'有' if role in {'owner', 'admin'} else '没有'}群管理权限。", "role": role, "can_manage": role in {"owner", "admin"}}
        except (ValueError, RuntimeError, TypeError) as exc:
            return {"success": False, "error": str(exc), "can_manage": False}

    async def _member(self, group_id: str, target: str) -> dict[str, Any]:
        user_id = _qq(target)
        if not user_id:
            raise ValueError("请使用准确的 QQ 号指定群成员")
        member = _result(await self._call("get_group_member_info", group_id=int(group_id), user_id=int(user_id), no_cache=True))
        if not isinstance(member, dict) or _qq(member.get("user_id")) != user_id:
            raise ValueError("该 QQ 号不是当前群成员，或成员信息暂时不可用")
        return member

    async def member(self, action: str, target: str = "", duration_minutes: int = 0, text: str = "", enable: bool = False, **kwargs: Any) -> dict[str, Any]:
        try:
            action = str(action).strip().lower()
            if action not in {"mute", "unmute", "kick", "card", "title", "admin", "whole_mute", "whole_unmute", "rename"}:
                raise ValueError("不支持的群成员或群设置操作")
            stream, bot_role = await self._preflight(kwargs, consume=True, owner_only=action in {"title", "admin"})
            group_id = _qq(stream["group_id"])
            bot_id = _qq(stream["account_id"])
            if action in {"whole_mute", "whole_unmute"}:
                response = await self._call("set_group_whole_ban", group_id=int(group_id), enable=action == "whole_mute")
            elif action == "rename":
                value = str(text).strip()
                if not 1 <= len(value) <= 60:
                    raise ValueError("群名须为 1–60 个字符")
                response = await self._call("set_group_name", group_id=int(group_id), group_name=value)
            else:
                member = await self._member(group_id, target)
                user_id = _qq(member["user_id"])
                target_role = str(member.get("role") or "").lower()
                if user_id == bot_id or target_role == "owner":
                    raise ValueError("不能操作麦麦自己或群主")
                if action in {"mute", "unmute", "kick"} and target_role == "admin" and bot_role != "owner":
                    raise ValueError("麦麦不是群主，不能管理其他群管理员")
                if action in {"mute", "unmute"}:
                    minutes = int(duration_minutes)
                    if action == "mute" and not 1 <= minutes <= 43200:
                        raise ValueError("禁言时长须为 1–43200 分钟")
                    response = await self._call("set_group_ban", group_id=int(group_id), user_id=int(user_id), duration=minutes * 60 if action == "mute" else 0)
                elif action == "kick":
                    response = await self._call("set_group_kick", group_id=int(group_id), user_id=int(user_id), reject_add_request=bool(enable))
                elif action == "card":
                    value = str(text).strip()
                    if not 1 <= len(value) <= 60:
                        raise ValueError("群名片须为 1–60 个字符")
                    response = await self._call("set_group_card", params={"group_id": int(group_id), "user_id": int(user_id), "card": value})
                elif action == "title":
                    value = str(text).strip()
                    if not 1 <= len(value) <= 30:
                        raise ValueError("群头衔须为 1–30 个字符")
                    response = await self._call("set_group_special_title", params={"group_id": int(group_id), "user_id": int(user_id), "special_title": value})
                else:
                    response = await self._call("set_group_admin", params={"group_id": int(group_id), "user_id": int(user_id), "enable": bool(enable)})
            _accepted(response)
            return {"success": True, "content": f"QQ群 {group_id} 的 {action} 操作已由 NapCat 确认成功。"}
        except (ValueError, RuntimeError, TypeError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception:
            LOG.exception("小秘书群成员操作失败")
            return {"success": False, "error": "群管理操作发生异常，请稍后重试"}

    async def notice(self, action: str, text: str = "", notice_id: str = "", **kwargs: Any) -> dict[str, Any]:
        try:
            action = str(action).strip().lower()
            if action not in {"list", "create", "delete"}:
                raise ValueError("公告操作只支持 list、create、delete")
            stream, _ = await self._preflight(kwargs, consume=action != "list")
            group_id = _qq(stream["group_id"])
            if action == "list":
                data = _accepted(await self._call("get_group_notice", params={"group_id": int(group_id)}))
                return {"success": True, "content": "以下是当前群公告；删除时使用准确公告 ID。", "notices": data}
            if action == "create":
                value = str(text).strip()
                if not 1 <= len(value) <= 2000:
                    raise ValueError("公告正文须为 1–2000 个字符")
                response = await self._call("send_group_notice", params={"group_id": int(group_id), "content": value})
            else:
                value = str(notice_id).strip()
                if not value or len(value) > 128:
                    raise ValueError("请先查询公告并填写准确公告 ID")
                response = await self._call("delete_group_notice", params={"group_id": int(group_id), "notice_id": value})
            data = _accepted(response)
            return {"success": True, "content": f"QQ群 {group_id} 的公告 {action} 操作已确认成功。", "data": data}
        except (ValueError, RuntimeError, TypeError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception:
            LOG.exception("小秘书公告操作失败")
            return {"success": False, "error": "群公告操作发生异常，请稍后重试"}

    async def _pending(self, group_id: str) -> list[dict[str, Any]]:
        raw = _result(await self._call("get_group_system_msg", params={}))
        rows = _pending_rows(raw)
        return [row for row in rows if _qq(row.get("group_id")) == group_id and row.get("checked") not in {True, "1"}]

    @staticmethod
    def _request_id(row: dict[str, Any]) -> str:
        return str(row.get("request_id") or row.get("flag") or row.get("requestId") or "").strip()

    async def join(self, action: str, request_id: str = "", reason: str = "", **kwargs: Any) -> dict[str, Any]:
        try:
            action = str(action).strip().lower()
            if action not in {"list", "approve", "reject"}:
                raise ValueError("进群审核只支持 list、approve、reject")
            stream, _ = await self._preflight(kwargs, consume=action != "list")
            group_id = _qq(stream["group_id"])
            pending = await self._pending(group_id)
            if action == "list":
                safe = [{"request_id": self._request_id(row), "user_id": _qq(row.get("requester_uin") or row.get("user_id")), "nickname": str(row.get("requester_nick") or row.get("nickname") or "")[:80], "comment": str(row.get("comment") or row.get("message") or "")[:300]} for row in pending]
                return {"success": True, "content": f"QQ群 {group_id} 当前有 {len(safe)} 条待审加群申请。", "requests": safe}
            wanted = str(request_id).strip()
            matched = [row for row in pending if self._request_id(row) == wanted]
            if not wanted or len(matched) != 1:
                raise ValueError("没有找到唯一的待审申请；请先用 list 查询准确 request_id")
            response = await self._call("set_group_add_request", params={"flag": wanted, "sub_type": "add", "approve": action == "approve", "reason": str(reason).strip()[:200] if action == "reject" else ""})
            _accepted(response)
            self.review_seen[f"{group_id}:{wanted}"] = time.time()
            self.plugin._save_state()
            return {"success": True, "content": f"QQ群 {group_id} 的申请 {wanted} 已{'通过' if action == 'approve' else '拒绝'}，NapCat 已确认。"}
        except (ValueError, RuntimeError, TypeError) as exc:
            return {"success": False, "error": str(exc)}
        except Exception:
            LOG.exception("小秘书进群审核失败")
            return {"success": False, "error": "进群审核发生异常，请稍后重试"}

    async def welcome(self, action: str, text: str = "", **kwargs: Any) -> dict[str, Any]:
        try:
            action = str(action).strip().lower()
            if action not in {"show", "set", "enable", "disable", "reset"}:
                raise ValueError("欢迎语操作只支持 show、set、enable、disable、reset")
            if not self.plugin.config.plugin.enabled or not self.plugin.config.group_admin.enabled:
                raise ValueError("小秘书群管模块未启用")
            stream = await self._stream(kwargs)
            group_id = _qq(stream["group_id"])
            await self._actor(str(kwargs["stream_id"]), consume=action != "show")
            config = self.plugin.config.group_admin
            if action == "reset":
                self.welcome_overrides.pop(group_id, None)
            elif action != "show":
                current = dict(self.welcome_overrides.get(group_id) or {"enabled": config.welcome_enabled, "text": config.welcome_template})
                if action == "set":
                    value = str(text).strip()
                    if not 1 <= len(value) <= 500:
                        raise ValueError("欢迎语须为 1–500 个字符")
                    current["text"] = value
                else:
                    current["enabled"] = action == "enable"
                self.welcome_overrides[group_id] = current
            if action != "show":
                self.plugin._save_state()
            current = self.welcome_overrides.get(group_id) or {"enabled": config.welcome_enabled, "text": config.welcome_template}
            return {"success": True, "content": f"QQ群 {group_id} 入群欢迎{'已开启' if current['enabled'] else '已关闭'}；欢迎语：{current['text']}。", "enabled": bool(current["enabled"]), "text": current["text"]}
        except (ValueError, RuntimeError, TypeError) as exc:
            return {"success": False, "error": str(exc)}

    async def on_notice(self, message: dict[str, Any] | None) -> None:
        settings = self.plugin.config.group_admin
        if not self.plugin.config.plugin.enabled or not settings.enabled:
            return
        if not isinstance(message, dict) or message.get("platform") != "qq" or not message.get("is_notify"):
            return
        info = message.get("message_info")
        extra = info.get("additional_config") if isinstance(info, dict) else None
        if not isinstance(extra, dict) or extra.get("napcat_notice_type") != "group_increase":
            return
        payload = extra.get("napcat_notice_payload")
        if not isinstance(payload, dict):
            return
        group_id, user_id = _qq(payload.get("group_id")), _qq(payload.get("user_id"))
        bot_id = _qq(payload.get("self_id") or message.get("account_id"))
        if group_id not in settings.managed_group_ids or not user_id or user_id == bot_id:
            return
        welcome_config = self.welcome_overrides.get(group_id) or {"enabled": settings.welcome_enabled, "text": settings.welcome_template}
        if not welcome_config["enabled"]:
            return
        event_key = f"{group_id}:{user_id}:{payload.get('time') or message.get('message_id') or ''}"
        if event_key in self.welcome_seen:
            return
        name = str((info.get("user_info") or {}).get("user_nickname") or "新朋友") if isinstance(info, dict) else "新朋友"
        name = " ".join(name.split())[:40] or "新朋友"
        welcome = str(welcome_config["text"]).replace("{name}", name).replace("{qq}", user_id).replace("{group}", group_id)
        try:
            _accepted(await self._call("send_group_msg", params={"group_id": int(group_id), "message": welcome}))
            self.welcome_seen[event_key] = time.time()
            self.plugin._save_state()
        except Exception:
            LOG.exception("小秘书入群欢迎发送失败：group=%s user=%s", group_id, user_id)

    async def tick(self, now: datetime) -> None:
        del now
        self._prune()
        settings = self.plugin.config.group_admin
        if not self.plugin.config.plugin.enabled or not settings.enabled or settings.review_mode != "keyword" or not settings.managed_group_ids:
            return
        response = await self.plugin.ctx.chat.get_all_streams(platform="qq")
        streams = response if isinstance(response, list) else response.get("streams") if isinstance(response, dict) and response.get("success") is not False else None
        if not isinstance(streams, list):
            return
        for group_id in settings.managed_group_ids:
            try:
                matching = [row for row in streams if isinstance(row, dict) and row.get("platform") == "qq" and row.get("chat_type") == "group" and _qq(row.get("group_id")) == group_id and _qq(row.get("account_id"))]
                if len(matching) != 1 or await self._bot_role(group_id, _qq(matching[0]["account_id"])) not in {"owner", "admin"}:
                    continue
                pending = await self._pending(group_id)
                for row in pending:
                    request_id = self._request_id(row)
                    if not request_id or f"{group_id}:{request_id}" in self.review_seen:
                        continue
                    comment = str(row.get("comment") or row.get("message") or row.get("answer") or "").casefold()
                    reject = any(word.casefold() in comment for word in settings.review_reject_words if word)
                    accept = any(word.casefold() in comment for word in settings.review_accept_words if word)
                    if not (reject or accept):
                        continue
                    response = await self._call("set_group_add_request", params={"flag": request_id, "sub_type": "add", "approve": not reject, "reason": settings.review_reject_reason if reject else ""})
                    _accepted(response)
                    self.review_seen[f"{group_id}:{request_id}"] = time.time()
                    self.plugin._save_state()
            except Exception:
                LOG.exception("小秘书自动进群审核失败：group=%s", group_id)
