# AI4Sec 前端中文文案本地化方案

## 结论

当前前端需要做一次系统性的中文文案本地化，重点不是把零散英文词替换成中文，而是建立统一的中文术语、枚举值展示层和页面文案规范。项目已经有 `frontend/src/lib/i18n.tsx`，但覆盖范围主要集中在首页、上传、运行页和知识库基础检索；新增的知识卡片、综合、写作、知识空间、论文库管理等页面仍有大量硬编码英文和后端枚举直出。

本方案建议先建立统一的 `label` 映射层，再逐页替换用户可见文案，最后用扫描和页面走查验收。保留少量标准格式名和生态专名，例如 Markdown、BibTeX、RIS、Zotero、Dify、MinerU、DeepLX、API Key、Base URL。

## 目标

- 默认中文体验完整可用，用户不需要理解英文枚举、字段名或内部状态值。
- 统一核心术语，避免同一概念在不同页面出现“缺口 / gap / 创新点候选”“素材 / snippet / writing snippet”等混用。
- 将后端枚举值与前端展示文案解耦，避免 `verified`、`draft`、`related_work`、`conflicting_claim`、`needs_more_evidence` 等内部值直接显示。
- 保留英文模式名作为辅助识别，但中文名优先，例如“快速洞察（Insight Snap）”。
- 不改变业务逻辑、API 参数和数据库枚举，只调整展示层。

## 非目标

- 不重构后端枚举命名。
- 不修改数据库字段、API schema 或已有数据。
- 不翻译论文原文、LLM 生成正文或用户输入内容。
- 不强行翻译标准格式名、产品名和模型配置项。

## 当前问题清单

### 1. 硬编码英文文案

集中在以下页面：

- `frontend/src/app/writing/page.tsx`
  - `Traceable Markdown`、`Clean Markdown`
  - `related_work`、`method`、`experiment`、`limitation`
  - `cards`、`evidence`、`plan`
  - `paper`、`venue`、`citation key`
- `frontend/src/app/synthesis/page.tsx`
  - `synthesis`、`multi-paper`
  - `supporting cards`
  - `conf`
  - `comparability`
  - `question`、`task`、`baseline`、`contribution`、`min exp`
  - `novel`、`feasible`、`hit`
  - `coverage`、`signals`
- `frontend/src/app/knowledge/page.tsx`
  - 卡片类型、状态、来源、资产层级直接显示内部值
  - `paper`、`card`、`quote`、`run`、`source`、`evidence`
  - “加入 related_work”等按钮
- `frontend/src/app/knowledge-spaces/page.tsx`
  - `dataset`、`unknown`
  - `source_type`、`sync_status`、`run_status` 直出
  - Dify 文档状态直出
- `frontend/src/app/paper/[paperId]/run/[runId]/page.tsx`
  - 文档分区 `References`、`Appendix`、`Supplementary`
  - `confidence`
  - 标注类型 `highlight`、`note`、`question`、`correction`
  - 复核状态直出
- `frontend/src/app/papers/components.tsx`
  - 部分关系、状态和发现图谱标签已有中文映射，但不完整。

### 2. 后端枚举值直出

这是本地化的主要风险。只替换页面硬编码文案不够，因为很多值来自后端：

- 卡片类型：`claim`、`method`、`dataset`、`metric`、`result`、`limitation`、`question`、`idea`
- 卡片状态：`draft`、`verified`、`rejected`、`merged`
- 资产层级：`action`、`synthesis`、`evidence`
- 创建来源：`ai`、`user`
- 写作段落：`related_work`、`method`、`experiment`、`limitation`
- 导出模式：`traceable`、`clean`
- 关系状态：`confirmed`、`verified`、`needs_more_evidence`、`rejected`
- gap 状态：`candidate`、`reviewing`、`pursue`、`experiment_planned`、`needs_more_evidence`、`promoted_to_idea`、`covered`、`rejected`
- 覆盖状态：`uncovered`、`partially_covered`、`covered`、`unknown`
- 同步状态：`not_synced`、`pending`、`running`、`synced`、`skipped`、`failed`
- Dify 文档状态：`indexing`、`completed`、`error` 等可能来自外部系统。

