# Daily Recommendations

## 2026-06-08

- Switched the runtime LLM client and `/settings` connection test to call the Responses API directly, with persisted `reasoning_effort` support.
- Added a `/settings` reasoning-effort selector (`none`, `minimal`, `low`, `medium`, `high`, `xhigh`) and set the running deployment to `gpt-5.5`.
- Rebuilt and restarted backend/frontend containers; verified `/api/settings/llm/test` returns `endpoint=responses`.
- Verified with:
  `.venv/bin/python -m pytest tests/test_llm_service.py tests/test_settings_api.py -q`,
  `.venv/bin/python -m ruff check app/services/llm_runtime_config.py app/services/llm_service.py app/api/settings.py app/models/schemas.py tests/test_llm_service.py tests/test_settings_api.py`,
  and `npm run build`.

- Fixed Logic Lens 504 failures caused by oversized Responses API requests:
  Lens now uses smaller per-section context/output budgets, and upstream `502/504` gateway errors fail fast instead of retrying the same long request repeatedly.
- Split the Logic Lens method deep-dive into two LLM requests, `lens_method_pipeline` and `lens_method_formulas`, while keeping the existing method output token budget per request.
- Removed explicit LLM output token caps from the shared LLM client and business workflows; requests no longer send `max_tokens` or `max_output_tokens`.
- Changed the running LLM reasoning effort from `xhigh` to `medium`; `/api/settings/llm/test` returns `endpoint=responses` with HTTP 200.
- Rebuilt and restarted the backend container.
- Verified with:
  `.venv/bin/python -m pytest tests/test_lens_segmented.py tests/test_llm_service.py -q`
  and `.venv/bin/python -m ruff check app/services/llm_service.py app/workflows/lens_subgraph.py tests/test_lens_segmented.py tests/test_llm_service.py`.

- Fixed `/papers` local paper deletion when papers have generated knowledge assets:
  deletion now clears card generation rows, knowledge-space items, snippets, evidence-card links, and daily recommendation back-links before removing the paper.
- Rebuilt and restarted the backend container serving `localhost:3001`; verified deletion with a temporary uploaded PDF returning `204` and subsequent `404`.
- Verified with:
  `.venv/bin/python -m pytest tests/test_paper_library.py -q`,
  `.venv/bin/python -m ruff check app/api/papers.py tests/test_paper_library.py`,
  and `npm run build`.

- Implemented the knowledge-space/library unification P0/P1:
  `/knowledge-spaces` is now titled "知识库中心", with "内容" and "Dify 索引" tabs.
- Added backend APIs for creating and binding a Dify dataset per knowledge space, listing that space's Dify documents, and previewing a document's Markdown from the bound dataset.
- Added frontend controls to create a Dify dataset, manually edit the bound `dify_dataset_id`, browse Dify documents, and preview Markdown with the existing library renderer.
- Hid the old `/library` entry from the top navigation while keeping the route accessible.
- Fixed `/knowledge-spaces` layout so the page no longer creates empty over-scroll beyond the content; scrolling is constrained to the side list, item list, and document preview panes.
- Added expanded full-page Dify document reading from the knowledge-space preview pane.
- Fixed upload-page `API 500`/proxy disconnects after PDF upload by routing the long-running collection-suggestion request directly to the backend instead of through the Next.js rewrite proxy.
- Verified with:
  `.venv/bin/python -m pytest tests/test_knowledge_spaces.py -q`,
  `.venv/bin/python -m ruff check app/services/knowledge_spaces.py app/api/knowledge_spaces.py app/models/schemas.py tests/test_knowledge_spaces.py`,
  `npm run build`,
  `sudo -n docker-compose build frontend`,
  and `sudo -n docker-compose up -d frontend`.

