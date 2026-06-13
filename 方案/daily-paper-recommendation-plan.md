# 每日论文推荐页面方案

## 结论

每日论文推荐应实现为“候选池 + 手动解读入库”功能：系统每日抓取、筛选、翻译并展示候选论文，但默认不进入本地论文库和知识库；只有用户点击“解读并入库”后，才下载 PDF、运行 LLM 解读并纳入本地知识库。

## 核心目标

- 推荐要恰当：宁可少推荐，也不要把明显无关论文推到页面上。
- 候选和知识库分离：每日推荐结果只是候选，不污染 `papers`、知识卡片、Dify 或本地长期知识资产。
- 翻译优先使用 DeepLX：标题和摘要翻译必须复用现有 `translation_cache.translate_text` / `/api/translator/translate` 能力。
- LLM 调用受控：LLM 只用于少量边界样本相关性复核，以及用户手动触发的整篇 PDF 解读。

## 不采用 `cv-arxiv-daily` 原始检索逻辑的原因

`cv-arxiv-daily` 的核心逻辑是把同一主题下的关键词用 `OR` 拼接后按提交时间排序。这会导致：

- 短词和缩写误召回严重，例如 `SAM`、`DINO`、`CLIP`、`MaPLe` 会命中大量非目标领域论文。
- 缺少 arXiv 分类约束，容易混入物理、天文、数学等无关类别。
- 排序按最新而非相关性，主题相关度弱的论文可能排在前面。
- 没有标题/摘要层面的正负关键词过滤和用户反馈闭环。

本项目只借鉴它的“每日定时抓取 + 主题配置”思路，不复用其宽松 OR 检索。

## 推荐管线

### 1. 主题配置

每个主题使用结构化配置，而不是简单关键词列表。

```yaml
topics:
  - id: prompt_learning_vlm
    name: Vision-Language Prompt Learning
    name_zh: 视觉语言模型提示学习
    arxiv_categories:
      - cs.CV
      - cs.LG
      - cs.AI
    must:
      any:
        - ["CLIP", "prompt"]
        - ["vision-language", "prompt"]
        - ["test-time", "prompt", "vision"]
    should:
      - prompt tuning
      - prompt learning
      - test-time adaptation
      - domain adaptation
      - vision-language model
    exclude:
      - quantum
      - black hole
      - lattice
      - astrophysics
      - maple leaf
    min_score: 0.68
    llm_review_band:
      low: 0.58
      high: 0.72
```

规则含义：

- `arxiv_categories`：硬过滤，候选必须属于允许类别。
- `must.any`：至少满足一组强条件，避免单个缩写独立命中。
- `should`：用于加分。
- `exclude`：硬排除或强降权。
- `min_score`：进入页面展示的最低分。
- `llm_review_band`：只有分数落在不确定区间时才允许调用 LLM 复核。

### 2. 候选召回

召回使用 arXiv Atom API + `httpx`，不新增 `arxiv` 包依赖。

召回查询应尽量包含：

- arXiv 分类限制，例如 `cat:cs.CV OR cat:cs.LG OR cat:cs.AI`。
- 主题核心词组合，不允许只用短缩写做独立查询。
- 最近时间窗口，默认 1-3 天，可配置。

召回结果只写入每日推荐候选表，不写入 `papers`。

### 3. 强过滤

过滤顺序：

1. `primary_category` 或 `categories` 必须命中主题允许类别。
2. 标题和摘要必须满足至少一组 `must.any`。
3. 命中 `exclude` 的候选直接排除，或在可配置情况下强降权。
4. 已被用户标记为“不相关”的相似主题、相同 arXiv ID 或相同标题候选降权/屏蔽。

### 4. 打分排序

推荐分数建议由规则分组成，不默认调用 LLM。

```text
score =
  category_score * 0.25
  + must_score * 0.30
  + should_score * 0.20
  + abstract_focus_score * 0.15
  + recency_score * 0.05
  + feedback_score * 0.05
```

说明：

- `category_score`：类别匹配强度。
- `must_score`：强条件满足情况。
- `should_score`：相关词覆盖度。
- `abstract_focus_score`：标题/摘要中目标主题词密度和位置。
- `recency_score`：近期论文轻微加分，不主导排序。
- `feedback_score`：用户历史反馈带来的加权。

### 5. LLM 复核边界

LLM 只在以下情况下用于推荐阶段：

- 规则分数落在 `llm_review_band`。
- 候选没有命中明显排除词。
- 每日 LLM 复核数量不超过配置上限，例如 `DAILY_RECOMMENDATION_LLM_REVIEW_LIMIT=20`。

LLM 复核只输出结构化结果：

```json
{
  "relevant": true,
  "confidence": 0.82,
  "reason": "The paper studies test-time prompt adaptation for vision-language models."
}
```

禁止在推荐阶段用 LLM 做批量翻译、长摘要生成或整篇解读。

## 翻译策略

标题和摘要翻译默认使用 DeepLX。

实现要求：

