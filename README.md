<p align="center"><img src="assets/icon.png" alt="麦麦小秘书头像：蓝天" width="144"></p>

# 麦麦小秘书（Mai Secretary）

[English](README.en.md) · **简体中文**

**[打开知识库：上传文档或粘贴文本](/extensions/worldcopyist.mai-secretary/knowledge)**

**[打开定时任务：日历、任务列表与手动创建](/extensions/worldcopyist.mai-secretary/tasks)**

**[打开模块管理：开关、关系、回访、任务回执与蓝莓预算](/extensions/worldcopyist.mai-secretary/workbench)**

以上入口供已登录 MaiBot WebUI 使用；在 GitHub 页面直接点击不会打开服务器工作区。

面向 MaiBot 1.3.7 / 插件 SDK 2.12.0 的独立插件。各功能各自保存状态，便于继续增加模块。已核验管理员可以在聊天里自然地说“列出小秘书功能”“开启约定回访”“关闭联网搜索”“恢复主动发言的页面配置”；麦麦会调用 `secretary_feature_switch`。普通用户不能改全局开关。聊天开关保存在插件数据文件中，覆盖 WebUI 配置值；模块管理页同时显示两者。若 MaiBot 管理页整体停用了插件，需要先在管理页重新启用。

插件列表中的头像使用 `assets/icon.png`，在 `_manifest.json` 的 `display.icon` 中声明。

## 功能一览

1. 在配置的每天时间窗口内，为指定聊天流按固定次数或平均间隔安排随机主动聊天。可选的每周模拟生活表让麦麦按当天当前时段安排活动；插件保存这次实际发出的文字，下次主动聊天时结合最新聊天和经过的时间自然续接。
2. 让麦麦通过三个工具创建、查看和取消当前用户在当前聊天流中的定时任务。支持单次、每天、每周。到点后仍交给麦麦的主动任务接口执行用户请求。
3. AI 反霸凌：识别针对麦麦的辱骂，结合自定义违禁词和聊天上下文判断，确认后私聊插件管理员，请管理员核查。
4. 私有知识库：管理员从本插件的 WebUI 详情页进入知识库工作区，上传文档或粘贴文本；插件提取文字、分段、建立关键词和语义向量索引，让麦麦在授权聊天流调用 `secretary_search_knowledge` 查询，并附来源。
5. DeepSeek 联网搜索与余额：小秘书自带 `secretary_deepseek_search` 和 `secretary_deepseek_fetch`，按需查询实时网页、读取已知网址；管理员还能用 `secretary_deepseek_balance` 查询所配置 DeepSeek API Key 对应账号的余额。
6. 角色识别：按当前消息的真实平台账号分为主人、熟人和陌生人，分别使用可编辑的提示词。
7. 日报：管理员可设定聊天流和每天的总结时间；管理员账号也可在当前聊天里直接请麦麦现在生成今日日报，不必等到定时点。两种方式都把当天聊天文字分段总结后填入「Azure 主题」图片。
8. 戳一戳互动：麦麦可通过 `secretary_poke` 戳当前聊天的人；被戳时可回戳、按现有人设简短回复或发表情包，也可按概率跟风戳群里正在互戳的人。
9. 蓝天语音：用户明确要求语音、朗读或唱歌时，麦麦可调用 `secretary_speak` 向当前 QQ 聊天发送语音。日常语音使用 MiMo V2.5 VoiceDesign 和可编辑的蓝天音色提示词，直接读取 MaiBot 已配置的 MiMo API Key；唱歌使用同系列预置音色，声线可能不同。
10. QQ 群管：仅在明确列出的 QQ 群启用。麦麦可用 `secretary_group_permission` 查询自己是否有群管权限；插件管理员可在当前群聊中使用群成员管理、公告、加群审核和欢迎语工具。所有群管理写操作都会核对管理员真实账号、当前群、麦麦群身份和 NapCat 操作回执，失败会作为工具结果交给麦麦。
11. 消息防抖：在私聊或群聊中，短时间内同一用户连续发送的内容会合并为一条交给麦麦处理，减少把一句话拆成多轮回复的情况。命令、通知、不同用户的消息不会混在一起。

