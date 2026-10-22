"""麦麦小秘书：主动聊天、定时任务和 AI 反霸凌。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar, Literal

from maibot_sdk import Field, HookHandler, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import HookMode, ToolParameterInfo, ToolParamType
from pydantic import field_validator

from .anti_bullying import AntiBullyingModule, normalize_admin_account
from .module_contract import SecretaryModule
from .proactive_chat import ProactiveChatModule
from .scheduled_tasks import ScheduledTasksModule

LOG = logging.getLogger(__name__)


class PluginSettings(PluginConfigBase):
    """控制小秘书运行和管理员账号的通用设置。"""

    __ui_label__: ClassVar[str] = "插件设置"

    config_version: str = Field(
        default="0.1.0",
        description="配置结构版本",
        json_schema_extra={"hidden": True},
    )
    enabled: bool = Field(
        default=True,
        description="启用麦麦小秘书",
        json_schema_extra={
            "label": "启用麦麦小秘书",
            "hint": "关闭后不会主动发言、执行定时任务或检查辱骂；已有任务仍可查看和取消。",
        },
    )
    timezone: str = Field(
        default="Asia/Shanghai",
        description="默认时区，如 Asia/Shanghai",
        json_schema_extra={
            "label": "默认时区",
            "hint": "用于主动发言时间窗口和定时任务；北京时间填写 Asia/Shanghai。",
        },
    )
    check_interval_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="调度检查间隔",
        json_schema_extra={
            "label": "任务检查间隔（秒）",
            "hint": "每隔多少秒检查一次是否有任务到点，范围为 5–300 秒。",
        },
    )
    misfire_grace_seconds: int = Field(
        default=600,
        ge=0,
        le=3600,
        description="停机后补执行的最长延迟",
        json_schema_extra={
            "label": "错过任务的补执行期限（秒）",
            "hint": "服务恢复后，超过这个期限的过期任务会跳过；0 表示不补执行。",
        },
    )
    max_tasks_per_user: int = Field(
        default=30,
        ge=1,
        le=200,
        description="每人最多保留的活动任务",
        json_schema_extra={
            "label": "每人活动任务上限",
            "hint": "限制同一用户在同一聊天流中可同时保留的定时任务数量。",
        },
    )
    admin_accounts: list[str] = Field(
        default_factory=list,
        description="接收 AI 反霸凌提醒的管理员账号，格式为 平台:用户号",
        json_schema_extra={
            "label": "管理员账号",
            "hint": "每行一个账号，例如 qq:123456789；也接受中文冒号。留空时不会发送告状。",
            "placeholder": "qq:123456789",
        },
    )

    @field_validator("admin_accounts")
    @classmethod
    def validate_admin_accounts(cls, accounts: list[str]) -> list[str]:
        if len(accounts) > 20:
            raise ValueError("管理员账号最多 20 个")
        return list(dict.fromkeys(normalize_admin_account(account) for account in accounts))


class ScheduledTasksSettings(PluginConfigBase):
    """定时任务模块的独立开关。"""

    __ui_label__: ClassVar[str] = "定时任务"

    enabled: bool = Field(
        default=True,
        description="启用定时任务",
        json_schema_extra={
            "label": "启用定时任务",
            "hint": "关闭后不再创建或执行任务；已有任务仍可查看和取消。",
        },
    )


class ProactiveSettings(PluginConfigBase):
    """设置随机主动发言的聊天目标、时间窗口和频率。"""

    __ui_label__: ClassVar[str] = "随机主动发言"

    enabled: bool = Field(
        default=True,
        description="启用随机主动聊天",
        json_schema_extra={
            "label": "启用随机主动发言",
            "hint": "只影响随机主动聊天，不影响定时任务。",
        },
    )
    target_chats: list[str] = Field(
        default_factory=list,
        description='目标，例如 ["qq:group:123456", "qq:private:123456"]',
        json_schema_extra={
            "label": "目标聊天流",
            "hint": "每行添加一个目标，例如 qq:group:123456 或 qq:private:123456。留空则不主动发言。",
            "placeholder": "qq:private:123456",
        },
    )
    window_start: str = Field(
        default="09:00",
        description="每天窗口开始时间 HH:MM",
        json_schema_extra={
            "label": "每天开始时间",
            "hint": "使用 24 小时制，例如 09:00。",
            "placeholder": "09:00",
        },
    )
    window_end: str = Field(
        default="21:00",
        description="每天窗口结束时间 HH:MM，可跨午夜",
        json_schema_extra={
            "label": "每天结束时间",
            "hint": "可跨午夜，例如开始 10:00、结束 02:00 表示到次日凌晨两点。",
            "placeholder": "21:00",
        },
    )
    messages_per_window: int = Field(
        default=1,
        ge=1,
        le=5,
        description="每个聊天流每个窗口随机触发次数",
        json_schema_extra={
            "label": "每个时间窗口的发言次数",
            "hint": "仅“按次数”模式生效；每个目标每个窗口随机发言 1–5 次。",
        },
    )
    scheduling_mode: Literal["count", "interval"] = Field(
        default="count",
        description="count 按窗口次数；interval 按平均间隔",
        json_schema_extra={
            "label": "发言频率模式",
            "hint": "count 表示按窗口次数；interval 表示按平均间隔。选项中的英文是配置值。",
        },
    )
    average_interval_hours: float = Field(
        default=2.0,
        ge=0.25,
        le=24,
        description="interval 模式下平均每隔多少小时发言",
        json_schema_extra={
            "label": "平均发言间隔（小时）",
            "hint": "仅“按平均间隔”模式生效，范围为 0.25–24 小时。",
        },
    )
    offset_minutes: int = Field(
        default=15,
        ge=0,
        le=720,
        description="interval 模式下每次间隔的随机偏移，正负分钟",
        json_schema_extra={
            "label": "随机偏移（分钟）",
            "hint": "每次间隔在平均值的基础上随机提前或推迟，偏移必须小于平均间隔。",
        },
    )
    intent: str = Field(
        default=(
            "请根据这个聊天流的最近对话、人物关系和已有记忆，找一个贴合上下文的话题，"
            "在当前聊天流发出一条自然的消息。避免复述最近说过的话；上下文较少时可聊轻松的日常话题。"
            "不要提及插件或定时器。"
        ),
        description="交给麦麦主动任务的发言意图",
        json_schema_extra={
            "label": "主动发言的引导文字",
            "hint": "麦麦会结合当前聊天和上次实际发出的内容自行选话题。",
            "x-widget": "textarea",
            "rows": 4,
        },
    )


class AntiBullyingSettings(PluginConfigBase):
    """独立控制 AI 反霸凌的识别与提醒。"""

    __ui_label__: ClassVar[str] = "AI 反霸凌"

    enabled: bool = Field(
        default=True,
        description="启用 AI 反霸凌",
        json_schema_extra={
            "label": "启用 AI 反霸凌",
            "hint": "管理员账号留空时不检查消息，也不发送提醒。",
        },
    )
    forbidden_words: list[str] = Field(
        default_factory=list,
        description="帮助 AI 识别针对麦麦的辱骂的违禁词",
        json_schema_extra={
            "label": "违禁词",
            "hint": "每行一个词；命中后仍由 AI 判断是否真的在辱骂麦麦，避免把引用或讨论误报。",
            "placeholder": "填写要留意的词语",
        },
    )
    confidence_threshold: float = Field(
        default=0.8,
        ge=0.5,
        le=1.0,
        description="AI 把握度达到该值才提醒管理员",
        json_schema_extra={
            "label": "提醒把握度",
            "hint": "范围 0.5–1.0；越高越谨慎，默认 0.8。",
        },
    )
    alert_cooldown_minutes: int = Field(
        default=10,
        ge=0,
        le=1440,
        description="同一人同一聊天流两次提醒的最短间隔",
        json_schema_extra={
            "label": "同一人提醒间隔（分钟）",
            "hint": "避免短时间重复告状；0 表示不限制。",
        },
    )

    @field_validator("forbidden_words")
    @classmethod
    def validate_forbidden_words(cls, words: list[str]) -> list[str]:
        if len(words) > 100:
            raise ValueError("违禁词最多 100 个")
        cleaned = [str(word).strip() for word in words if str(word).strip()]
        if any(len(word) > 50 for word in cleaned):
            raise ValueError("每个违禁词最多 50 字")
        return list(dict.fromkeys(cleaned))


class SecretaryConfig(PluginConfigBase):
    plugin: PluginSettings = Field(default_factory=PluginSettings)
    scheduled_tasks: ScheduledTasksSettings = Field(
        default_factory=ScheduledTasksSettings
    )
    proactive: ProactiveSettings = Field(default_factory=ProactiveSettings)
    anti_bullying: AntiBullyingSettings = Field(default_factory=AntiBullyingSettings)


class MaiSecretaryPlugin(MaiBotPlugin):
    """SDK entry point; modules own behavior and persistent state."""

    config_model = SecretaryConfig

    def __init__(self) -> None:
        super().__init__()
        self.scheduled = ScheduledTasksModule(self)
        self.proactive = ProactiveChatModule(self)
        self.anti_bullying = AntiBullyingModule(self)
        self._modules: dict[str, SecretaryModule] = {}
        self._register_module(self.scheduled)
        self._register_module(self.proactive)
        self._register_module(self.anti_bullying)
        self._state_path: Path | None = None
        self._extra_state: dict[str, Any] = {}
        self._lock = asyncio.Lock()
        self._wake = asyncio.Event()
        self._runner: asyncio.Task[None] | None = None

    def _register_module(self, feature: SecretaryModule) -> None:
        if feature.name in self._modules:
            raise ValueError(f"模块名称重复：{feature.name}")
        occupied = {key for item in self._modules.values() for key in item.state_keys}
        if feature.state_keys & (occupied | {"schema_version"}):
            raise ValueError(f"模块状态字段重复：{feature.name}")
        self._modules[feature.name] = feature

    async def on_load(self) -> None:
        self._state_path = Path(self.ctx.paths.data_dir) / "secretary-state.json"
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._load_state()
        await self.anti_bullying.start()
        self._runner = asyncio.create_task(self._run(), name="mai-secretary-scheduler")
        self.ctx.logger.info(
            "麦麦小秘书已加载：%s 个定时任务", len(self.scheduled.tasks)
        )

    async def on_unload(self) -> None:
        await self.anti_bullying.stop()
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
            for feature in self._modules.values():
                feature.on_config_update()
            self._wake.set()

    def _load_state(self) -> None:
        assert self._state_path is not None
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                raise ValueError("未知的数据版本")
            for feature in self._modules.values():
                feature.load_state(data)
            module_keys = {
                key for feature in self._modules.values() for key in feature.state_keys
            }
            self._extra_state = {
                key: value
                for key, value in data.items()
                if key not in module_keys | {"schema_version"}
            }
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(
                f"小秘书数据无法读取，原文件已保留：{self._state_path}"
            ) from exc

    def _save_state(self) -> None:
        if self._state_path is None:
            return
        payload = {"schema_version": 1, **self._extra_state}
        for feature in self._modules.values():
            feature.dump_state(payload)
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
        for feature in self._modules.values():
            await feature.tick(now)

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

    @HookHandler(
        "chat.receive.before_process",
        name="secretary_cancel_pending_on_inbound",
        mode=HookMode.OBSERVE,
        description="用户先发来消息时停止认领主动聊天回复",
    )
    async def cancel_pending_on_inbound(
        self, message: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        await self.proactive.cancel_pending_on_inbound(message, **kwargs)

    @HookHandler(
        "chat.receive.after_process",
        name="secretary_anti_bullying_inspect",
        mode=HookMode.OBSERVE,
        description="旁路判断针对麦麦的辱骂，并私聊管理员",
    )
    async def inspect_anti_bullying(
        self, message: dict[str, Any] | None = None, **kwargs: Any
    ) -> None:
        del kwargs
        await self.anti_bullying.on_inbound(message)

    @HookHandler(
        "send_service.after_send",
        name="secretary_capture_proactive_reply",
        mode=HookMode.OBSERVE,
        description="记录主动聊天实际发出的文字，供下次自然续接",
    )
    async def capture_proactive_reply(
        self, message: dict[str, Any] | None = None, sent: bool = False, **kwargs: Any
    ) -> None:
        await self.proactive.capture_proactive_reply(message, sent, **kwargs)

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
        return await self.scheduled.create_task(**kwargs)

    @Tool(
        "secretary_list_tasks",
        description="列出当前用户在当前聊天流设置的定时任务。用户问已安排了什么、任务编号或执行状态时使用。",
        parameters=[],
    )
    async def secretary_list_tasks(self, **kwargs: Any) -> dict[str, Any]:
        return await self.scheduled.list_tasks(**kwargs)

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
        return await self.scheduled.cancel_task(**kwargs)


def create_plugin() -> MaiSecretaryPlugin:
    return MaiSecretaryPlugin()
