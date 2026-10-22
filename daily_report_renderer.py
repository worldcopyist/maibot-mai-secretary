"""Fill the approved Azure theme with a dated Chinese report."""

from __future__ import annotations

from datetime import date
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).resolve().parent / "assets"
THEME = ASSETS / "azure_theme.png"
FONT = ASSETS / "fonts" / "NotoSansSC.ttf"
INK = "#244F78"


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


def render_azure_report(day: date, summary: str, *, theme_path: Path = THEME) -> bytes:
    """Return PNG bytes; refuse to silently crop report text."""
    with Image.open(theme_path) as source:
        canvas = source.convert("RGB")
    draw = ImageDraw.Draw(canvas)
    width, height = canvas.size
    left, right = round(width * 0.12), round(width * 0.89)
    top = round(height * (0.235 if height / width >= 1.6 else 0.32))
    bottom = round(height * 0.89)
    date_font = ImageFont.truetype(FONT, round(width * 0.032))
    date_font.set_variation_by_axes([600])
    draw.text((left, top), f"{day:%Y年%m月%d日}  ·  蓝天的聊天日记", font=date_font, fill=INK)
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
                draw.text((left, content_top + index * line_height), line, font=font, fill=INK)
            result = BytesIO()
            canvas.save(result, format="PNG", optimize=True)
            return result.getvalue()
    raise ValueError("日报内容超出 Azure 主题留白，请缩短总结")
