"""Keep published config labels English while installing Chinese labels locally."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

UI_TEXT = {
    "enabled": ("开启生活照片", "麦麦谈到当前模拟生活时可自行决定是否分享图片。需要填写生图密钥，每张图可能收费。"),
    "provider": ("生图 API 服务商", "选择千问生图或 MiniMax；两者共用生活照片工具、冷却时间与每日上限。"),
    "api_key": ("千问生图 API Key", "密钥只放在已安装插件的配置中，不要提交仓库或放进提示词。"),
    "region": ("API 地区", "选择生图密钥所属的地区。"),
    "model": ("生图模型", "千问图像 2.1 Turbo 可接收角色和场景参考图。"),
    "minimax_api_key": ("MiniMax 生图 API Key", "填写所选 MiniMax 地区的生图 API Key，只保存在已安装插件配置中。"),
    "minimax_region": ("MiniMax API 地区", "国内选 china，国际选 global；密钥必须匹配地区。"),
    "character_reference": ("角色参考图", "builtin:icon 使用插件头像；替换时将 PNG/JPEG/WebP 放入插件数据目录 life-photo-references，再填文件名。"),
    "home_reference": ("客厅参考图", "内置三视角客厅图；builtin:home 为原始单视角。也可填写参考图目录中的文件名。"),
    "kitchen_reference": ("厨房餐桌参考图", "内置厨房餐桌三视角图，也可填写自制参考图文件名。"),
    "bedroom_reference": ("卧室参考图", "内置卧室三视角图，也可填写自制参考图文件名。"),
    "hobby_reference": ("手工桌参考图", "内置手工和游戏桌三视角图，也可填写自制参考图文件名。"),
    "balcony_reference": ("阳台参考图", "内置阳台与植物角三视角图，也可填写自制参考图文件名。"),
    "bathroom_reference": ("洗漱区参考图", "内置洗漱区三视角图，也可填写自制参考图文件名。"),
    "neighborhood_reference": ("附近街道参考图", "内置街道和买菜小店三视角图，也可填写自制参考图文件名。"),
    "restaurant_reference": ("炸鸡店参考图", "内置炸鸡店三视角图，也可填写自制参考图文件名。"),
    "park_reference": ("湿地公园参考图", "内置湿地公园三视角图；builtin:park 为原始单视角。也可填写自制参考图文件名。"),
    "character_prompt": ("角色一致性提示词", "可写通用外貌要求，也可按自己的角色调整；MaiBot 当前人设优先。"),
    "scene_prompt": ("场景一致性提示词", "只写画面要求；活动来自当前模拟生活场景，最终生成单张图片。"),
    "cooldown_minutes": ("两张图片之间的最短间隔（分钟）", "所有聊天流共享冷却，从请求开始时计算。"),
    "max_images_per_day": ("每天最多生成张数", "按插件时区统计所有聊天流的每日尝试次数；失败的请求也可能产生费用。"),
}


def localize(source: str) -> str:
    source = source.replace('__ui_label__: ClassVar[str] = "Life Photos"', '__ui_label__: ClassVar[str] = "生活照片"')
    lines = source.splitlines(keepends=True)
    active = None
    seen: set[str] = set()
    for index, line in enumerate(lines):
        match = re.match(r"    (\w+): \w+ = Field\(", line)
        if match and match.group(1) in UI_TEXT:
            active = match.group(1)
            seen.add(active)
        if active:
            label, hint = UI_TEXT[active]
            line = re.sub(r'("label": )"[^"]*"', lambda m, label=label: m.group(1) + json.dumps(label, ensure_ascii=False), line)
            line = re.sub(r'("hint": )"[^"]*"', lambda m, hint=hint: m.group(1) + json.dumps(hint, ensure_ascii=False), line)
            lines[index] = line
            if line.strip() == "})":
                active = None
    if seen != UI_TEXT.keys():
        raise ValueError(f"Unexpected LifePhotoSettings fields: missing={UI_TEXT.keys() - seen}, extra={seen - UI_TEXT.keys()}")
    return "".join(lines)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: localize_life_photo_for_server.py SOURCE DESTINATION")
    source_path, output_path = map(Path, sys.argv[1:])
    output_path.write_text(localize(source_path.read_text(encoding="utf-8")), encoding="utf-8")