- 后端服务直接复用 `app.services.translation_cache.translate_text`。
- 翻译结果写入现有 `translation_cache`，并在每日推荐表中保存当前展示快照和状态。
- 标题和摘要可以分开翻译，便于缓存命中。
- DeepLX 未配置或失败时，页面展示英文原文，并显示翻译状态为 `skipped` 或 `failed`。
- 不允许把标题/摘要常规翻译交给 LLM。

推荐展示字段：

- `title_en`
- `title_zh`
- `abstract_en`
- `abstract_zh`
- `title_translation_status`
- `abstract_translation_status`

## 手动解读入库流程

用户点击“解读并入库”后才进入本地知识链路。

流程：

1. 根据 arXiv ID 获取 PDF URL。
2. 下载 PDF 到临时或正式论文目录。
3. 创建 `papers` 记录。
4. 将该候选状态改为 `ingested`，记录关联 `paper_id`。
5. 触发现有解析和 LLM 解读流程，可默认使用 `auto` 或让用户选择 `snap/lens/sphere`。
6. 解读结果、知识卡片、Dify/本地知识库同步沿用现有论文库流程。

失败处理：

- PDF 下载失败：候选仍保留，状态为 `ingest_failed`，显示错误信息。
- 解析失败：论文可进入论文库，但状态提示解析失败，允许重试。
- LLM 解读失败：不回滚论文入库，记录运行失败并允许重试。

## 前端页面设计

路由：`/daily`

导航：在 `AI4Sec/frontend/src/app/client-layout.tsx` 中新增“每日推荐”。

页面区域：

- 顶部：日期、主题、推荐数量、刷新状态。
- 筛选栏：主题、日期、状态、最低分、仅看未处理、搜索。
- 论文列表：中英文标题、中英文摘要、作者、arXiv 分类、提交/更新时间、推荐分数、推荐理由。
- 操作按钮：`感兴趣`、`不相关`、`忽略`、`解读并入库`、`打开 arXiv`、`打开 PDF`。
- 状态标识：`candidate`、`interested`、`dismissed`、`irrelevant`、`ingesting`、`ingested`、`ingest_failed`。

展示原则：

- 默认显示中文标题；英文标题紧随其后或可折叠显示。
- 摘要默认显示中文摘要；英文摘要保留可展开。
- 翻译失败时不阻塞展示。
- 推荐理由优先来自规则命中，例如“命中 cs.CV + CLIP/prompt 强条件 + 摘要包含 test-time adaptation”。

## 后端模块

新增文件建议：

- `AI4Sec/backend/app/api/daily.py`
- `AI4Sec/backend/app/services/daily_recommendations.py`
- `AI4Sec/backend/app/services/daily_recommendation_scoring.py`
- `AI4Sec/backend/app/services/arxiv_client.py`
- `AI4Sec/backend/app/services/daily_recommendation_ingest.py`

职责边界：

- `daily.py`：API 路由和请求/响应模型绑定。
- `arxiv_client.py`：arXiv Atom API 请求与解析。
- `daily_recommendations.py`：每日刷新、缓存、列表查询、状态更新。
- `daily_recommendation_scoring.py`：规则过滤、打分、LLM 复核入口。
- `daily_recommendation_ingest.py`：手动入库，桥接现有论文下载、解析、运行和知识库流程。

避免把这些逻辑继续塞进 `papers.py` 或 `papers/page.tsx`。

## API 设计

```text
GET  /api/daily/topics
GET  /api/daily/items?date=2026-06-07&topic_id=...&status=...
POST /api/daily/refresh
POST /api/daily/items/{item_id}/feedback
POST /api/daily/items/{item_id}/ingest
GET  /api/daily/items/{item_id}/ingest-status
```

`feedback` 请求：

```json
{
  "action": "interested | irrelevant | dismissed",
  "note": ""
}
```

`ingest` 请求：

```json
{
  "mode": "auto",
  "language": "zh",
  "llm_model": "",
  "collection_id": ""
}
```

## 数据库设计