### 3. i18n 结构覆盖不足

现有 `frontend/src/lib/i18n.tsx` 已有 `translations` 和 `t()`，但存在三点不足：

- 默认 locale 是 `en`，对中文论文阅读平台不合适。
- `translations` 只覆盖部分页面，新增页面大量硬编码。
- 缺少通用枚举翻译函数，导致组件只能直接显示原始值。

## 文案原则

### 中文优先

界面主文案使用中文。英文只保留在以下场景：

- 标准格式名：Markdown、BibTeX、RIS、Zotero CSL JSON。
- 产品和服务名：Dify、MinerU、DeepLX、OpenAI、arXiv。
- 配置字段专名：API Key、Base URL、dataset id、paper_id、run_id。
- 模式品牌名可作为括注：快速洞察（Insight Snap）、逻辑透镜（Logic Lens）、研究全景（Research Sphere）、智能问答（Smart Q&A）。

### 中文术语稳定

同一枚举在所有页面使用同一中文名。不要在不同页面混用“gap / 缺口 / 创新点候选”；建议统一为：

- `gap`：研究空白
- `candidate gap`：研究空白候选
- `synthesis card`：综合卡
- `writing snippet`：写作片段
- `evidence`：证据
- `claim`：论点
- `dataset`：数据集
- `metric`：指标

### 不翻译内部标识

内部 ID 保持原样，例如 `paper_id`、`run_id`、`card_id`、`dataset_id`。但标签应中文化，例如：

- `paper_id` 输入框：占位符可写“论文 ID（paper_id）”
- `run_id` 输入框：占位符可写“运行 ID（run_id）”
- `dataset id`：写作“Dify 数据集 ID”

## 推荐术语表

| 内部/英文 | 中文展示 |
|---|---|
| Insight Snap | 快速洞察 |
| Logic Lens | 逻辑透镜 |
| Research Sphere | 研究全景 |
| Smart Q&A | 智能问答 |
| Direct Q&A | 直接问答 |
| paper | 论文 |
| local paper | 本地论文 |
| corpus | 语料库 |
| knowledge base | 知识库 |
| knowledge space | 知识空间 |
| knowledge card | 知识卡片 |
| synthesis card | 综合卡 |
| writing snippet | 写作片段 |
| evidence | 证据 |
| source quote | 原文摘录 |
| confidence | 置信度 |
| relation | 关系 |
| conflict | 冲突 |
| comparability | 可比性 |
| gap | 研究空白 |
| research question | 研究问题 |
| baseline | 基线方案 |
| contribution | 贡献点 |
| minimum experiment | 最小实验 |
| target task | 目标任务 |
| target venue | 目标会议/期刊 |
| traceable | 带证据追踪 |
| clean | 纯净文本 |
| source paper | 原文论文 |
| analysis report | 解读报告 |
| reading asset | 阅读资产 |
| health check | 健康检查 |

## 枚举映射设计

建议新增 `frontend/src/lib/labels.ts`，集中处理展示文案。页面不直接写 `card.card_type`、`gap.status`、`edge.relation`，统一调用函数。

### 基础结构

```ts
export type LabelLocale = "zh" | "en";

export function labelFor(
  group: LabelGroup,
  value: string,
  locale: LabelLocale = "zh",
): string {
  return LABELS[group]?.[value]?.[locale] ?? value;
}
```

`LabelGroup` 至少包括：

- `cardType`
- `cardStatus`
- `assetLevel`
- `createdBy`
- `sectionHint`
- `traceMode`
- `syncStatus`
- `runStatus`
- `paperParseStatus`
- `paperReadingStatus`
- `paperPriority`
- `readingDecision`
- `annotationType`
- `reviewStatus`
- `documentPart`
- `discoveryRelation`
- `discoveryRelationStatus`
- `gapStatus`
- `coverageStatus`
- `scoreName`
- `sourceType`
- `itemKind`
- `difyDocumentStatus`

