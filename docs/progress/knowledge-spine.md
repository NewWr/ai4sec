# Knowledge Spine

## 2026-06-13

- Added `方案/research-second-brain-hardening-plan.md` as the post-closure hardening plan for turning the current MVP loop into a research-grade second brain, with priorities for Dify-independent local QA, stronger evidence chains, semantic synthesis verification, Gap lifecycle management, writing upgrades, feedback loops, and health metrics.
- Implemented the P0 Evidence -> Claim service invariant for `方案/knowledge-spine-full-lifecycle-research-platform-plan.md`:
  fact cards now resolve anchored `source_quote` values into `research_evidence_items` and bind through `research_evidence_cards` during manual creation, AI creation, and status promotion.
- Tightened verified fact-card validation so a raw `source_quote` alone is not enough; verified factual cards require same-paper evidence IDs unless `allow_untraceable` is explicitly set.
- Kept startup backfill behavior for legacy cards and added tests for automatic bridge creation, promotion-time anchoring, and legacy demotion.
- Fixed `knowledge_assets._like()` to be Python 3.10-compatible for ruff parsing.
- Implemented the first P1 card-quality rule:
  AI card generation no longer fills `why_useful`, `use_case`, `next_action`, `expected_output`, or `risk_or_caveat` with template defaults; candidates missing value fields stay draft with `missing_value_fields`.
- Routed AI `question` / `idea` candidates into `research_gaps` as gap seeds instead of adding them to the flat knowledge-card list.
- Injected matching `knowledge_spaces.research_profile` values into the card-generation context for papers that belong to profiled spaces.
- Implemented P2 synthesis foundation:
  verified action cards are clustered into `asset_level='synthesis'` cards with `supporting_card_ids`, `supporting_paper_ids`, and `evidence_strength='multi-paper'`; discovery rebuilds synthesis cards and verified-card promotion triggers a lightweight rebuild.
- Implemented P3 graph-first corpus QA:
  `/library/ask` now fuses local verified knowledge-card/evidence records before Dify results and returns source metadata including `source_type`, `card_id`, `paper_id`, and `page`.
- Implemented P4 writing/export foundation:
  added APIs for related-work snippet composition, cross-paper comparison tables, and Obsidian-style Markdown export.
- Added frontend pages `/synthesis` and `/writing`, plus navigation entries for synthesis/gap review and writing/export workflows.
- Completed the remaining P3 behavior loop:
  daily recommendation refresh now builds a local behavior profile from read papers, verified cards, interested/ingested daily items, and Q&A questions; matching terms add a bounded score boost and are stored in `score_detail`.
- Added deterministic research-gap hit tracking for daily recommendations:
  new papers are matched against existing `research_gaps`, recommendation details record `matched_gaps`, and gaps persist `hit_by_paper_ids` with `coverage_status='partially_covered'` when a new recommendation covers an open direction.
- Tightened P1 two-stage extraction plumbing:
  Logic Lens now persists section-scoped contexts with target card types, and the card generator prioritizes those `SECTION_CONTEXT` blocks before falling back to report markdown / block excerpts.
- Extended P4 external export:
  `/papers/export/zotero-csl-json` now emits Zotero-importable CSL JSON, and `/writing` exposes a Zotero CSL export button alongside Markdown, BibTeX, RIS, and Obsidian.
- Added the P1 deterministic critique gate:
  AI card candidates now receive critique flags/scores, low-quality or profile-unreferenced candidates remain draft, and `knowledge_card_generations.critique_summary_json` records the critique pass/low/filter counts for frontend observability.
- Added the P2 deterministic relation verifier:
  `research_discovery` now verifies rule-recalled relation candidates before persistence, writes `verifier_version='rule_verifier_v1'`, upgrades exact dataset/problem/method evidence matches to `verified`, keeps transfer hypotheses and under-specified conflicts in `needs_more_evidence`, and records counter-evidence IDs for review.
