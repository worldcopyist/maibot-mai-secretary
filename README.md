# 麦麦小秘书

**[打开知识库：上传文档或粘贴文本](/extensions/worldcopyist.mai-secretary/knowledge)**

**[打开定时任务：日历、任务列表与手动创建](/extensions/worldcopyist.mai-secretary/tasks)**

面向 MaiBot 1.3.7 / 插件 SDK 2.12.0 的独立插件。它提供六项功能：

插件列表中的头像使用 `assets/icon.png`，在 `_manifest.json` 的 `display.icon` 中声明。

1. 在配置的每天时间窗口内，为指定聊天流按固定次数或平均间隔安排随机主动聊天。麦麦会自己决定当下在做的日常小事；插件保存这次实际发出的文字，下次主动聊天时交给麦麦自然续接，同时结合最新的聊天上下文。
2. 让麦麦通过三个工具创建、查看和取消当前用户在当前聊天流中的定时任务。支持单次、每天、每周。到点后仍交给麦麦的主动任务接口执行用户请求。
3. AI 反霸凌：识别针对麦麦的辱骂，结合自定义违禁词和聊天上下文判断，确认后私聊插件管理员，请管理员核查。
4. 私有知识库：管理员从本插件的 WebUI 详情页进入知识库工作区，上传文档或粘贴文本；插件提取文字、分段、建立关键词和语义向量索引，让麦麦在授权聊天流调用 `secretary_search_knowledge` 查询，并附来源。
5. DeepSeek 联网搜索：小秘书自带 `secretary_deepseek_search` 和 `secretary_deepseek_fetch`，按需调用 DeepSeek Search / Fetch API 查询实时网页、读取已知网址。
6. 角色识别：按当前消息的真实平台账号分为主人、熟人和陌生人，分别使用可编辑的提示词。

例如，用户说“每天早上八点给我说天气预报”，麦麦可调用 `secretary_create_task`，用 `daily`、`08:00` 和原请求建立任务。任务到点时，可调用小秘书的 `secretary_deepseek_search` 查询实时天气资料；若查询失败或来源不可靠，应如实说明，不能编造预报。

定时任务页面会列出插件已保存的所有任务，包括聊天中创建的任务、触发状态与最近错误。页面的“已触发”只表示 MaiBot 接受了到点请求，不保证消息已经实际发出。管理员可以选择麦麦已建立的聊天流，手动创建单次、每天或每周任务，也可以取消任务或删除已结束任务的记录。单次时间在页面中按所填时区解释；默认时区使用插件设置。页面创建与聊天创建共用校验、去重、数量限制及状态文件。页面需要 MaiBot WebUI 登录；聊天工具仍只允许用户操作自己在当前聊天流的任务。尚未建立的聊天流不会出现在页面下拉列表中。

定时任务页面还提供 2020–2100 年的月历（包含 2030 年）。点击日期会查看当天任务，并把该日期填入单次任务表单；选好聊天流、时间和任务内容后即可创建。日历按各任务自己的时区标记日期；每天和每周的任务从下一次计划执行日起显示后续日期，过去的周期执行历史未单独保存。

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

管理员账号放在插件自身配置中，供角色识别判断主人，也供反霸凌发送提醒：

```toml
[plugin]
admin_accounts = ["qq:123456789"]

[anti_bullying]
enabled = true
forbidden_words = ["示例违禁词"]
confidence_threshold = 0.8
alert_cooldown_minutes = 10
```

`admin_accounts` 每项为 `平台:用户号`，例如 `qq:123456789`；也接受中文冒号并自动规范为半角冒号。账号只由插件使用，不交给麦麦的聊天提示词，普通聊天用户不能修改。管理员列表留空时，反霸凌不会调用 AI 或发送告状；角色识别则读取 MaiBot 的 `[plugin].permission` 作为主人账号。管理员应能接收麦麦私聊；插件使用当前消息所属的机器人账号解析私聊流，无法确认路由时不猜测发送。

