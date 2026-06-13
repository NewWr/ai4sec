<p align="center">
  <img src="scholar.png" alt="AI4Sec logo" width="160" />
</p>

<h1 align="center">AI4Sec · Local AI Research Workspace</h1>

<p align="center">
  A local workspace for security and AI research, covering paper intake, PDF parsing, evidence-grounded reading, cross-paper retrieval, knowledge cards, synthesis, writing export, and knowledge-base sync.
</p>

<p align="center">
  <a href="./README.md">中文 README</a>
</p>

## Current Capabilities

- **Paper intake and parsing**: upload PDFs or ingest papers from daily recommendations, parse text, equations, tables, figures, and supplementary material with MinerU, then persist everything locally.
- **Four analysis workflows**: Insight Snap for quick triage, Logic Lens for structured deep reading, Research Sphere for citation and related-work expansion, and Smart Q&A for intent-based routing to triage, deep reading, landscape analysis, or single-paper Q&A.
- **Evidence-grounded knowledge assets**: generate claim, method, dataset, metric, result, limitation, question, and writing-snippet cards with page references, source snippets, and relationship metadata.
- **Local library and knowledge spaces**: manage metadata, collections, reading status, notes, annotations, AI review marks, Dify sync state, and bind different knowledge spaces to different Dify datasets.
- **Daily arXiv recommendations**: fetch candidates by topic, score, translate, collect feedback, ingest selected papers, promote them to knowledge spaces, and launch follow-up analysis.
- **Cross-paper retrieval and synthesis**: use the local graph and optional Dify RAG for corpus search, cross-paper Q&A, conflict discovery, research-gap candidates, and synthesis cards.
- **Writing and export**: compose related-work/method/experiment/limitation snippets from verified cards, build comparison tables, and export Markdown, Obsidian, BibTeX, RIS, and Zotero CSL JSON.
- **Operations**: runtime LLM settings, model connectivity tests, DeepLX translation, health checks, cache maintenance, rate limiting, and public-release checks.

## UI Routes

| Route | Purpose |
|---|---|
| `/upload` | Upload PDFs and create paper records |
| `/daily` | Daily recommendations, feedback, ingestion, and promotion |
| `/papers` | Paper list, analysis entry points, recent runs, and PDF viewing |
| `/library` | Local library, collections, states, sync, and deletion |
| `/knowledge` | Knowledge cards, batch review, merging, and duplicate checks |
| `/synthesis` | Synthesis cards, conflict relations, and research-gap board |
| `/writing` | Draft composition, comparison tables, and external exports |
| `/knowledge-spaces` | Knowledge spaces, dataset binding, and Dify document management |
| `/translate` | DeepLX text translation |
| `/health` | Parsing, sync, knowledge-asset, and index health checks |
| `/settings` | LLM base URL, models, API key, and reasoning effort |

## Architecture

| Service | Stack | Default port | Purpose |
|---|---|---:|---|
| `frontend` | Next.js 15 / React 19 / Tailwind | `3001` | Web UI, PDF viewer, SSE run status, and API proxy |
| `backend` | FastAPI / LangGraph / SQLite | `8001` | Parsing, LLM workflows, knowledge assets, retrieval, exports, and health checks |
| `dify-proxy` | FastAPI | `3002` | Optional service that keeps the Dify Dataset API key server-side |
| `ai4sec-dify-sync` | Python CLI / SQLite | - | Optional watcher that syncs parsed papers into a Dify Dataset |

The default deployment needs only `frontend` and `backend`. Enable `dify-proxy` when you need cross-paper RAG, Dify document sync, or dataset-bound knowledge spaces.

## Quick Start

Docker 24+ and Docker Compose 2.20+ are required.

```bash
git clone https://github.com/NewWr/ai4sec.git
cd ai4sec
cp .env.example .env
```

Edit `.env` and fill at least:

```dotenv
LLM_BASEURL=https://api.openai.com/v1
LLM_APIKEY=
THINKING_MODELNAME=
MINERU_TOKEN=
```

Clear `AI4SEC_BACKEND_PROXY` if you do not use a local proxy; otherwise set it to your actual proxy URL.

```bash
./start_ai4sec.sh
```

Open:

- Frontend: http://localhost:3001
- Backend: http://localhost:8001
- API docs: http://localhost:8001/docs

Stop services:

```bash
docker compose --profile dify down
cd ai4sec-dify-sync && docker compose down
```

