from __future__ import annotations

import base64
import importlib
import io
import json
import logging
import sys
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("mai_secretary")
package.__path__ = [str(ROOT)]
sys.modules.setdefault("mai_secretary", package)
kb = importlib.import_module("mai_secretary.knowledge_base")
plugin_module = importlib.import_module("mai_secretary.plugin")


def make_module(tmp_path: Path, *, semantic=False, allowed=None):
    plugin = plugin_module.MaiSecretaryPlugin()
    plugin._plugin_config_instance = plugin_module.SecretaryConfig.model_validate(
        {"knowledge_base": {"allowed_chats": ["safe-stream"] if allowed is None else allowed, "semantic_search": semantic}}
    )

    class FakeLLM:
        async def embed(self, text=None, *, texts=None, **kwargs):
            del kwargs
            def vector(value):
                return [float(value.lower().count("天气") + 1), float(value.lower().count("项目") + 1)]
            if texts is not None:
                return {"success": True, "results": [{"embedding": vector(item)} for item in texts]}
            return {"success": True, "embedding": vector(text)}

    plugin._ctx = types.SimpleNamespace(
        paths=types.SimpleNamespace(data_dir=tmp_path),
        llm=FakeLLM(),
        chat=types.SimpleNamespace(get_all_streams=lambda: None),
        logger=logging.getLogger("test_knowledge"),
    )
    return plugin.knowledge_base


def test_common_document_extraction_and_chunk_boundaries():
    assert "天气" in kb.extract_text("天气资料：今天晴朗，明天也晴朗".encode(), "a.md")
    assert "Hello" in kb.extract_text(b"<html><script>ignore</script><p>Hello world!</p></html>", "a.html")
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="urn:test"><w:p><w:t>项目说明和交付安排</w:t></w:p></w:document>')
    assert "项目说明" in kb.extract_text(stream.getvalue(), "a.docx")
    xlsx = io.BytesIO()
    with zipfile.ZipFile(xlsx, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", '<sst xmlns="urn:test"><si><t>项目计划和交付日期</t></si></sst>')
        archive.writestr("xl/worksheets/sheet1.xml", '<worksheet xmlns="urn:test"><sheetData><row><c t="s"><v>0</v></c></row></sheetData></worksheet>')
    assert "项目计划" in kb.extract_text(xlsx.getvalue(), "a.xlsx")
    pptx = io.BytesIO()
    with zipfile.ZipFile(pptx, "w") as archive:
        archive.writestr("ppt/slides/slide1.xml", '<slide xmlns="urn:test"><t>演示文稿的内容摘要</t></slide>')
    assert "演示文稿" in kb.extract_text(pptx.getvalue(), "a.pptx")
    epub = io.BytesIO()
    with zipfile.ZipFile(epub, "w") as archive:
        archive.writestr("chapter1.xhtml", "<html><body><p>Chapter one project overview.</p></body></html>")
    assert "project overview" in kb.extract_text(epub.getvalue(), "a.epub")
    chunks = kb.split_text("天气预报。" * 300, 300, 40)
    assert len(chunks) > 1
    assert all(len(chunk) <= 300 for chunk in chunks)
    with pytest.raises(kb.KnowledgeError):
        kb.extract_text(b"1234567890", "a.exe")


@pytest.mark.asyncio
async def test_upload_index_search_access_and_delete(tmp_path):
    module = make_module(tmp_path, semantic=True)
    await module.start()
    raw = ("这份项目文档讲解麦麦小秘书的知识库。" * 25).encode()
    started = await module.start_upload("项目.txt", len(raw))
    upload_id = started["upload_id"]
    await module.append_upload(upload_id, 0, base64.b64encode(raw).decode())
    with pytest.raises(kb.KnowledgeError, match="顺序"):
        await module.append_upload(upload_id, 0, base64.b64encode(b"x").decode())
    result = await module.finish_upload(upload_id)
    await next(iter(module.jobs))
    document_id = result["document_id"]
    listed = await module.list_documents()
    assert listed["documents"][0]["status"] == "ready"
    assert listed["documents"][0]["chunk_count"] > 0
    assert (await module.search("项目知识库"))["results"][0]["source"] == "项目.txt"
    assert not (await module.tool_search("项目", stream_id="other", chat_id="other"))["success"]
    assert not (await module.tool_search("项目", stream_id="safe-stream", chat_id="wrong"))["success"]
    assert (await module.tool_search("项目", stream_id="safe-stream", chat_id="safe-stream"))["success"]
    assert (await module.add_text("重复", raw.decode()))["duplicate"]
    await module.delete_document(document_id)
    assert (await module.search("项目"))["results"] == []
    await module.stop()


@pytest.mark.asyncio
async def test_chat_alias_requires_matching_host_stream(tmp_path):
    module = make_module(tmp_path, allowed=["qq:private:123456789"])
    await module.start()

    async def streams():
        return [{"stream_id": "actual-stream", "platform": "qq", "chat_type": "private", "user_id": "123456789"}]

    module.plugin.ctx.chat.get_all_streams = streams
    await module.add_text("说明", "这份资料专门解释知识库授权聊天流的访问方式。")
    await next(iter(module.jobs))
    assert (await module.tool_search("知识库", stream_id="actual-stream", chat_id="actual-stream"))["success"]
    assert not (await module.tool_search("知识库", stream_id="another-stream", chat_id="another-stream"))["success"]
    await module.stop()


@pytest.mark.asyncio
async def test_invalid_format_finishes_with_visible_failure(tmp_path):
    module = make_module(tmp_path)
    await module.start()
    result = await module.add_text("短文", "x")
    await next(iter(module.jobs))
    row = (await module.list_documents())["documents"][0]
    assert row["id"] == result["document_id"]
    assert row["status"] == "failed"
    assert "足够文字" in row["error"]
    await module.stop()


def test_webui_bindings_match_plugin_api_components():
    declaration = json.loads((ROOT / "webui.json").read_text(encoding="utf-8"))
    page = declaration["pages"][0]
    api_names = {item["name"] for item in plugin_module.MaiSecretaryPlugin().get_components() if item["type"] == "API"}
    assert {binding["api"] for binding in [*page["queries"].values(), *page["actions"].values()]} <= api_names
    assert (ROOT / page["entry"]).exists()


@pytest.mark.asyncio
async def test_webui_reports_expected_input_errors():
    async def fails():
        raise kb.KnowledgeError("文件格式不受支持")

    assert await plugin_module.MaiSecretaryPlugin._kb_api(fails()) == {"error": "文件格式不受支持"}
