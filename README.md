# 麦麦小秘书

面向 MaiBot 1.3.7 / 插件 SDK 2.12.0 的独立插件。它提供两件事：

1. 在配置的每天时间窗口内，为指定聊天流随机安排 1–5 次主动聊天。到点后把“结合当前对话找话题”的意图交给 MaiBot 的主动任务接口，由麦麦按当时的上下文和人设决定怎么说。
2. 让麦麦通过三个工具创建、查看和取消当前用户在当前聊天流中的定时任务。支持单次、每天、每周。到点后仍交给麦麦的主动任务接口执行用户请求。

例如，用户说“每天早上八点给我说天气预报”，麦麦可调用 `secretary_create_task`，用 `daily`、`08:00` 和原请求建立任务。任务到点时，小秘书会要求麦麦使用运行时已有的信息来源查询天气；若没有可靠的实时天气来源，应如实说明，不能编造预报。插件本身不提供天气数据源。

## 配置

编辑 `config.toml` 或在 MaiBot 插件配置页面修改设置。`target_chats` 为空时，不会随机主动发言。格式为 `平台:group:群号` 或 `平台:private:用户号`：

```toml
[proactive]
target_chats = ["qq:group:123456789", "qq:private:987654321"]
window_start = "09:00"
window_end = "21:00"
messages_per_window = 1
```

窗口可以跨午夜，例如 `20:00` 到 `01:00`。时区由 `[plugin].timezone` 指定，默认 `Asia/Shanghai`。每个目标和窗口的随机时间点会保存在 MaiBot 授予的 `data/plugins/worldcopyist.mai-secretary/` 中，重启后继续使用。目标会由 `chat.open_session` 解析为真实聊天流，不自行计算聊天流 ID。

自然语言工具只操作调用者所在聊天流、该用户自己的任务。单次任务使用带时区的 ISO 时间，例如 `2026-10-21T08:00:00+08:00`；每天和每周使用 `HH:MM`，每周还需星期数字（周一为 1，周日为 7）。时间含糊时应先澄清。

到点后的“成功”表示 MaiBot 接受了主动任务请求，不等于已经观察到消息发出。插件先持久化“已尝试”再触发，避免重启造成重复消息。服务中断超过 `misfire_grace_seconds`（默认 10 分钟）时会跳过过期触发；单次任务会标记为 `missed`，可通过列出任务查看。接口报错时，单次任务标记为 `failed`；周期任务保留下一次执行。

## 开发与安装

本仓库直接作为 MaiBot `plugins/` 下的独立插件目录使用，不修改 MaiBot 主程序。安装依赖：

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

**仓库地址仍待提供。** `_manifest.json` 中的 `urls.repository` 目前是明显的占位地址；收到 GitHub 仓库地址后必须替换，再做服务器加载验证。许可证也暂为 `UNLICENSED`，发布前需由仓库现有许可或用户决定。
