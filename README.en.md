<p align="center"><img src="assets/icon.png" alt="Mai Secretary avatar: Azure" width="144"></p>

# Mai Secretary · 麦麦小秘书

**English** · [简体中文](README.md)

## At a glance

- **Companionship and plans:** shared simulated life and mood, proactive chat, scheduled tasks, class reminders, daily reports, relationships, and follow-ups.
- **Information and expression:** knowledge retrieval, web search, Blueberry balance, experimental voice replies, and pokes.
- **Chat management:** QQ group management, anti-bullying, message debouncing, and natural-language feature switches for administrators.

## Token usage and cost

> [!IMPORTANT]
> **Token usage:** Most features exposed to MaiBot send tool results or extra context back to the LLM (language model) for a decision or reply, increasing input token use and potentially increasing cost when the model charges per token. Daily summaries, AI group moderation, and chat-driven mood changes may also make separate model calls. Actual usage depends on how often features run and how much text they return.

## Open the plugin pages

- [Module workbench: switches, relationships, follow-ups, and delivery receipts](/extensions/worldcopyist.mai-secretary/workbench)
- [Task calendar and manual scheduling](/extensions/worldcopyist.mai-secretary/tasks)
- [Timetable import and class reminders](/extensions/worldcopyist.mai-secretary/timetable)
- [Knowledge base and QQ moderation word lists](/extensions/worldcopyist.mai-secretary/knowledge)

These routes open inside an authenticated MaiBot WebUI installation. Their Markdown links may not open directly from GitHub.

## Features and modules

