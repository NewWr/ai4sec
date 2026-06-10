<p align="center">
  <img src="scholar.png" alt="AI4Sec logo" width="160" />
</p>

<h1 align="center">AI4Sec · Local AI Research Workspace</h1>

<p align="center">
  A local workspace for security and AI research: paper discovery, PDF parsing, cited deep reading, corpus retrieval, knowledge cards, translation, knowledge-base sync, and maintenance checks.
</p>

<p align="center">
  <a href="./README.md">中文 README</a>
</p>

## Capabilities

- **Upload and deep-read papers**: upload PDFs, parse text/equations/tables/figures with MinerU, and generate AI reports with page-level evidence citations.
- **Four analysis modes**: Insight Snap for triage, Logic Lens for formulas/algorithms/experiments, Research Sphere for citation networks and research gaps, and Smart Q&A for intent-based routing.
- **Local paper library**: manage metadata, collections, reading status, analysis history, Dify sync state, deletion, and retry operations.
- **Daily recommendations**: fetch arXiv candidates, score by topic, translate, collect feedback, import selected papers, and launch follow-up analysis.
- **Knowledge spaces and cards**: store claims, methods, datasets, metrics, results, limitations, questions, and writing snippets; bind different spaces to different Dify datasets.
- **Corpus search and cross-paper Q&A**: retrieve over your own paper corpus through a Dify proxy and synthesize answers from cited passages.
- **Translation and runtime settings**: optional DeepLX translation; configure OpenAI-compatible LLM base URL, model list, API key, and reasoning effort from the web UI.
- **Health checks**: inspect parsing, sync, metadata, knowledge assets, and index status across the local corpus.

## Architecture

AI4Sec has three services:

| Service | Purpose | Default port |
|---|---|---|
| `frontend` | Next.js UI for upload, library, daily recommendations, knowledge spaces, knowledge cards, translation, and settings | `3001` |
| `backend` | FastAPI backend for PDF parsing, LLM workflows, SQLite data, SSE streaming, and knowledge assets | `8001` |
| `dify-proxy` | Optional proxy that keeps the Dify Dataset API key server-side and exposes dataset/document/retrieval/sync endpoints to the backend | `3002` |

The default deployment starts only `frontend` and `backend`. Dify is optional. Enable `dify-proxy` only when you need cross-paper RAG, Dify sync, or dataset-bound knowledge spaces.

## Quick Start

### 1. Prepare the environment

Docker 24+ and Docker Compose 2.20+ are required.
The commands below use `docker compose`; if your system only has the standalone binary, replace `docker compose` with `docker-compose`.

```bash
git clone https://github.com/NewWr/ai4sec.git
cd ai4sec
cp .env.example .env
```

Edit `.env` and fill at least:

```bash
LLM_BASEURL=https://api.openai.com/v1
LLM_APIKEY=your OpenAI-compatible API key
THINKING_MODELNAME=your model name
MINERU_TOKEN=your MinerU token
```

### 2. Start the base deployment

```bash
docker compose up -d --build
```

- Frontend: http://localhost:3001
- Backend: http://localhost:8001
- API docs: http://localhost:8001/docs

The base deployment supports upload analysis, paper library, daily recommendations, knowledge cards, translation, settings, and health checks. Dify-related features will report that the knowledge base is not configured.

### 3. Stop

```bash
docker compose down
```

Uploaded PDFs, SQLite databases, and generated content are stored in `./docker-data/`, which is ignored by Git.

## Configure Dify RAG

`dify-rag/` is a developer-local Dify deployment directory and is not published with this project. Public users should deploy Dify separately, then let AI4Sec access the Dify Dataset API through `dify-proxy`.

### Option A: Use a separate Dify checkout

```bash
git clone https://github.com/langgenius/dify.git dify-rag
cd dify-rag/docker
cp .env.example .env
docker compose up -d
```

Dify is available at http://localhost by default. Create the first admin account, then create or prepare a knowledge-base dataset in the Dify console.

