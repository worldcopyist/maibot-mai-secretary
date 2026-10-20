"""麦麦小秘书：随机主动聊天与由自然语言创建的定时任务。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from maibot_sdk import Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .secretary_core import (
    ScheduledTask,
    next_occurrence,
    next_window,
    parse_clock,
    random_slots,
)

LOG = logging.getLogger(__name__)


class PluginSettings(PluginConfigBase):
    config_version: str = Field(default="0.1.0", description="配置结构版本")
    enabled: bool = Field(default=True, description="启用麦麦小秘书")
    timezone: str = Field(
        default="Asia/Shanghai", description="默认时区，如 Asia/Shanghai"
    )
    check_interval_seconds: int = Field(
        default=30, ge=5, le=300, description="调度检查间隔"
    )
    misfire_grace_seconds: int = Field(
        default=600, ge=0, le=3600, description="停机后补执行的最长延迟"
    )
    max_tasks_per_user: int = Field(
        default=30, ge=1, le=200, description="每人最多保留的活动任务"
    )


class ProactiveSettings(PluginConfigBase):
    enabled: bool = Field(default=True, description="启用随机主动聊天")
    target_chats: list[str] = Field(
        default_factory=list,
        description='目标，例如 ["qq:group:123456", "qq:private:123456"]',
    )
    window_start: str = Field(default="09:00", description="每天窗口开始时间 HH:MM")
    window_end: str = Field(
        default="21:00", description="每天窗口结束时间 HH:MM，可跨午夜"
    )
    messages_per_window: int = Field(
        default=1, ge=1, le=5, description="每个聊天流每个窗口随机触发次数"
    )
    intent: str = Field(
        default=(
            "请根据这个聊天流的最近对话、人物关系和已有记忆，找一个贴合上下文的话题，"
            "在当前聊天流发出一条自然的消息。避免复述最近说过的话；上下文较少时可聊轻松的日常话题。"
            "不要提及插件或定时器。"
        ),
        description="交给麦麦主动任务的发言意图",
    )


class SecretaryConfig(PluginConfigBase):
    plugin: PluginSettings = Field(default_factory=PluginSettings)
    proactive: ProactiveSettings = Field(default_factory=ProactiveSettings)


class MaiSecretaryPlugin(MaiBotPlugin):
    config_model = SecretaryConfig

    def __init__(self) -> None:
        super().__init__()
        self._tasks: dict[str, ScheduledTask] = {}
        self._plans: dict[str, dict[str, Any]] = {}
        self._streams: dict[str, str] = {}
        self._state_path: Path | None = None
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None
        self._rng = random.Random()

    async def on_load(self) -> None:
        self._state_path = Path(self.ctx.paths.data_dir) / "secretary-state.json"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
        self._runner = asyncio.create_task(self._run(), name="mai-secretary-scheduler")
        self.ctx.logger.info("麦麦小秘书已加载：%s 个定时任务", len(self._tasks))

    async def on_unload(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._runner
            self._runner = None
        self._save_state()

    async def on_config_update(
        self, scope: str, config_data: dict[str, Any], version: str
    ) -> None:
        del config_data, version
        if scope == "self":
            self._streams.clear()
            self._wake.set()

    def _load_state(self) -> None:
        assert self._state_path is not None
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if data.get("schema_version") != 1:
                raise ValueError("未知的数据版本")
            tasks = [ScheduledTask.from_dict(item) for item in data.get("tasks", [])]
            plans = data.get("proactive_plans", {})
            if not isinstance(plans, dict):
                raise TypeError("主动聊天计划格式无效")
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(
                f"小秘书数据无法读取，原文件已保留：{self._state_path}"
            ) from exc
        self._tasks = {task.id: task for task in tasks}
        self._plans = plans

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        payload = {
            "schema_version": 1,
            "tasks": [task.to_dict() for task in self._tasks.values()],
            "proactive_plans": self._plans,
        }
        temporary = self._state_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, self._state_path)

    async def _run(self) -> None:
        while True:
            try:
                async with self._lock:
                    await self._tick(datetime.now(UTC))
            except asyncio.CancelledError:
                raise
            except Exception:
                LOG.exception("麦麦小秘书调度检查失败")
            try:
                await asyncio.wait_for(
                    self._wake.wait(),
                    timeout=int(self.config.plugin.check_interval_seconds),
                )
                self._wake.clear()
            except TimeoutError:
                pass

    async def _tick(self, now: datetime) -> None:
        if not self.config.plugin.enabled:
            return
        await self._tick_tasks(now)
        if self.config.proactive.enabled:
            await self._tick_proactive(now)

    async def _tick_tasks(self, now: datetime) -> None:
        grace = int(self.config.plugin.misfire_grace_seconds)
        for task in sorted(self._tasks.values(), key=lambda item: item.next_run):
            if task.status != "active" or task.next_run > now.timestamp():
                continue
            late = now.timestamp() - task.next_run
            if task.schedule == "once":
                task.status = "missed" if late > grace else "completed"
            else:
                task.next_run = next_occurrence(
                    task.schedule, task.at, task.timezone, task.weekdays, now
                )
            self._save_state()  # Record the attempt before calling the Host; avoid duplicate wakeups.
            if late > grace:
                task.last_error = "服务停止或延迟过久，已跳过本次执行"
                self._save_state()
                continue
            intent = (
                "用户之前设置的定时任务现在到点了。请在当前聊天流中完成这项请求："
                f"{task.instruction}。结合当前上下文回答；如任务需要天气等实时信息，"
                "请使用当前可用的查询工具。若无法取得可靠的实时数据，明确说明，勿编造。"
            )
            try:
                await self._trigger(
                    task.stream_id, intent, "麦麦小秘书定时任务", task.id
                )
                task.last_error = ""
            except Exception as exc:
                task.last_error = str(exc)[:300]
                if task.schedule == "once":
                    task.status = "failed"
                LOG.exception("定时任务触发失败：%s", task.id)
            self._save_state()

    async def _tick_proactive(self, now: datetime) -> None:
        settings = self.config.proactive
        zone = ZoneInfo(self.config.plugin.timezone)
        start, end = (
            parse_clock(settings.window_start),
            parse_clock(settings.window_end),
        )
        window_key, first, last = next_window(now, start, end, zone)
        signature = json.dumps(
            [
                settings.window_start,
                settings.window_end,
                settings.messages_per_window,
                self.config.plugin.timezone,
            ],
            ensure_ascii=False,
        )
        configured = set(settings.target_chats)
        for key in list(self._plans):
            if key not in configured:
                del self._plans[key]
                self._save_state()
        for target in settings.target_chats:
            plan = self._plans.get(target)
            if (
                not isinstance(plan, dict)
                or plan.get("window_key") != window_key
                or plan.get("signature") != signature
            ):
                plan = {
                    "window_key": window_key,
                    "signature": signature,
                    "slots": random_slots(
                        now, first, last, settings.messages_per_window, self._rng
                    ),
                }
                self._plans[target] = plan
                self._save_state()
            slots = plan.get("slots", [])
            if not isinstance(slots, list):
                raise TypeError("主动聊天计划格式无效")
            while slots and float(slots[0]) <= now.timestamp():
                due_at = float(slots[0])
                if now.timestamp() - due_at > self.config.plugin.misfire_grace_seconds:
                    slots.pop(0)
                    self._save_state()
                    continue
                try:
                    stream_id = await self._resolve_stream(target)
                except Exception:
                    LOG.exception("主动聊天目标解析失败：%s", target)
                    break
                slots.pop(0)
                self._save_state()  # Consume before triggering to avoid double sends on restart.
                try:
                    await self._trigger(
                        stream_id,
                        settings.intent,
                        "麦麦小秘书随机主动聊天",
                        f"{target}:{window_key}:{int(due_at)}",
                    )
                except Exception:
                    LOG.exception("随机主动聊天触发失败：%s", target)
                break

    async def _resolve_stream(self, target: str) -> str:
        if target in self._streams:
            return self._streams[target]
        parts = target.split(":", 2)
        if len(parts) != 3 or parts[1] not in {"group", "private"} or not all(parts):
            raise ValueError("目标格式须为 platform:group:id 或 platform:private:id")
        platform, chat_type, target_id = parts
        result = await self.ctx.chat.open_session(
            platform=platform,
            chat_type=chat_type,
            group_id=target_id if chat_type == "group" else "",
            user_id=target_id if chat_type == "private" else "",
        )
        if not isinstance(result, dict):
            raise TypeError("聊天流解析未返回数据")
        stream_id = str(
            result.get("stream_id") or result.get("session_id") or ""
        ).strip()
        if not stream_id:
            raise ValueError("聊天流解析未返回 stream_id")
        self._streams[target] = stream_id
        return stream_id

    async def _trigger(
        self, stream_id: str, intent: str, reason: str, event_id: str
    ) -> None:
        result = await self.ctx.maisaka.proactive.trigger(
            stream_id=stream_id,
            intent=intent,
            reason=reason,
            metadata={"source": "mai-secretary", "event_id": event_id},
        )
        if isinstance(result, dict) and result.get("success") is False:
            raise RuntimeError(str(result.get("error") or "主动任务接口拒绝了请求"))

    @staticmethod
    def _tool_identity(kwargs: dict[str, Any]) -> tuple[str, str]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        chat_id = str(kwargs.get("chat_id") or "").strip()
        user_id = str(kwargs.get("user_id") or "").strip()
        if not stream_id or not chat_id or stream_id != chat_id or not user_id:
            raise ValueError("未取得可靠的当前聊天流和用户身份，不能操作定时任务")
        return stream_id, user_id

    @Tool(
        "secretary_create_task",
        description=(
            "当用户用自然语言要求你在未来某个时间执行任务时使用，例如‘每天早上八点给我说天气预报’。"
            "只为当前聊天流建立任务。将用户要求整理为 instruction；schedule 为 once、daily、weekly；"
            "once 的 at 必须是带时区的 ISO 时间，daily/weekly 的 at 为 24 小时制 HH:MM；"
            "weekly 的 weekdays 用 1=周一到 7=周日的逗号分隔数字。不要猜测含糊的时间，先向用户确认。"
            "创建成功后告知准确的下次执行时间。"
        ),
        parameters=[
            ToolParameterInfo(
                name="instruction",
                param_type=ToolParamType.STRING,
                description="到点时让麦麦执行的原始用户请求",
                required=True,
            ),
            ToolParameterInfo(
                name="schedule",
                param_type=ToolParamType.STRING,
                description="once、daily 或 weekly",
                required=True,
            ),
            ToolParameterInfo(
                name="at",
                param_type=ToolParamType.STRING,
                description="单次用带时区 ISO 时间；重复用 HH:MM",
                required=True,
            ),
            ToolParameterInfo(
                name="weekdays",
                param_type=ToolParamType.STRING,
                description="weekly 必填，例如 1,3,5",
                required=False,
            ),
            ToolParameterInfo(
                name="timezone",
                param_type=ToolParamType.STRING,
                description="IANA 时区；不填使用插件默认时区",
                required=False,
            ),
        ],
    )
    async def secretary_create_task(self, **kwargs: Any) -> dict[str, Any]:
        try:
            stream_id, user_id = self._tool_identity(kwargs)
            instruction = str(kwargs.get("instruction") or "").strip()
            schedule = str(kwargs.get("schedule") or "").strip().lower()
            at = str(kwargs.get("at") or "").strip()
            weekdays = str(kwargs.get("weekdays") or "").strip()
            timezone_name = str(
                kwargs.get("timezone") or self.config.plugin.timezone
            ).strip()
            if not self.config.plugin.enabled:
                raise ValueError("麦麦小秘书尚未启用")
            if not instruction or len(instruction) > 1000:
                raise ValueError("任务内容须为 1 到 1000 字")
            ZoneInfo(timezone_name)
            now = datetime.now(UTC)
            next_run = next_occurrence(schedule, at, timezone_name, weekdays, now)
            async with self._lock:
                active = [
                    item
                    for item in self._tasks.values()
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
                if len(active) >= self.config.plugin.max_tasks_per_user:
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
                self._tasks[task.id] = task
                self._save_state()
                self._wake.set()
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

    @Tool(
        "secretary_list_tasks",
        description="列出当前用户在当前聊天流设置的定时任务。用户问已安排了什么、任务编号或执行状态时使用。",
        parameters=[],
    )
    async def secretary_list_tasks(self, **kwargs: Any) -> dict[str, Any]:
        try:
            stream_id, user_id = self._tool_identity(kwargs)
            async with self._lock:
                tasks = [
                    item
                    for item in self._tasks.values()
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

    @Tool(
        "secretary_cancel_task",
        description="用户明确要求取消自己在当前聊天流中的定时任务时使用。先从列表取得准确 task_id。",
        parameters=[
            ToolParameterInfo(
                name="task_id",
                param_type=ToolParamType.STRING,
                description="要取消的任务编号",
                required=True,
            ),
        ],
    )
    async def secretary_cancel_task(self, **kwargs: Any) -> dict[str, Any]:
        try:
            stream_id, user_id = self._tool_identity(kwargs)
            task_id = str(kwargs.get("task_id") or "").strip()
            async with self._lock:
                task = self._tasks.get(task_id)
                if (
                    task is None
                    or task.stream_id != stream_id
                    or task.owner_user_id != user_id
                ):
                    raise ValueError("没有找到你在当前聊天流中的这个任务")
                del self._tasks[task_id]
                self._save_state()
                self._wake.set()
            return {"success": True, "content": f"已取消任务 {task_id}"}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}


def create_plugin() -> MaiSecretaryPlugin:
    return MaiSecretaryPlugin()
