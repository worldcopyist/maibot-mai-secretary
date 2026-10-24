"""Validate a custom daily-report background and render a sample locally."""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from daily_report_renderer import render_report

SAMPLE = (
    "今日概览：今天聊了天气和周末计划。\n"
    "聊了什么：大家分享了散步见闻，也谈到明天的安排。\n"
    "重要约定：明天上午继续讨论。\n"
    "暖心片段：互相道了晚安。"
)


def main() -> None:
    parser = argparse.ArgumentParser(description="预览麦麦小秘书自制日报主题")
    parser.add_argument("image", type=Path, help="9:16 PNG 底图")
    parser.add_argument("--output", type=Path, help="预览图输出路径，默认在底图旁加 -preview")
    args = parser.parse_args()
    output = args.output or args.image.with_name(f"{args.image.stem}-preview.png")
    png = render_report(date.today(), SAMPLE, theme="custom", custom_theme_path=args.image)
    output.write_bytes(png)
    print(f"Theme valid; preview: {output.resolve()}")


if __name__ == "__main__":
    main()