### Option B: Use an existing Dify instance

Any Dify instance works as long as AI4Sec's `dify-proxy` can reach its API URL. If both Dify and AI4Sec run with Docker Compose, the recommended setup is to attach `dify-proxy` to Dify's Compose network.

### Required values

You need:

| Variable | Meaning |
|---|---|
| `DIFY_BASE_URL` | The Dify API URL as seen from `dify-proxy`. In the same Docker network this is usually `http://nginx`; from the host it is usually `http://host.docker.internal` or your Dify server URL |
| `DIFY_DATASET_API_KEY` | Dify Dataset / Knowledge API key. Store it only in `.env` |
| `DIFY_DEFAULT_DATASET_ID` / `DIFY_ANALYSIS_DATASET_ID` | Dataset IDs for source paper text and generated analysis reports. You can also bind individual knowledge spaces to different datasets in the UI |

If you use the separate Dify Compose setup above, find its Docker network:

```bash
docker network ls | grep dify
```

Common names are `docker_default` or `dify_default`. Put the values in AI4Sec's `.env`:

```bash
DIFY_DOCKER_NETWORK=docker_default
DIFY_API_BASE=http://dify-proxy:3002
DIFY_BASE_URL=http://nginx
DIFY_DATASET_API_KEY=your Dify Dataset API key
DIFY_DEFAULT_DATASET_ID=your source-paper dataset id
DIFY_ANALYSIS_DATASET_ID=your analysis-report dataset id
DIFY_SEARCH_METHOD=keyword_search
```

Then start AI4Sec with the Dify profile:

```bash
docker compose --profile dify up -d --build
```

Check the integration:

```bash
curl http://localhost:3002/health
curl http://localhost:8001/api/library/status
```

When `enabled: true` is returned by the backend status endpoint, the Knowledge Base page, Knowledge Spaces page, Research Sphere library matching, and paper/analysis sync are ready.

## Common Configuration

| Variable | Purpose |
|---|---|
| `LLM_BASEURL` / `LLM_APIKEY` / `THINKING_MODELNAME` | OpenAI-compatible LLM endpoint, key, and comma-separated model list |
| `MINERU_TOKEN` | Required for PDF parsing |
| `EASYSCHOLAR_SECRET_KEY` | Journal/conference ranking |
| `TAVILY_KEY` | Web fallback for publication ranking and research context |
| `UNPAYWALL_EMAIL` / `CORE_API_KEY` / `ELSEVIER_API_KEY` / `WILEY_TDM_TOKEN` | Full-text fetching for Research Sphere |
| `DEEPLX_API_BASE` / `DEEPLX_API_KEY` | Translation page and daily recommendation translation |
| `DAILY_RECOMMENDATION_*` | Daily recommendation topics, limits, score threshold, and auto-refresh schedule |
| `AUTO_KNOWLEDGE_CARDS_ENABLED` | Generate knowledge cards after analysis |
| `ADMIN_API_TOKEN` | Protect `/api/admin/*` and runtime settings update endpoints |
| `ENABLE_DOCS=false` | Disable Swagger/OpenAPI in production |

See [`.env.example`](./.env.example) for all variables.

## Local Development

Backend:

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

## Project Layout

```text
ai4sec/
├── backend/          # FastAPI, LangGraph workflows, SQLite, PDF/LLM/Dify/knowledge-asset services
├── frontend/         # Next.js pages and components
├── dify-proxy/       # Optional Dify Dataset API proxy
├── docker-compose.yml
├── .env.example
├── scripts/          # Public-release checks
└── docs/             # Release and deployment notes
```

## Public Release and Privacy

Do not commit `.env`, `docker-data/`, `backend/data/`, `dify-rag/`, PDFs, databases, or API keys. Run the release check before publishing:

```bash
scripts/check_public_release.sh
```

## License

Released under the [MIT License](./LICENSE).