- Added `/settings` and `/api/settings/llm` so the LLM base URL, API key, and selectable model list can be changed from the web UI.
- Added `/api/settings/llm/test` and a `/settings` test button to verify the current form values against the LLM gateway before saving or starting analysis runs.
- Runtime LLM settings are persisted in the backend data directory as `llm_runtime_config.json`; API keys are not returned to the frontend, only configured status and the last four characters are shown.
- Switched model listing, run model validation, library Q&A validation, paper collection suggestions, Sphere paper-search LLM wiring, and `LLMService` to use runtime LLM settings before falling back to `.env`.
- Verified with:
  `.venv/bin/python -m pytest tests/test_llm_service.py tests/test_settings_api.py tests/test_daily_recommendations.py -q`,
  targeted `ruff check`,
  and `npm run build`.

- Changed `/api/daily/items` so an empty `date` means all recommendation dates instead of today's date.
- Added pagination metadata and defaults: `limit=20`, `offset=0`, `total`, and `has_more`; sorting is now `fetched_date DESC, score DESC, updated_at DESC, published_at DESC`.
- Updated `/daily` to show all dates by default, keep date as an optional filter, display 20 items per page, and use backend pagination controls.
- Removed the page-level manual refresh button from `/daily`; refresh remains available as an API operation while the backend scheduler handles routine updates.
- Added a backend daily scheduler that runs `refresh_daily_recommendations(..., force=True)` every day at 06:00 `Asia/Shanghai` by default, configurable via `DAILY_RECOMMENDATION_AUTO_REFRESH_*`.
- Verified backend changes with:
  `.venv/bin/python -m pytest tests/test_daily_recommendations.py tests/test_knowledge_spaces.py tests/test_dify_sync.py -q`
  and `.venv/bin/python -m ruff check ...`.

## 2026-06-07

- Implemented P0 of `方案/daily-recommendation-knowledge-base-redesign-plan.md`:
  local `knowledge_spaces` and `knowledge_space_items` tables, default system spaces, backend list/move/copy/remove APIs, and a `/knowledge-spaces` web management page.
- Routed user uploads to `main_source`, daily recommendation papers to `daily_source`, and daily recommendation runs to `daily_analysis`.
- Changed daily recommendation ingest to use explicit per-paper `parse_mode` selection; source-only ingest is supported.
- Prevented daily recommendation Dify sync from falling back to the main research dataset when daily-specific Dify datasets are empty.
- Updated the daily recommendation UI so Chinese and English abstracts are expanded by default.
- Completed the remaining redesign steps:
  editable knowledge-space metadata, editable item notes/sync status, per-item Dify resync, daily recommendation promotion to main research spaces, and multi-dataset analysis Dify sync keyed by `(run_id, dataset_id)`.
- Added web controls for saving space configuration, saving item notes, retrying sync, and promoting daily recommendations to the main library.
- Verified with:
  `.venv/bin/python -m pytest tests/test_knowledge_spaces.py tests/test_dify_sync.py tests/test_daily_recommendations.py -q`,
  `.venv/bin/python -m ruff check ...`,
  and `npm run build`.

- Added planning document `方案/daily-recommendation-knowledge-base-redesign-plan.md` for:
  daily recommendation source/analysis knowledge spaces, web-side move/copy/remove/resync operations, explicit parse-mode selection during daily ingest, and full default abstract display.

- Broadened the topic design from medical-only CLIP/SAM/DINO variants to the user's intended five-track layout:
  medical image deep learning, CLIP prompt learning, SAM segmentation, DINO self-supervised learning, and CLIP model design/transfer.
- Kept medical imaging as one broad domain topic while allowing CLIP prompt learning, SAM segmentation, and DINO self-supervised work from general vision, remote sensing, video, open-vocabulary, and other relevant directions.
- Added tests to ensure generic CLIP prompt learning, SAM segmentation, and DINO self-supervised papers pass without requiring medical keywords.

- Replaced broad AI security/VLM default topics with focused medical-imaging topics:
  medical image deep learning, medical CLIP prompt learning, medical SAM segmentation, medical DINO self-supervised learning, and CLIP model design/transfer.
- Updated default-topic synchronization so built-in topic definitions are refreshed in SQLite and old built-in topics are disabled.
- Isolated arXiv refresh errors by topic and returned structured `errors` in refresh responses.
- Improved frontend refresh/error messages so upstream API failures are visible without surfacing only `API 500`.
- Verified with backend daily tests and frontend production build.