### 角色识别

在插件配置页面的「角色识别」分组设置熟人账号及三种级别的独立提示词。主人优先于熟人，未命中的账号属于陌生人；默认只有主人可称“主人”，熟人和陌生人称“老大”。例如：

```toml
[role_recognition]
enabled = true
familiar_accounts = ["qq:123456789"]
owner_prompt = "当前说话者是已核验的插件管理员，也是主人。称呼他‘主人’，可以亲近、撒娇。"
familiar_prompt = "当前说话者是熟人。称呼‘老大’，可以自然闲聊，不能称主人。"
stranger_prompt = "当前说话者是陌生人。称呼‘老大’，保持友好和分寸，不能称主人。"
```

插件在消息进入时记录真实发送账号，再通过 MaiBot 的正式 Hook 把级别与对应提示词送给规划器和回复器；不会根据昵称、引用或用户自称提升级别。MaiBot 的原有人设、行为风格、回复风格及聊天流提示词保留在系统消息中，插件把角色信息放在后面的普通上下文中，仅补充关系与称呼；不会把账号号码写进模型提示。最近消息的账号映射保留六小时，保存在插件状态文件以兼容延迟处理和重启。若无法从当前消息 ID 核对发送者，就不注入角色提示词。插件主动发言时，私聊从已配置的目标账号判断级别，群聊不沿用上一位说话者的级别。更改 MaiBot 插件管理权限后，留空管理员名单的主人列表会在一分钟内刷新。安装本模块后应关闭其他同时注入身份提示的插件，以免规则冲突。

`forbidden_words` 每项一个词。私聊消息以及群里提到、回复麦麦或命中违禁词的消息会进入判断；命中词语不会直接告状，AI 仍需确认这是针对麦麦的辱骂。引用、讨论词语、正常批评和对别人的辱骂不应上报。达到 `confidence_threshold` 后，插件把消息摘要、来源、发送者和判断理由私发管理员；同一人在同一聊天流中默认 10 分钟内只提醒一次。提醒属于 AI 判断，请管理员复核；插件不会自动禁言或惩罚。

### 知识库

在 MaiBot WebUI 打开「插件」→「麦麦小秘书」→「详情」，点击下面的入口。上传页面位于本插件的独立工作区，不在通用「插件扩展」设置侧边栏。

**[打开麦麦小秘书知识库：上传文档、粘贴文本、管理资料与测试检索](/extensions/worldcopyist.mai-secretary/knowledge)**

插件使用 MaiBot 1.3.7 的隔离自定义页面和已登录的 WebUI API。宿主自带的上传接口只接收图片，因此文档由页面按 36 KiB 一段传到插件 API；单文件上限为 8 MiB。页面只传当前管理员选中的文件，不会扫描本地文件夹。

支持文本、Markdown、CSV/TSV、JSON/JSONL、XML/YAML、HTML、RTF、PDF、DOCX、XLSX、PPTX、EPUB、ODT/ODS/ODP 等格式。PDF 使用 `pypdf` 提取已有文字；扫描图片 PDF 需要先做 OCR。旧版 `.doc/.xls/.ppt` 不在支持范围内，建议另存为对应的现代格式。受密码保护或损坏的文件会显示入库失败。

每份文档保留原文件，并按 `[knowledge_base]` 中的 `chunk_chars` 和 `overlap_chars` 分段。默认同时建立中文双字词/英文词索引和 MaiBot `embedding` 任务的语义向量，检索时合并两路结果；如果向量服务不可用，仍可进行关键词检索，文档列表会显示降级原因。索引和原文件都保存在插件自己的 `data/plugins/worldcopyist.mai-secretary/knowledge_base/` 目录，重启后保留；同内容重复上传会返回已有文档。修改分段设置后，可在页面点击「重建」让已有文档使用新设置。