- Added the P2 hybrid verifier path:
  `RESEARCH_DISCOVERY_LLM_VERIFY_ENABLED` enables a bounded LLM verification pass over rule-recalled relation candidates; accepted JSON decisions can update status, confidence, positive/negative checks, counter-evidence IDs, and `verifier_version='llm_relation_verifier_v1'`, while missing/failed LLM verification falls back to deterministic rule verification.
- Added P2 local incremental rediscovery:
  verified action-card creation or promotion now rebuilds synthesis cards and runs `rebuild_discovery_for_card(card_id)` over the promoted card's related verified-card paper scope without requiring the full `/papers/discovery` batch.
- Updated synthesis frontend/API typing so relation status can include `verified`, and the `/synthesis` conflict board shows verifier version plus negative checks.
- Updated synthesis and papers frontend relation status types through a shared `DiscoveryRelationStatus`, and `/synthesis` now exposes source/target paper links plus evidence IDs for relation review.
- Added verifier tests covering exact dataset verification, LLM verifier overlay, LLM rejection, transfer-review status, conflict counter-evidence, and verified-card promotion triggering incremental relation discovery.
- Verified with:
  `.venv/bin/python -m pytest tests/test_knowledge_synthesis.py tests/test_corpus_qa.py tests/test_qa_retrieval.py tests/test_knowledge_assets.py tests/test_knowledge_card_generator.py tests/test_evidence_store.py tests/test_paper_library.py tests/test_daily_recommendations.py tests/test_lens_segmented.py tests/test_research_discovery.py -q`
  (56 tests, final closure rerun passed)
  and
  `.venv/bin/python -m ruff check app/services/knowledge_synthesis.py app/services/corpus_qa.py app/services/knowledge_assets.py app/services/knowledge_card_generator.py app/services/research_discovery.py app/services/recommendation_behavior.py app/services/daily_recommendations.py app/services/daily_recommendation_scoring.py app/workflows/lens_subgraph.py app/api/knowledge.py app/api/papers.py app/api/daily.py app/db/database.py app/models/schemas.py app/config.py tests/test_knowledge_synthesis.py tests/test_corpus_qa.py tests/test_knowledge_assets.py tests/test_knowledge_card_generator.py tests/test_daily_recommendations.py tests/test_lens_segmented.py tests/test_research_discovery.py`,
  plus `npm run build`; final closure reruns passed.
- Restarted the formal Docker deployment through `/media/dc/M2_DATA/Paper_read/start_ai4sec.sh`:
  the script now stops the temporary Next.js dev server on 3003, stops/recreates AI4Sec compose services, starts only one formal `scholar-frontend` / `scholar-backend` / `ai4sec-dify-proxy` set plus one `ai4sec-dify-sync`, and verifies `/`, `/synthesis`, `/writing`, and `/api/models`.
- Added patch-image fallback Dockerfiles for the current Docker Hub mirror failure:
  when the daemon's mirror returns `403 Forbidden` for `python:3.13-slim` or `node:22-alpine`, the script reuses existing dependency-layer images and copies current backend code plus local Next.js standalone build output into fresh formal images.
- Verified the restarted formal instance:
  `http://127.0.0.1:3001/`, `/synthesis`, and `/writing` return HTTP 200; `http://127.0.0.1:8001/api/models` returns HTTP 200; only `scholar-frontend`, `scholar-backend`, `ai4sec-dify-proxy`, and `ai4sec-dify-sync` remain under AI4Sec-related containers.
- Fixed and verified `/settings` LLM connection testing for the formal Docker deployment:
  backend now runs on host networking with host proxy environment variables, frontend rewrites target `host.docker.internal:8001`, and the connection probe tries Responses with reasoning, plain Responses, then Chat Completions. Runtime verification through both `http://127.0.0.1:8001/api/settings/llm/test` and `http://127.0.0.1:3001/api/settings/llm/test` returned `ok: true` for the saved `gpt-5.5` config.