新增独立模块：任务回执用 `secretary_task_receipts` 区分到点请求“已入队”“确认发送”“发送失败”“未知”，未知不会自动重发；管理员可以对明确发送失败的任务手动重试一次。关系管理用 `secretary_relationship` 自然语言查询或调整熟人、陌生人，主人身份始终由管理员权限决定，原先超过 50 次互动自动升级熟人的逻辑保留。约定回访用 `secretary_followup` 安排或取消当前用户的后续问候；自动发现只看私聊中明确提到的明天/后天事件，默认关闭。蓝莓预算用 `secretary_blueberry_budget` 读取已有余额记录的两次差额、设低余额提醒线；自动低余额提醒只使用原有自动查询结果，默认关闭，不会额外调用余额接口。

模块管理页可以设置功能开关、手动关系、取消回访、查看任务回执与蓝莓历史。通过聊天调整的开关会在重启后恢复；“恢复配置”会撤销聊天覆盖值。页面需要 MaiBot WebUI 登录。

### 消息防抖

插件配置页的「消息防抖」可独立开关，并设置等待后续消息的秒数、最长等待、私聊与群聊开关、命令前缀。默认收到消息后等待 2 秒；期间同一用户又发消息就重新计时，但最多等 8 秒。合并文本用换行分开，图片、表情、语音等消息段会保留。为防止把不同群友的话算成同一人，本模块始终按真实发送者分开处理；合并结果使用最后一条真实消息的 ID，供角色识别核验。插件默认增加 2 秒的单条消息等待时间；相隔更久的消息仍会分开处理。

「取消过时的私聊回复」默认开启：若麦麦还在生成针对某条私聊消息的回复，而同一私聊又收到了新消息，发送前会取消那条旧回复，让后续处理以新消息为准。只取消能确认对应近期旧用户消息的私聊回复；群聊、没有回复锚点的主动发言与定时任务不会受影响。MaiBot 规划器对同一条消息自行重复调用造成的多轮回复仍不属于消息防抖。

