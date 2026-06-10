from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.db.database import close_db, init_db, open_db, set_db_path
from app.rate_limit import limiter
from app.services.daily_scheduler import start_daily_scheduler, stop_daily_scheduler
from app.services.http_clients import close_http_clients, init_http_clients


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    return Response(
        content=f'{{"detail":"Rate limit exceeded: {exc.detail}"}}',
        status_code=429,
        media_type="application/json",
    )


def _setup_logging() -> None:
    """Configure logging so all scholar.* loggers output at INFO level."""
    fmt = "%(asctime)s [%(name)s] %(levelname)s %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt, stream=sys.stdout, force=True)
    # Ensure our loggers are at INFO even if root is higher
    for name in ("scholar", "scholar.runs", "scholar.graph", "scholar.llm", "scholar.mineru", "scholar.papers"):
        logging.getLogger(name).setLevel(logging.INFO)
    # httpx logs full request URLs at INFO. DeepLX deployments often carry the
    # API key in the URL path, so keep transport logs above INFO.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    logger = logging.getLogger("scholar")
    logger.info("Scholar Platform starting up...")

    settings = get_settings()
    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "papers").mkdir(exist_ok=True)

    set_db_path(data_dir / "app.db")
    await init_db()
    await open_db()
    await init_http_clients()
    await start_daily_scheduler()
    logger.info(f"Database initialized at {data_dir / 'app.db'}")
    logger.info(
        f"LLM base_url={settings.llm_base_url} "
        f"default_model={settings.default_thinking_model or '(none)'} "
        f"models={settings.thinking_models}"
    )

    try:
        yield
    finally:
        await stop_daily_scheduler()
        await close_http_clients()
        await close_db()
        logger.info("Scholar Platform shutting down.")


def create_app() -> FastAPI:
    settings = get_settings()

    # Interactive docs / openapi schema leak the full API surface; allow turning
    # them off in production via ENABLE_DOCS=false (kept on by default for dev).
    if settings.enable_docs:
        app = FastAPI(title="Scholar Platform", version="0.1.0", lifespan=lifespan)
    else:
        app = FastAPI(
            title="Scholar Platform",
            version="0.1.0",
            lifespan=lifespan,
            docs_url=None,
            redoc_url=None,
            openapi_url=None,
        )

    # Rate limiter
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # CORS: the app authenticates with an owner_token carried in the query/body,
    # never via cookies, so credentials are not needed. Keeping
    # allow_credentials=False also neutralises the unsafe "*" + credentials
    # combination should cors_origins ever be set to ["*"]. In practice only the
    # cross-origin SSE stream (a plain GET straight to the backend) relies on
    # CORS — every other /api call is same-origin through the Next.js proxy.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    from app.api.admin import router as admin_router
    from app.api.daily import router as daily_router
    from app.api.knowledge import router as knowledge_router
    from app.api.knowledge_spaces import router as knowledge_spaces_router
    from app.api.library import router as library_router
    from app.api.papers import router as papers_router
    from app.api.runs import router as runs_router
    from app.api.settings import router as settings_router
    from app.api.system import router as system_router
    from app.api.translator import router as translator_router

    app.include_router(papers_router, prefix="/api")
    app.include_router(daily_router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    app.include_router(knowledge_spaces_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(admin_router, prefix="/api")
    app.include_router(settings_router, prefix="/api")
    app.include_router(system_router, prefix="/api")
    app.include_router(library_router, prefix="/api")
    app.include_router(translator_router, prefix="/api")

    return app


app = create_app()