### 核心映射建议

| 分组 | 值 | 中文 |
|---|---|---|
| `cardType` | `claim` | 论点 |
| `cardType` | `method` | 方法 |
| `cardType` | `dataset` | 数据集 |
| `cardType` | `metric` | 指标 |
| `cardType` | `result` | 结果 |
| `cardType` | `limitation` | 局限 |
| `cardType` | `question` | 问题 |
| `cardType` | `idea` | 想法 |
| `cardStatus` | `draft` | 草稿 |
| `cardStatus` | `verified` | 已确认 |
| `cardStatus` | `rejected` | 已废弃 |
| `cardStatus` | `merged` | 已合并 |
| `assetLevel` | `action` | 行动卡 |
| `assetLevel` | `synthesis` | 综合卡 |
| `assetLevel` | `evidence` | 证据卡 |
| `createdBy` | `ai` | AI 生成 |
| `createdBy` | `user` | 用户创建 |
| `sectionHint` | `related_work` | 相关工作 |
| `sectionHint` | `method` | 方法 |
| `sectionHint` | `experiment` | 实验 |
| `sectionHint` | `limitation` | 局限 |
| `traceMode` | `traceable` | 带证据追踪 |
| `traceMode` | `clean` | 纯净文本 |
| `annotationType` | `highlight` | 高亮 |
| `annotationType` | `note` | 笔记 |
| `annotationType` | `question` | 问题 |
| `annotationType` | `correction` | 纠错 |
| `reviewStatus` | `trusted` | 可信 |
| `reviewStatus` | `pending` | 待核验 |
| `reviewStatus` | `error` | 错误 |
| `reviewStatus` | `valuable` | 有价值 |
| `documentPart` | `main` | 正文 |
| `documentPart` | `references` | 参考文献 |
| `documentPart` | `appendix` | 附录 |
| `documentPart` | `supplementary` | 补充材料 |
| `gapStatus` | `candidate` | 候选 |
| `gapStatus` | `reviewing` | 复核中 |
| `gapStatus` | `pursue` | 追踪 |
| `gapStatus` | `experiment_planned` | 已规划实验 |
| `gapStatus` | `needs_more_evidence` | 需要更多证据 |
| `gapStatus` | `promoted_to_idea` | 已推进为想法 |
| `gapStatus` | `covered` | 已覆盖 |
| `gapStatus` | `rejected` | 已忽略 |
| `coverageStatus` | `uncovered` | 未覆盖 |
| `coverageStatus` | `partially_covered` | 部分覆盖 |
| `coverageStatus` | `covered` | 已覆盖 |
| `coverageStatus` | `unknown` | 未知 |
| `scoreName` | `novelty` | 新颖性 |
| `scoreName` | `feasibility` | 可行性 |
| `scoreName` | `evidence_strength` | 证据强度 |
| `scoreName` | `risk` | 风险 |
| `scoreName` | `experiment_cost` | 实验成本 |
| `scoreName` | `domain_value` | 领域价值 |

## 分阶段实施计划

### 阶段 1：建立本地化基础设施

目标：先解决枚举直出问题，降低后续页面改造成本。

任务：

- 新建 `frontend/src/lib/labels.ts`。
- 将枚举映射集中到 `labels.ts`，提供 `labelFor()` 和更具体的辅助函数，例如 `cardTypeLabel()`、`sectionHintLabel()`。
- 把默认语言从 `en` 调整为 `zh`，保留切换英文能力。
- 在 `i18n.tsx` 中补齐全局通用文案：
  - 加载、刷新、保存、取消、删除、确认、废弃、重试、同步中、无数据。
  - 页面标题和按钮通用文案。
- 定义英文 fallback 策略：未映射值显示原值，但开发环境打印警告。

