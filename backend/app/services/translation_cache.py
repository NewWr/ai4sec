from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings
from app.db import database as db

logger = logging.getLogger("scholar.translate_cache")


@dataclass(frozen=True)
class TranslationResult:
    source_text: str
    translated_text: str
    status: str
    provider: str = "deeplx"
    error_msg: str = ""


def text_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def _normalize_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _normalize_multiline_text(text: str) -> str:
    return (text or "").strip()


def _looks_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _normalize_lang(lang: str, *, default: str = "auto") -> str:
    cleaned = (lang or default).strip().replace("_", "-")
    if not cleaned:
        return default
    return cleaned.lower()


def _deepl_lang(lang: str, *, auto: bool = False) -> str:
    normalized = _normalize_lang(lang)
    if auto and normalized in {"auto", "detect"}:
        return "AUTO"
    return normalized.upper()


def _extract_translation(data: dict[str, Any]) -> str:
    for key in ("data", "translation", "translated_text", "result", "text"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    translations = data.get("translations")
    if isinstance(translations, list) and translations:
        first = translations[0]
        if isinstance(first, dict):
            value = first.get("text") or first.get("translation")
            if isinstance(value, str):
                return value.strip()
    return ""


def _redact_secret(text: str, secret: str) -> str:
    if not secret:
        return text
    return text.replace(secret, "***")


async def translate_text(
    text: str,
    *,
    source_lang: str = "auto",
    target_lang: str = "zh",
    provider: str = "deeplx",
    skip_same_language: bool = True,
    preserve_whitespace: bool = False,
) -> TranslationResult:
    source_text = _normalize_multiline_text(text) if preserve_whitespace else _normalize_text(text)
    source_lang = _normalize_lang(source_lang)
    target_lang = _normalize_lang(target_lang, default="zh")
    if not source_text:
        return TranslationResult(source_text="", translated_text="", status="skipped", provider=provider)
    if skip_same_language and source_lang != "auto" and source_lang == target_lang:
        return TranslationResult(source_text=source_text, translated_text=source_text, status="skipped", provider=provider)
    if skip_same_language and target_lang in {"zh", "zh-cn", "zh-hans"} and _looks_chinese(source_text):
        return TranslationResult(source_text=source_text, translated_text=source_text, status="skipped", provider=provider)

    digest = text_hash(source_text)
    row = await db.fetch_one(
        """
        SELECT translated_text, status, error_msg
          FROM translation_cache
         WHERE text_hash = ? AND source_lang = ? AND target_lang = ? AND provider = ?
        """,
        (digest, source_lang, target_lang, provider),
    )
    if row and row.get("translated_text"):
        return TranslationResult(
            source_text=source_text,
            translated_text=str(row.get("translated_text") or source_text),
            status=str(row.get("status") or "done"),
            provider=provider,
            error_msg=str(row.get("error_msg") or ""),
        )

    settings = get_settings()
    if provider != "deeplx" or not settings.deeplx_api_base.strip():
        await _upsert_translation(
            digest,
            source_lang,
            target_lang,
            provider,
            source_text,
            source_text,
            "skipped",
            "DEEPLX_API_BASE is not configured",
        )
        return TranslationResult(
            source_text=source_text,
            translated_text=source_text,
            status="skipped",
            provider=provider,
            error_msg="DEEPLX_API_BASE is not configured",
        )

    error_msg = ""
    translated = ""
    try:
        base = settings.deeplx_api_base.rstrip("/")
        if "{{apiKey}}" in base and settings.deeplx_api_key:
            base = base.replace("{{apiKey}}", settings.deeplx_api_key)
        url = base if base.endswith("/translate") else f"{base}/translate"
        headers = {"Content-Type": "application/json"}
        if settings.deeplx_api_key:
            headers["Authorization"] = f"Bearer {settings.deeplx_api_key}"
        payload = {
            "text": source_text,
            "source_lang": _deepl_lang(source_lang, auto=True),
            "target_lang": _deepl_lang(target_lang),
        }
        async with httpx.AsyncClient(timeout=float(settings.deeplx_timeout_seconds)) as client:
            resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        translated = _extract_translation(resp.json())
        if not translated:
            raise RuntimeError("DeepLX response did not contain translated text")
        status = "done"
    except Exception as exc:
        error_msg = _redact_secret(str(exc), settings.deeplx_api_key)
        translated = source_text
        status = "failed"
        logger.warning("DeepLX translation failed hash=%s: %s", digest[:10], error_msg)

    await _upsert_translation(digest, source_lang, target_lang, provider, source_text, translated, status, error_msg)
    return TranslationResult(
        source_text=source_text,
        translated_text=translated,
        status=status,
        provider=provider,
        error_msg=error_msg,
    )


async def translate_many(texts: list[str], *, target_lang: str = "zh") -> list[TranslationResult]:
    results: list[TranslationResult] = []
    for text in texts:
        results.append(await translate_text(text, target_lang=target_lang))
    return results


async def _upsert_translation(
    digest: str,
    source_lang: str,
    target_lang: str,
    provider: str,
    source_text: str,
    translated_text: str,
    status: str,
    error_msg: str,
) -> None:
    await db.execute(
        """
        INSERT INTO translation_cache (
            text_hash, source_lang, target_lang, provider, source_text,
            translated_text, status, error_msg, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
        ON CONFLICT(text_hash, source_lang, target_lang, provider) DO UPDATE SET
            source_text = excluded.source_text,
            translated_text = excluded.translated_text,
            status = excluded.status,
            error_msg = excluded.error_msg,
            updated_at = datetime('now')
        """,
        (digest, source_lang, target_lang, provider, source_text, translated_text, status, error_msg[:1000]),
    )