```sql
CREATE TABLE IF NOT EXISTS daily_recommendation_topics (
    topic_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    name_zh TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS daily_recommendation_items (
    item_id TEXT PRIMARY KEY,
    arxiv_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    title_en TEXT NOT NULL DEFAULT '',
    title_zh TEXT NOT NULL DEFAULT '',
    abstract_en TEXT NOT NULL DEFAULT '',
    abstract_zh TEXT NOT NULL DEFAULT '',
    authors_json TEXT NOT NULL DEFAULT '[]',
    primary_category TEXT NOT NULL DEFAULT '',
    categories_json TEXT NOT NULL DEFAULT '[]',
    published_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT '',
    arxiv_url TEXT NOT NULL DEFAULT '',
    pdf_url TEXT NOT NULL DEFAULT '',
    score REAL NOT NULL DEFAULT 0.0,
    score_detail_json TEXT NOT NULL DEFAULT '{}',
    reason TEXT NOT NULL DEFAULT '',
    title_translation_status TEXT NOT NULL DEFAULT 'pending',
    abstract_translation_status TEXT NOT NULL DEFAULT 'pending',
    llm_review_status TEXT NOT NULL DEFAULT 'not_needed',
    llm_review_json TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'candidate',
    linked_paper_id TEXT NOT NULL DEFAULT '',
    error_msg TEXT NOT NULL DEFAULT '',
    fetched_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(arxiv_id, topic_id, fetched_date)
);

CREATE INDEX IF NOT EXISTS idx_daily_items_date_topic
    ON daily_recommendation_items(fetched_date, topic_id, score DESC);

CREATE INDEX IF NOT EXISTS idx_daily_items_status
    ON daily_recommendation_items(status, fetched_date DESC);

CREATE TABLE IF NOT EXISTS daily_recommendation_feedback (
    feedback_id TEXT PRIMARY KEY,
    item_id TEXT NOT NULL REFERENCES daily_recommendation_items(item_id),
    arxiv_id TEXT NOT NULL DEFAULT '',
    topic_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

迁移要求：

- 表创建必须放入 `schema.sql`，并在 `database.py` 中保持 legacy-safe 初始化。
- 所有新增索引使用 `CREATE INDEX IF NOT EXISTS`。
- 不修改现有 `papers` 表语义。

## 配置项

新增环境变量建议：

```text
DAILY_RECOMMENDATION_ENABLED=true
DAILY_RECOMMENDATION_LOOKBACK_DAYS=3
DAILY_RECOMMENDATION_MAX_RESULTS_PER_TOPIC=80
DAILY_RECOMMENDATION_MIN_SCORE=0.68
DAILY_RECOMMENDATION_LLM_REVIEW_ENABLED=true
DAILY_RECOMMENDATION_LLM_REVIEW_LIMIT=20
DAILY_RECOMMENDATION_TRANSLATE_ENABLED=true
DAILY_RECOMMENDATION_TRANSLATE_TARGET=zh
```

DeepLX 继续使用现有配置：

```text
DEEPLX_API_BASE
DEEPLX_API_KEY
DEEPLX_TIMEOUT_SECONDS
```

## 实施阶段

### Phase 1：后端候选池与规则推荐

- 新增 arXiv 客户端。
- 新增主题配置、候选表、反馈表。
- 实现召回、强过滤、规则打分、缓存。
- 单元测试覆盖短缩写误召回、分类过滤、负关键词排除。

验收标准：

- 无关类别论文不会进入候选。
- `SAM/DINO/CLIP/MaPLe` 单独命中不会通过强过滤。
- 候选不会写入 `papers`。

### Phase 2：DeepLX 翻译与展示 API

- 每日候选标题/摘要调用 `translate_text`。
- 翻译状态写入推荐 item。
- 列表 API 返回中英文标题和摘要。

验收标准：

- DeepLX 可用时返回中文标题/摘要。
- DeepLX 失败时展示英文原文且状态准确。
- 推荐阶段不调用 LLM 做翻译。

### Phase 3：前端 `/daily` 页面

- 新增导航和页面。
- 实现筛选、列表、状态、反馈操作。
- 展示规则推荐理由和翻译状态。

验收标准：

- 用户能查看每日候选，但论文库数量不变化。
- 用户反馈会改变候选状态。
- 页面可以清楚区分候选、已忽略、已入库。

### Phase 4：手动解读并入库

- 实现 `POST /api/daily/items/{item_id}/ingest`。
- 下载 PDF、创建论文、触发现有解读流程。
- 记录 `linked_paper_id` 和入库状态。

验收标准：

- 只有点击入库后才创建 `papers` 记录。
- 入库后可在现有论文页看到对应论文。
- LLM 只在入库解读流程中常规使用。

### Phase 5：边界样本 LLM 复核

- 对规则分数不确定区间启用可选 LLM 复核。
- 限制每日调用次数。
- 保存结构化复核结果。

验收标准：

- LLM 复核可关闭。
- 超出每日上限后自动退回规则判断。
- LLM 复核不参与翻译和整篇解读之外的重型任务。

## 测试重点

- 推荐恰当性：
  - `MaPLe` 不应召回 maple-leaf lattice。
  - `SAM` 不应召回与 Segment Anything 无关的论文。
  - 非 `cs.CV/cs.LG/cs.AI/eess.IV` 的候选默认排除。
- 翻译边界：
  - DeepLX 成功、失败、未配置三种状态。
  - 缓存命中时不重复请求 DeepLX。
  - 推荐阶段不调用 LLM 翻译。
- 入库边界：
  - 刷新每日推荐不会新增 `papers`。
  - 只有手动 ingest 才新增 `papers`。
  - ingest 失败不会删除候选。
- API 合约：
  - 前后端类型一致。
  - 状态枚举稳定。
  - 重复刷新同一天同主题不会重复插入。

## 最终验收标准

- `/daily` 可以展示经过筛选的每日论文候选。
- 推荐结果明显减少无关领域论文。
- 候选论文默认不进入论文库或知识库。
- 标题和摘要优先由 DeepLX 翻译，并有缓存和失败回退。
- 用户手动选择后，系统才下载 PDF、LLM 解读并纳入本地知识库。
- LLM 使用边界清晰、可配置、可审计。
