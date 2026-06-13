# 每日推荐知识库隔离与入库流程改造方案

## 结论

每日论文推荐应从“候选列表 + 可选导入论文库”升级为“候选浏览区 + 推荐原文知识库 + 推荐解读知识库”的隔离体系：用户主动上传论文仍进入主论文库和主知识库；每日推荐论文只有在用户确认后才进入推荐专用知识库，且原文解析结果和解读报告分别收纳，避免污染用户高置信研究库。

## Skill 协同

- `long-term-scholar-knowledge`：用于约束长期知识库边界、Dify/本地知识资产分离、进度文档维护。
- `spec-driven-develop`：用于这类跨后端、前端、数据库、同步链路的结构化改造方案，不在本轮直接编码。

## 当前问题

1. 知识库边界不清：用户上传论文天然代表强相关、高优先级；每日推荐论文只是候选，可能只是浏览兴趣，不能默认混入同一知识空间。
2. 现有 Dify 同步只有主原文 dataset 和分析报告 dataset 两类配置，缺少每日推荐专用的原文/解读收纳目标。
3. `解读并入库` 使用页面顶部统一模式，默认 `auto`，容易在用户未确认解析方式时启动不合适的流程。
4. 每日推荐卡片中文摘要使用 `line-clamp-6`，英文摘要默认折叠，导致浏览判断信息不完整。
5. 网页端缺少对知识库内容的移动、改名、重新归类、跨库迁移、同步状态修复等管理入口。

## 目标架构

### 三类知识空间

| 知识空间 | 内容来源 | 可信度假设 | 用途 | 默认同步目标 |
|---|---|---:|---|---|
| 主研究知识库 | 用户上传、本地主动导入 | 高 | 长期研究、写作、复现、问答 | `DIFY_DEFAULT_DATASET_ID` / `DIFY_ANALYSIS_DATASET_ID` |
| 每日推荐原文知识库 | 每日推荐中用户确认导入的 PDF 解析结果 | 中 | 浏览、主题追踪、后续筛选 | 新增 `DAILY_RECOMMENDATION_SOURCE_DATASET_ID` |
| 每日推荐解读知识库 | 每日推荐中用户触发的 Snap/Lens/Sphere/Auto 解读报告 | 中 | 快速比较、研究线索发现、判断是否转正 | 新增 `DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID` |

本地也要有同样的逻辑隔离：不能只依赖 Dify dataset。建议新增本地 `knowledge_spaces` 抽象，把 Dify dataset 作为外部同步配置。

## 数据模型设计

### 新增表：`knowledge_spaces`

