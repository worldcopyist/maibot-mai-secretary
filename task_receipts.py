"""Track scheduled-task queue acceptance separately from actual message delivery."""

from __future__ import annotations

import time
import uuid
from datetime import datetime
from typing import Any

from .secretary_core import ScheduledTask


class TaskReceiptModule:
    name = "task_receipts"
    state_keys = frozenset({"task_receipts"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.records: list[dict[str, Any]] = []

    def load_state(self, data: dict[str, Any]) -> None:
        raw = data.get("task_receipts", [])
        if not isinstance(raw, list):
            raise TypeError("任务回执状态格式错误")
        self.records = [row for row in raw if isinstance(row, dict) and isinstance(row.get("id"), str)][-300:]

    def dump_state(self, payload: dict[str, Any]) -> None:
        if self.records:
            payload["task_receipts"] = self.records[-300:]

    def on_config_update(self) -> None:
        pass

    async def tick(self, now: datetime) -> None:
        if not self.plugin.config.task_receipts.enabled:
            return
        changed = False
        cutoff = now.timestamp() - self.plugin.config.task_receipts.wait_minutes * 60
        for row in self.records:
            if row.get("status") == "accepted" and float(row.get("accepted_at", 0)) < cutoff:
                row["status"] = "unknown"
                row["error"] = "已入队，但等待期内没有匹配到实际发送回执；不会自动重发"
                changed = True
        if changed:
            self.plugin._save_state()

    def accepted(self, task: Any, host_result: Any, *, retry_of: str = "") -> dict[str, Any] | None:
        if not self.plugin.config.task_receipts.enabled:
            return None
        host_id = str(host_result.get("task_id") or "").strip() if isinstance(host_result, dict) else ""
        row = {
            "id": uuid.uuid4().hex[:12],
            "task_id": task.id,
            "stream_id": task.stream_id,
            "owner_user_id": task.owner_user_id,
            "instruction": task.instruction[:200],
            "host_task_id": host_id,
            "accepted_at": time.time(),
            "status": "accepted" if host_id else "unknown",
            "sent_message_id": "",
            "error": "" if host_id else "主程序未返回可用于匹配发送的任务编号",
            "retry_of": retry_of,
        }
        if task.schedule == "once":
            row["task_snapshot"] = task.to_dict()
        self.records.append(row)
        self.records = self.records[-300:]
        self.plugin._save_state()
        return row

    def trigger_error(self, task: Any, reason: str) -> None:
        if not self.plugin.config.task_receipts.enabled:
            return
        self.records.append({
            "id": uuid.uuid4().hex[:12], "task_id": task.id, "stream_id": task.stream_id,
            "owner_user_id": task.owner_user_id, "instruction": task.instruction[:200],
            "host_task_id": "", "accepted_at": time.time(), "status": "unknown",
            "sent_message_id": "", "error": f"提交任务时出错：{reason[:250]}；是否入队无法确认，不自动重发",
            "retry_of": "",
        })
        self.records = self.records[-300:]
        self.plugin._save_state()

    async def observe_send(
        self, message: dict[str, Any] | None, sent: bool,
        reply_message_id: str | None = None,
    ) -> None:
        if not self.plugin.config.task_receipts.enabled or not isinstance(message, dict):
            return
        stream_id = str(message.get("session_id") or "").strip()
        anchors = {str(value).strip() for value in (reply_message_id, message.get("reply_to")) if value}
        if not stream_id or not anchors:
            return
        async with self.plugin._lock:
            for row in reversed(self.records):
                if row.get("stream_id") != stream_id or row.get("host_task_id") not in anchors:
                    continue
                if row.get("status") == "sent":
                    return
                if sent is True:
                    row["status"] = "sent"
                    row["sent_message_id"] = str(message.get("message_id") or "")
                    row["sent_at"] = time.time()
                    row["error"] = ""
                elif row.get("status") == "accepted":
                    row["status"] = "send_failed"
                    row["error"] = "主程序确认这次消息发送失败；管理员可明确要求重试"
                else:
                    return
                self.plugin._save_state()
                return

    def list_rows(self, *, stream_id: str = "", owner_user_id: str = "") -> list[dict[str, Any]]:
        return [
            {key: value for key, value in row.items() if key != "task_snapshot"}
            for row in reversed(self.records)
            if (not stream_id or row.get("stream_id") == stream_id)
            and (not owner_user_id or row.get("owner_user_id") == owner_user_id)
        ][:100]

    async def retry(self, receipt_id: str) -> dict[str, Any]:
        if not self.plugin.config.task_receipts.enabled:
            return {"success": False, "error": "任务回执模块未启用"}
        async with self.plugin._lock:
            row = next((item for item in self.records if item.get("id") == receipt_id), None)
            if row is None or row.get("status") != "send_failed" or row.get("retry_of"):
                return {"success": False, "error": "只有首次明确发送失败的任务可以重试一次"}
            task = self.plugin.scheduled.tasks.get(str(row["task_id"]))
            if task is None:
                try:
                    task = ScheduledTask.from_dict(row["task_snapshot"])
                except (KeyError, TypeError, ValueError):
                    return {"success": False, "error": "原任务资料不完整，无法安全重试"}
                if (task.id != row["task_id"] or task.stream_id != row["stream_id"]
                        or task.owner_user_id != row["owner_user_id"] or task.schedule != "once"):
                    return {"success": False, "error": "原任务资料不匹配，无法安全重试"}
            row["status"] = "retrying"
            self.plugin._save_state()
        intent = self.plugin.scheduled.build_intent(task)
        try:
            result = await self.plugin._trigger(task.stream_id, intent, "管理员重试已确认发送失败的定时任务", f"retry:{receipt_id}")
        except Exception as exc:  # noqa: BLE001 - uncertain delivery must not be retried automatically
            async with self.plugin._lock:
                row["status"] = "unknown"
                row["error"] = f"重试请求未获确认：{str(exc)[:200]}；请核对聊天记录"
                self.plugin._save_state()
            return {"success": False, "error": row["error"]}
        async with self.plugin._lock:
            self.accepted(task, result, retry_of=receipt_id)
            row["status"] = "retried"
            self.plugin._save_state()
        return {"success": True, "content": "重试已入队；实际送达请再查看回执"}

    async def tool(self, action: str = "list", receipt_id: str = "", **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        if not stream_id or stream_id != str(kwargs.get("chat_id") or "").strip():
            return {"success": False, "error": "无法核验当前聊天流"}
        actor = self.plugin.role_recognition.peek_planner_speaker(stream_id)
        admins = await self.plugin.role_recognition.admin_accounts(force_refresh=True)
        if action == "retry":
            if not actor or actor not in admins:
                return {"success": False, "error": "只有已核验管理员能重试失败任务"}
            return await self.retry(str(receipt_id or "").strip())
        if action != "list":
            return {"success": False, "error": "action 只能为 list 或 retry"}
        if not actor:
            return {"success": False, "error": "无法核验任务所属用户"}
        rows = self.list_rows(stream_id=stream_id) if actor in admins else [
            row for row in self.list_rows(stream_id=stream_id)
            if row.get("owner_user_id") == actor.split(":", 1)[-1]
        ]
        return {"success": True, "content": f"当前聊天流找到 {len(rows)} 条任务回执；sent 才表示确认送达，unknown 需要人工核对。", "receipts": rows}

    async def webui_list(self) -> dict[str, Any]:
        async with self.plugin._lock:
            return {"receipts": self.list_rows()}
