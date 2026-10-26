"""Check the plugin pages against MaiBot's four supported UI languages."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from scripts.build_webui_i18n import I18N, PAGES, build_page

ROOT = Path(__file__).resolve().parents[1]
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
CONFIRMATIONS = {
    "workbench": "确定取消这项回访吗？",
    "tasks": "确定取消这项定时任务吗？",
    "timetable": "确定删除这个聊天流的课表和全部未来上课提醒吗？",
    "knowledge": "确定永久删除这份文档和它的检索索引吗？",
}


def test_generated_pages_current() -> None:
    fragments = json.loads((I18N / "fragments.json").read_text(encoding="utf-8"))
    catalogs = {
        language: json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))
        for language in ("en", "ja", "ko")
    }
    for name in PAGES:
        path = ROOT / "assets" / f"{name}.html"
        assert path.read_text(encoding="utf-8") == build_page(name, fragments, catalogs)


@pytest.mark.skipif(not CHROME.exists(), reason="Chrome is unavailable")
@pytest.mark.parametrize("page", PAGES)
def test_live_language_switch(page: str) -> None:
    source = (ROOT / "assets" / f"{page}.html").read_text(encoding="utf-8")
    start = "<script>window.maibot={context:{language:'zh'},ready:Promise.resolve(),query:async()=>({}),action:async()=>({})};</script>"
    probe = """<script>
      setTimeout(() => {
        const result = {initial: document.querySelector('main').textContent};
        for (const lang of ['zh', 'en', 'ja', 'ko', 'zh']) {
          maibot.context.language = lang;
          window.dispatchEvent(new CustomEvent('maibot:context', {detail: {language: lang}}));
          result[lang] = {
            heading: document.querySelector('h2').textContent,
            visible: document.querySelector('main').textContent.slice(0, 20000),
            confirmation: window.secretaryTranslate(CONFIRMATION_TEXT),
          };
        }
        const pre = document.createElement('pre');
        pre.id = 'language-probe';
        pre.textContent = JSON.stringify(result);
        document.body.append(pre);
      }, 100);
    </script>""".replace(
        "CONFIRMATION_TEXT", json.dumps(CONFIRMATIONS[page], ensure_ascii=False)
    )
    with tempfile.TemporaryDirectory() as directory:
        file = Path(directory) / f"{page}.html"
        file.write_text(
            f"<!doctype html><html><body>{start}{source}{probe}</body></html>",
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                str(CHROME),
                "--headless=new",
                "--disable-gpu",
                "--no-first-run",
                "--virtual-time-budget=2000",
                "--dump-dom",
                file.as_uri(),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=True,
        )
    match = re.search(r'<pre id="language-probe">(.*?)</pre>', result.stdout, re.DOTALL)
    assert match, result.stdout[-1000:]
    headings = json.loads(match.group(1))
    assert len({headings[lang]["heading"] for lang in ("zh", "en", "ja", "ko")}) == 4, (
        headings
    )
    assert headings["zh"]["visible"] == headings["initial"]
    assert headings["zh"]["confirmation"] == CONFIRMATIONS[page]
    for language in ("en", "ko"):
        remaining = re.findall(r"[\u3400-\u9fff]+", headings[language]["visible"])
        assert not remaining, (
            page,
            language,
            [ascii(item) for item in remaining],
            [
                ascii(
                    headings[language]["visible"][
                        max(0, headings[language]["visible"].index(item) - 45) :
                    ][:100]
                )
                for item in remaining
            ],
        )
        assert headings[language]["confirmation"] != CONFIRMATIONS[page]
