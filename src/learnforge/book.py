"""教材检索（轻量 RAG）：PDF 按页抽文字，用中文字二元组 + BM25 检索，返回页码和片段。

先不上向量库：教材术语很固定（“银行家算法”“快表”），关键词检索命中率已经够用，
而且零依赖、可解释（能告诉你在第几页）。命中不好再接本地 bge-m3。
扫描版 PDF 没有文字层，先用有视觉的模型或 OCR 转成文字，再用 lf book add 导入 .md/.txt。
"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path

from .store import Data, LFError


def _book_dir(data: Data, pack: str) -> Path:
    d = data.p("packs", pack, "book")
    d.mkdir(parents=True, exist_ok=True)
    return d


def add(data: Data, pack: str, src: str, name: str | None = None, offset: int = 0) -> dict:
    """导入教材。offset：PDF 第 1 页对应的书上页码 - 1（封面、前言不计页码时用来对齐）。"""
    path = Path(src).expanduser()
    if not path.exists():
        raise LFError(f"找不到文件 {path}")
    name = name or path.stem
    pages, toc = [], []
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise LFError("导入 PDF 需要 pypdf：uv tool install 时加上 [book] 扩展") from e
        reader = PdfReader(str(path))
        for i, pg in enumerate(reader.pages):
            pages.append({"pdf_page": i + 1, "page": i + 1 - offset, "text": (pg.extract_text() or "").strip()})

        def walk(items, depth=0):
            for it in items:
                if isinstance(it, list):
                    walk(it, depth + 1)
                else:
                    try:
                        pno = reader.get_destination_page_number(it) + 1
                    except Exception:
                        pno = None
                    toc.append({"level": depth, "title": it.title, "pdf_page": pno,
                                "page": pno - offset if pno else None})
        try:
            walk(reader.outline)
        except Exception:
            pass
    else:
        text = path.read_text(encoding="utf-8")
        chunks = re.split(r"\n(?=#{1,3} )", text) if "\n#" in text else re.split(r"\n\s*\n", text)
        pages = [{"pdf_page": i + 1, "page": i + 1, "text": c.strip()} for i, c in enumerate(chunks) if c.strip()]
        toc = [{"level": len(m.group(1)) - 1, "title": m.group(2), "page": i + 1}
               for i, c in enumerate(pages) for m in [re.match(r"(#{1,3}) (.+)", c["text"])] if m]
    empty = sum(1 for p in pages if len(p["text"]) < 20)
    d = _book_dir(data, pack)
    (d / f"{name}.pages.jsonl").write_text(
        "\n".join(json.dumps(p, ensure_ascii=False) for p in pages) + "\n", encoding="utf-8")
    (d / f"{name}.toc.json").write_text(json.dumps(toc, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"book": name, "pages": len(pages), "toc_entries": len(toc), "empty_pages": empty,
            "warning": "超过一半的页没有文字层，可能是扫描版，需要先 OCR" if pages and empty > len(pages) / 2 else ""}


def _tokens(text: str) -> list:
    text = text.lower()
    out = re.findall(r"[a-z0-9_]+", text)
    han = re.findall(r"[一-鿿]+", text)
    for run in han:
        out += [run[i:i + 2] for i in range(len(run) - 1)] or [run]
    return out


def find(data: Data, pack: str, query: str, k: int = 5) -> list:
    d = data.p("packs", pack, "book")
    files = sorted(d.glob("*.pages.jsonl")) if d.exists() else []
    if not files:
        raise LFError(f"{pack} 还没有导入教材：lf book add {pack} <教材.pdf>")
    docs = []
    for f in files:
        book = f.name.removesuffix(".pages.jsonl")
        for line in f.read_text(encoding="utf-8").splitlines():
            p = json.loads(line)
            docs.append((book, p, Counter(_tokens(p["text"]))))
    n = len(docs)
    avg = sum(sum(c.values()) for _, _, c in docs) / max(n, 1)
    q = _tokens(query)
    df = Counter(t for _, _, c in docs for t in set(c) if t in q)
    scored = []
    for book, p, c in docs:
        dl = sum(c.values())
        s = 0.0
        for t in q:
            if t in c:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * c[t] * 2.2 / (c[t] + 1.2 * (0.25 + 0.75 * dl / avg))
        if s > 0:
            scored.append((s, book, p))
    scored.sort(key=lambda x: -x[0])
    out = []
    for s, book, p in scored[:k]:
        text = p["text"]
        hit = next((text.find(w) for w in [query] + q if w in text), 0)
        snippet = text[max(0, hit - 60): hit + 140].replace("\n", " ")
        out.append({"book": book, "page": p["page"], "pdf_page": p["pdf_page"], "score": round(s, 2),
                    "snippet": snippet})
    return out


def toc(data: Data, pack: str) -> list:
    d = data.p("packs", pack, "book")
    out = []
    for f in sorted(d.glob("*.toc.json")) if d.exists() else []:
        for e in json.loads(f.read_text(encoding="utf-8")):
            out.append({"book": f.name.removesuffix(".toc.json"), **e})
    return out
