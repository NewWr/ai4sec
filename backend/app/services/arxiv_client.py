from __future__ import annotations

import datetime as dt
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from app.config import get_settings
from app.services.http_clients import get_default_http_client

ATOM_NS = "{http://www.w3.org/2005/Atom}"
ARXIV_NS = "{http://arxiv.org/schemas/atom}"
_ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")


class ArxivSearchError(RuntimeError):
    """Raised when arXiv search cannot return usable Atom results."""


@dataclass(frozen=True)
class ArxivPaper:
    arxiv_id: str
    title: str
    abstract: str
    authors: list[str]
    primary_category: str
    categories: list[str]
    published_at: str
    updated_at: str
    arxiv_url: str
    pdf_url: str


def _clean_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _short_arxiv_id(entry_id: str) -> str:
    match = _ARXIV_ID_RE.search(entry_id or "")
    return match.group(1) if match else (entry_id.rsplit("/", 1)[-1] if entry_id else "")


def _text(parent: ET.Element, tag: str) -> str:
    node = parent.find(f"{ATOM_NS}{tag}")
    return _clean_text(node.text or "") if node is not None else ""


def _date_only(iso: str) -> str:
    return (iso or "").strip()[:10]


def _entry_to_paper(entry: ET.Element) -> ArxivPaper:
    entry_id = _text(entry, "id")
    arxiv_id = _short_arxiv_id(entry_id)
    title = _text(entry, "title")
    abstract = _text(entry, "summary")
    authors = [
        _text(author, "name")
        for author in entry.findall(f"{ATOM_NS}author")
        if _text(author, "name")
    ]
    primary_node = entry.find(f"{ARXIV_NS}primary_category")
    primary_category = primary_node.attrib.get("term", "") if primary_node is not None else ""
    categories = [
        node.attrib.get("term", "")
        for node in entry.findall(f"{ATOM_NS}category")
        if node.attrib.get("term", "")
    ]
    published_at = _text(entry, "published")
    updated_at = _text(entry, "updated")
    pdf_url = ""
    for link in entry.findall(f"{ATOM_NS}link"):
        if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
            pdf_url = link.attrib.get("href", "")
            break
    arxiv_url = f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else entry_id
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}"
    return ArxivPaper(
        arxiv_id=arxiv_id,
        title=title,
        abstract=abstract,
        authors=authors,
        primary_category=primary_category,
        categories=categories,
        published_at=_date_only(published_at),
        updated_at=_date_only(updated_at),
        arxiv_url=arxiv_url,
        pdf_url=pdf_url,
    )


def _topic_terms(topic: dict[str, Any]) -> list[str]:
    groups = ((topic.get("must") or {}).get("any") or [])
    terms: list[str] = []
    for group in groups:
        if not isinstance(group, list):
            continue
        phrase_terms = [str(term).strip() for term in group if str(term).strip()]
        if len(phrase_terms) >= 2:
            terms.append(" AND ".join(f'all:"{term}"' for term in phrase_terms))
        elif phrase_terms and len(phrase_terms[0]) > 4:
            terms.append(f'all:"{phrase_terms[0]}"')
    return terms[:8]


def build_query(topic: dict[str, Any]) -> str:
    categories = [str(c).strip() for c in topic.get("arxiv_categories") or [] if str(c).strip()]
    category_query = " OR ".join(f"cat:{cat}" for cat in categories)
    term_query = " OR ".join(_topic_terms(topic))
    if category_query and term_query:
        return f"({category_query}) AND ({term_query})"
    if category_query:
        return category_query
    return term_query or "cat:cs.CV"


async def search_arxiv(topic: dict[str, Any], *, max_results: int) -> list[ArxivPaper]:
    settings = get_settings()
    params = {
        "search_query": build_query(topic),
        "start": "0",
        "max_results": str(max(1, min(max_results, 200))),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{settings.daily_recommendation_arxiv_api_url}?{urlencode(params)}"
    client = get_default_http_client()
    try:
        resp = await client.get(url, headers={"User-Agent": "AI4Sec daily recommendations/0.1"})
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        body = _clean_text(exc.response.text)[:300]
        detail = body or exc.response.reason_phrase or "HTTP error"
        raise ArxivSearchError(f"arXiv API {status}: {detail}") from exc
    except httpx.TimeoutException as exc:
        raise ArxivSearchError("arXiv API timeout") from exc
    except httpx.RequestError as exc:
        raise ArxivSearchError(f"arXiv API request failed: {exc}") from exc
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        raise ArxivSearchError("arXiv API returned malformed XML") from exc
    return [_entry_to_paper(entry) for entry in root.findall(f"{ATOM_NS}entry")]


def within_lookback(paper: ArxivPaper, *, fetched_date: str, lookback_days: int) -> bool:
    try:
        base = dt.date.fromisoformat(fetched_date)
        published = dt.date.fromisoformat(paper.updated_at or paper.published_at)
    except ValueError:
        return True
    return published >= base - dt.timedelta(days=max(1, lookback_days))