| Module | What it does | Main controls or tools |
| --- | --- | --- |
| `feature_control.py` | Lets a verified administrator list, enable, disable, or reset module and Boolean subfeature switches in natural language. Chat-set values persist in plugin state and override the WebUI configuration until reset. | `secretary_feature_switch`; workbench |
| `scheduled_tasks.py` | Creates one-time, daily, or weekly tasks for the current user and chat stream. At the due time, asks Maisaka to carry out the original request with current context. | `secretary_create_task`, `secretary_list_tasks`, `secretary_cancel_task`; calendar |
| `timetable.py` | Imports the CDUT-exported student timetable .xls (via the xlrd dependency), timetable HTML, or CDUT-Studio course JSON, calculates actual teaching weeks from the supplied first Monday, and creates one-time reminders before future classes. The lead time and section start times are configurable. | `secretary_query_timetable`; `[timetable]`; timetable page |
| `task_receipts.py` | Separates Maisaka's queue acceptance from a matched actual send result. Records accepted, sent, failed, and unknown states. Unknown results are never automatically resent; an administrator can retry a confirmed failure once. | `secretary_task_receipts`; workbench |
| `proactive_chat.py` | Randomly starts conversations in selected chat streams during configured time windows. Supports a target average interval plus random offset, recent context, and continuity from the last message actually sent. | `[proactive]` |
| `virtual_life.py` | Chooses one activity per time period and shares it across every chat stream, including after a restart. Editable random choices and fixed weekday activities remain available. MaiBot's own persona has priority. | `[virtual_life].*_choices`, `fixed_activities` |
| `mood.py` | Draws one shared mood per time period, influenced by activity and previous mood. Addressed chats can change it through a background model judgment. Confirmed anti-bullying events use a separate editable mood distribution. Each set of nine probabilities must total 100%. Owner, familiar, and stranger tiers express it with different intensity. Off by default. | `[mood]`; `secretary_feature_switch` |
| `daily_report.py`, `daily_report_renderer.py` | Summarizes one chat stream's text on schedule or on an administrator's request. Local rendering places the text on a 9:16 Azure, classical letter-paper, or custom theme; no image generation model is required. | `secretary_generate_daily_report`; `[daily_report].theme` |
| `role_recognition.py` | Checks the real platform account and applies separate owner, familiar, or stranger prompts. The owner's identity comes from plugin admins or MaiBot plugin managers; strangers become familiar after more than 50 counted successful interactions by default. | `[role_recognition]` |
| `relationship_management.py` | Lets an administrator mark an exact account familiar or stranger, or clear that decision. Any verified user can ask about their own relationship. An owner cannot be demoted here. | `secretary_relationship`; workbench |
| `followups.py` | Schedules a later, context-aware question about a user's event in the current chat. Users can list, cancel, opt out, or opt back in. Optional automatic discovery of explicit tomorrow/day-after events is limited to private chats and off by default. | `secretary_followup`; `[followups]` |
| `poke_interaction.py` | Gives MaiBot a contextual poke tool and configurable reactions to being poked, including poking back, following other users' pokes, response probabilities, and cooldowns. | `secretary_poke`; `[poke]` |
| `group_admin.py` | Limits QQ management to configured groups and verifies both the requesting administrator and the bot's group permissions. Covers join requests, welcome text, member operations, titles, mute/unmute, and announcements. | `secretary_group_permission`, `secretary_group_member`, `secretary_group_notice`, `secretary_group_join`, `secretary_group_welcome` |
| `group_moderation.py` | Checks isolated per-group word lists, asks MaiBot's model to judge context and sensitivity, then optionally recalls or mutes a message. | `[group_admin].moderation_*`; knowledge page |
| `anti_bullying.py` | Assesses possible abuse directed at MaiBot and sends a private report to configured administrators for review. Confirmed abuse can also draw a shared mood from the separate distribution. | `[anti_bullying]`; `[mood].bullying_*` |
| `knowledge_base.py` | Accepts uploaded documents or pasted text, extracts and chunks content, builds keyword and optional embedding indexes, and restricts chat retrieval to administrator-approved streams. Keeps moderation word lists separate. | `secretary_search_knowledge`; knowledge page |
| `deepseek_web.py`, `balance_history.py` | Offers DeepSeek Search, Fetch, and a verified administrator's live API balance query. Stores each successful balance snapshot locally and can refresh automatically. Search and balance can be switched independently. | `secretary_deepseek_search`, `secretary_deepseek_fetch`, `secretary_deepseek_balance`; `[deepseek_web]` |
| `blueberry_budget.py` | Treats the configured alias “蓝莓” (“Blueberry”) as the API balance, compares saved snapshots, and can notify administrators privately when an automatic snapshot crosses the low-balance threshold. It does not make extra balance requests. Off by default. Its settings share the DeepSeek section; legacy `[blueberry_budget]` values migrate automatically. | `secretary_blueberry_budget`; `[deepseek_web].budget_*` |
| `voice_synthesis.py` (Voice module) | Experimental; reliability remains uncertain. Sends speech or singing when explicitly requested. The editable default VoiceDesign prompt avoids a fixed character, age, or gender and uses MaiBot's existing MiMo API key. | `secretary_speak`; `[voice_synthesis]` |
| `message_debounce.py` | Merges closely spaced messages from the same real sender and optionally suppresses a stale private reply after a newer message arrives. | `[message_debounce]` |

The **DeepSeek 联网与余额** plugin configuration section contains search, balance, and low-balance alert settings together. The old standalone Blueberry budget card was removed from the workbench; existing budget tools and saved balance history remain available. Set a mood's base probability to zero to exclude it from time-period draws; a sufficiently clear chat interaction can still cause that mood. Activity and previous mood adjust the remaining draw weights. When enabled, chat influence analyzes private messages and group messages addressed to MaiBot in the background. Each analyzed message makes one short model call, without holding up the current reply. A confirmed targeted abuse verdict from the anti-bullying module uses separate `[mood].bullying_*` weights (defaults: wronged 40%, sad 30%, irritable 20%, angry 10%). This local draw overrides ordinary chat analysis of the same message and adds no model call beyond anti-bullying's existing judgment. The shared state stores the resulting mood, never the message text or another stream's conversation. MaiBot's persona and current conversation take priority.