验收标准：

- 新增枚举展示函数有单元级或简单脚本校验。
- 新进入系统默认中文。
- 任一页面不需要手写 `verified`、`draft`、`related_work` 这类展示值。

### 阶段 2：优先处理英文最明显的页面

优先级按用户感知强弱排序：

1. `frontend/src/app/writing/page.tsx`
2. `frontend/src/app/synthesis/page.tsx`
3. `frontend/src/app/knowledge/page.tsx`
4. `frontend/src/app/knowledge-spaces/page.tsx`

任务：

- 将硬编码英文按钮、标题、字段名改为中文。
- 下拉选项展示中文，提交值保持原枚举。
- 标签 chip 使用 `labelFor()` 显示中文。
- 把 `supporting cards`、`conf`、`novel`、`feasible`、`hit`、`plan`、`quote` 等替换为中文。
- 保留 Markdown、BibTeX、RIS、Zotero、Obsidian 等格式名，但按钮前加中文动作，例如“导出带证据 Markdown”。

验收标准：

- `/writing` 和 `/synthesis` 首屏无非必要英文。
- 所有下拉框选项显示中文。
- 所有状态 chip 显示中文。
- 标准格式名保留英文，但上下文中文完整。

### 阶段 3：处理阅读页、论文库和知识空间细节

范围：

- `frontend/src/app/paper/[paperId]/run/[runId]/page.tsx`
- `frontend/src/app/papers/components.tsx`
- `frontend/src/app/library/page.tsx`
- `frontend/src/components/RecentRuns.tsx`
- `frontend/src/components/PdfViewer.tsx`
- `frontend/src/components/LibraryDocumentPreview.tsx`

任务：

- 文档结构分区中文化：正文、参考文献、附录、补充材料。
- 复核状态、标注类型、阅读状态、分析状态统一映射。
- 论文发现图谱中的关系类型、关系状态、阅读路径状态补齐中文。
- Dify 文档状态做中文展示。
- 错误提示保留技术细节，但加中文解释前缀。

验收标准：

- 阅读页右侧“阅读资产”内无枚举英文直出。
- 论文库卡片、发现图谱和知识空间列表中的状态均中文化。
- Dify 外部状态至少有常见值中文映射，未知值保留原值。

### 阶段 4：扫描、测试和视觉验收

任务：

- 使用 `rg` 扫描 TSX 中用户可见英文残留。
- 用 Playwright 或手动走查核心页面：
  - `/`
  - `/upload`
  - `/daily`
  - `/papers`
  - `/knowledge`
  - `/synthesis`
  - `/writing`
  - `/knowledge-spaces`
  - `/health`
  - `/settings`
- 检查移动端宽度下中文按钮不溢出。
- 检查英文模式下基本可用，不要求完全新增所有英文文案。

建议扫描命令：