Runtime data is stored in `./docker-data/`, which is ignored by Git.

## Configure Dify RAG

`dify-rag/` is a local development directory and is not published with this project. For public deployments, deploy Dify separately and let AI4Sec access the Dify Dataset API through `dify-proxy`.

Example:

```bash
git clone https://github.com/langgenius/dify.git dify-rag
cd dify-rag/docker
cp .env.example .env
docker compose up -d
```

Configure AI4Sec's `.env`:

```dotenv
DIFY_DOCKER_NETWORK=docker_default
DIFY_API_BASE=http://dify-proxy:3002
DIFY_BASE_URL=http://nginx
DIFY_DATASET_API_KEY=
DIFY_DATASET_ID=
DIFY_DEFAULT_DATASET_ID=
DIFY_ANALYSIS_DATASET_ID=
DIFY_SEARCH_METHOD=keyword_search
```

Start the full stack:

```bash
./start_ai4sec.sh
```

Check the integration:

```bash
curl http://localhost:3002/health
curl http://localhost:8001/api/library/status
```

When the backend status returns `enabled: true`, the Knowledge Base page, knowledge spaces, Research Sphere library matching, paper sync, and analysis sync are ready.

`ai4sec-dify-sync/` is included in this repository. The one-click startup script uses the root `.env`, builds and starts the watcher, reads `./docker-data/app.db` and PaperIR files, uploads parsed papers to `DIFY_DATASET_ID`, and stores sync state in `ai4sec-dify-sync/state/dify_syncs.db`.

## Common Configuration

| Variable | Purpose |
|---|---|
| `LLM_BASEURL` / `LLM_APIKEY` / `THINKING_MODELNAME` | OpenAI-compatible LLM endpoint, key, and optional comma-separated model list |
| `MINERU_TOKEN` | Required for PDF parsing |
| `EASYSCHOLAR_SECRET_KEY` / `TAVILY_KEY` | Publication ranking and web fallback search |
| `UNPAYWALL_EMAIL` / `CORE_API_KEY` / `ELSEVIER_API_KEY` / `WILEY_TDM_TOKEN` | Full-text fetching for Research Sphere |
| `DIFY_*` | Dify RAG, sync, and knowledge-space dataset binding |
| `DEEPLX_API_BASE` / `DEEPLX_API_KEY` | Translation page and daily recommendation translation |
| `DAILY_RECOMMENDATION_*` | Daily topics, limits, score threshold, auto-refresh schedule, and target knowledge spaces |
| `AUTO_KNOWLEDGE_CARDS_ENABLED` | Generate knowledge cards after analysis |
| `RESEARCH_DISCOVERY_LLM_VERIFY_ENABLED` | Verify cross-paper relation candidates with an LLM |
| `DOCUMENT_PARTITION_ENABLED` / `SUPPLEMENTARY_INDEX_ENABLED` | Large-document partitioning and supplementary-material indexing |
| `ADMIN_API_TOKEN` | Protect `/api/admin/*` and runtime settings write endpoints |
| `ENABLE_DOCS=false` | Disable Swagger/OpenAPI in production |

See [`.env.example`](./.env.example) for the full list.

## Local Development

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```

Frontend:

```bash
cd frontend
npm install
npm run dev
npm run build
```

## Project Layout

```text
ai4sec/
├── backend/          # FastAPI, LangGraph workflows, SQLite, PDF/LLM/Dify/knowledge-asset services
├── frontend/         # Next.js pages, components, PDF viewer, and API client
├── dify-proxy/       # Optional Dify Dataset API proxy
├── ai4sec-dify-sync/ # Optional PaperIR-to-Dify Dataset sync watcher
├── docs/             # Release and deployment notes
├── scripts/          # Public-release checks
├── start_ai4sec.sh   # One-click startup for Dify, AI4Sec, and the sync watcher
├── docker-compose.yml
└── .env.example
```

## Privacy and Public Release

Do not commit `.env`, `docker-data/`, `.local-dev-data/`, `backend/data/`, `dify-rag/`, `ai4sec-dify-sync/state/*.db`, PDFs, databases, parser outputs, or API keys. Run the pre-release check:

```bash
scripts/check_public_release.sh
```

If local Git history ever contained private files, publish from a clean-history snapshot or rewrite history with `git filter-repo`/BFG first.

## License

Released under the [MIT License](./LICENSE).
