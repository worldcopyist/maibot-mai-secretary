# 麦麦小秘书

面向 MaiBot 1.3.7 / 插件 SDK 2.12.0 的独立插件。它提供两件事：

插件列表中的头像使用 `assets/icon.png`，在 `_manifest.json` 的 `display.icon` 中声明。

1. 在配置的每天时间窗口内，为指定聊天流按固定次数或平均间隔安排随机主动聊天。麦麦会自己决定当下在做的日常小事；插件保存这次实际发出的文字，下次主动聊天时交给麦麦自然续接，同时结合最新的聊天上下文。
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
scheduling_mode = "count"
average_interval_hours = 2.0
offset_minutes = 15
```

`scheduling_mode = "count"` 沿用每窗口 `messages_per_window` 次的方式（1–5 次）。设为 `"interval"` 后，改用 `average_interval_hours` 和 `offset_minutes`，例如平均 2 小时、偏移 15 分钟时，从窗口开始或修改设置的时刻起，每次与上次计划发言相隔 1 小时 45 分至 2 小时 15 分，次数随窗口长度变化。偏移可设为 0，必须小于平均间隔；平均间隔可设 0.25–24 小时。修改模式或参数后，只重新安排尚未发生的随机发言，不影响定时任务。

窗口可以跨午夜，例如 `10:00` 到次日 `02:00`。时区由 `[plugin].timezone` 指定，默认 `Asia/Shanghai`。每个目标和窗口的随机时间点会保存在 MaiBot 授予的 `data/plugins/worldcopyist.mai-secretary/` 中，重启后继续使用。插件先查询已有聊天流并使用带机器人账号的真实会话；若目标尚无会话，仅在能确定唯一机器人账号时调用 `chat.open_session`。无法确定时跳过本次触发，不创建缺少账号的重复聊天流。

主动聊天的续接记录按目标聊天流分别保存。插件只在 MaiBot 报告消息发送成功后记录文字；若主动任务排队后麦麦没有发言，就不会把它记成“做过的事”。若用户先发来消息，插件会停止认领这轮主动回复，避免把普通聊天误记为主动发言。若上一条说“我在吃饭”，下一次会请麦麦根据经过的时间说后来吃了什么、现在又在做什么；实际措辞仍由麦麦决定。为了兼容拆分发送，插件会合并首次成功发送后 15 秒内的文字。记录保存在同一个插件数据文件中，移除目标聊天流时会删除对应续接记录。

自然语言工具只操作调用者所在聊天流、该用户自己的任务。单次任务使用带时区的 ISO 时间，例如 `2026-10-21T08:00:00+08:00`；每天和每周使用 `HH:MM`，每周还需星期数字（周一为 1，周日为 7）。时间含糊时应先澄清。

插件发给 MaiBot 的主动聊天和定时任务执行提示词会直接列出工具名：`deepseek_search` 用于实时搜索，`deepseek_fetch` 用于读取已知网页，`secretary_create_task`、`secretary_list_tasks`、`secretary_cancel_task` 分别用于创建、查看和取消定时任务。若目标工具列在 MaiBot 的延迟展示工具中，提示词要求先用 `tool_search` 发现，再按实际参数调用。到点执行的任务不会重新创建同一任务；普通主动闲聊也不会无故联网或创建任务。工具不可用时应如实说明。

到点后的“成功”表示 MaiBot 接受了主动任务请求，不等于已经观察到消息发出。插件先持久化“已尝试”再触发，避免重启造成重复消息。服务中断超过 `misfire_grace_seconds`（默认 10 分钟）时会跳过过期触发；单次任务会标记为 `missed`，可通过列出任务查看。接口报错时，单次任务标记为 `failed`；周期任务保留下一次执行。

## 开发与安装

本仓库直接作为 MaiBot `plugins/` 下的独立插件目录使用，不修改 MaiBot 主程序。安装依赖：

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

GitHub 仓库：[worldcopyist/maibot-mai-secretary](https://github.com/worldcopyist/maibot-mai-secretary)。插件按 MIT 许可证发布，详见 `LICENSE`。发布后仍需在服务器上验证从仓库安装或更新的流程。
