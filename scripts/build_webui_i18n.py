"""Embed a shared translation runtime into MaiBot's network-isolated custom pages."""

from __future__ import annotations

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
I18N = ASSETS / "i18n"
START = "<!-- secretary-i18n:start -->"
END = "<!-- secretary-i18n:end -->"
BLOCK = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
PAGES = ("workbench", "tasks", "timetable", "knowledge")


class VisibleStrings(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ignored = 0
        self.strings: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored += 1
        if not self.ignored:
            for name, value in attrs:
                if (
                    name in {"placeholder", "aria-label", "title"}
                    and value
                    and re.search(r"[\u3400-\u9fff]", value)
                ):
                    self.strings.add(value.strip())

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.ignored -= 1

    def handle_data(self, value: str) -> None:
        if not self.ignored and re.search(r"[\u3400-\u9fff]", value):
            self.strings.add(value.strip())


def build_page(
    name: str, fragments: dict[str, list[str]], catalogs: dict[str, dict[str, str]]
) -> str:
    path = ASSETS / f"{name}.html"
    source = BLOCK.sub("", path.read_text(encoding="utf-8")).rstrip() + "\n"
    visible = VisibleStrings()
    visible.feed(source)
    keys = visible.strings | set(fragments["common"]) | set(fragments[name])
    missing = {
        language: sorted(keys - set(catalog)) for language, catalog in catalogs.items()
    }
    missing = {language: items for language, items in missing.items() if items}
    if missing:
        raise ValueError(f"{name}: missing translations: {missing}")
    runtime = (I18N / "runtime.js").read_text(encoding="utf-8")
    subset = {
        language: {key: catalog[key] for key in sorted(keys)}
        for language, catalog in catalogs.items()
    }
    fragment_keys = sorted(
        set(fragments["common"]) | set(fragments[name]),
        key=lambda key: (-len(key), key),
    )
    runtime = runtime.replace(
        "__SECRETARY_CATALOGS__",
        json.dumps(subset, ensure_ascii=False, separators=(",", ":")),
    )
    runtime = runtime.replace(
        "__SECRETARY_FRAGMENTS__",
        json.dumps(fragment_keys, ensure_ascii=False, separators=(",", ":")),
    )
    runtime = runtime.replace("</", "<\\/")
    return source + f"{START}\n<script>\n{runtime}\n</script>\n{END}\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    fragments = json.loads((I18N / "fragments.json").read_text(encoding="utf-8"))
    catalogs = {
        language: json.loads((I18N / f"{language}.json").read_text(encoding="utf-8"))
        for language in ("en", "ja", "ko")
    }
    for name in PAGES:
        path = ASSETS / f"{name}.html"
        built = build_page(name, fragments, catalogs)
        if args.check:
            if path.read_text(encoding="utf-8") != built:
                raise SystemExit(f"{name}: generated page is stale")
        else:
            path.write_text(built, encoding="utf-8")


if __name__ == "__main__":
    main()