实现参考 [Message_Debouncing_Refactored](https://github.com/Blackwindy2333/Message_Debouncing_Refactored)，原作者版权及 MIT 许可证见 `THIRD_PARTY_NOTICES.md`。

### QQ 群管

在插件配置页「QQ群管」里开启模块并填写 `managed_group_ids`。群号为空时不会管理任何群。`secretary_group_member` 支持禁言、解禁、踢出、群名片、群头衔、设置管理员、全员禁言和改群名；`secretary_group_notice` 支持查询、发布、删除公告；`secretary_group_join` 支持查询待审申请、通过和拒绝；`secretary_group_welcome` 支持查看、修改、开关及重置本群入群欢迎语。麦麦在群内不是管理员时，工具会明确返回权限不足；设置管理员和群头衔要求麦麦是群主。只有已核验的插件管理员可以发起更改，普通群友无法借麦麦操作群管。所有工具只接受当前聊天群，不接受模型指定其他群号。

群消息自动审核也在「QQ群管」设置中配置。先在本插件知识库页面的「QQ群管 · 禁言敏感词」区域按群上传文档或粘贴词语，每行或每个表格单元格一个词。词库按群隔离，单群最多 100 份文档、3000 个词；不会进入普通知识检索。随后开启 `moderation_enabled`，分别设置 `moderation_recall`（自动撤回）、`moderation_mute`（自动禁言）、`moderation_mute_minutes`（禁言分钟数）和 `moderation_sensitivity`（0–100，越高越严格）。默认自动审核关闭。插件会在消息防抖合并前保留原消息编号；命中词语后将当前消息和最近聊天交给 MaiBot 配置的模型判断，再按设置处理。像词语“你妈”出现在“你妈身体怎么样了”这种正常询问中，应被判为无害，不触发处罚。0、50、100 敏感程度对应的处罚把握门槛分别是 95%、75%、55%；模型仍须明确判定违规且非无害。模型无有效结果、队列已满、麦麦没有群管权限或发送者是群管理人员时，不自动处罚。只审核文本消息，审核与 QQ 接口结果可在知识库页面查看；AI 误判风险仍需管理员通过小范围词库和审核记录观察。

加群审核默认由管理员手动确认。也可在配置页切换到 `keyword` 模式，用通过词和拒绝词自动审核；拒绝词优先，未命中则保持待审。入群欢迎默认关闭；开启后只在已列出的群发送。工具调用只报告 NapCat 明确确认的成功，接口报错或权限不足会把原因返回麦麦。插件不会替换或复制已有 QQAdmin 插件的代码。

### 蓝天语音

插件配置页的「蓝天语音 · MiMo」可编辑音色提示词、单条字数、发送间隔与唱歌音色。音色提示词描述声音，不替代 MaiBot 的蓝天人设；实际说什么仍由麦麦根据聊天内容决定。`secretary_speak(text, mode)` 中 `mode=speech` 为普通语音，`mode=sing` 为唱歌。语音只发往当前 QQ 聊天流，发送失败会把错误交给麦麦按人设用文字说明。插件不会在自己的配置中复制 MiMo 密钥。

例如，用户说“每天早上八点给我说天气预报”，麦麦可调用 `secretary_create_task`，用 `daily`、`08:00` 和原请求建立任务。任务到点时，可调用小秘书的 `secretary_deepseek_search` 查询实时天气资料；若查询失败或来源不可靠，应如实说明，不能编造预报。

定时任务页面会列出插件已保存的所有任务，包括聊天中创建的任务、触发状态与最近错误。页面的“已触发”只表示 MaiBot 接受了到点请求，不保证消息已经实际发出。管理员可以选择麦麦已建立的聊天流，手动创建单次、每天或每周任务，也可以取消任务或删除已结束任务的记录。单次时间在页面中按所填时区解释；默认时区使用插件设置。页面创建与聊天创建共用校验、去重、数量限制及状态文件。页面需要 MaiBot WebUI 登录；聊天工具仍只允许用户操作自己在当前聊天流的任务。尚未建立的聊天流不会出现在页面下拉列表中。

定时任务页面还提供 2020–2100 年的月历（包含 2030 年）。点击日期会查看当天任务，并把该日期填入单次任务表单；选好聊天流、时间和任务内容后即可创建。日历按各任务自己的时区标记日期；每天和每周的任务从下一次计划执行日起显示后续日期，过去的周期执行历史未单独保存。

## 配置

编辑 `config.toml` 或在 MaiBot 插件配置页面修改设置。`target_chats` 为空时，不会随机主动发言。格式为 `平台:group:群号` 或 `平台:private:用户号`：

### 戳一戳互动

`secretary_poke(target?)` 是给麦麦使用的工具。私聊只会戳当前对方；群聊可以指定准确群名片、昵称或 QQ 号，插件会核对当前群成员，同名或无法核实时拒绝发送。`target="我"` 只在插件能核验本轮真实发言者时生效；`target="刚刚戳我的人"` 只使用五分钟内的戳一戳事件。工具发送成功后才会告诉麦麦“已戳到”，失败不会冒充成功。每人冷却和每聊天流每小时上限同时适用于工具、回戳和跟风戳。

收到戳一戳后，插件把“谁对麦麦做了什么动作”写入麦麦的聊天上下文；动作由插件配置中的 `received_action_description` 决定。默认是“戳一戳”，例如改成“摸摸头”，麦麦就会将这次互动理解为对方摸摸头，后续回复也按这个场景生成；这不是固定回复台词。即使这次没有触发回复，事件仍会记录。成功戳出时会把“麦麦戳了谁”写入上下文。麦麦若需文字或表情回应，会通过 MaiBot 自己的人设与主动任务接口生成，表情使用内置 `send_emoji` 工具。戳的不是麦麦时，通知继续交给 MaiBot；跟风戳按独立概率决定，默认戳被戳的人。插件发出的戳一戳回声会被过滤，避免重复记录。

```toml
[poke]
enabled = true
respond_to_poke = true
received_action_description = "戳一戳" # 可改为“摸摸头”等动作
reaction_probability = 0.85
back_poke_probability = 0.6
reply_after_back_poke_probability = 0.3
bystander_enabled = true
bystander_probability = 0.35
bystander_target = "victim" # 或 actor：戳发起者
allow_model_poke = true
group_enabled = true
private_enabled = true
reaction_mode = "auto" # text 仅文字；emoji 优先表情
reaction_cooldown_seconds = 12
max_reactions_per_minute = 6
poke_cooldown_seconds = 60
max_pokes_per_hour = 6
```

`reaction_probability` 决定被戳后是否反应；反应时按 `back_poke_probability` 决定是否先回戳。没有回戳时会请麦麦按人设回复或发表情；成功回戳后，再按 `reply_after_back_poke_probability` 决定是否追加一次回复。即使这次选择沉默，麦麦仍能看到被戳事件。实际 QQ 互动需要提供公开 `adapter.napcat.message.send_poke` 接口的适配器。若原有 Smart Poke 插件也在运行，应先确认小秘书可用，再关闭旧插件的 `[plugin].enabled`，否则同一通知可能触发两套反应；旧插件的其他设置无需删除。

### Azure 主题日报

在插件配置页面的「日报 · Azure 主题」中，可以分别控制定时发送和聊天中即时生成。定时发送需要打开「启用定时日报」、添加一个或多个聊天流，并设置每日总结时间；默认关闭且目标为空。即时生成默认允许，但**只有插件管理员账号**可以使用，不需要设置定时目标和时间。管理员在聊天中说“蓝天，现在给我生成今日日报”，麦麦会调用 `secretary_generate_daily_report`，只读取当前聊天流从今天零点到请求时刻的记录，并把图片发回同一聊天流；不能让工具读取或发送到别的聊天流。工具先回复“已开始”，图片发出后才算完成。生成失败时插件把结果交给麦麦按现有人设回复，不直接发送固定报错文字；若图片发送状态不明，插件不会谎称发送失败或自动重发。管理员账号使用 `[plugin].admin_accounts`；名单留空时继承 MaiBot 的插件管理权限账号，无法核验时拒绝生成。

```toml
[daily_report]
enabled = false
manual_enabled = true
manual_cooldown_minutes = 10
text_model = "" # 留空使用 MaiBot 的 utils 模型任务；也可填已配置的文字模型名
fallback_text_model = "" # 主模型输出截断或超时时使用；留空表示不切换
target_chats = ["qq:private:2767263382"]
summary_time = "21:00"
```

日报采用插件的 `Asia/Shanghai` 等默认时区，统计当天零点至设定时间的聊天文字；图片和表情只标记其存在，不分析画面。聊天记录按小时分批读取，长记录继续拆段总结，再合并为一张图。服务刚启动时若聊天流暂未就绪，插件会短暂重查。图片底图是已确认的 [9:16 Azure 主题](assets/azure_theme.png)，中文排版使用附带的开源 Noto Sans SC 字体。若总结无法放进留白，插件会记录错误，不会裁掉正文。插件会在发送前记录状态，避免服务重启后重复发图；如发送结果不明，需要查看日志确认。生成阶段失败会在补执行期限内最多重试三次，过期后当天日报不会补发。

日报只让 MaiBot 的文字模型写总结，再由插件本地把文字填进 Azure 底图；不要求模型生成图片。`text_model` 可指定 MaiBot 模型配置中准确的 `name`，不是 `model_identifier`；留空则使用 `utils` 任务。`fallback_text_model` 可填另一个已配置的文字模型；主模型因输出截断或超时失败时，当前日报会改用备用模型完成失败步骤及后续总结。备用模型留空则按原错误处理。聊天内容只发送到已配置的 MaiBot 模型服务，不会进入 DeepSeek 搜索或知识库。模型调用会消耗额度。每个目标只有该聊天流的记录进入对应的总结。即时生成在工具执行时核验实际平台账号，非管理员不能启动；同一聊天流不能同时启动两份，发送成功或结果不明后默认 10 分钟内不再重复生成。管理员可修改间隔，设为 0 则不限制。即时生成不会占用当天定时日报的发送次数。关闭 `manual_enabled` 可停止聊天请求，关闭 `enabled` 可停止定时发送。

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
auto_upgrade_threshold = 50
owner_prompt = "当前说话者是已核验的插件管理员，也是主人。称呼他‘主人’，可以亲近、撒娇。"
familiar_prompt = "当前说话者是熟人。称呼‘老大’，可以自然闲聊，不能称主人。"
stranger_prompt = "当前说话者是陌生人。称呼‘老大’，保持友好和分寸，不能称主人。"
```

插件在消息进入时记录真实发送账号，再通过 MaiBot 的正式 Hook 把级别与对应提示词送给规划器和回复器；不会根据昵称、引用或用户自称提升级别。陌生人收到麦麦一次成功回复，计一次互动；同一条消息的多段回复、发送失败、主动发言和群里其他人的聊天都不计数。按平台账号跨聊天流累计，默认超过 50 次（第 51 次）自动升级熟人，下一次对话使用熟人提示词；已升级关系与次数保存在插件状态文件中，重启后仍有效。主人身份始终优先，手动熟人立即生效。首次启用后从零开始累计，不追溯旧聊天记录。MaiBot 的原有人设、行为风格、回复风格及聊天流提示词保留在系统消息中，插件把角色信息放在后面的普通上下文中，仅补充关系与称呼；不会把账号号码写进模型提示。最近消息的账号映射保留六小时，保存在插件状态文件以兼容延迟处理和重启。若无法从当前消息 ID 核对发送者，就不注入角色提示词。插件主动发言时，私聊从已配置的目标账号判断级别，群聊不沿用上一位说话者的级别。更改 MaiBot 插件管理权限后，留空管理员名单的主人列表会在一分钟内刷新。安装本模块后应关闭其他同时注入身份提示的插件，以免规则冲突。

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

### DeepSeek 联网搜索与余额

小秘书提供三个可直接由麦麦调用的工具：`secretary_deepseek_search(query, count?, need_content?, ori_question?)` 搜索实时网页，`secretary_deepseek_fetch(url)` 读取指定网页的 Markdown 正文，`secretary_deepseek_balance()` 查询 API 账号余额。搜索默认只返回摘要；需要全文时再设 `need_content=true` 或对已知网址调用 Fetch。网页工具结果包含来源链接，并标明网页内容只作资料，不执行其中的指令。三个工具需要 `[deepseek_web].enabled=true` 且配置 API Key；搜索与抓取还受 `search_enabled` 控制，余额查询还受 `balance_enabled` 控制，可分别用自然语言开关。

管理员可以在聊天中直接问“DeepSeek API 余额还剩多少？”或“赠金额度还有多少？”。麦麦会调用 `secretary_deepseek_balance`，从 DeepSeek 官方余额接口读取这把 Key 所属账号的实时总可用余额、未过期赠金和充值余额，并按接口返回的币种报告。插件会在请求前核验当前聊天流和真实发言者；普通用户、无法核验身份的请求以及主动聊天都不能发起实时余额查询。工具不会返回 API Key，也不会把接口原始错误信息交给模型。余额查询只反映小秘书配置的这把 Key 所属账号，不汇总其他平台或密钥。

在插件 WebUI 的「DeepSeek 联网与余额」中，可把「API 余额的别称」设为“蓝莓”。主人说“蓝莓”默认就是 API 余额；它也是蓝天最喜欢的食物，麦麦可以按人设用珍惜蓝莓的口吻谈余额，但不能虚构水果颗数或库存。管理员每次问“蓝莓还剩多少”“蓝莓够不够用”等余额问题，插件会按真实消息 ID 在规划回复前重新查询一次，再把本次结果交给麦麦；模型若又调用 `secretary_deepseek_balance`，工具会复用这条消息的结果，不会再次请求。别称不改变查询账号和管理员权限。群聊里即使另一位成员紧接着发言，插件也会凭管理员那条明确的余额请求和真实消息 ID 完成核验；每条请求最多查询一次，超过两分钟失效。

开启「自动更新余额」后，小秘书启动时若没有近期记录，会查询一次，此后默认每 6 小时更新；管理员手动查询成功后，自动查询间隔从这次查询时间重新开始，失败后至少 30 分钟再试。每次**成功**的自动或管理员手动查询都会追加到本机插件数据目录的 `deepseek-balance.sqlite3`，重启后仍在；只保存余额、币种、查询时间、来源、当时的别称与不可逆的密钥指纹，不保存 API Key。换 Key 后，麦麦不会把旧账号的记录当作新账号余额。

开启「所有聊天流可谈论余额」后，最近一次查询结果会作为后台事实加入麦麦的规划与回复上下文，所有群聊和私聊的人都可能听到具体金额。提示词会标明查询时间和币种，要求按 MaiBot 人设、结合话题自然使用，不把历史数字说成实时余额。主人提到“蓝莓”时默认指 API 余额；其他人的说法按上下文理解。不开此项时，别称仍能供管理员手动查询，但普通聊天看不到缓存金额。公开配置默认不自动查询，也不向聊天共享余额。

在插件 WebUI 的「DeepSeek 联网与余额」设置中填写 Key，或编辑本机 `config.toml`：

```toml
[deepseek_web]
enabled = true
api_key = "在本机填写，不要提交到 Git 仓库"
balance_alias = "蓝莓"
auto_balance_enabled = true
auto_balance_interval_hours = 6.0
balance_context_all_chats = true
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

小秘书通过 DeepSeek 官方 [Search / Fetch API](https://api-docs.deepseek.com/zh-cn/guides/search/) 和[余额接口](https://api-docs.deepseek.com/zh-cn/api/get-user-balance/)发起请求。搜索结果短时间缓存，同一请求不会反复调用；超时、限流和临时服务错误最多重试两次。DeepSeek 按成功请求计费，具体价格和账号限速以官方文档为准。已有独立 DeepSeek Search 插件的部署，应先确认小秘书的 Key 和工具可用，再关闭旧插件的 `[plugin].enabled`，避免同一用途出现两套工具。公开仓库的默认配置关闭该模块，且不保存任何 API Key。

`scheduling_mode = "count"` 沿用每窗口 `messages_per_window` 次的方式（1–5 次）。设为 `"interval"` 后，改用 `average_interval_hours` 和 `offset_minutes`，例如平均 2 小时、偏移 15 分钟时，从窗口开始或修改设置的时刻起，每次与上次计划发言相隔 1 小时 45 分至 2 小时 15 分，次数随窗口长度变化。偏移可设为 0，必须小于平均间隔；平均间隔可设 0.25–24 小时。修改模式或参数后，只重新安排尚未发生的随机发言，不影响定时任务。

#### 每周模拟生活

在插件配置页「模拟生活 · 每周安排」中打开开关，按标有“周几 · 时段”的输入项分别填写早晨、上午、中午、下午、傍晚、夜晚、深夜、凌晨的生活安排，共 56 项。配置时间按 `[plugin].timezone` 解释：凌晨 00:00–06:59，早晨 07:00–08:59，上午 09:00–11:29，中午 11:30–13:29，下午 13:30–17:29，傍晚 17:30–19:29，夜晚 19:30–22:29，深夜 22:30–23:59。默认配置包含独自在家的规律日常，以及周三下午清理蓝天小窝、周四下午疯狂星期四吃 KFC、周五傍晚湿地公园散步吹风；每项都可以独立修改。

主动发言触发时，小秘书以**实际触发时间**读取对应星期和时段，把安排作为生活背景交给麦麦，再让麦麦结合本聊天流的最近对话与上次实际发出的内容选话题。若上次做的事与现在不同，会提示麦麦按经过的时间自然转场；MaiBot 原本的人设始终优先。模拟生活只作用于随机主动发言，不改普通聊天和定时任务。睡觉时段若不想主动发言，还需把 `[proactive]` 发言窗口设在清醒时段，例如 `07:00`–`00:00`。

```toml
[virtual_life]
enabled = true
wednesday_afternoon = "固定清理蓝天小窝：擦桌子、收玩偶、整理床铺和地板。"
thursday_afternoon = "固定过疯狂星期四：去 KFC 爽吃炸鸡和薯条。"
friday_dusk = "固定去湿地公园散步吹风，看水面、芦苇和傍晚的天空。"
```

窗口可以跨午夜，例如 `10:00` 到次日 `02:00`。时区由 `[plugin].timezone` 指定，默认 `Asia/Shanghai`。每个目标和窗口的随机时间点会保存在 MaiBot 授予的 `data/plugins/worldcopyist.mai-secretary/` 中，重启后继续使用。插件先查询已有聊天流并使用带机器人账号的真实会话；若目标尚无会话，仅在能确定唯一机器人账号时调用 `chat.open_session`。无法确定时跳过本次触发，不创建缺少账号的重复聊天流。

主动聊天的续接记录按目标聊天流分别保存。插件只在 MaiBot 报告消息发送成功后记录文字；若主动任务排队后麦麦没有发言，就不会把它记成“做过的事”。若用户先发来消息，插件会停止认领这轮主动回复，避免把普通聊天误记为主动发言。若上一条说“我在吃饭”，下一次会请麦麦根据经过的时间说后来吃了什么、现在又在做什么；实际措辞仍由麦麦决定。为了兼容拆分发送，插件会合并首次成功发送后 15 秒内的文字。记录保存在同一个插件数据文件中，移除目标聊天流时会删除对应续接记录。

自然语言工具只操作调用者所在聊天流、该用户自己的任务。单次任务使用带时区的 ISO 时间，例如 `2026-10-21T08:00:00+08:00`；每天和每周使用 `HH:MM`，每周还需星期数字（周一为 1，周日为 7）。时间含糊时应先澄清。

插件发给 MaiBot 的主动聊天和定时任务执行提示词会直接列出工具名：`secretary_deepseek_search` 用于实时搜索，`secretary_deepseek_fetch` 用于读取已知网页，`secretary_deepseek_balance` 仅在已核验管理员明确询问时查询 API 余额，`secretary_create_task`、`secretary_list_tasks`、`secretary_cancel_task` 分别用于创建、查看和取消定时任务，`secretary_task_receipts` 查询送达回执，`secretary_feature_switch` 由管理员控制模块开关，`secretary_relationship` 管理关系，`secretary_followup` 管理回访，`secretary_blueberry_budget` 查看余额历史与提醒线，`secretary_generate_daily_report` 用于管理员明确要求即时生成今日日报，`secretary_poke` 用于合适的当前聊天戳一戳互动，`secretary_search_knowledge` 用于查询授权知识库，`send_emoji` 用于在合适时从表情库挑选表情。若目标工具列在 MaiBot 的延迟展示工具中，提示词要求先用 `tool_search` 发现，再按实际参数调用。到点执行的任务不会重新创建同一任务；普通主动闲聊也不会无故联网或创建任务。工具不可用时应如实说明。

到点后的“成功”表示 MaiBot 接受了主动任务请求，不等于已经观察到消息发出。插件先持久化“已尝试”再触发，避免重启造成重复消息。服务中断超过 `misfire_grace_seconds`（默认 10 分钟）时会跳过过期触发；单次任务会标记为 `missed`，可通过列出任务查看。接口报错时，单次任务标记为 `failed`；周期任务保留下一次执行。

## 模块结构

```text
MaiBot SDK ── plugin.py（配置、工具、Hook、WebUI API、统一调度）
                  ├─ module_contract.py（模块接入约定）
                  ├─ feature_control.py（自然语言开关）
                  ├─ 定时与主动行为模块
                  ├─ 聊天、安全与身份模块
                  └─ 知识、联网与语音模块
插件数据 ── data/plugins/worldcopyist.mai-secretary/
WebUI ──── webui.json → assets/*.html
```

`plugin.py` 是唯一的 MaiBot 插件入口。每个业务模块负责自己的行为及状态，入口只注册模块并转发 SDK 工具、事件钩子和 WebUI API。模块按 `module_contract.py` 实现 `name`、`state_keys`、`load_state`、`dump_state`、`on_config_update`、`tick`。状态集中写进 `secretary-state.json`，注册时会拒绝重复状态键，读写时保留未知键，方便升级后继续增添模块。聊天里设定的开关是 `feature_control.py` 的状态覆盖层：它不改服务器原 `config.toml`，重启后仍保留；管理页会同时显示原配置和当前开关。全局插件若在 MaiBot 管理页被卸载或停用，聊天工具无法把它重新唤醒。

| 模块文件 | 功能与边界 |
| --- | --- |
| `scheduled_tasks.py`、`secretary_core.py` | 单次、每日、每周定时任务；时间解析、下次运行和过期处理。 |
| `task_receipts.py` | 记录任务入队、实际发送、明确失败与结果未知；未知不自动重发。 |
| `daily_report.py`、`daily_report_renderer.py` | 到点或管理员手动总结当日聊天，文字模型写内容，本地渲染 9:16 Azure 主题图片。 |
| `proactive_chat.py`、`virtual_life.py` | 指定聊天流随机主动发言、按上次实际发言续接话题，并按每周日常表安排背景。 |
| `role_recognition.py`、`relationship_management.py` | 真实账号核验、主人/熟人/陌生人提示、成功互动计数和管理员手动关系。 |
| `followups.py` | 用户自行安排后续问候；可选私聊未来事件自动发现，默认关闭。 |
| `poke_interaction.py` | 戳一戳工具、被戳回应、回戳、跟风戳、概率和冷却。 |
| `group_admin.py`、`group_moderation.py` | 限定 QQ 群的权限核对、入群审核与欢迎、成员管理、公告，以及命中词后交 AI 审核的撤回/禁言。 |
| `anti_bullying.py` | 判断针对麦麦的辱骂，向管理员私聊提醒复核。 |
| `knowledge_base.py` | 文档上传、粘贴、分段、关键词/语义检索及按聊天流授权；群管词库单独隔离。 |
| `deepseek_web.py`、`balance_history.py` | Search / Fetch、实时余额及成功查询历史；API Key 留在本机配置。 |
| `blueberry_budget.py` | 从已有余额记录比较变化，按管理员提醒线低余额通知；默认关闭。 |
| `voice_synthesis.py` | 语音和唱歌工具，读取 MaiBot 已配置的 MiMo Key。 |
| `message_debounce.py` | 同用户短消息合并及过时私聊回复取消。 |
| `stream_router.py`、`prompts.py` | 解析真实聊天流；集中保存工具路由与人设优先提示。 |
| `webui.json`、`assets/*.html` | 在 MaiBot WebUI 内提供定时日历、知识库和模块管理页面。 |

新功能只需新增符合 `module_contract.py` 的模块、在 `plugin.py` 注册，并按需添加薄转发工具或 Hook。各模块可在配置页设置，已核验管理员也可通过 `secretary_feature_switch` 用自然语言开关模块和布尔子功能。前置开关、管理员权限、目标聊天流和 API Key 仍各自生效；开关打开不代表尚未填写的配置已经齐备。

## 安装与验证

本仓库是 MaiBot 的独立插件，不修改 MaiBot 主程序。将仓库放入 MaiBot `plugins/` 下的独立目录，按 `requirements.txt` 安装 Python 依赖，再通过 MaiBot 插件管理页启用并填写本机配置。最低版本以 `_manifest.json` 为准，目前是 MaiBot 1.3.7、插件 SDK 2.12.0。不要把 API Key 或服务器上的 `config.toml` 提交到 Git。升级时保留安装目录中的实际 `config.toml` 和 MaiBot 的 `data/plugins/worldcopyist.mai-secretary/` 数据目录。

本地检查：

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
uv pip install --python .venv/Scripts/python.exe pytest ruff
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
```

## 参考项目与许可证

| 项目 | 本插件参考之处 | 上游许可 |
| --- | --- | --- |
| [Message_Debouncing_Refactored](https://github.com/Blackwindy2333/Message_Debouncing_Refactored) | 消息防抖的窗口与合并方案；`message_debounce.py` 按其 MIT 许可改写。 | MIT，原版权与完整许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。 |
| [smart_poke_plugin](https://github.com/TAIY2020/smart_poke_plugin) | 戳一戳的回戳、跟风与概率交互形式；本插件实现自己的 SDK 模块。 | [MIT](https://github.com/TAIY2020/smart_poke_plugin/blob/main/LICENSE)。 |
| [idle_proactive_chat](https://github.com/YukiSakiko/idle_proactive_chat) | 真实聊天流解析和 Maisaka 主动任务的使用思路；本插件实现按时间窗口随机调度。 | 仓库未见根目录许可证文件；仅作设计参考。 |
| [deepseek-web-search](https://github.com/glcoge/deepseek-web-search) | Search / Fetch 的功能与接口用途；本插件独立实现请求、缓存和余额记录。 | [GPL-3.0](https://github.com/glcoge/deepseek-web-search/blob/main/LICENSE)，不纳入本仓库代码。 |
| [astrbot_plugin_qqadmin](https://github.com/Zhalslar/astrbot_plugin_qqadmin) | QQ 群管操作范围；本插件通过 MaiBot SDK 与适配器接口独立实现。 | [GPL-3.0](https://github.com/Zhalslar/astrbot_plugin_qqadmin/blob/main/LICENSE)，不纳入本仓库代码。 |

本插件自身按 [MIT 许可证](LICENSE) 发布；`_manifest.json` 的 `license` 字段也为 `MIT`，符合 [MaiBot 插件仓库文件要求](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md)。随仓库分发的字体 `assets/fonts/NotoSansSC.ttf` 另按 [SIL Open Font License 1.1](assets/fonts/OFL.txt) 授权，不改为 MIT。上述 GPL 项目是功能和接口参考，不能把它们的源码直接复制进 MIT 模块。用户提供的头像和已审定的 Azure 日报底图分别位于 `assets/icon.png`、`assets/azure_theme.png`。

项目仓库：[worldcopyist/maibot-mai-secretary](https://github.com/worldcopyist/maibot-mai-secretary)。向 MaiBot 官方插件中心提交时，还需按其要求发布与清单版本一致的 GitHub Release。
