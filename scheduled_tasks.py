"""Natural-language scheduled tasks: execution, storage and tool operations."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .prompts import PERSONA_PRIORITY_PROMPT, TOOL_ROUTING_PROMPT
from .secretary_core import ScheduledTask, next_occurrence

LOG = logging.getLogger(__name__)


class ScheduledTasksModule:
    name = "scheduled_tasks"
    state_keys = frozenset({"tasks"})

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.tasks: dict[str, ScheduledTask] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        tasks = [ScheduledTask.from_dict(item) for item in data.get("tasks", [])]
        self.tasks = {task.id: task for task in tasks}

    def dump_state(self, payload: dict[str, Any]) -> None:
        payload["tasks"] = [task.to_dict() for task in self.tasks.values()]

    def on_config_update(self) -> None:
        pass

    async def tick(self, now: datetime) -> None:
        if not self.plugin.config.scheduled_tasks.enabled:
            return
        grace = int(self.plugin.config.plugin.misfire_grace_seconds)
        for task in sorted(self.tasks.values(), key=lambda item: item.next_run):
            if task.status != "active" or task.next_run > now.timestamp():
                continue
            late = now.timestamp() - task.next_run
            if task.schedule == "once":
                task.status = "missed" if late > grace else "completed"
            else:
                task.next_run = next_occurrence(
                    task.schedule, task.at, task.timezone, task.weekdays, now
                )
            self.plugin._save_state()  # Record the attempt before calling the Host; avoid duplicate wakeups.
            if late > grace:
                task.last_error = "服务停止或延迟过久，已跳过本次执行"
                self.plugin._save_state()
                continue
            intent = (
                f"{PERSONA_PRIORITY_PROMPT}\n"
                "用户之前设置的定时任务现在到点了。请在当前聊天流中完成这项请求："
                f"{task.instruction}。结合当前上下文回答；如任务需要天气等实时信息，"
                "请调用 `secretary_deepseek_search` 查证；已有链接需要正文时再调用 `secretary_deepseek_fetch`。"
                "若无法取得可靠的实时数据，明确说明，勿编造。"
                "本轮是在执行已创建的任务，不要调用 `secretary_create_task` 重复设置。"
                f"{TOOL_ROUTING_PROMPT}"
            )
            try:
                await self.plugin._trigger(
                    task.stream_id, intent, "定时任务到点", task.id
                )
                task.last_error = ""
            except Exception as exc:
                task.last_error = str(exc)[:300]
                if task.schedule == "once":
                    task.status = "failed"
                LOG.exception("定时任务触发失败：%s", task.id)
            self.plugin._save_state()

    @staticmethod
    def _tool_identity(kwargs: dict[str, Any]) -> tuple[str, str]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        chat_id = str(kwargs.get("chat_id") or "").strip()
        user_id = str(kwargs.get("user_id") or "").strip()
        if not stream_id or not chat_id or stream_id != chat_id or not user_id:
            raise ValueError("未取得可靠的当前聊天流和用户身份，不能操作定时任务")
        return stream_id, user_id

    async def create_task(self, **kwargs: Any) -> dict[str, Any]:
        try:
            stream_id, user_id = self._tool_identity(kwargs)
            return await self._create_task(
                stream_id=stream_id,
                user_id=user_id,
                instruction=kwargs.get("instruction"),
                schedule=kwargs.get("schedule"),
                at=kwargs.get("at"),
                weekdays=kwargs.get("weekdays"),
                timezone_name=kwargs.get("timezone"),
            )
        except (ValueError, KeyError, OSError) as exc:
            return {"success": False, "error": str(exc)}

    async def _create_task(
        self, *, stream_id: str, user_id: str, instruction: Any,
        schedule: Any, at: Any, weekdays: Any, timezone_name: Any,
        deduplicate_all_owners: bool = False,
    ) -> dict[str, Any]:
        instruction = str(instruction or "").strip()
        schedule = str(schedule or "").strip().lower()
        at = str(at or "").strip()
        weekdays = str(weekdays or "").strip()
        timezone_name = str(timezone_name or self.plugin.config.plugin.timezone).strip()
        if not self.plugin.config.plugin.enabled or not self.plugin.config.scheduled_tasks.enabled:
            raise ValueError("麦麦小秘书的定时任务模块尚未启用")
        if not instruction or len(instruction) > 1000:
            raise ValueError("任务内容须为 1 到 1000 字")
        ZoneInfo(timezone_name)
        next_run = next_occurrence(schedule, at, timezone_name, weekdays, datetime.now(UTC))
        async with self.plugin._lock:
            active = [
                item for item in self.tasks.values()
                if item.stream_id == stream_id and item.owner_user_id == user_id
                and item.status == "active"
            ]
            for item in self.tasks.values():
                if item.status != "active" or item.stream_id != stream_id:
                    continue
                if item.owner_user_id != user_id and not deduplicate_all_owners:
                    continue
                if (
                    item.instruction, item.schedule, item.at, item.timezone, item.weekdays,
                ) == (instruction, schedule, at, timezone_name, weekdays):
                    return self._task_result(item, "相同任务已存在")
            if len(active) >= self.plugin.config.plugin.max_tasks_per_user:
                raise ValueError("当前聊天流的活动任务已达上限")
            task = ScheduledTask(
                id=uuid.uuid4().hex[:12], stream_id=stream_id,
                owner_user_id=user_id, instruction=instruction,
                schedule=schedule, at=at, timezone=timezone_name,
                weekdays=weekdays, next_run=next_run,
            )
            self.tasks[task.id] = task
            self.plugin._save_state()
            self.plugin._wake.set()
            return self._task_result(task, "已建立定时任务")

    async def webui_streams(self) -> dict[str, Any]:
        try:
            streams = await self.plugin.ctx.chat.get_all_streams(platform="all_platforms")
            if isinstance(streams, dict):
                streams = streams.get("streams") if streams.get("success") else None
            if not isinstance(streams, list):
                raise TypeError("无法读取现有聊天流，请稍后刷新")
            entries = []
            seen = set()
            for stream in streams:
                if not isinstance(stream, dict):
                    continue
                stream_id = str(stream.get("stream_id") or stream.get("session_id") or "").strip()
                if not stream_id or stream_id in seen:
                    continue
                seen.add(stream_id)
                platform = str(stream.get("platform") or "")
                group = bool(stream.get("is_group_session") or stream.get("chat_type") == "group")
                target = str((stream.get("group_id") if group else stream.get("user_id")) or "")
                name = str((stream.get("group_name") if group else stream.get("user_nickname")) or "").strip()
                label = f"{platform}:{'group' if group else 'private'}:{target or stream_id}"
                entries.append({"stream_id": stream_id, "label": f"{label} · {name}" if name else label})
            label_counts: dict[str, int] = {}
            for item in entries:
                label_counts[item["label"]] = label_counts.get(item["label"], 0) + 1
            for item in entries:
                if label_counts[item["label"]] > 1:
                    item["label"] += f" · 会话 {item['stream_id'][-8:]}"
            entries.sort(key=lambda item: item["label"])
            return {"streams": entries}
        except (TypeError, ValueError, OSError) as exc:
            return {"error": str(exc)}

    async def webui_create_task(
        self, stream_id: str, instruction: str, schedule: str, at: str,
        weekdays: str = "", timezone: str = "",
    ) -> dict[str, Any]:
        try:
            stream_id = str(stream_id or "").strip()
            available = await self.webui_streams()
            if "error" in available:
                raise ValueError(available["error"])
            if stream_id not in {item["stream_id"] for item in available["streams"]}:
                raise ValueError("所选聊天流已不可用，请刷新列表后重选")
            timezone_name = timezone or self.plugin.config.plugin.timezone
            if schedule == "once":
                candidate = datetime.fromisoformat(at)
                if candidate.tzinfo is None:
                    at = candidate.replace(tzinfo=ZoneInfo(timezone_name)).isoformat(timespec="minutes")
            return await self._create_task(
                stream_id=stream_id, user_id="__secretary_webui__",
                instruction=instruction, schedule=schedule, at=at,
                weekdays=weekdays, timezone_name=timezone_name,
                deduplicate_all_owners=True,
            )
        except (ValueError, KeyError, OSError) as exc:
            return {"error": str(exc)}

    async def webui_list_tasks(self) -> dict[str, Any]:
        async with self.plugin._lock:
            entries = [
                {**self._task_entry(task), "stream_id": task.stream_id,
                 "owner_user_id": task.owner_user_id}
                for task in sorted(self.tasks.values(), key=lambda item: item.next_run)
            ]
        return {
            "tasks": entries,
            "timezone": self.plugin.config.plugin.timezone,
            "enabled": self.plugin.config.plugin.enabled and self.plugin.config.scheduled_tasks.enabled,
        }

    async def webui_cancel_task(self, task_id: str) -> dict[str, Any]:
        async with self.plugin._lock:
            if task_id not in self.tasks:
                return {"error": "任务不存在或已取消，请刷新列表"}
            del self.tasks[task_id]
            self.plugin._save_state()
            self.plugin._wake.set()
        return {"content": f"已取消任务 {task_id}"}

    @staticmethod
    def _task_result(task: ScheduledTask, label: str) -> dict[str, Any]:
        next_local = datetime.fromtimestamp(
            task.next_run, ZoneInfo(task.timezone)
        ).isoformat(timespec="minutes")
        return {
            "success": True,
            "content": f"{label}：{task.id}；下次执行 {next_local}",
            "task_id": task.id,
            "next_run": next_local,
        }

    async def list_tasks(self, **kwargs: Any) -> dict[str, Any]:
        try:
            stream_id, user_id = self._tool_identity(kwargs)
            async with self.plugin._lock:
                tasks = [
                    item
                    for item in self.tasks.values()
                    if item.stream_id == stream_id and item.owner_user_id == user_id
                ]
                tasks.sort(key=lambda item: item.next_run)
                entries = [self._task_entry(task) for task in tasks]
            return {
                "success": True,
                "content": json.dumps(entries, ensure_ascii=False),
                "tasks": entries,
            }
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    @staticmethod
    def _task_entry(task: ScheduledTask) -> dict[str, Any]:
        return {
            "id": task.id, "instruction": task.instruction,
            "schedule": task.schedule, "at": task.at,
            "timezone": task.timezone, "weekdays": task.weekdays,
            "next_run": datetime.fromtimestamp(
                task.next_run, ZoneInfo(task.timezone)
            ).isoformat(timespec="minutes"),
            "status": task.status, "last_error": task.last_error,
        }

    async def cancel_task(self, **kwargs: Any) -> dict[str, Any]:
        try:
            stream_id, user_id = self._tool_identity(kwargs)
            task_id = str(kwargs.get("task_id") or "").strip()
            async with self.plugin._lock:
                task = self.tasks.get(task_id)
                if (
                    task is None
                    or task.stream_id != stream_id
                    or task.owner_user_id != user_id
                ):
                    raise ValueError("没有找到你在当前聊天流中的这个任务")
                del self.tasks[task_id]
                self.plugin._save_state()
                self.plugin._wake.set()
            return {"success": True, "content": f"已取消任务 {task_id}"}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
