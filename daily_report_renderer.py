"""Render daily-report text onto a built-in or user-supplied portrait theme."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent / "assets"
AZURE_THEME = ASSETS / "azure_theme.png"
LETTER_THEME = ASSETS / "letter_theme.png"
FONT = ASSETS / "fonts" / "NotoSansSC.ttf"
CUSTOM_THEME_FILENAME = "daily_report_theme.png"
MAX_THEME_BYTES = 8 * 1024 * 1024
OUTPUT_SIZE = (936, 1664)


@dataclass(frozen=True)
class _Theme:
    image: Path
    ink: str
    title: str | None
    date_suffix: str


def _wrap(draw: ImageDraw.ImageDraw, value: str, font: ImageFont.FreeTypeFont, width: int) -> list[str]:
    lines: list[str] = []
    for paragraph in value.splitlines():
        if not paragraph.strip():
            lines.append("")
            continue
        line = ""
        for char in paragraph:
            candidate = line + char
            if line and draw.textlength(candidate, font=font) > width:
                lines.append(line)
                line = char
            else:
                line = candidate
        lines.append(line)
    return lines


def _theme(name: str, custom_theme_path: Path | None) -> _Theme:
    if name == "azure":
        return _Theme(AZURE_THEME, "#244F78", None, "  ·  蓝天的聊天日记")
    if name == "letter":
        return _Theme(LETTER_THEME, "#513D2B", "今日日报", "")
    if name == "custom":
        if custom_theme_path is None:
            raise ValueError("自制日报主题需要放入插件数据目录")
        return _Theme(custom_theme_path, "#333333", "今日日报", "")
    raise ValueError(f"未知日报主题：{name}")


def _load_background(path: Path) -> Image.Image:
    if not path.is_file():
        raise ValueError(f"日报主题图片不存在：{path.name}")
    if path.stat().st_size > MAX_THEME_BYTES:
        raise ValueError("日报主题图片不能超过 8 MiB")
    try:
        with Image.open(path) as source:
            width, height = source.size
            if source.format != "PNG":
                raise ValueError("日报主题必须是 PNG 图片")
            if source.mode not in {"RGB", "RGBA"}:
                raise ValueError("日报主题必须是 RGB 或 RGBA 图片")
            if not (900 <= width <= 2000 and 1600 <= height <= 3600):
                raise ValueError("日报主题尺寸须在 900×1600 至 2000×3600 之间")
            if abs(width / height - 9 / 16) > 0.002:
                raise ValueError("日报主题必须为 9:16 竖版比例")
            if "A" in source.getbands() and source.getchannel("A").getextrema()[0] < 255:
                raise ValueError("日报主题不能使用透明背景")
            canvas = source.convert("RGB")
            return canvas if canvas.size == OUTPUT_SIZE else canvas.resize(OUTPUT_SIZE, Image.Resampling.LANCZOS)
    except OSError as exc:
        raise ValueError("日报主题图片无法读取") from exc


def _render(day: date, summary: str, spec: _Theme) -> bytes:
    """Return PNG bytes; refuse to crop text or use malformed backgrounds."""
    canvas = _load_background(spec.image)
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    left, right = round(width * 0.12), round(width * 0.89)
    top, bottom = round(height * 0.235), round(height * 0.89)

    if spec.title:
        title_font = ImageFont.truetype(FONT, round(width * 0.060))
        title_font.set_variation_by_axes([700])
        bounds = draw.textbbox((0, 0), spec.title, font=title_font)
        title_width = bounds[2] - bounds[0]
        draw.text(((width - title_width) / 2, round(height * 0.165)), spec.title,
                  font=title_font, fill=spec.ink)

    date_font = ImageFont.truetype(FONT, round(width * 0.032))
    date_font.set_variation_by_axes([600])
    draw.text((left, top), f"{day:%Y年%m月%d日}{spec.date_suffix}", font=date_font, fill=spec.ink)
    content_top = top + round(height * 0.06)
    body = summary.strip()
    if not body:
        raise ValueError("日报正文为空")
    for size in range(round(width * 0.027), round(width * 0.016), -1):
        font = ImageFont.truetype(FONT, size)
        font.set_variation_by_axes([450])
        lines = _wrap(draw, body, font, right - left)
        line_height = round(size * 1.62)
        if len(lines) * line_height <= bottom - content_top:
            for index, line in enumerate(lines):
                draw.text((left, content_top + index * line_height), line, font=font, fill=spec.ink)
            result = BytesIO()
            canvas.save(result, format="PNG", optimize=True)
            return result.getvalue()
    raise ValueError("日报内容超出主题留白，请缩短总结")


def render_report(day: date, summary: str, *, theme: str = "azure",
                  custom_theme_path: Path | None = None) -> bytes:
    """Render the configured built-in or custom daily-report theme."""
    return _render(day, summary, _theme(theme, custom_theme_path))


def render_azure_report(day: date, summary: str, *, theme_path: Path = AZURE_THEME) -> bytes:
    """Keep the original Azure renderer entry point for existing callers."""
    return _render(day, summary, _Theme(theme_path, "#244F78", None, "  ·  蓝天的聊天日记"))
