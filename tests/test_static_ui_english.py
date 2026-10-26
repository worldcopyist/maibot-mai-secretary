"""Keep MaiBot-rendered fixed labels in the public source in English."""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u9fff]")


def test_manifest_and_navigation_labels_are_english() -> None:
    manifest = json.loads((ROOT / "_manifest.json").read_text(encoding="utf-8"))
    webui = json.loads((ROOT / "webui.json").read_text(encoding="utf-8"))
    texts = [manifest["name"], manifest["description"], webui["workspace_title"]]
    for page in webui["pages"]:
        texts.extend((page["title"], page["description"]))
    assert all(not HAN.search(text) for text in texts)


def test_configuration_metadata_is_english() -> None:
    checked = 0
    for filename in ("plugin.py", "mood.py", "timetable.py", "virtual_life.py"):
        tree = ast.parse((ROOT / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            values: list[str] = []
            if (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id == "__ui_label__"
                and isinstance(node.value, ast.Constant)
            ):
                values.append(node.value.value)
            if (
                isinstance(node, ast.ClassDef)
                and any(
                    isinstance(base, ast.Name) and base.id == "PluginConfigBase"
                    for base in node.bases
                )
                and node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
            ):
                values.append(node.body[0].value.value)
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Field"
            ):
                for keyword in node.keywords:
                    if keyword.arg == "description" and isinstance(
                        keyword.value, ast.Constant
                    ):
                        values.append(keyword.value.value)
                    if keyword.arg == "json_schema_extra" and isinstance(
                        keyword.value, ast.Dict
                    ):
                        for key, value in zip(
                            keyword.value.keys, keyword.value.values, strict=True
                        ):
                            if (
                                isinstance(key, ast.Constant)
                                and key.value in {"label", "hint", "placeholder"}
                                and isinstance(value, ast.Constant)
                            ):
                                values.append(value.value)
            for value in values:
                assert isinstance(value, str) and not HAN.search(value), (
                    filename,
                    node.lineno,
                    value,
                )
                checked += 1
    assert checked >= 300