```sql
CREATE TABLE IF NOT EXISTS knowledge_spaces (
    space_id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    name_zh TEXT NOT NULL DEFAULT '',
    space_type TEXT NOT NULL DEFAULT '', -- main | daily_source | daily_analysis | custom
    description TEXT NOT NULL DEFAULT '',
    description_zh TEXT NOT NULL DEFAULT '',
    dify_dataset_id TEXT NOT NULL DEFAULT '',
    is_system INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

系统默认创建：

- `main_source`：主研究原文知识库。
- `main_analysis`：主研究解读知识库。
- `daily_source`：每日推荐原文知识库。
- `daily_analysis`：每日推荐解读知识库。

### 新增表：`knowledge_space_items`

```sql
CREATE TABLE IF NOT EXISTS knowledge_space_items (
    space_id TEXT NOT NULL REFERENCES knowledge_spaces(space_id),
    item_kind TEXT NOT NULL DEFAULT '', -- paper | run | dify_document | card | snippet
    item_id TEXT NOT NULL DEFAULT '',
    paper_id TEXT NOT NULL DEFAULT '',
    run_id TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT '', -- upload | daily | manual | generated
    sync_status TEXT NOT NULL DEFAULT 'pending',
    dify_document_id TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (space_id, item_kind, item_id)
);
```

作用：

- 支持同一 `paper_id` 同时出现在多个知识空间。
- 支持网页端移动：本质是更新 `space_id` 或复制/删除关联记录。
- 支持推荐论文后续“转正”：从 `daily_*` 移动到 `main_*`，并保留来源标记。

### 扩展现有同步表

现有 `dify_syncs` 已有 `(paper_id, dataset_id)` 主键，足够支持多个 dataset；`analysis_dify_syncs` 当前以 `run_id` 为主键，不利于同一 run 同步到多个 dataset。

建议将分析同步改为兼容多 dataset：

```sql
CREATE TABLE IF NOT EXISTS analysis_dify_syncs_v2 (
    run_id TEXT NOT NULL REFERENCES runs(run_id),
    paper_id TEXT NOT NULL REFERENCES papers(paper_id),
    dataset_id TEXT NOT NULL DEFAULT '',
    dify_document_id TEXT DEFAULT '',
    source_hash TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    error_msg TEXT DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (run_id, dataset_id)
);
```

也可以先做低风险兼容方案：保留旧表，新增 `analysis_dify_sync_targets`，避免大迁移。

## 后端服务设计

### `knowledge_spaces.py`

新增服务模块，负责：

- 初始化系统知识空间。
- 列出知识空间、统计 paper/run/document 数量。
- 把 paper/run/card/snippet 加入指定空间。
- 移动或复制条目。
- 根据 `space_id` 选择本地查询范围和 Dify dataset。
- 修复同步状态、重试同步。

避免把逻辑继续塞进 `papers.py`、`library.py` 或 `daily_recommendations.py`。

### 每日推荐入库流程

`POST /api/daily/items/{item_id}/ingest` 改为显式参数：

```json
{
  "parse_mode": "snap | lens | sphere | auto",
  "source_space_id": "daily_source",
  "analysis_space_id": "daily_analysis",
  "collection_id": "",
  "start_run": true,
  "language": "zh",
  "llm_model": ""
}
```

流程：

1. 下载 PDF，创建 `papers` 记录，但 `source_type=daily`。
2. 将 paper 加入 `daily_source`。
3. 解析 PDF 并把原文同步到 `daily_source` 对应 Dify dataset。
4. 根据用户选择的 `parse_mode` 启动 Snap/Lens/Sphere/Auto。
5. run 完成后将解读报告同步到 `daily_analysis`。
6. 页面显示两个同步状态：原文入库、解读入库。

默认模式建议：

- 不再默认自动运行快速洞察。
- 按钮改为“选择解析方式”，打开确认弹窗。
- 弹窗默认选中上一次用户使用的模式；无历史时默认 `Lens` 或不预选，要求用户确认。

### 转正流程

新增 API：

```text
POST /api/daily/items/{item_id}/promote
POST /api/knowledge-spaces/items/move
POST /api/knowledge-spaces/items/copy
POST /api/knowledge-spaces/items/remove
POST /api/knowledge-spaces/items/resync
```

`promote` 语义：

- 将每日推荐 paper 从 `daily_source` 复制或移动到 `main_source`。
- 将相关 run 从 `daily_analysis` 复制或移动到 `main_analysis`。
- 将论文 collection 从“推荐候选/未归类”移动到用户指定研究 collection。
- 保留 `daily_recommendation_items.linked_paper_id`，状态变为 `promoted` 或扩展字段 `promotion_status`。

## 前端设计

### 每日推荐页

1. 顶部移除全局解析模式下拉。
2. 每张论文卡片的“解读并入库”改为打开弹窗：
   - 解析方式：Snap / Lens / Sphere / Auto。
   - 原文知识库：默认“每日推荐原文知识库”。
   - 解读知识库：默认“每日推荐解读知识库”。
   - 是否同步到 Dify。
   - 是否只入库原文、不立即解读。
3. 卡片状态拆分显示：
   - 候选状态：candidate/interested/dismissed/irrelevant。
   - 原文状态：not_ingested/ingesting/ingested/source_sync_failed。
   - 解读状态：not_started/running/done/analysis_sync_failed。
4. 中文摘要和英文摘要默认展开：
   - 去掉 `line-clamp-6`。
   - 英文摘要不再放在默认关闭的 `details` 中。
   - 可增加“收起摘要”按钮，但默认完整展示。

### 知识库管理页

建议在 `/library` 增加“知识空间”维度，或新增 `/knowledge-spaces` 页面。

核心能力：

- 左侧：知识空间列表，包括主研究原文、主研究解读、每日推荐原文、每日推荐解读、自定义空间。
- 中间：空间内容列表，支持 paper/run/card/snippet/document 切换。
- 右侧：内容预览和元数据编辑。
- 操作：
  - 移动到其他知识空间。
  - 复制到其他知识空间。
  - 从当前空间移除。
  - 修改标题、备注、标签、collection。
  - 重试同步。
  - 将每日推荐内容“转正”到主研究知识库。

必须显示持久化失败，不能只在前端乐观更新。

## 配置项

新增环境变量：

```text
DAILY_RECOMMENDATION_SOURCE_DATASET_ID=
DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID=
DAILY_RECOMMENDATION_DEFAULT_SOURCE_SPACE=daily_source
DAILY_RECOMMENDATION_DEFAULT_ANALYSIS_SPACE=daily_analysis
DAILY_RECOMMENDATION_REQUIRE_PARSE_MODE_CONFIRM=true
```

兼容策略：

- 如果推荐专用 dataset 未配置，本地知识空间仍可用，Dify 同步状态显示 `skipped`。
- 不阻塞 PDF 入库和本地解读。
- 主研究库继续使用现有 `DIFY_DEFAULT_DATASET_ID` 和 `DIFY_ANALYSIS_DATASET_ID`。

## 实施阶段

### Phase 1：本地知识空间基础

- 新增 `knowledge_spaces` 和 `knowledge_space_items`。
- 初始化四个系统空间。
- 提供 list/add/move/copy/remove API。
- 测试覆盖初始化幂等、移动不丢引用、删除只删关联不删实体。

验收：

- 用户上传论文默认进入主研究空间。
- 每日推荐导入默认进入推荐空间。
- 同一 paper 可存在于多个空间。

### Phase 2：每日推荐入库流程改造

- 扩展 ingest 请求模型，显式传入 `parse_mode/source_space_id/analysis_space_id`。
- 后端把原文和解读分别写入对应空间。
- run 完成后按空间同步分析报告。
- 不再使用页面顶部全局默认模式。

验收：

- 点击“解读并入库”必须先确认解析方式。
- 推荐论文不会自动进入主研究知识库。
- 原文和解读可分别查询、分别重试同步。

### Phase 3：网页端知识空间管理

- 增加知识空间管理视图。
- 支持修改、移动、复制、移除、重试同步。
- 支持每日推荐内容转正。

验收：

- 可从每日推荐解读库移动到主研究解读库。
- 可从推荐原文库复制到主研究原文库。
- 操作失败时页面明确显示错误，并保持真实状态。

### Phase 4：每日推荐页面体验修复

- 摘要默认完整展示。
- 英文摘要默认展开。
- 卡片状态拆分显示原文/解读/同步状态。
- “解读并入库”弹窗支持解析方式和知识库选择。

验收：

- 中文摘要不再隐藏。
- 英文摘要无需点击即可阅读。
- 用户可单篇选择 Snap/Lens/Sphere/Auto。

## 风险与约束

- Dify dataset 管理能力有限时，本地知识空间必须先成为 source of truth。
- `analysis_dify_syncs` 当前以 `run_id` 为主键，若同一 run 要同步多个 dataset，需要迁移或新增目标表。
- 每日推荐论文如果未解析成功，仍应保留候选 item 和错误状态，不应污染主库。
- “移动”应默认移动知识空间关联，不物理删除 paper/run/card，避免误删原始证据。

## 建议优先级

P0：

- 本地知识空间表和 API。
- 每日推荐入库显式选择解析方式。
- 推荐原文/推荐解读两个默认空间。
- 摘要默认完整展示。

P1：

- 知识空间管理页面。
- Dify 推荐专用 dataset 同步。
- 每日推荐内容转正。

P2：

- 自定义知识空间。
- 批量移动、批量转正。
- 空间级检索和问答聚合策略。
