"""Natural-language scheduled tasks: execution, storage and tool operations."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .prompts import TOOL_ROUTING_PROMPT
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
                "用户之前设置的定时任务现在到点了。请在当前聊天流中完成这项请求："
                f"{task.instruction}。结合当前上下文回答；如任务需要天气等实时信息，"
                "请调用 `deepseek_search` 查证；已有链接需要正文时再调用 `deepseek_fetch`。"
                "若无法取得可靠的实时数据，明确说明，勿编造。"
                "本轮是在执行已创建的任务，不要调用 `secretary_create_task` 重复设置。"
                f"{TOOL_ROUTING_PROMPT}"
            )
            try:
                await self.plugin._trigger(
                    task.stream_id, intent, "麦麦小秘书定时任务", task.id
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
            instruction = str(kwargs.get("instruction") or "").strip()
            schedule = str(kwargs.get("schedule") or "").strip().lower()
            at = str(kwargs.get("at") or "").strip()
            weekdays = str(kwargs.get("weekdays") or "").strip()
            timezone_name = str(
                kwargs.get("timezone") or self.plugin.config.plugin.timezone
            ).strip()
            if (
                not self.plugin.config.plugin.enabled
                or not self.plugin.config.scheduled_tasks.enabled
            ):
                raise ValueError("麦麦小秘书尚未启用")
            if not instruction or len(instruction) > 1000:
                raise ValueError("任务内容须为 1 到 1000 字")
            ZoneInfo(timezone_name)
            now = datetime.now(UTC)
            next_run = next_occurrence(schedule, at, timezone_name, weekdays, now)
            async with self.plugin._lock:
                active = [
                    item
                    for item in self.tasks.values()
                    if item.stream_id == stream_id
                    and item.owner_user_id == user_id
                    and item.status == "active"
                ]
                for item in active:
                    if (
                        item.instruction,
                        item.schedule,
                        item.at,
                        item.timezone,
                        item.weekdays,
                    ) == (instruction, schedule, at, timezone_name, weekdays):
                        return self._task_result(item, "相同任务已存在")
                if len(active) >= self.plugin.config.plugin.max_tasks_per_user:
                    raise ValueError("当前聊天流的活动任务已达上限")
                task = ScheduledTask(
                    id=uuid.uuid4().hex[:12],
                    stream_id=stream_id,
                    owner_user_id=user_id,
                    instruction=instruction,
                    schedule=schedule,
                    at=at,
                    timezone=timezone_name,
                    weekdays=weekdays,
                    next_run=next_run,
                )
                self.tasks[task.id] = task
                self.plugin._save_state()
                self.plugin._wake.set()
                return self._task_result(task, "已建立定时任务")
        except (ValueError, KeyError, OSError) as exc:
            return {"success": False, "error": str(exc)}

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
                entries = [
                    {
                        "id": task.id,
                        "instruction": task.instruction,
                        "schedule": task.schedule,
                        "at": task.at,
                        "timezone": task.timezone,
                        "weekdays": task.weekdays,
                        "next_run": datetime.fromtimestamp(
                            task.next_run, ZoneInfo(task.timezone)
                        ).isoformat(timespec="minutes"),
                        "status": task.status,
                        "last_error": task.last_error,
                    }
                    for task in tasks
                ]
            return {
                "success": True,
                "content": json.dumps(entries, ensure_ascii=False),
                "tasks": entries,
            }
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

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