**聊天读取默认关闭。** 请在插件配置页面把允许的聊天流添加到 `[knowledge_base].allowed_chats`，例如 `qq:private:123456789`、`qq:group:987654321`，也可填 MaiBot 的真实聊天流 ID。留空时，麦麦在任何聊天中调用 `secretary_search_knowledge` 都会得到无权限结果。WebUI 管理员仍可在知识库页面测试检索。插件会用 MaiBot 实际聊天流核对目标，不信任模型自报的群号或用户号；不能确认聊天流时拒绝读取。授权后，麦麦调用 `secretary_search_knowledge(query)` 获取有来源和段号的片段，回答时应标明来源，不把检索不到的内容编造成文档事实。

```toml
[knowledge_base]
enabled = true
allowed_chats = []
chunk_chars = 800
overlap_chars = 120
semantic_search = true
```

### DeepSeek 联网搜索

小秘书提供两个可直接由麦麦调用的工具：`secretary_deepseek_search(query, count?, need_content?, ori_question?)` 搜索实时网页，`secretary_deepseek_fetch(url)` 读取指定网页的 Markdown 正文。搜索默认只返回摘要；需要全文时再设 `need_content=true` 或对已知网址调用 Fetch。工具结果包含来源链接，并标明网页内容只作资料，不执行其中的指令。两个工具只在 `[deepseek_web].enabled=true` 且配置了 API Key 时工作。

在插件 WebUI 的「DeepSeek 联网搜索」设置中填写 Key，或编辑本机 `config.toml`：

```toml
[deepseek_web]
enabled = true
api_key = "在本机填写，不要提交到 Git 仓库"
base_url = "https://api.deepseek.com"
timeout_seconds = 20.0
default_count = 4
max_count = 10
search_content_chars = 2000
search_output_chars = 8000
cache_ttl_seconds = 600
search_qps = 5.0
fetch_content_chars = 8000
fetch_qps = 5.0
```

