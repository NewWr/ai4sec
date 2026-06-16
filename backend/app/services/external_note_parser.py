from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any

_ARXIV_RE = re.compile(r"(?:arxiv\.org/(?:abs|pdf)/|arXiv[:\s]+)(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")
_HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.M)
_CONF_YEAR_RE = re.compile(r"([A-Za-z][A-Za-z0-9_-]*?)[\s_-]*(20\d{2})")
_CODE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "huggingface.co")


@dataclass(frozen=True)
class ExternalPaperNoteIR:
    note_id: str
    source_path: str
    conference: str
    year: int
    domain: str
    title: str
    title_zh: str
    arxiv_id: str
    arxiv_url: str
    pdf_url: str
    code_url: str
    project_url: str
    authors: list[str]
    tags: list[str]
    keywords: list[str]
    summary: str
    method: str
    experiments: str
    limitations: str
    related_papers: list[str]
    markdown: str
    parsed: dict[str, Any]
    content_hash: str

    def db_payload(self) -> dict[str, Any]:
        data = asdict(self)
        data["authors_json"] = json.dumps(self.authors, ensure_ascii=False)
        data["tags_json"] = json.dumps(self.tags, ensure_ascii=False)
        data["keywords_json"] = json.dumps(self.keywords, ensure_ascii=False)
        data["related_papers_json"] = json.dumps(self.related_papers, ensure_ascii=False)
        data["parsed_json"] = json.dumps(self.parsed, ensure_ascii=False, sort_keys=True)
        return data


def parse_external_note(source_path: str, markdown: str) -> ExternalPaperNoteIR:
    source_path = source_path.strip().lstrip("/")
    markdown = markdown or ""
    conference, year, domain = _parse_path(source_path)
    title = _extract_title(source_path, markdown)
    title_zh = _extract_labeled_value(markdown, ("中文标题", "标题翻译", "Title Zh", "Title_zh"))
    arxiv_id = _extract_arxiv_id(markdown)
    urls = _URL_RE.findall(markdown)
    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else _first_url(urls, "arxiv.org/abs")
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}" if arxiv_id else _first_url(urls, "arxiv.org/pdf")
    code_url = _first_url(urls, *_CODE_HOSTS)
    project_url = _first_url(urls, "project", "pages", "sites.google.com") or _first_non_arxiv_non_code_url(urls)
    sections = _extract_sections(markdown)
    summary = _section_by_keywords(sections, "abstract", "summary", "摘要", "简介", "概述")
    method = _section_by_keywords(sections, "method", "approach", "方法", "模型")
    experiments = _section_by_keywords(sections, "experiment", "evaluation", "实验", "结果")
    limitations = _section_by_keywords(sections, "limitation", "局限", "不足", "future")
    keywords = _extract_keywords(markdown, domain, title)
    parsed = {
        "sections": {key: value[:2000] for key, value in sections.items()},
        "urls": urls[:50],
    }
    content_hash = hashlib.sha1(markdown.encode("utf-8")).hexdigest()
    note_id = hashlib.sha1(f"paper_notes:{source_path}".encode("utf-8")).hexdigest()[:24]
    return ExternalPaperNoteIR(
        note_id=note_id,
        source_path=source_path,
        conference=conference,
        year=year,
        domain=domain,
        title=title,
        title_zh=title_zh,
        arxiv_id=arxiv_id,
        arxiv_url=arxiv_url,
        pdf_url=pdf_url,
        code_url=code_url,
        project_url=project_url,
        authors=_extract_list_value(markdown, ("Authors", "作者")),
        tags=[],
        keywords=keywords,
        summary=summary,
        method=method,
        experiments=experiments,
        limitations=limitations,
        related_papers=[],
        markdown=markdown,
        parsed=parsed,
        content_hash=content_hash,
    )


def _parse_path(source_path: str) -> tuple[str, int, str]:
    parts = PurePosixPath(source_path).parts
    conference = ""
    year = 0
    domain = ""
    if len(parts) >= 2:
        match = _CONF_YEAR_RE.search(parts[1])
        if match:
            conference = match.group(1).upper()
            year = int(match.group(2))
        else:
            conference = parts[1].upper()
    if len(parts) >= 3:
        domain = parts[2].replace("_", " ").replace("-", " ").strip()
    return conference, year, domain


def _extract_title(source_path: str, markdown: str) -> str:
    match = _HEADING_RE.search(markdown)
    if match:
        title = _clean_title(match.group(1))
        if title:
            return title
    stem = PurePosixPath(source_path).stem
    return _clean_title(stem.replace("_", " ").replace("-", " "))


def _clean_title(text: str) -> str:
    text = re.sub(r"\[[^\]]+\]\(([^)]+)\)", "", text or "")
    text = re.sub(r"^\d+[.)\s-]+", "", text)
    return " ".join(text.strip(" #`*-|").split())


def _extract_arxiv_id(markdown: str) -> str:
    match = _ARXIV_RE.search(markdown or "")
    return match.group(1) if match else ""


def _first_url(urls: list[str], *needles: str) -> str:
    lowered = tuple(needle.lower() for needle in needles)
    for url in urls:
        clean = url.rstrip(".,;")
        if any(needle in clean.lower() for needle in lowered):
            return clean
    return ""


def _first_non_arxiv_non_code_url(urls: list[str]) -> str:
    for url in urls:
        low = url.lower()
        if "arxiv.org" in low or any(host in low for host in _CODE_HOSTS):
            continue
        return url.rstrip(".,;")
    return ""


def _extract_labeled_value(markdown: str, labels: tuple[str, ...]) -> str:
    for label in labels:
        match = re.search(rf"^\s*(?:[-*]\s*)?\**{re.escape(label)}\**\s*[:：]\s*(.+)$", markdown, re.I | re.M)
        if match:
            return " ".join(match.group(1).strip().strip("`*").split())[:500]
    return ""


def _extract_list_value(markdown: str, labels: tuple[str, ...]) -> list[str]:
    value = _extract_labeled_value(markdown, labels)
    if not value:
        return []
    return [item.strip() for item in re.split(r"[,，;；]", value) if item.strip()][:20]


def _extract_sections(markdown: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(re.finditer(r"^(#{1,4})\s+(.+?)\s*$", markdown or "", re.M))
    for idx, match in enumerate(matches):
        title = _clean_title(match.group(2)).lower()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        body = " ".join(markdown[start:end].strip().split())
        if title and body:
            sections[title] = body[:6000]
    return sections


def _section_by_keywords(sections: dict[str, str], *keywords: str) -> str:
    lowered = tuple(k.lower() for k in keywords)
    for title, body in sections.items():
        if any(k in title for k in lowered):
            return body[:2000]
    return ""


def _extract_keywords(markdown: str, domain: str, title: str) -> list[str]:
    explicit = _extract_list_value(markdown, ("Keywords", "关键词", "Tags", "标签"))
    terms = explicit[:]
    for source in (domain, title):
        for token in re.split(r"[^A-Za-z0-9\u4e00-\u9fff]+", source):
            token = token.strip()
            if len(token) >= 3 and token.lower() not in {"paper", "notes"}:
                terms.append(token)
    seen: set[str] = set()
    ret: list[str] = []
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            ret.append(term[:80])
    return ret[:20]