The knowledge base accepts text, Markdown, CSV/TSV, JSON/JSONL, XML/YAML, HTML, RTF, PDF with extractable text, DOCX, XLSX, PPTX, EPUB, ODT/ODS/ODP. Scanned PDFs require OCR before upload. The upload limit is 8 MiB per file. Chat retrieval is denied until `[knowledge_base].allowed_chats` contains an approved stream.

### CDUT timetable import

In the [timetable page](/extensions/worldcopyist.mai-secretary/timetable), select an existing chat stream, enter the **Monday of teaching week 1** and the semester length, then upload the school-exported 学生个人课表 .xls workbook (parsed automatically, up to about 48 KB), upload the personal timetable HTML saved from the authenticated CDUT academic site, or paste the `courses` JSON returned by [CDUT-Studio](https://github.com/Nya-Angle/CDUT-Studio). Review the parsed courses and future reminder count before confirming. Each stream has its own timetable. The import replaces only that stream's previous timetable reminders. `[timetable].remind_before_minutes` defaults to 20; the 11 section start times are editable and should be checked against the current school timetable. MaiBot receives a scheduled task for each future class and answers in its existing persona. `secretary_query_timetable(date)` can only read the current stream's imported schedule.

CDUT-Studio authenticates through a local desktop browser session and handles the academic site's dynamic security checks. This server-side plugin does **not** log in to CDUT or store a student number, password, or session cookie. Reimport after timetable changes. CDUT's [academic office notice](https://aao.cdut.edu.cn/__local/E/BE/F1/EC76DBD3B507867475376F2102F_4146917D_24873.pdf) says the official academic system remains authoritative.

## Natural-language examples and permissions

An authenticated plugin administrator can say “列出小秘书功能”, “开启约定回访”, “关闭联网搜索”, “把 qq:123456789 设为熟人”, or “把蓝莓提醒线设为 10”. MaiBot uses the exact tools listed above. Other users can ask about their own relationship, schedule their own tasks or follow-ups in the current chat, and opt out of personal follow-ups. An administrator must explicitly request global changes, group management writes, or an immediate daily report.

The administrator list is `[plugin].admin_accounts`; when it is empty, role recognition and admin-only tools use MaiBot's plugin management permission accounts. The plugin verifies the current real sender rather than trusting a nickname or a tool argument. If MaiBot disables or unloads the entire plugin, no chat tool can re-enable it; use MaiBot's plugin management page. Enabling a switch does not fill in required target streams, group IDs, API keys, or permissions.

The daily report and follow-up modules submit proactive tasks to MaiBot. Queue acceptance is not proof of delivery. Task receipts only mark a scheduled task as sent after a matching host send hook reports success. A manually queried Blueberry balance is refreshed on every explicit administrator question; the next automatic refresh interval starts from that successful query. Historical values are labeled with their query time.

### Experimental Focus mode

On MaiBot 1.3.7, if Focus applies to a target chat but that chat does not hold the active focus slot, MaiBot may accept a proactive task and then discard its queued turn before the model runs. The plugin consumes the scheduled random-chat slot before submitting it, so a “queued” response neither proves delivery nor automatically retries that slot. Scheduled tasks and follow-ups use the same proactive interface and can also be accepted without a message being sent. A chat already holding the focus slot is not blocked this way. See the [MaiBot 1.3.7 decision loop](https://github.com/Mai-with-u/MaiBot/blob/1.3.7/src/maisaka/reasoning_engine.py#L953-L967).

This restriction does not apply with `focus_mode=false`, or to private chats when `focus_on_private=false`. Exclude the target chat from Focus to avoid this specific gate. The proactive trigger API reports queue acceptance but exposes neither focus-slot status nor a final send receipt for that task; the plugin records a result through a send hook only after a message is actually sent. Blind retries could send duplicate messages.

## Architecture and persistence

```text
MaiBot SDK → plugin.py (configuration, tools, hooks, WebUI APIs, scheduler)
                 ├── module_contract.py + independent feature modules
                 ├── secretary_core.py / stream_router.py / prompts.py
                 └── data/plugins/worldcopyist.mai-secretary/
WebUI      → webui.json → assets/workbench.html, tasks.html, timetable.html, knowledge.html
```

`plugin.py` is the only SDK entry point. Each feature owns its behavior and state fields, while the entry point registers it and forwards SDK events. New modules implement `name`, `state_keys`, `load_state`, `dump_state`, `on_config_update`, and `tick` from `module_contract.py`; `_register_module` rejects duplicate state keys. The shared `secretary-state.json` uses schema version 1 and retains unknown keys for future modules. The switch overlay lives there rather than writing back to the server's `config.toml`. Balance snapshots use `deepseek-balance.sqlite3`, and knowledge documents and indexes remain in the plugin's data directory. `prompts.py` keeps tool-routing text together and gives MaiBot's existing persona priority.

The avatar above is declared as `assets/icon.png` in `_manifest.json` for MaiBot's plugin list.

## Install and test

This plugin runs through the MaiBot SDK without changing MaiBot's source code. It was tested on MaiBot 1.3.7 and plugin SDK 2.12.0; consult `_manifest.json` for declared bounds and capabilities. The repository's manifest version is `0.29.1`.

Place this repository in its own directory under MaiBot's `plugins/` directory, install `requirements.txt` in MaiBot's Python environment, then enable the plugin and configure it in MaiBot WebUI. Preserve the installation's actual `config.toml` and `data/plugins/worldcopyist.mai-secretary/` when updating. Keep API keys out of Git. The default DeepSeek web module, daily scheduled report, follow-ups, and Blueberry budget alerts are off until configured. A proactive target list left empty sends no random messages.

Local development on Windows:

```powershell
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
uv pip install --python .venv/Scripts/python.exe pytest ruff
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
```

The [Chinese guide](README.md) contains the full configuration examples for QQ moderation, voice, reports, virtual life, DeepSeek, and the knowledge base. See the [custom report-theme format](docs/daily-report-themes.md) for image size, text-safe areas, and a local preview command. The plugin manifest follows the [MaiBot plugin repository requirements](https://github.com/Mai-with-u/plugin-repo/blob/main/CONTRIBUTING.md). Submission to the official plugin center also requires a published GitHub Release whose version matches `_manifest.json`; a pushed commit alone is not that release.

## References and licenses

| Project | What we referred to | Upstream license |
| --- | --- | --- |
| [Message_Debouncing_Refactored](https://github.com/Blackwindy2333/Message_Debouncing_Refactored) | Debounce window and merge behavior. `message_debounce.py` is adapted under its MIT terms. | MIT; original copyright and full notice are retained in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). |
| [smart_poke_plugin](https://github.com/TAIY2020/smart_poke_plugin) | Poke-back, bystander poke, and probability-based interaction ideas. | [MIT](https://github.com/TAIY2020/smart_poke_plugin/blob/main/LICENSE); this plugin has its own SDK implementation. |
| [idle_proactive_chat](https://github.com/YukiSakiko/idle_proactive_chat) | Resolving real chat streams and submitting Maisaka proactive tasks. | No root license file was visible; used as a design reference only. |
| [deepseek-web-search](https://github.com/glcoge/deepseek-web-search) | Search and Fetch feature/API behavior. | [GPL-3.0](https://github.com/glcoge/deepseek-web-search/blob/main/LICENSE); its source is not included in this MIT repository. |
| [astrbot_plugin_qqadmin](https://github.com/Zhalslar/astrbot_plugin_qqadmin) | Scope of QQ group administration operations. | [GPL-3.0](https://github.com/Zhalslar/astrbot_plugin_qqadmin/blob/main/LICENSE); its source is not included in this MIT repository. |

Mai Secretary itself is licensed under [MIT](LICENSE), matching `_manifest.json`. The bundled `assets/fonts/NotoSansSC.ttf` remains under the separate [SIL Open Font License 1.1](assets/fonts/OFL.txt). The avatar and approved Azure report background are `assets/icon.png` and `assets/azure_theme.png`.

Repository: [worldcopyist/maibot-mai-secretary](https://github.com/worldcopyist/maibot-mai-secretary).