```bash
rg -n '>[A-Za-z][^<{]*<|\"[A-Za-z][^\"]{2,}\"|`[A-Za-z][^`]{2,}`' frontend/src/app frontend/src/components -g '*.tsx'
```

验收标准：

- 除产品名、格式名、配置名和内部 ID 外，中文模式下无明显英文操作文案。
- 所有枚举值展示均通过映射函数。
- `npm run build` 通过。
- 页面宽度 390px、768px、1440px 下无按钮文本明显溢出。

## 页面级改造清单

### `/writing`

必须替换：

- `Traceable Markdown` -> `导出带证据 Markdown`
- `Clean Markdown` -> `导出纯净 Markdown`
- `related_work` -> `相关工作`
- `method` -> `方法`
- `experiment` -> `实验`
- `limitation` -> `局限`
- `cards` -> `卡片`
- `evidence` -> `证据`
- `plan` -> `段落计划`
- `citation key` -> `引用键`
- `venue` -> `会议/期刊`

### `/synthesis`

必须替换：

- `synthesis` -> `综合`
- `multi-paper` -> `多论文`
- `papers` -> `篇论文`
- `supporting cards` -> `支撑卡片`
- `conf` -> `置信度`
- `comparability` -> `可比性`
- `task` -> `任务`
- `dataset` -> `数据集`
- `metric` -> `指标`
- `setting` -> `设置`
- `claim_direction` -> `论点方向`
- `verdict` -> `结论`
- `novel` -> `新颖性`
- `feasible` -> `可行性`
- `hit` -> `命中`
- `question` -> `研究问题`
- `baseline` -> `基线方案`
- `contribution` -> `贡献点`
- `min exp` -> `最小实验`
- `trace` -> `证据链`
- `coverage` -> `覆盖状态`
- `signals` -> `信号`

### `/knowledge`

必须替换：

- 卡片类型、状态、资产层级、来源全部使用映射。
- `conf` -> `置信度`
- `run` -> `运行`
- `source` -> `来源`
- `supporting papers` -> `支撑论文`
- `flags` -> `质量标记`
- `paper` -> `论文`
- `card` -> `卡片`
- `quote` -> `原文摘录`
- `加入 related_work` -> `加入相关工作`

### `/knowledge-spaces`

必须替换：

- `dataset` -> `数据集`
- `unknown` -> `未知`
- `source_type` 相关展示 -> `来源类型`
- `sync_status` -> `同步状态`
- `run_status` -> `分析状态`
- Dify 文档状态做中文映射。

### `/paper/[paperId]/run/[runId]`

必须替换：

- `References` -> `参考文献`
- `Appendix` -> `附录`
- `Supplementary` -> `补充材料`
- `confidence` -> `置信度`
- `highlight` -> `高亮`
- `note` -> `笔记`
- `question` -> `问题`
- `correction` -> `纠错`
- 复核标记状态使用映射。

## 风险与处理

### 风险 1：翻译后按钮变长导致布局溢出

处理：

- 工具栏按钮优先使用短词，例如“导出带证据 Markdown”可在窄屏缩为“带证据 Markdown”。
- 宽按钮区域允许换行，不使用固定宽度。
- 重要按钮保留图标和 tooltip。

### 风险 2：后端新增枚举后前端未映射

处理：

- `labelFor()` fallback 保留原值。
- 开发环境 `console.warn("[labels] missing label", group, value)`。
- 增加映射完整性测试，覆盖 `frontend/src/lib/types.ts` 中可枚举联合类型。

### 风险 3：中英文混合导致术语不统一

处理：

- 统一维护术语表，新增页面必须复用。
- PR 检查时重点看用户可见字符串，不只看功能。

### 风险 4：过度翻译损害专业识别

处理：

- 标准格式和产品名不翻译。
- 模式名采用“中文名（英文名）”策略，只在首次或关键入口显示英文名。

## 建议提交拆分

1. `feat(frontend): add centralized label mappings`
2. `refactor(frontend): localize writing and synthesis pages`
3. `refactor(frontend): localize knowledge cards and spaces`
4. `refactor(frontend): localize run and paper library metadata`
5. `test(frontend): add localization scan and build checks`

## 最小验收命令

```bash
cd /media/dc/M2_DATA/Paper_read/AI4Sec/frontend
npm run build
```

补充扫描：

```bash
cd /media/dc/M2_DATA/Paper_read/AI4Sec
rg -n '>[A-Za-z][^<{]*<|\"[A-Za-z][^\"]{2,}\"|`[A-Za-z][^`]{2,}`' frontend/src/app frontend/src/components -g '*.tsx'
```

发布前仍需运行：

```bash
cd /media/dc/M2_DATA/Paper_read/AI4Sec
scripts/check_public_release.sh
```

## 推荐执行顺序

先做阶段 1 和 `/writing`、`/synthesis`，因为这两页英文残留最明显，也最能验证映射层是否足够。确认效果后再迁移 `/knowledge`、`/knowledge-spaces` 和运行页，最后全局扫描收尾。