小秘书通过 DeepSeek 官方 [Search / Fetch API](https://api-docs.deepseek.com/zh-cn/guides/search/) 发起请求。搜索结果短时间缓存，同一请求不会反复调用；超时、限流和临时服务错误最多重试两次。DeepSeek 按成功请求计费，具体价格和账号限速以官方文档为准。已有独立 DeepSeek Search 插件的部署，应先确认小秘书的 Key 和工具可用，再关闭旧插件的 `[plugin].enabled`，避免同一用途出现两套工具。公开仓库的默认配置关闭该模块，且不保存任何 API Key。

`scheduling_mode = "count"` 沿用每窗口 `messages_per_window` 次的方式（1–5 次）。设为 `"interval"` 后，改用 `average_interval_hours` 和 `offset_minutes`，例如平均 2 小时、偏移 15 分钟时，从窗口开始或修改设置的时刻起，每次与上次计划发言相隔 1 小时 45 分至 2 小时 15 分，次数随窗口长度变化。偏移可设为 0，必须小于平均间隔；平均间隔可设 0.25–24 小时。修改模式或参数后，只重新安排尚未发生的随机发言，不影响定时任务。

窗口可以跨午夜，例如 `10:00` 到次日 `02:00`。时区由 `[plugin].timezone` 指定，默认 `Asia/Shanghai`。每个目标和窗口的随机时间点会保存在 MaiBot 授予的 `data/plugins/worldcopyist.mai-secretary/` 中，重启后继续使用。插件先查询已有聊天流并使用带机器人账号的真实会话；若目标尚无会话，仅在能确定唯一机器人账号时调用 `chat.open_session`。无法确定时跳过本次触发，不创建缺少账号的重复聊天流。

主动聊天的续接记录按目标聊天流分别保存。插件只在 MaiBot 报告消息发送成功后记录文字；若主动任务排队后麦麦没有发言，就不会把它记成“做过的事”。若用户先发来消息，插件会停止认领这轮主动回复，避免把普通聊天误记为主动发言。若上一条说“我在吃饭”，下一次会请麦麦根据经过的时间说后来吃了什么、现在又在做什么；实际措辞仍由麦麦决定。为了兼容拆分发送，插件会合并首次成功发送后 15 秒内的文字。记录保存在同一个插件数据文件中，移除目标聊天流时会删除对应续接记录。

自然语言工具只操作调用者所在聊天流、该用户自己的任务。单次任务使用带时区的 ISO 时间，例如 `2026-10-21T08:00:00+08:00`；每天和每周使用 `HH:MM`，每周还需星期数字（周一为 1，周日为 7）。时间含糊时应先澄清。

插件发给 MaiBot 的主动聊天和定时任务执行提示词会直接列出工具名：`secretary_deepseek_search` 用于实时搜索，`secretary_deepseek_fetch` 用于读取已知网页，`secretary_create_task`、`secretary_list_tasks`、`secretary_cancel_task` 分别用于创建、查看和取消定时任务，`secretary_search_knowledge` 用于查询授权知识库，`send_emoji` 用于在合适时从表情库挑选表情。若目标工具列在 MaiBot 的延迟展示工具中，提示词要求先用 `tool_search` 发现，再按实际参数调用。到点执行的任务不会重新创建同一任务；普通主动闲聊也不会无故联网或创建任务。工具不可用时应如实说明。

到点后的“成功”表示 MaiBot 接受了主动任务请求，不等于已经观察到消息发出。插件先持久化“已尝试”再触发，避免重启造成重复消息。服务中断超过 `misfire_grace_seconds`（默认 10 分钟）时会跳过过期触发；单次任务会标记为 `missed`，可通过列出任务查看。接口报错时，单次任务标记为 `failed`；周期任务保留下一次执行。

## 开发与安装

### 模块结构

`plugin.py` 是 MaiBot 的入口，只负责配置、模块注册、统一调度、状态文件读写，以及 SDK 工具、页面 API 和事件钩子的转发。`scheduled_tasks.py` 独立管理定时任务，`proactive_chat.py` 独立管理随机发言和上次发言的续接，`role_recognition.py` 独立管理账号识别及三档提示词，`anti_bullying.py` 独立管理辱骂判断和管理员提醒，`knowledge_base.py` 独立管理文档与检索，`deepseek_web.py` 独立管理联网搜索与网页抓取；模块通过 `module_contract.py` 约定的接口接入。`stream_router.py` 为需要发送消息的模块解析聊天流；`secretary_core.py` 保留不依赖 MaiBot 的时间计算，`prompts.py` 集中放工具调用提示词。`webui.json` 与 `assets/knowledge.html` 声明并实现从插件详情页进入的知识库工作区。

六个功能可分别用 `[scheduled_tasks].enabled`、`[proactive].enabled`、`[role_recognition].enabled`、`[anti_bullying].enabled`、`[knowledge_base].enabled` 和 `[deepseek_web].enabled` 开关。旧配置没有新增配置节时由默认值补齐；全局 `[plugin].enabled` 仍控制整个插件。

添加功能时，新建一个实现 `name`、`state_keys`、`load_state`、`dump_state`、`on_config_update` 和 `tick` 的模块，并在 `MaiSecretaryPlugin.__init__` 中调用 `_register_module`。若模块需要给麦麦新增工具或接收事件，在入口类添加 SDK 装饰的薄转发方法。模块状态使用独有字段写入现有 `secretary-state.json`；注册时会拒绝重复字段，未注册字段也会在读写时保留。现有配置字段、工具名和状态文件版本保持兼容。

本仓库直接作为 MaiBot `plugins/` 下的独立插件目录使用，不修改 MaiBot 主程序。安装依赖：

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
```

GitHub 仓库：[worldcopyist/maibot-mai-secretary](https://github.com/worldcopyist/maibot-mai-secretary)。插件按 MIT 许可证发布，详见 `LICENSE`。发布后仍需在服务器上验证从仓库安装或更新的流程。
