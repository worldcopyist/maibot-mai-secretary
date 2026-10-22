"""Shared tool names injected into proactive MaiBot intents."""

TOOL_ROUTING_PROMPT = (
    "\n按需使用以下 MaiBot 工具，调用时使用准确的工具名："
    "`deepseek_search` 接收 query，用于天气、新闻等实时信息的联网搜索；"
    "`deepseek_fetch` 接收 url，用于读取已知链接的网页正文，不用它寻找未知链接；"
    "`secretary_create_task` 接收 instruction、schedule、at，用于用户要求新建未来的定时任务；"
    "`secretary_list_tasks` 用于查看用户已有的定时任务；"
    "`secretary_cancel_task` 接收 task_id，用于取消用户指定的任务，先查看列表确认任务编号；"
    "`send_emoji` 无需参数，会从现有表情库挑选并发送一张表情包；"
    "`tool_search` 只用于发现列在 deferred tools 中、但当前尚不可直接调用的工具，"
    "发现后再按其实际参数调用。"
    "定时任务管理工具只处理当前用户明确提出的请求，不因旧聊天内容重复操作。"
    "结合当前聊天话题、氛围和对方情绪决定是否配表情；贴切时调用 `send_emoji`，"
    "严肃、敏感或不需要表情的场景不要强行发送，每轮最多一次。"
    "只在对应场景调用；工具不存在、调用失败或查不到可靠信息时如实说明，"
    "不要编造工具结果或声称任务已创建。"
)