- Revalidated the targeted LLM/settings surface with:
  `.venv/bin/python -m pytest tests/test_llm_service.py tests/test_settings_api.py -q`
  and frontend `npm run build`.
- Updated and verified `/media/dc/M2_DATA/Paper_read/start_ai4sec.sh` so the formal startup path first runs the full vendored Dify stack from `AI4Sec/dify-rag/docker` with `postgresql,weaviate,collaboration` profiles, then starts AI4Sec `dify-proxy/backend/frontend` and `ai4sec-dify-sync`.
  Runtime verification passed for `http://127.0.0.1:3080/console/api/setup`, `http://127.0.0.1:3002/api/datasets`, `http://127.0.0.1:8001/api/models`, `http://127.0.0.1:3001/`, `/synthesis`, and `/writing`.
- Implemented `方案/research-second-brain-hardening-plan.md` P0 local knowledge independent QA:
  added `app/services/local_graph_retrieval.py` as a Dify-independent retrieval port over verified cards, evidence, relations, gaps, and writing snippets; `/library/ask` now accepts `graph_only`, skips the Dify enabled gate, and automatically falls back to local graph records if Dify is disabled or raises `DifyError`.
- Updated `/library` ask UI so question answering remains usable when Dify is unconfigured, with an explicit local-graph-only scope and source labels that distinguish Dify documents from local graph/snippet/relation sources.
- Verified P0 with:
  `.venv/bin/python -m pytest tests/test_corpus_qa.py -q`,
  `.venv/bin/python -m ruff check app/services/local_graph_retrieval.py app/services/corpus_qa.py app/api/library.py app/models/schemas.py tests/test_corpus_qa.py`,
  `.venv/bin/python -m pytest tests/test_corpus_qa.py tests/test_dify_client.py tests/test_knowledge_assets.py tests/test_knowledge_synthesis.py tests/test_research_discovery.py -q`,
  and frontend `npm run build`.
- Implemented `方案/research-second-brain-hardening-plan.md` P1-P5 in one pass:
  writing snippets now carry multiple `source_card_ids`, `evidence_ids`, paragraph plans, trace mode, and traceable/clean Markdown export; comparison tables merge multiple evidence-backed cards and show conflict/missing markers.
- Strengthened research discovery semantics:
  relation edges now persist `comparability_json` for task/dataset/metric/setting/claim direction, rule conflicts stay `needs_more_evidence` unless LLM/manual review confirms them, and `/synthesis` displays comparability checks.
- Upgraded Gap lifecycle:
  gaps now store research question, target task, constraints, baseline plan, contribution, target venue, related cards/synthesis, and append-only history; API/frontend status flow covers reviewing, pursue, experiment_planned, rejected, covered, and legacy states.
- Added feedback and observability:
  `research_asset_events` records card/snippet/export/comparison/health/gap events; `library_qa_events` records graph/Dify/source hit counts; local card listing uses event counts as a ranking boost; `/health` exposes second-brain quality metrics including evidence gaps, weak synthesis, draft backlog, local QA graph hit ratio, export citation missing rate, and isolated evidence.
- Updated frontend `/writing`, `/synthesis`, and `/health` for trace metadata, clean/traceable export, relation comparability, Gap lifecycle controls, and expanded health metrics.
- Verified P1-P5 with:
  `.venv/bin/python -m pytest tests/test_research_discovery.py tests/test_knowledge_assets.py tests/test_corpus_qa.py -q` (23 tests),
  `.venv/bin/python -m pytest tests/test_dify_client.py tests/test_knowledge_synthesis.py tests/test_research_discovery.py tests/test_corpus_qa.py tests/test_knowledge_assets.py -q` (35 tests),
  `.venv/bin/python -m ruff check app/db/database.py app/services/knowledge_assets.py app/services/research_discovery.py app/services/corpus_qa.py app/services/recommendation_behavior.py app/services/http_clients.py app/api/knowledge.py app/api/papers.py app/models/schemas.py tests/test_research_discovery.py tests/test_knowledge_assets.py tests/test_corpus_qa.py`,
  and frontend `npm run build`.
