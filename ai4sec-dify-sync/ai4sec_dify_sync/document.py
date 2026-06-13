from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SKIP_TYPES = {"header", "footer", "page_number", "aside_text"}


@dataclass(frozen=True)
class SourceDocument:
    paper_id: str
    title: str
    text: str
    source_hash: str

    @property
    def name(self) -> str:
        title = " ".join(self.title.split()).strip()
        return title or self.paper_id


def build_from_paper_ir(
    paper_id: str,
    ir_path: Path,
    fallback_title: str = "",
    max_chars: int = 0,
) -> SourceDocument:
    payload = json.loads(ir_path.read_text(encoding="utf-8"))
    title = str(payload.get("title") or fallback_title or "").strip()
    blocks = payload.get("blocks") if isinstance(payload.get("blocks"), list) else []
    text = blocks_to_markdown(blocks, title=title)
    return _document(paper_id, title, text, max_chars)


def build_from_blocks(
    paper_id: str,
    blocks: list[dict[str, Any]],
    fallback_title: str = "",
    max_chars: int = 0,
) -> SourceDocument:
    title = fallback_title.strip()
    if not title:
        for block in blocks:
            if str(block.get("type") or "") == "title":
                title = _clean_text(block.get("text")).strip()
                break
    text = blocks_to_markdown(blocks, title=title)
    return _document(paper_id, title, text, max_chars)


def blocks_to_markdown(blocks: list[dict[str, Any]], title: str = "") -> str:
    parts: list[str] = []
    if title:
        parts.append(f"# {_clean_text(title)}")

    last_section = ""
    for block in sorted(blocks, key=lambda item: int(item.get("order_idx") or 0)):
        block_type = str(block.get("type") or "").strip()
        if block_type in SKIP_TYPES:
            continue
        raw_text = block.get("text")
        text = _clean_text(raw_text)
        if not text:
            continue

        section = _clean_text(block.get("section_path"))
        if section and section != last_section and block_type != "title":
            heading = section.split("/")[-1].strip()
            if heading and (not parts or parts[-1].strip("# ") != heading):
                parts.append(f"## {heading}")
            last_section = section

        if block_type == "title":
            level = 2 if parts else 1
            heading = "#" * level
            if not parts or parts[-1].strip("# ") != text:
                parts.append(f"{heading} {text} {_page_ref(block)}")
            last_section = section or last_section
        elif block_type == "table":
            parts.append(f"[Table {_page_ref(block)}]\n{text}")
        elif block_type == "image":
            parts.append(f"[Figure {_page_ref(block)}]\n{text}")
        elif block_type == "equation":
            parts.append(f"{_page_ref(block)}\n$$\n{text}\n$$")
        else:
            parts.append(f"{_page_ref(block)} {text}")

    return "\n\n".join(part for part in parts if part.strip()).strip()


def source_hash(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _document(paper_id: str, title: str, text: str, max_chars: int) -> SourceDocument:
    text = text.strip()
    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip()
    return SourceDocument(
        paper_id=paper_id,
        title=title.strip(),
        text=text,
        source_hash=source_hash(text),
    )


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value if str(item).strip())
    text = str(value)
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _page_ref(block: dict[str, Any]) -> str:
    try:
        page = int(block.get("page_idx") or 0) + 1
    except (TypeError, ValueError):
        page = 1
    return f"[p.{max(1, page)}]"
