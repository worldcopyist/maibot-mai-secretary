"""Private, plugin-owned document library and hybrid RAG retrieval."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import html
import json
import math
import re
import sqlite3
import time
import unicodedata
import uuid
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_EXTRACTED_CHARS = 1_000_000
MAX_CHUNKS = 1600
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".xml", ".yaml", ".yml", ".log", ".rst", ".tex"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".pdf", ".docx", ".xlsx", ".pptx", ".html", ".htm", ".rtf", ".epub", ".odt", ".ods", ".odp"}
WORD_RE = re.compile(r"[a-z0-9_]{2,}|[\u3400-\u9fff]+", re.IGNORECASE)


class KnowledgeError(ValueError):
    pass


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self.hidden:
            self.hidden -= 1
        if tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise KnowledgeError("文档编码无法识别，请转换成 UTF-8")


def _xml_text(raw: bytes) -> str:
    root = ET.fromstring(raw)
    return " ".join(part.strip() for part in root.itertext() if part.strip())


def _zip_text(raw: bytes, suffix: str) -> str:
    from io import BytesIO

    try:
        archive = zipfile.ZipFile(BytesIO(raw))
        names = archive.namelist()
        if len(names) > 2000:
            raise KnowledgeError("文档内部文件过多")
        if suffix == ".docx":
            wanted = [name for name in names if name == "word/document.xml" or re.fullmatch(r"word/(header|footer)\d+\.xml", name)]
        elif suffix == ".pptx":
            wanted = sorted((name for name in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)), key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))
        elif suffix == ".xlsx":
            wanted = [name for name in names if name == "xl/sharedStrings.xml"] + sorted(name for name in names if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
        elif suffix in {".odt", ".ods", ".odp"}:
            wanted = ["content.xml"] if "content.xml" in names else []
        else:
            wanted = [name for name in names if name.lower().endswith((".xhtml", ".html", ".htm"))]
        if not wanted:
            raise KnowledgeError("文档中未找到可读取的正文")
        parts: list[str] = []
        total = 0
        shared: list[str] = []
        for name in wanted:
            info = archive.getinfo(name)
            if info.file_size > 4 * MAX_EXTRACTED_CHARS or total + info.file_size > 8 * MAX_EXTRACTED_CHARS:
                raise KnowledgeError("文档解压后的内容过大")
            content = archive.read(name)
            total += len(content)
            if suffix == ".epub":
                parser = _HTMLText()
                parser.feed(_decode(content))
                part = "".join(parser.parts)
            elif suffix == ".xlsx" and name == "xl/sharedStrings.xml":
                shared = ["".join(node.itertext()) for node in ET.fromstring(content) if node.tag.endswith("}si")]
                continue
            elif suffix == ".xlsx":
                root = ET.fromstring(content)
                rows: list[str] = []
                for row in root.iter():
                    if not row.tag.endswith("}row"):
                        continue
                    cells: list[str] = []
                    for cell in row:
                        if not cell.tag.endswith("}c"):
                            continue
                        val = next((n.text or "" for n in cell.iter() if n.tag.endswith("}v")), "")
                        if cell.attrib.get("t") == "s" and val.isdigit() and int(val) < len(shared):
                            val = shared[int(val)]
                        if cell.attrib.get("t") == "inlineStr":
                            val = "".join(n.text or "" for n in cell.iter() if n.tag.endswith("}t"))
                        cells.append(val)
                    rows.append("\t".join(cells))
                part = "\n".join(rows)
            else:
                part = _xml_text(content)
            parts.append(f"[{name}]\n{part}")
        return "\n".join(parts)
    except (zipfile.BadZipFile, ET.ParseError) as exc:
        raise KnowledgeError("文档压缩包或正文已损坏") from exc


def extract_text(raw: bytes, filename: str, *, minimum_chars: int = 10) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise KnowledgeError("不支持该格式；可上传 PDF、Word、Excel、PPT、EPUB、ODF、RTF、HTML、文本等")
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise KnowledgeError("文件为空或超过 8 MiB")
    if suffix in TEXT_SUFFIXES:
        text = _decode(raw)
    elif suffix in {".html", ".htm"}:
        parser = _HTMLText()
        parser.feed(_decode(raw))
        text = "".join(parser.parts)
    elif suffix in {".docx", ".xlsx", ".pptx", ".epub", ".odt", ".ods", ".odp"}:
        text = _zip_text(raw, suffix)
    elif suffix == ".rtf":
        source = _decode(raw)
        source = re.sub(r"\\u(-?\d+)\??", lambda m: chr(int(m.group(1)) % 65536), source)
        source = re.sub(r"\\'[0-9a-fA-F]{2}", " ", source)
        text = re.sub(r"\\[a-zA-Z]+-?\d* ?|[{}]", " ", source)
    else:
        try:
            from io import BytesIO

            from pypdf import PdfReader
            reader = PdfReader(BytesIO(raw), strict=False)
            if len(reader.pages) > 500:
                raise KnowledgeError("PDF 超过 500 页")
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except ImportError as exc:
            raise KnowledgeError("缺少 pypdf，无法解析 PDF") from exc
        except KnowledgeError:
            raise
        except Exception as exc:
            raise KnowledgeError("PDF 无法解析，可能加密或损坏") from exc
    text = unicodedata.normalize("NFKC", html.unescape(text)).replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_EXTRACTED_CHARS:
        raise KnowledgeError("提取的文字超过 100 万字")
    if len(text) < minimum_chars:
        raise KnowledgeError("没有提取到足够文字；扫描版 PDF 需先做 OCR")
    return text


def parse_moderation_terms(text: str) -> list[str]:
    """Read one sensitive word/phrase per line, cell or delimited item."""
    ignored = {"敏感词", "违禁词", "禁言词", "关键词", "词语", "内容", "词库"}
    words: dict[str, str] = {}
    for part in re.split(r"[\s,，;；]+", text):
        word = part.strip("\"'“”‘’[]()（）:：-—、.。")
        if not word or word.startswith("#") or "/" in word or word.isdecimal() or word in ignored:
            continue
        if not 1 <= len(word) <= 50:
            raise KnowledgeError("敏感词须为 1–50 字；请每行或每个单元格只写一个词")
        words.setdefault(word.casefold(), word)
        if len(words) > 1000:
            raise KnowledgeError("每份群管词库最多 1000 个敏感词")
    if not words:
        raise KnowledgeError("没有找到敏感词；请每行或每个单元格写一个词")
    return list(words.values())


def split_text(text: str, size: int, overlap: int) -> list[str]:
    if size < 200 or overlap < 0 or overlap >= size // 2:
        raise KnowledgeError("分段大小或重叠长度不合法")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            nearby = max(text.rfind("\n", start + size // 2, end), text.rfind("。", start + size // 2, end))
            if nearby > start:
                end = nearby + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
        if len(chunks) > MAX_CHUNKS:
            raise KnowledgeError("文档分段超过上限，请拆分文件")
    return chunks


def _terms(text: str) -> Counter[str]:
    terms: Counter[str] = Counter()
    for match in WORD_RE.finditer(text.lower()):
        word = match.group()
        if "\u3400" <= word[0] <= "\u9fff":
            terms.update(word[i : i + 2] for i in range(max(0, len(word) - 1)))
            if len(word) == 1:
                terms[word] += 1
        else:
            terms[word[:40]] += 1
    return terms


def _vector(result: Any) -> list[float]:
    if not isinstance(result, dict) or result.get("success") is False:
        raise KnowledgeError("向量模型调用失败")
    vector = result.get("embedding")
    if not isinstance(vector, list) or not vector or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
        raise KnowledgeError("向量模型返回无效数据")
    norm = math.sqrt(sum(float(x) ** 2 for x in vector))
    if norm == 0:
        raise KnowledgeError("向量模型返回零向量")
    return [float(x) / norm for x in vector]


class KnowledgeBaseModule:
    name = "knowledge_base"
    state_keys = frozenset()

    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.root: Path | None = None
        self.db_path: Path | None = None
        self.jobs: set[asyncio.Task[Any]] = set()
        self.sessions: dict[str, dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        self._moderation_terms: dict[str, tuple[tuple[str, str], ...]] = {}

    def load_state(self, data: dict[str, Any]) -> None:
        del data

    def dump_state(self, payload: dict[str, Any]) -> None:
        del payload

    def on_config_update(self) -> None:
        pass

    async def tick(self, now: datetime) -> None:
        del now
        expired = [key for key, item in self.sessions.items() if time.time() - item["created"] > 3600]
        for key in expired:
            self.sessions.pop(key, None)
            (self.root / "staging" / key).unlink(missing_ok=True)

    @contextmanager
    def _db(self):
        assert self.db_path is not None
        db = sqlite3.connect(self.db_path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    async def start(self) -> None:
        self.root = Path(self.plugin.ctx.paths.data_dir) / "knowledge_base"
        (self.root / "sources").mkdir(parents=True, exist_ok=True)
        (self.root / "staging").mkdir(exist_ok=True)
        (self.root / "moderation_sources").mkdir(exist_ok=True)
        self.db_path = self.root / "knowledge.sqlite3"
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                    sha256 TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '', chunk_count INTEGER NOT NULL DEFAULT 0,
                    created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS documents_sha ON documents(sha256);
                CREATE TABLE IF NOT EXISTS chunks(id INTEGER PRIMARY KEY, document_id TEXT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE, ordinal INTEGER NOT NULL,
                    body TEXT NOT NULL, vector TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS terms(term TEXT NOT NULL, chunk_id INTEGER NOT NULL
                    REFERENCES chunks(id) ON DELETE CASCADE, tf INTEGER NOT NULL,
                    PRIMARY KEY(term,chunk_id));
                CREATE INDEX IF NOT EXISTS terms_chunk ON terms(chunk_id);
                CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(document_id);
                CREATE TABLE IF NOT EXISTS moderation_documents(
                    id TEXT PRIMARY KEY, group_id TEXT NOT NULL, name TEXT NOT NULL,
                    sha256 TEXT NOT NULL, size INTEGER NOT NULL, terms_json TEXT NOT NULL,
                    created REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS moderation_group_sha
                    ON moderation_documents(group_id,sha256);
            """)
            db.commit()
            pending = [row["id"] for row in db.execute("SELECT id FROM documents WHERE status IN ('queued','indexing')")]
        for document_id in pending:
            self._launch(document_id)
        self._reload_moderation_terms()

    async def stop(self) -> None:
        for job in self.jobs:
            job.cancel()
        if self.jobs:
            await asyncio.gather(*self.jobs, return_exceptions=True)
        self.jobs.clear()

    def _launch(self, document_id: str) -> None:
        job = asyncio.create_task(self._index(document_id), name=f"secretary-index-{document_id}")
        self.jobs.add(job)
        job.add_done_callback(self.jobs.discard)

    def _enabled(self) -> None:
        if not self.plugin.config.plugin.enabled or not self.plugin.config.knowledge_base.enabled:
            raise KnowledgeError("知识库模块未启用")

    def _moderation_group(self, group_id: str) -> str:
        group_id = str(group_id).strip()
        if group_id not in self.plugin.config.group_admin.managed_group_ids:
            raise KnowledgeError("请先在小秘书的 QQ群管设置中添加这个群号")
        return group_id

    def _upload_allowed(self, session: dict[str, Any]) -> None:
        if session.get("purpose") == "moderation":
            self._moderation_group(str(session.get("group_id") or ""))
        else:
            self._enabled()

    async def start_upload(self, filename: str, size: int, *, purpose: str = "general", group_id: str = "") -> dict[str, Any]:
        if purpose == "moderation":
            group_id = self._moderation_group(group_id)
        elif purpose == "general":
            self._enabled()
        else:
            raise KnowledgeError("未知的知识库区域")
        name = Path(str(filename).replace("\\", "/")).name.strip()[:120]
        if not name or Path(name).suffix.lower() not in SUPPORTED_SUFFIXES:
            raise KnowledgeError("文件名或文件格式不受支持")
        if type(size) is not int or not 0 < size <= MAX_FILE_BYTES:
            raise KnowledgeError("文件须为 1 字节至 8 MiB")
        if len(self.sessions) >= 4:
            raise KnowledgeError("已有 4 个上传进行中")
        token = uuid.uuid4().hex
        (self.root / "staging" / token).write_bytes(b"")
        self.sessions[token] = {"name": name, "size": size, "received": 0, "sequence": 0, "created": time.time(), "purpose": purpose, "group_id": group_id}
        return {"upload_id": token}

    async def append_upload(self, upload_id: str, sequence: int, data: str) -> dict[str, Any]:
        async with self.lock:
            session = self.sessions.get(upload_id)
            if not session or time.time() - session["created"] > 3600:
                raise KnowledgeError("上传会话不存在或已过期")
            self._upload_allowed(session)
            if type(sequence) is not int or sequence != session["sequence"]:
                raise KnowledgeError("上传分块顺序错误")
            try:
                raw = base64.b64decode(data, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise KnowledgeError("上传分块编码无效") from exc
            if not raw or len(raw) > 36 * 1024 or session["received"] + len(raw) > session["size"]:
                raise KnowledgeError("上传分块为空、过大或超出声明大小")
            with (self.root / "staging" / upload_id).open("ab") as stream:
                stream.write(raw)
            session["received"] += len(raw)
            session["sequence"] += 1
            return {"received": session["received"], "total": session["size"]}

    async def finish_upload(self, upload_id: str) -> dict[str, Any]:
        async with self.lock:
            session = self.sessions.get(upload_id)
            if not session or session["received"] != session["size"]:
                raise KnowledgeError("上传未完成或已过期")
            self._upload_allowed(session)
            self.sessions.pop(upload_id)
            path = self.root / "staging" / upload_id
            raw = path.read_bytes()
            path.unlink(missing_ok=True)
        if session["purpose"] == "moderation":
            result = await asyncio.to_thread(self._save_moderation_document, session["group_id"], session["name"], raw)
            self._reload_moderation_terms()
            return result
        return self._save_document(session["name"], raw)

    async def add_text(self, title: str, content: str) -> dict[str, Any]:
        self._enabled()
        name = re.sub(r"[^\w\u3400-\u9fff .()-]", "_", str(title).strip())[:100] or "粘贴文本"
        raw = str(content).encode("utf-8")
        if len(raw) > 50_000:
            raise KnowledgeError("单次粘贴最多 50 KB；更长文本请保存为文件上传")
        return self._save_document(name + ".txt", raw)

    async def add_moderation_text(self, group_id: str, title: str, content: str) -> dict[str, Any]:
        group_id = self._moderation_group(group_id)
        name = re.sub(r"[^\w\u3400-\u9fff .()-]", "_", str(title).strip())[:100] or "群管敏感词"
        raw = str(content).encode("utf-8")
        if not raw or len(raw) > 50_000:
            raise KnowledgeError("敏感词文本最多 50 KB")
        result = await asyncio.to_thread(self._save_moderation_document, group_id, name + ".txt", raw)
        self._reload_moderation_terms()
        return result

    def _save_moderation_document(self, group_id: str, name: str, raw: bytes) -> dict[str, Any]:
        text = extract_text(raw, name, minimum_chars=1)
        terms = parse_moderation_terms(text)
        digest = hashlib.sha256(raw).hexdigest()
        with self._db() as db:
            existing = db.execute(
                "SELECT id FROM moderation_documents WHERE group_id=? AND sha256=?", (group_id, digest),
            ).fetchone()
            if existing:
                return {"document_id": existing["id"], "duplicate": True, "term_count": len(terms)}
            rows = db.execute("SELECT terms_json FROM moderation_documents WHERE group_id=?", (group_id,)).fetchall()
            all_terms = {unicodedata.normalize("NFKC", term).casefold() for row in rows for term in json.loads(row["terms_json"])}
            all_terms.update(unicodedata.normalize("NFKC", term).casefold() for term in terms)
            if len(all_terms) > 3000 or len(rows) >= 100:
                raise KnowledgeError("这个群的词库已达到 3000 词或 100 份文档上限")
            document_id = uuid.uuid4().hex
            source = self.root / "moderation_sources" / document_id
            source.write_bytes(raw)
            try:
                db.execute(
                    "INSERT INTO moderation_documents(id,group_id,name,sha256,size,terms_json,created) VALUES(?,?,?,?,?,?,?)",
                    (document_id, group_id, name, digest, len(raw), json.dumps(terms, ensure_ascii=False), time.time()),
                )
                db.commit()
            except Exception:
                source.unlink(missing_ok=True)
                raise
        return {"document_id": document_id, "duplicate": False, "term_count": len(terms)}

    def _reload_moderation_terms(self) -> None:
        by_group: dict[str, dict[str, str]] = {}
        with self._db() as db:
            rows = db.execute("SELECT group_id,terms_json FROM moderation_documents").fetchall()
        for row in rows:
            group = by_group.setdefault(str(row["group_id"]), {})
            for term in json.loads(row["terms_json"]):
                group.setdefault(unicodedata.normalize("NFKC", term).casefold(), term)
        self._moderation_terms = {
            group: tuple((term, folded) for folded, term in sorted(words.items(), key=lambda pair: -len(pair[0])))
            for group, words in by_group.items()
        }

    def moderation_matches(self, group_id: str, text: str) -> list[str]:
        folded = unicodedata.normalize("NFKC", text).casefold()
        return [term for term, key in self._moderation_terms.get(group_id, ()) if key in folded][:12]

    async def list_moderation_documents(self) -> dict[str, Any]:
        with self._db() as db:
            rows = db.execute(
                "SELECT id,group_id,name,size,terms_json,created FROM moderation_documents ORDER BY created DESC LIMIT 200",
            ).fetchall()
        settings = self.plugin.config.group_admin
        return {
            "groups": settings.managed_group_ids,
            "settings": {
                "enabled": settings.enabled and settings.moderation_enabled,
                "recall": settings.moderation_recall,
                "mute": settings.moderation_mute,
                "mute_minutes": settings.moderation_mute_minutes,
                "sensitivity": settings.moderation_sensitivity,
            },
            "documents": [
                {"id": row["id"], "group_id": row["group_id"], "name": row["name"],
                 "size": row["size"], "term_count": len(terms := json.loads(row["terms_json"])),
                 "preview": terms[:20], "created": row["created"]}
                for row in rows
            ],
        }

    async def delete_moderation_document(self, document_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{32}", str(document_id)):
            raise KnowledgeError("词库文档编号无效")
        with self._db() as db:
            row = db.execute("SELECT id FROM moderation_documents WHERE id=?", (document_id,)).fetchone()
            if row is None:
                raise KnowledgeError("词库文档不存在")
            db.execute("DELETE FROM moderation_documents WHERE id=?", (document_id,))
            db.commit()
        (self.root / "moderation_sources" / document_id).unlink(missing_ok=True)
        self._reload_moderation_terms()
        return {"deleted": True}

    def _save_document(self, name: str, raw: bytes) -> dict[str, Any]:
        if not raw or len(raw) > MAX_FILE_BYTES:
            raise KnowledgeError("文档为空或过大")
        digest = hashlib.sha256(raw).hexdigest()
        with self._db() as db:
            existing = db.execute("SELECT id,status FROM documents WHERE sha256=?", (digest,)).fetchone()
            if existing:
                return {"document_id": existing["id"], "status": existing["status"], "duplicate": True}
            count = db.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            if count >= 500:
                raise KnowledgeError("知识库已达到 500 份文档上限，请先清理旧资料")
            document_id = uuid.uuid4().hex
            (self.root / "sources" / document_id).write_bytes(raw)
            db.execute("INSERT INTO documents(id,name,sha256,size,status,created) VALUES(?,?,?,?,?,?)", (document_id, name, digest, len(raw), "queued", time.time()))
            db.commit()
        self._launch(document_id)
        return {"document_id": document_id, "status": "queued", "duplicate": False}

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        result = await self.plugin.ctx.llm.embed(texts=texts, task_name="embedding", max_concurrent=2)
        if not isinstance(result, dict) or result.get("success") is False:
            raise KnowledgeError("向量模型调用失败")
        items = result.get("results")
        if not isinstance(items, list) or len(items) != len(texts):
            raise KnowledgeError("向量模型返回数量不匹配")
        return [_vector({"success": True, **item} if isinstance(item, dict) and "success" not in item else item) for item in items]

    async def _index(self, document_id: str) -> None:
        try:
            with self._db() as db:
                row = db.execute("SELECT name FROM documents WHERE id=?", (document_id,)).fetchone()
                if row is None:
                    return
                name = row["name"]
                db.execute("UPDATE documents SET status='indexing',error='' WHERE id=?", (document_id,))
                db.commit()
            raw = await asyncio.to_thread((self.root / "sources" / document_id).read_bytes)
            text = await asyncio.to_thread(extract_text, raw, name)
            settings = self.plugin.config.knowledge_base
            chunks = split_text(text, settings.chunk_chars, settings.overlap_chars)
            with self._db() as db:
                existing_chunks = db.execute("SELECT COUNT(*) FROM chunks WHERE document_id!=?", (document_id,)).fetchone()[0]
            if existing_chunks + len(chunks) > 10000:
                raise KnowledgeError("知识库已达到 10000 段上限，请先删除旧资料")
            vectors: list[list[float]] = []
            embedding_error = ""
            if settings.semantic_search:
                try:
                    for offset in range(0, len(chunks), 8):
                        vectors.extend(await self._embed_batch(chunks[offset : offset + 8]))
                except Exception as exc:  # noqa: BLE001 - keep keyword retrieval when embeddings fail
                    embedding_error = f"向量生成失败，已保留关键词检索：{str(exc)[:160]}"
                    vectors = []
            with self._db() as db:
                db.execute("BEGIN IMMEDIATE")
                db.execute("DELETE FROM chunks WHERE document_id=?", (document_id,))
                for ordinal, body in enumerate(chunks):
                    cursor = db.execute("INSERT INTO chunks(document_id,ordinal,body,vector) VALUES(?,?,?,?)", (document_id, ordinal, body, json.dumps(vectors[ordinal]) if vectors else ""))
                    db.executemany("INSERT INTO terms(term,chunk_id,tf) VALUES(?,?,?)", [(term, cursor.lastrowid, tf) for term, tf in _terms(body).items()])
                db.execute("UPDATE documents SET status='ready',error=?,chunk_count=? WHERE id=?", (embedding_error, len(chunks), document_id))
                db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.plugin.ctx.logger.exception("知识库索引失败：%s", document_id)
            with self._db() as db:
                db.execute("UPDATE documents SET status='failed',error=? WHERE id=?", (str(exc)[:300], document_id))
                db.commit()

    async def list_documents(self) -> dict[str, Any]:
        with self._db() as db:
            rows = db.execute("SELECT id,name,size,status,error,chunk_count,created FROM documents ORDER BY created DESC LIMIT 200").fetchall()
        return {"documents": [dict(row) for row in rows], "formats": sorted(SUPPORTED_SUFFIXES), "max_file_mb": 8}

    async def delete_document(self, document_id: str) -> dict[str, Any]:
        self._enabled()
        if not re.fullmatch(r"[0-9a-f]{32}", document_id):
            raise KnowledgeError("文档编号无效")
        with self._db() as db:
            db.execute("DELETE FROM documents WHERE id=?", (document_id,))
            db.commit()
        (self.root / "sources" / document_id).unlink(missing_ok=True)
        return {"deleted": True}

    async def rebuild_document(self, document_id: str) -> dict[str, Any]:
        self._enabled()
        if not re.fullmatch(r"[0-9a-f]{32}", document_id):
            raise KnowledgeError("文档编号无效")
        with self._db() as db:
            row = db.execute("SELECT id,status FROM documents WHERE id=?", (document_id,)).fetchone()
            if row is None or not (self.root / "sources" / document_id).is_file():
                raise KnowledgeError("文档不存在")
            if row["status"] in {"queued", "indexing"}:
                return {"status": row["status"], "already_running": True}
            db.execute("UPDATE documents SET status='queued',error='' WHERE id=?", (document_id,))
            db.commit()
        self._launch(document_id)
        return {"status": "queued"}

    async def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        self._enabled()
        query = str(query).strip()[:500]
        if not query:
            raise KnowledgeError("检索词不能为空")
        limit = max(1, min(int(limit), 8))
        query_terms = list(_terms(query))[:30]
        lexical: dict[int, float] = {}
        with self._db() as db:
            if query_terms:
                marks = ",".join("?" for _ in query_terms)
                for row in db.execute(f"SELECT t.chunk_id,SUM(t.tf) AS score FROM terms t JOIN chunks c ON c.id=t.chunk_id JOIN documents d ON d.id=c.document_id WHERE d.status='ready' AND t.term IN ({marks}) GROUP BY t.chunk_id ORDER BY score DESC LIMIT 80", query_terms):
                    lexical[row["chunk_id"]] = float(row["score"])
            vector_rows = db.execute("SELECT c.id,c.vector FROM chunks c JOIN documents d ON d.id=c.document_id WHERE d.status='ready' AND c.vector!='' LIMIT 10000").fetchall()
        semantic: dict[int, float] = {}
        if vector_rows and self.plugin.config.knowledge_base.semantic_search:
            try:
                vector = _vector(await self.plugin.ctx.llm.embed(text=query, task_name="embedding"))
                for row in vector_rows:
                    candidate = json.loads(row["vector"])
                    if len(candidate) == len(vector):
                        semantic[row["id"]] = sum(a * b for a, b in zip(vector, candidate))
            except Exception:
                self.plugin.ctx.logger.warning("知识库向量检索失败，使用关键词结果", exc_info=True)
        scores: dict[int, float] = {}
        for rank, key in enumerate(sorted(lexical, key=lexical.get, reverse=True)):
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        for rank, key in enumerate(sorted(semantic, key=semantic.get, reverse=True)[:80]):
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
        if not scores:
            return {"results": [], "message": "没有找到相关知识库内容"}
        selected = sorted(scores, key=scores.get, reverse=True)[:limit]
        with self._db() as db:
            marks = ",".join("?" for _ in selected)
            rows = db.execute(f"SELECT c.id,c.ordinal,c.body,d.id AS document_id,d.name FROM chunks c JOIN documents d ON d.id=c.document_id WHERE c.id IN ({marks})", selected).fetchall()
        by_id = {row["id"]: row for row in rows}
        return {"results": [{"document_id": by_id[key]["document_id"], "source": by_id[key]["name"], "chunk": by_id[key]["ordinal"] + 1, "text": by_id[key]["body"][:1800]} for key in selected if key in by_id]}

    async def tool_search(self, query: str, **kwargs: Any) -> dict[str, Any]:
        stream_id = str(kwargs.get("stream_id") or "").strip()
        chat_id = str(kwargs.get("chat_id") or "").strip()
        allowed = set(self.plugin.config.knowledge_base.allowed_chats)
        authorized = bool(stream_id and stream_id == chat_id and stream_id in allowed)
        if not authorized and stream_id and stream_id == chat_id and any(item.count(":") == 2 for item in allowed):
            try:
                streams = await self.plugin.ctx.chat.get_all_streams()
                if isinstance(streams, dict):
                    streams = streams.get("streams", [])
                matching = [item for item in streams if isinstance(item, dict) and str(item.get("stream_id") or item.get("session_id") or "") == stream_id]
                if len(matching) == 1:
                    item = matching[0]
                    kind = str(item.get("chat_type") or "")
                    target_id = str(item.get("group_id" if kind == "group" else "user_id") or "")
                    alias = f"{item.get('platform')}:{kind}:{target_id}"
                    authorized = bool(target_id and alias in allowed)
            except Exception:  # noqa: BLE001 - deny access if stream validation fails
                authorized = False
        if not authorized:
            return {"success": False, "error": "当前聊天流没有知识库访问权限"}
        try:
            result = await self.search(query)
            return {"success": True, **result}
        except KnowledgeError as exc:
            return {"success": False, "error": str(exc)}