- Reset the local paper-reading state so the platform can be reused from a clean library:
  backed up the formal Docker database, dev databases, Dify sync state, PDFs, MinerU output, uploads, and daily-download payloads under `backups/reset-reading-state-20260613-175721`; then cleared local papers, parse blocks, hierarchy nodes, runs, run outputs/progress, paper notes/annotations, paper collections, display/translation cache, Dify sync mappings, knowledge-space items, knowledge cards, evidence, relations, gaps, writing snippets, QA/asset events, daily recommendation items/feedback/topics, and standalone `ai4sec-dify-sync` state.
- Preserved code, `.env`, LLM runtime config, publication-rank cache, Dify datasets/proxy configuration, and progress/plan documents; default knowledge spaces and daily topics are re-created lazily by their APIs after reset.
- Verified reset state on the formal deployment:
  `http://127.0.0.1:8001/api/papers` and `/api/knowledge/cards` return `[]`; `/api/papers/discovery` reports zero papers/evidence/relations/gaps; `/api/health/knowledge` reports zero issues; `/api/knowledge-spaces` returns the four default spaces with `item_count=0`; `/api/daily/topics` re-created the five default topics; frontend `/`, `/papers`, and `/knowledge-spaces` return HTTP 200.
- Improved the synthesis/writing workflow UI:
  `/synthesis` Gap cards in the idea board now expose a detail dialog via a "放大查看" action, showing full description, hypothesis, research question, target task, constraints, baseline plan, contribution, target venue, minimum experiment, evidence/card/paper trace IDs, signals, history, scores, and status actions without relying on truncated card text.
- Reworked `/writing` cross-paper comparison from manual `paper_id` entry into a paper selector:
  the page now loads `/api/papers`, supports searchable multi-select by title/title_zh/venue/year/citation/status/id, shows selected papers as removable items, can add paper IDs from selected cards, and keeps raw `paper_id` paste input only as an advanced fallback.
- Verified the frontend change with `npm run build`, refreshed the formal `scholar-frontend` container from the rebuilt standalone output, and confirmed `http://127.0.0.1:3001/synthesis`, `/writing`, and `/` return HTTP 200 with the new frontend chunks.
- Fixed the remaining Gap detail truncation issue:
  discovery responses now expose `full_description` by joining `research_evidence_items` back to the original `blocks.text`; compact cards continue using the shortened `description`, while the `/synthesis` "放大查看" dialog renders `full_description || description`.
- Verified the full-description contract with:
  `.venv/bin/python -m pytest tests/test_research_discovery.py -q` (8 tests),
  `.venv/bin/python -m ruff check app/services/research_discovery.py app/models/schemas.py tests/test_research_discovery.py`,
  frontend `npm run build`,
  rebuilt/recreated formal backend and frontend containers, and runtime checks showing the first Gap has `description` length 170 and `full_description` length 1174 from the source block; `/synthesis`, `/writing`, and `/` return HTTP 200.
- Implemented `方案/frontend-chinese-localization-plan.md` foundation and priority pages:
  added centralized frontend enum/status label mappings in `frontend/src/lib/labels.ts`, switched the default frontend locale to Chinese, and localized user-facing labels for writing exports, synthesis/gap review, knowledge cards, knowledge spaces, reading assets, paper discovery relations, library source types, Dify document statuses, and PDF load errors while preserving backend enum/API values.
- Verified the localization pass with frontend `npm run build`; targeted scans no longer show the plan's high-priority user-facing strings such as `Traceable Markdown`, `Clean Markdown`, raw `supporting cards`, `confidence=`, `Unknown paper`, or `Failed to load PDF`.
