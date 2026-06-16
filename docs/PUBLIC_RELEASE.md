# Public Release Checklist

This repository can be published, but do not push the current Git history as-is if it ever contained private papers, generated parsing output, runtime databases, or local `.env` files.

## Private Data That Must Stay Local

- `.env`, `.env.*`, nested `.env` files
- `docker-data/`, `.local-dev-data/`, `backend/data/`
- uploaded PDFs, MinerU zips, layout JSON, parsed Markdown, generated analysis output
- Dify deployment data and local Dify checkout/runtime folders such as `dify-rag/`
- SQLite databases, WAL/SHM files, rank caches
- API keys and provider tokens: LLM, MinerU, Dify, DeepLX, EasyScholar, Tavily, Semantic Scholar, IEEE, Elsevier, Wiley, CORE

## Configuration for Users

Users should copy the public template and fill in their own values:

```bash
cp .env.example .env
```

Minimum useful configuration:

```dotenv
LLM_BASEURL=https://api.openai.com/v1
LLM_APIKEY=
THINKING_MODELNAME=
MINERU_TOKEN=
NEXT_PUBLIC_BACKEND_URL=http://localhost:8001
```

Optional integrations:

- Dify corpus RAG: set `DIFY_API_BASE`, `DIFY_BASE_URL`, `DIFY_DATASET_API_KEY`, and dataset IDs.
- Translation: set `DEEPLX_API_BASE` and optionally `DEEPLX_API_KEY`.
- Publication ranking: set `EASYSCHOLAR_SECRET_KEY` and optionally `TAVILY_KEY`.
- Reference full-text fetching: set `UNPAYWALL_EMAIL`, `CORE_API_KEY`, `ELSEVIER_API_KEY`, `ELSEVIER_INSTTOKEN`, or `WILEY_TDM_TOKEN`.
- Public deployment hardening: set `ADMIN_API_TOKEN` and `ENABLE_DOCS=false`.

## Pre-Release Checks

Run:

```bash
chmod +x scripts/check_public_release.sh
scripts/check_public_release.sh
```

The script checks tracked files, ignored private files, obvious secret literals, private deployment examples, large tracked files, and Git history.

## Safe Publish Options

Recommended for this workspace: create a clean-history public export. This avoids publishing old commits that may contain private PDFs or parsed paper content.

```bash
cd /media/dc/M2_DATA/Paper_read/AI4Sec
scripts/check_public_release.sh || true

git archive --format=tar HEAD | tar -x -C /tmp/ai4sec-public
cd /tmp/ai4sec-public
git init
git add .
git commit -m "Initial public release"
git branch -M main
git remote add origin git@github.com:<user>/<repo>.git
git push -u origin main
```

If you need to preserve history, rewrite it first with `git filter-repo` or BFG to remove `backend/data/`, `docker-data/`, `.local-dev-data/`, old tool `.env` files, PDFs, SQLite files, and generated parser outputs from every commit. After rewriting, rerun `scripts/check_public_release.sh`.

## Current Workspace Finding

This workspace has current private runtime data ignored correctly, but Git history has contained `backend/data` papers and databases plus old tool `.env` paths. Use a clean-history export or rewrite history before making the GitHub repository public.
