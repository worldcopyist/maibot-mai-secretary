"""Resolve a platform chat target to an account-scoped MaiBot stream."""

from __future__ import annotations

from typing import Any


async def resolve_stream(
    ctx: Any,
    target: str,
    cache: dict[str, str],
    *,
    preferred_account_id: str = "",
) -> str:
    cache_key = f"{preferred_account_id}|{target}" if preferred_account_id else target
    if cache_key in cache:
        return cache[cache_key]
    parts = target.split(":", 2)
    if len(parts) != 3 or parts[1] not in {"group", "private"} or not all(parts):
        raise ValueError("目标格式须为 platform:group:id 或 platform:private:id")
    platform, chat_type, target_id = parts
    discovered = await ctx.chat.get_all_streams(platform=platform)
    if isinstance(discovered, list):
        streams = discovered
    elif isinstance(discovered, dict) and discovered.get("success") is not False:
        streams = discovered.get("streams")
    else:
        raise RuntimeError("无法查询现有聊天流")
    if not isinstance(streams, list):
        raise TypeError("现有聊天流查询未返回列表")
    existing = [
        item
        for item in streams
        if isinstance(item, dict)
        and item.get("platform") == platform
        and item.get("chat_type") == chat_type
        and str(item.get("group_id" if chat_type == "group" else "user_id") or "")
        == target_id
        and str(item.get("account_id") or "").strip()
        and (
            not preferred_account_id
            or str(item.get("account_id") or "").strip() == preferred_account_id
        )
    ]
    if len(existing) == 1:
        stream_id = str(
            existing[0].get("stream_id") or existing[0].get("session_id") or ""
        ).strip()
        if not stream_id:
            raise ValueError("现有聊天流缺少 stream_id")
        cache[cache_key] = stream_id
        return stream_id
    if len(existing) > 1:
        raise ValueError(f"目标 {target} 对应多个机器人账号或路由范围")
    routes = {
        (
            str(item.get("account_id") or "").strip(),
            str(item.get("scope") or "").strip(),
        )
        for item in streams
        if isinstance(item, dict)
        and item.get("platform") == platform
        and str(item.get("account_id") or "").strip()
        and (
            not preferred_account_id
            or str(item.get("account_id") or "").strip() == preferred_account_id
        )
    }
    if len(routes) != 1:
        raise ValueError(f"无法确定 {target} 使用的机器人账号，请先让目标与麦麦建立聊天流")
    account_id, scope = next(iter(routes))
    result = await ctx.chat.open_session(
        platform=platform,
        chat_type=chat_type,
        group_id=target_id if chat_type == "group" else "",
        user_id=target_id if chat_type == "private" else "",
        account_id=account_id,
        scope=scope,
    )
    if not isinstance(result, dict) or result.get("success") is False:
        raise TypeError("聊天流解析未返回数据")
    stream_id = str(result.get("stream_id") or result.get("session_id") or "").strip()
    if not stream_id:
        raise ValueError("聊天流解析未返回 stream_id")
    cache[cache_key] = stream_id
    return stream_id
