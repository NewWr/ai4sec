from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings


class AppSettings(BaseSettings):
    # --- paths ---
    data_dir: Path = Path("data")

    # --- LLM (Qwen Responses API) ---
    llm_base_url: str = Field(default="", alias="LLM_BASEURL")
    llm_api_key: str = Field(default="", alias="LLM_APIKEY")
    # May hold a comma-separated list of selectable models, e.g.
    # "qwen3.6-plus,qwen3.7-max". The first entry is the default; the full list
    # is offered to the frontend as a dropdown (see `thinking_models`).
    thinking_model: str = Field(default="", alias="THINKING_MODELNAME")
    embed_model: str = Field(default="", alias="EMBED_MODELNAME")
    rerank_model: str = Field(default="", alias="RERANK_MODELNAME")

    # --- Tavily web search (used by publication-rank fallback) ---
    tavily_api_key: str = Field(default="", alias="TAVILY_KEY")
    tavily_search_url: str = Field(
        default="https://api.tavily.com/search",
        alias="TAVILY_SEARCH_URL",
    )

    # --- Publication rank (EasyScholar) ---
    easyscholar_secret_key: str = Field(default="", alias="EASYSCHOLAR_SECRET_KEY")
    easyscholar_api_url: str = Field(
        default="https://www.easyscholar.cc/open/getPublicationRank",
        alias="EASYSCHOLAR_API_URL",
    )

    # --- MinerU ---
    mineru_token: str = Field(default="", alias="MINERU_TOKEN")
    mineru_api_base: str = Field(default="https://mineru.net/api/v4", alias="MINERU_API_BASE")
    mineru_model_version: str = Field(default="vlm", alias="MINERU_MODEL_VERSION")
    mineru_poll_interval_seconds: int = Field(default=6, alias="MINERU_POLL_INTERVAL_SECONDS")
    mineru_parse_timeout_seconds: int = Field(default=1800, alias="MINERU_PARSE_TIMEOUT_SECONDS")
    mineru_batch_timeout_seconds: int = Field(default=7200, alias="MINERU_BATCH_TIMEOUT_SECONDS")

    # --- Paper downloader (OA Resolver / Elsevier TDM / Wiley TDM) ---
    unpaywall_email: str = Field(default="", alias="UNPAYWALL_EMAIL")
    core_api_key: str = Field(default="", alias="CORE_API_KEY")
    elsevier_api_key: str = Field(default="", alias="ELSEVIER_API_KEY")
    elsevier_inst_token: str = Field(default="", alias="ELSEVIER_INSTTOKEN")
    wiley_tdm_token: str = Field(default="", alias="WILEY_TDM_TOKEN")
    unpaywall_api_url: str = Field(
        default="https://api.unpaywall.org/v2/{doi}",
        alias="UNPAYWALL_API_URL",
    )
    core_search_api_url: str = Field(
        default="https://api.core.ac.uk/v3/search/works/",
        alias="CORE_SEARCH_API_URL",
    )
    elsevier_article_api_url: str = Field(
        default="https://api.elsevier.com/content/article/doi/{doi}",
        alias="ELSEVIER_ARTICLE_API_URL",
    )
    wiley_tdm_api_url: str = Field(
        default="https://api.wiley.com/onlinelibrary/tdm/v1/articles/{doi}",
        alias="WILEY_TDM_API_URL",
    )

    # --- Academic metadata APIs ---
    openalex_api_base: str = Field(default="https://api.openalex.org", alias="OPENALEX_API_BASE")
    semantic_scholar_api_base: str = Field(
        default="https://api.semanticscholar.org",
        alias="SEMANTIC_SCHOLAR_API_BASE",
    )
    semantic_scholar_api_key: str = Field(default="", alias="PAPERSEARCH_SEMANTICSCHOLAR_API_KEY")
    crossref_api_base: str = Field(default="https://api.crossref.org", alias="CROSSREF_API_BASE")

    # --- Research Sphere ---
    sphere_radius: int = Field(default=1, alias="SPHERE_RADIUS")
    sphere_candidate_cap: int = Field(default=200, alias="SPHERE_CANDIDATE_CAP")
    sphere_layer1_cap: int = Field(default=40, alias="SPHERE_LAYER1_CAP")
    sphere_pdf_parse_cap: int = Field(default=0, alias="SPHERE_PDF_PARSE_CAP")

    # --- Dify knowledge base (self-hosted proxy) ---
    # Base URL of the Dify knowledge API proxy (e.g. http://dify-proxy:3002).
    # Empty disables every library feature (see `dify_enabled`); the proxy holds
    # the real Dify API key server-side, so no key is configured here.
    dify_api_base: str = Field(default="", alias="DIFY_API_BASE")
    # Optional explicit dataset id. When empty, the proxy's own default dataset
    # (DIFY_DEFAULT_DATASET_ID on the proxy) is used via the short `/api/...` paths.
    dify_default_dataset_id: str = Field(default="", alias="DIFY_DEFAULT_DATASET_ID")
    # Separate dataset for generated analysis reports. Empty disables analysis
    # report ingestion while preserving paper-text ingestion.
    dify_analysis_dataset_id: str = Field(default="", alias="DIFY_ANALYSIS_DATASET_ID")
    # Default retrieval mode. `keyword_search` works for economy/text-model Dify
    # datasets without requiring configured embedding/reranking providers.
    dify_search_method: str = Field(default="keyword_search", alias="DIFY_SEARCH_METHOD")
    dify_timeout_seconds: int = Field(default=90, alias="DIFY_TIMEOUT_SECONDS")
    # How many library candidates Research Sphere pulls per run (0 disables the
    # library channel in Sphere while leaving the standalone library API on).
    dify_sphere_top_k: int = Field(default=10, alias="DIFY_SPHERE_TOP_K")

    # --- DeepLX translation ---
    # Optional DeepLX endpoint used for lightweight UI text translation. Empty
    # keeps the app functional and returns original text with a skipped status.
    deeplx_api_base: str = Field(default="", alias="DEEPLX_API_BASE")
    deeplx_api_key: str = Field(default="", alias="DEEPLX_API_KEY")
    deeplx_timeout_seconds: int = Field(default=30, alias="DEEPLX_TIMEOUT_SECONDS")

    # --- Daily arXiv recommendations ---
    daily_recommendation_enabled: bool = Field(default=True, alias="DAILY_RECOMMENDATION_ENABLED")
    daily_recommendation_lookback_days: int = Field(default=3, alias="DAILY_RECOMMENDATION_LOOKBACK_DAYS")
    daily_recommendation_max_results_per_topic: int = Field(default=80, alias="DAILY_RECOMMENDATION_MAX_RESULTS_PER_TOPIC")
    daily_recommendation_min_score: float = Field(default=0.68, alias="DAILY_RECOMMENDATION_MIN_SCORE")
    daily_recommendation_llm_review_enabled: bool = Field(default=False, alias="DAILY_RECOMMENDATION_LLM_REVIEW_ENABLED")
    daily_recommendation_llm_review_limit: int = Field(default=20, alias="DAILY_RECOMMENDATION_LLM_REVIEW_LIMIT")
    daily_recommendation_translate_enabled: bool = Field(default=True, alias="DAILY_RECOMMENDATION_TRANSLATE_ENABLED")
    daily_recommendation_translate_target: str = Field(default="zh", alias="DAILY_RECOMMENDATION_TRANSLATE_TARGET")
    daily_recommendation_arxiv_api_url: str = Field(
        default="https://export.arxiv.org/api/query",
        alias="DAILY_RECOMMENDATION_ARXIV_API_URL",
    )
    daily_recommendation_source_dataset_id: str = Field(
        default="",
        alias="DAILY_RECOMMENDATION_SOURCE_DATASET_ID",
    )
    daily_recommendation_analysis_dataset_id: str = Field(
        default="",
        alias="DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID",
    )
    daily_recommendation_default_source_space: str = Field(
        default="daily_source",
        alias="DAILY_RECOMMENDATION_DEFAULT_SOURCE_SPACE",
    )
    daily_recommendation_default_analysis_space: str = Field(
        default="daily_analysis",
        alias="DAILY_RECOMMENDATION_DEFAULT_ANALYSIS_SPACE",
    )
    daily_recommendation_auto_refresh_enabled: bool = Field(
        default=True,
        alias="DAILY_RECOMMENDATION_AUTO_REFRESH_ENABLED",
    )
    daily_recommendation_auto_refresh_hour: int = Field(
        default=6,
        alias="DAILY_RECOMMENDATION_AUTO_REFRESH_HOUR",
    )
    daily_recommendation_auto_refresh_minute: int = Field(
        default=0,
        alias="DAILY_RECOMMENDATION_AUTO_REFRESH_MINUTE",
    )
    daily_recommendation_auto_refresh_timezone: str = Field(
        default="Asia/Shanghai",
        alias="DAILY_RECOMMENDATION_AUTO_REFRESH_TIMEZONE",
    )

    # --- Local automatic knowledge-card generation ---
    auto_knowledge_cards_enabled: bool = Field(default=True, alias="AUTO_KNOWLEDGE_CARDS_ENABLED")
    auto_knowledge_card_max_per_run: int = Field(default=12, alias="AUTO_KNOWLEDGE_CARD_MAX_PER_RUN")
    auto_knowledge_card_model: str = Field(default="", alias="AUTO_KNOWLEDGE_CARD_MODEL")
    auto_knowledge_card_prompt_version: str = Field(default="kg_card_v1", alias="AUTO_KNOWLEDGE_CARD_PROMPT_VERSION")
    # Confidence gate for the card promotion state machine: a fact card that is
    # evidence-anchored and scores at/above this auto-promotes draft -> verified;
    # otherwise it stays draft in the bounded review queue (ADR-10).
    knowledge_card_promote_confidence: float = Field(default=0.8, alias="KNOWLEDGE_CARD_PROMOTE_CONFIDENCE")

    # --- Research discovery relation verification ---
    research_discovery_llm_verify_enabled: bool = Field(default=False, alias="RESEARCH_DISCOVERY_LLM_VERIFY_ENABLED")
    research_discovery_llm_verify_limit: int = Field(default=24, alias="RESEARCH_DISCOVERY_LLM_VERIFY_LIMIT")
    research_discovery_llm_verify_model: str = Field(default="", alias="RESEARCH_DISCOVERY_LLM_VERIFY_MODEL")

    # --- Document partitioning for large papers and Supplementary PDFs ---
    document_partition_enabled: bool = Field(default=True, alias="DOCUMENT_PARTITION_ENABLED")
    supplementary_index_enabled: bool = Field(default=True, alias="SUPPLEMENTARY_INDEX_ENABLED")
    supplementary_max_index_chars: int = Field(default=18000, alias="SUPPLEMENTARY_MAX_INDEX_CHARS")
    supplementary_max_expand_chars: int = Field(default=24000, alias="SUPPLEMENTARY_MAX_EXPAND_CHARS")
    supplementary_detection_min_confidence: float = Field(default=0.65, alias="SUPPLEMENTARY_DETECTION_MIN_CONFIDENCE")
    lens_main_body_only: bool = Field(default=True, alias="LENS_MAIN_BODY_ONLY")

    # --- server ---
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = ["http://localhost:3000"]

    # --- security / ops ---
    # When set, /api/admin/* requires a matching `X-Admin-Token` header.
    # Empty (default) keeps admin routes open for backward compatibility on
    # trusted/local deployments — set it before exposing the API publicly.
    admin_api_token: str = Field(default="", alias="ADMIN_API_TOKEN")
    # Comma-separated CIDRs of trusted reverse proxies (Next.js rewrite layer,
    # docker bridge networks). Only requests arriving FROM these networks get
    # their `X-Forwarded-For` honoured for rate-limit accounting; everything
    # else is keyed by the direct remote address so the header can't be forged
    # to dodge limits. Defaults cover loopback + RFC1918 docker ranges.
    trusted_proxy_cidrs: str = Field(
        default="127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
        alias="TRUSTED_PROXY_CIDRS",
    )
    # Swagger UI / ReDoc / openapi.json. Safe to leave on for local dev; set
    # ENABLE_DOCS=false to stop leaking the full API surface in production.
    enable_docs: bool = Field(default=True, alias="ENABLE_DOCS")

    model_config = {
        "env_file": str(Path(__file__).resolve().parents[2] / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
        "populate_by_name": True,
    }

    @property
    def thinking_models(self) -> list[str]:
        """Selectable thinking models, parsed from the comma-separated env var."""
        return [m.strip() for m in self.thinking_model.split(",") if m.strip()]

    @property
    def default_thinking_model(self) -> str:
        """First configured model — used when the caller does not pick one."""
        models = self.thinking_models
        return models[0] if models else ""

    @property
    def dify_enabled(self) -> bool:
        """Whether the Dify knowledge base integration is configured."""
        return bool(self.dify_api_base.strip())


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    return AppSettings()
