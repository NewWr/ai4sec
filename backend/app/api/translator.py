from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import TranslatorRequest, TranslatorResponse
from app.rate_limit import limiter
from app.services.translation_cache import translate_text

router = APIRouter(tags=["translator"])

SUPPORTED_LANGS = {
    "auto",
    "bg",
    "cs",
    "da",
    "de",
    "el",
    "en",
    "en-gb",
    "en-us",
    "es",
    "et",
    "fi",
    "fr",
    "hu",
    "id",
    "it",
    "ja",
    "ko",
    "lt",
    "lv",
    "nb",
    "nl",
    "pl",
    "pt",
    "pt-br",
    "pt-pt",
    "ro",
    "ru",
    "sk",
    "sl",
    "sv",
    "tr",
    "uk",
    "zh",
}


def _normalize_lang(value: str, *, default: str = "auto") -> str:
    lang = (value or default).strip().replace("_", "-").lower()
    return lang or default


@router.post("/translator/translate", response_model=TranslatorResponse)
@limiter.limit("60/minute")
async def translate(request: Request, body: TranslatorRequest) -> TranslatorResponse:
    del request
    source_text = body.text.strip()
    source_lang = _normalize_lang(body.source_lang)
    target_lang = _normalize_lang(body.target_lang, default="zh")

    if not source_text:
        raise HTTPException(status_code=400, detail="text is required")
    if source_lang not in SUPPORTED_LANGS:
        raise HTTPException(status_code=400, detail=f"unsupported source_lang: {source_lang}")
    if target_lang == "auto" or target_lang not in SUPPORTED_LANGS:
        raise HTTPException(status_code=400, detail=f"unsupported target_lang: {target_lang}")

    result = await translate_text(
        source_text,
        source_lang=source_lang,
        target_lang=target_lang,
        skip_same_language=True,
        preserve_whitespace=True,
    )
    return TranslatorResponse(
        source_text=result.source_text,
        translated_text=result.translated_text,
        source_lang=source_lang,
        target_lang=target_lang,
        status=result.status,
        provider=result.provider,
        error_msg=result.error_msg,
    )
