# 知识脊柱与全流程科研平台重构方案

> 日期：2026-06-13
> 定位：AI4Sec 从「论文阅读器」演进为「随阅读自我生长的研究第二大脑」的总纲方案
> 项目根：`/media/dc/M2_DATA/Paper_read/AI4Sec`
> 关联文档：`方案/knowledge-space-library-unification-plan.md`、`方案/daily-recommendation-knowledge-base-redesign-plan.md`、`方案/p9-fix-implementation-task-prompts.md`
> 性质：架构重构 + 全流程功能补全，跨多个迭代，按 P0→P4 分期串行交付

---

## 0. 管理摘要

- **核心判断**：当前平台不是「功能少」，而是「三套知识系统各自为政」。Schema 雄心极大（证据 / 关系 / 冲突 / 想法 / 写作片段 / BibTeX 全建了表），但三套知识表示从不互相喂数据，且只有最浅的一套（知识卡片）接了完整界面。用户用最弱的一环评判整个知识能力，于是「卡片没用」。
- **重构总纲**：不再新增第四个孤岛。所有改进服从单一架构原则——**沿抽象阶梯自下而上的知识图谱（知识脊柱）**：`Evidence 证据 → Claim 卡片 → Synthesis 综合 → Gap 想法 → Draft 产出`，每层可向下追溯到原文逐字引用，每次自动抽象进入可控审核漏斗。
- **分期**：P0 统一数据模型（地基）→ P1 卡片重做（止血，唯一可见环）→ P2 综合层上界面 + 规则升级（汇聚）→ P3 问答接图谱 + 想法看板 + 行为反哺（闭环）→ P4 产出层开门（写作 / 对比表 / 导出 / 同步）。
- **可控性是设计核心**：每次自动抽象只产生候选，沿脊柱晋级须过置信闸门或经人工轻点；全程可追溯到 PDF 页码；利用 schema 已预埋的 `*_version` / `revision_history` 建审计轨道。
- **降级范围**：见 §9 Backlog。本期不做语义向量库自建（先用 Dify 顶）、不做多用户协作、不做移动端。

---

## 1. 诊断：三套知识孤岛

顺着 22 张表逐一追「谁写入、谁读取、前端有没有」，得到三套并行且互不连通的「知识」定义：

| 子系统 | 后端 | 抽取方式 | 前端 | 实际质量 |
|---|---|---|---|---|
| **A 知识卡片** `knowledge_cards` | ✅ 完整 | LLM 单次、单篇、上下文截断 8000 字 | ✅ **唯一完整界面** `app/knowledge/page.tsx` | 浅、模板兜话 |
| **B 研究发现** `research_evidence_items` / `research_relation_edges` / `research_gaps` | ✅ 完整 | **规则关键词匹配** `EXTRACTOR="rule_v1"` | ❌ **零界面**（仅一个计数 `types.ts:514`） | 跨论文但脆弱 |
| **C 跨论文问答** `corpus_qa` | ✅ 完整 | **只查 Dify** | ✅ | 不读 A 也不读 B |
| **D 产出层** BibTeX / RIS / related-work / `writing_snippets` | ✅ 端点都在 | — | ❌ 几乎无界面 | 没人用 |

### 1.1 关键证据

- **B 是孤儿**。`research_discovery.py` 真会产出跨论文关系：`uses_same_dataset`、`same_problem`、`method_variant`、`transferable_method`，以及**冲突检测 `conflicting_claim`**（`research_discovery.py:649`）。但它由 `api/papers.py:622 build_research_discovery` 独立批处理端点触发，**前端完全不消费**（`api.ts` 无任何 `research-discovery` / `gap` / `relation` 调用）。且 `sphere_subgraph.py` 根本不 import 它——Research Sphere 模式只产 markdown，与这套跨论文引擎毫无关系。
- **B 的抽取是脆弱的规则匹配**。`EXTRACTOR = "rule_v1"`（`research_discovery.py:26`），靠 `_PROBLEM_RULES` / `_METHOD_RULES` 关键词碰撞抽证据、靠标签相同判定关系。`conflicting_claim`（`:634-660`）的触发条件是「两篇共享 metric+problem 且一篇有 result 证据、另一篇有 claim 证据」——典型的关键词碰撞，召回与精度都不可信。
- **C 自我封闭**。`corpus_qa.py:117` 只调 `dify_client.search_records`，完全不读 `knowledge_cards`、不读 `research_evidence_items`。**读 50 篇论文、攒几百张卡，问答一个字都用不上。**
- **A 最弱却唯一可见**。`asset_level` 有 `synthesis` 档，前端 `app/knowledge/page.tsx:424` 专门做了「综合卡」筛选标签——但**全代码库无任何地方产出 synthesis 卡**（`grep` 确认 `knowledge_card_generator` 只产 `action` 级）。用户点「综合卡」永远是空的。
- **A 不向上、不横向、不向下连通**。自动生成器从不写 `research_evidence_cards` 桥表（桥表只被 `knowledge_assets.py:685` 的手动挂证据操作写入），于是卡片游离于统一证据层之外，B 无法把「3 篇论文的同一 dataset 卡」识别为一个综合节点。
- **D 是隐形的**。`export_bibtex` / `export_ris` / `export_writing_markdown`（`api/knowledge.py:320-332`）、`writing_snippets` 全套 CRUD 都写好，前端 `api.ts` 基本不调，无专门写作 / 导出界面。

### 1.2 「卡片没用」的真正根因

不在卡片的 prompt，而在卡片是一个**被孤立的、单篇的、一次性的摘要碎片**：不向上汇聚（无 B 的综合）、不横向连通（不进 C 的问答）、不向下产出（不接 D 的写作）。把它当「知识卡片」，系统却只把它当「另一种格式的摘要」。

---

## 2. 架构总纲：知识脊柱

所有改进服从单一原则——**沿抽象阶梯自下而上的单一知识图谱，每层可向下追溯到原文逐字引用**：

```
Evidence 证据   ──  逐字引用 + (paper, page, block) 锚点。原子、可验证、永不改写。  [地基]
   │ 支撑 (supports)
Claim 主张/卡片 ──  研究者可读的一句话(方法做了X/数据集是Y/结果是Z)，由≥1条Evidence支撑。
   │ 汇聚 (rolls up)
Synthesis 综合 ──  跨论文聚合同类Claim(5篇都用ImageNet / 方法族A vs B / 指标M上结论冲突)。 ← B在这层
   │ 提炼 (derives)
Gap 想法     ──  从综合(尤其冲突与空白)派生的研究机会，带新颖性/可行性/成本评分。 ← research_gaps
   │ 引用 (cites)
Draft 产出    ──  相关工作段落 / 对比表 / BibTeX，每句都引到Claim及其Evidence。 ← D
```

这条脊柱一次性解释所有子系统的归位：

- **A 产出 Claim**（卡片重做，P1）
- **B 产出 Synthesis + Gap**（综合层，P2）
- **C 在 Claim + Evidence 上检索**（问答接图谱，P3）
- **D 把 Claim 组装成 Draft**（产出层，P4）

卡片不再是「摘要」，而是「图谱里一个被证据支撑、会向上汇聚成综合的 Claim 节点」。这就是它从「没用」变「有用」的根本转变。

**Schema 早已预埋这条脊柱的字段**，现状是「写了没人读」：`research_evidence_cards`（证据↔卡片桥）、`supporting_card_ids` / `supporting_paper_ids` / `evidence_strength`（汇聚）、`evidence_version` / `relation_version` / `gap_version` / `revision_history`（审计轨道）。**重构不是发明新东西，是把已有骨架接上神经。**

---

## 3. 架构决策记录（ADR）

### ADR-1 证据层统一为唯一地基
当前存在三套证据表示：① run JSON 里的 `evidence_pool`（`snap_subgraph` 的 `extract_evidence_pool`）；② `research_evidence_items` 表（`research_discovery` 规则抽取）；③ `knowledge_cards.source_quote` 字符串。**决策**：以 `research_evidence_items` 为唯一持久化证据层，`evidence_pool` 与卡片引用全部落地到该表并复用 `validate_card_source`（`knowledge_card_generator.py:235`）的锚定校验。证据永不被 LLM 改写，只存逐字引用 + 锚点。理由：只有证据统一，跨论文汇聚（B）与可追溯产出（D）才有共同底座。

### ADR-2 卡片必须绑定证据（桥表强制）
**决策**：每张事实类 Claim 卡（method/dataset/metric/result/limitation）入库时，其锚定引用必须落 `research_evidence_items` 并写 `research_evidence_cards` 桥表（自动生成器目前完全不写桥表）。无法锚定到证据的事实卡不得晋级 `active`。`question` / `idea` 类不强制（它们是 Gap 种子，见 ADR-4）。

### ADR-3 抽取范式：单次 → 两段式（分区抽取 + 批判）
**决策**：① 分区抽取——复用 Lens 模式已并行产出的 section 分析结果作为输入（方法段→method/dataset/metric，结果段→result/claim，讨论段→limitation/question），替换 `_build_context` 的 8000 字截断（`knowledge_card_generator.py:286`）与前 80 block 限制（`:293`）；② 批判过滤——第二次 LLM 调用对候选卡逐张打分，淘汰率目标 ≥50%。理由：宁缺毋滥，每篇 3-5 张高价值卡胜过 12 张水卡。

### ADR-4 卡片类型映射到脊柱角色
**决策**：`method/dataset/metric/result/limitation` = Claim（挂证据，进 `knowledge_cards`）；`question/idea` = Gap 种子（直接喂 `research_gaps`，而非孤躺卡片列表）。卡片类型不再是 8 个平级标签，而是脊柱上不同高度的节点。

### ADR-5 删除模板兜底，价值字段由模型负责
**决策**：删除 `_default_why_useful` / `_default_next_action` / `_default_expected_output` 等兜底函数（`knowledge_card_generator.py:388-432`）。LLM articulate 不出 `why_useful` / `next_action` 的卡，不晋级 `active`，留 `draft` 或弃。理由：兜底是「劣币驱逐良币」元凶，让放之四海皆准的废话卡合法化。

### ADR-6 研究画像条件化抽取
**决策**：`knowledge_spaces` 增 `research_profile` 字段（研究问题 / 关注方法族 / 在写主题，一段话，用户填或从已有卡自动归纳）。抽取与批判 prompt 注入画像，`why_useful` / `next_action` 必须引用画像具体内容，引用不到即被批判器杀。

### ADR-7 综合层：规则召回 + LLM 验证（hybrid）
**决策**：保留 `research_discovery` 的规则匹配作为**廉价候选召回**，新增 LLM **精度验证**层（尤其 `conflicting_claim`）。规则产候选关系 → LLM 判定关系是否成立、填 `positive_checks` / `negative_checks` / `counter_evidence_ids` → 通过的写 `status='verified'`。沿用 adversarial-verify 思路：冲突类候选由独立验证「这两条结论是否真的在同一设定下矛盾」，默认存疑。

### ADR-8 综合触发：批处理 → 增量
**决策**：每新增一张 `active` 卡，增量触发该卡所属 dataset/method/problem 维度的局部重新发现，而非只靠 `build_research_discovery(200)` 全量批处理。全量批处理保留为「重建索引」运维动作。

### ADR-9 问答检索源：Dify-only → 图谱优先 + Dify 融合
**决策**：`corpus_qa` 检索改为：先查 Claim + Evidence 图谱（卡片及其锚定引用），与 Dify chunk 召回融合排序，回答引用具体卡片（`card_id`）。理由：让「读得越多，问答越聪明」成真，且回答可追溯到原文。

### ADR-10 可控漏斗与晋级状态机
**决策**：每层只产候选；沿脊柱晋级须过置信闸门或经人工轻点（详见 §6）。高置信 + 锚定成功 → 自动 `active`；否则入有界审核队列。每周需人工处理的卡控制在 10 张内。

---

## 4. 统一数据模型（P0 落地，后续各期消费）

### 4.1 复用 / 激活的现有表

| 表 | 现状 | 重构后角色 |
|---|---|---|
| `research_evidence_items` | B 规则抽取写入 | **唯一证据地基**；卡片引用、evidence_pool 全部落此 |
| `research_evidence_cards` | 仅手动挂证据写入 | **证据↔卡片桥**，自动生成器强制写入（ADR-2） |
| `knowledge_cards` | A 写入，`synthesis` 档空置 | Claim 节点；新增真正的 `synthesis` 级（P2 由综合产出） |
| `research_relation_edges` | B 规则写入，无人读 | Synthesis 关系；新增 `verified` 状态（ADR-7） |
| `research_gaps` | B 写入，无界面 | Gap 节点；接「想法看板」（P3） |
| `writing_snippets` | CRUD 在，无界面 | Draft 片段；接「写作合成器」（P4） |
| `paper_annotations` | 表在，与卡片断开 | 「高亮→证据→卡片」人工路径（P1 尾） |

### 4.2 字段新增

- `knowledge_spaces.research_profile TEXT`（ADR-6）
- `knowledge_cards`：激活已存在但未用的 `supporting_card_ids` / `supporting_paper_ids` / `evidence_strength` 的**读取**（现仅写不读，`knowledge_assets.py:493-494`）
- `research_evidence_items.source_run_id TEXT`（标记证据来自哪次精读，便于复用 Lens 产出）
- 审计：统一启用 `*_version` + `revision_history`（schema 已有，激活写入逻辑）

### 4.3 晋级状态机（卡片）

```
draft ──(置信闸门: confidence≥阈值 且 证据锚定成功)──▶ active
  │                                                      │
  ├──(人工 reject + 理由)──▶ rejected                     ├──(人工 / 自动去重)──▶ merged
  └──(批判器低分)──▶ 留 draft 进审核队列                    └──(汇聚成综合)──▶ 支撑 synthesis 卡
```

---

## 5. 分期实施

> 每期格式：目标 / 范围 / 设计要点 / Schema / 验收标准 / 依赖。各期串行，期内可并行。

### ── P0 地基：统一知识模型 ──

**目标**：把三套证据表示收敛为一条脊柱的底两层（Evidence + Claim），让卡片成为图谱公民。无直接可见产出，但解锁全部后续。

**范围**：`backend/app/services/knowledge_card_generator.py`、`knowledge_assets.py`、`research_discovery.py`（仅证据写入段）、`db/database.py`（字段新增 + 迁移）、`models/schemas.py`。

**设计要点**：
- 定义统一证据写入函数 `upsert_evidence(paper_id, quote, page, block_id, evidence_type, source_run_id)`，所有证据来源（evidence_pool / 卡片引用 / 规则抽取）共用，落 `research_evidence_items`。
- 卡片创建路径强制走桥表：`create_card` 时若为事实类且有锚定引用，自动 `upsert_evidence` + 写 `research_evidence_cards`（ADR-2）。
- 实现晋级状态机（§4.3），置信闸门可配置阈值（env / settings）。
- 激活 `supporting_*` / `evidence_strength` 的读取路径与审计字段写入。

**Schema**：`knowledge_spaces.research_profile`、`research_evidence_items.source_run_id`；迁移脚本把现有 `knowledge_cards.source_quote` 回填为 `research_evidence_items` + 桥表记录。

**验收标准**：a) 新单测——证据去重（同引用不重复入库）、桥表强制（事实卡无证据不晋级）、状态机迁移合法性；b) 迁移后存量卡片 100% 有桥表证据或被标记 `draft`；c) `cd backend && pytest` 全绿。

**依赖**：无（地基）。

---

### ── P1 止血：知识卡片重做 ──

**目标**：让用户唯一可见的一环从「通用废话」变「与我相关的高价值卡」，每篇 3-5 张精卡。

**范围**：`knowledge_card_generator.py`（核心重写）、`lens_subgraph.py`（暴露 section 中间产出供复用）、`knowledge_assets.py`（批判 / 晋级）、`app/knowledge/page.tsx`（审核队列 UI）、`app/paper/[paperId]/`（高亮→卡片路径）。

**设计要点**：
- **两段式抽取**（ADR-3）：分区抽取复用 Lens section 产出（零额外 LLM 成本）→ 批判器逐卡打分淘汰。
- **删兜底**（ADR-5）：移除 `_default_*`，价值字段缺失即不晋级。
- **研究画像注入**（ADR-6）：抽取与批判 prompt 带 `research_profile`。
- **类型映射**（ADR-4）：`question`/`idea` 候选写入 `research_gaps` 而非卡片列表。
- **审核队列 UI**：前端「综合卡」空标签暂隐藏（P2 才有内容）；新增 draft 审核队列视图，支持改 / 弃 / 合并，每周限额提示。
- **高亮→卡片**（P1 尾）：`paper_annotations` 的人工高亮可一键转 Evidence + Claim，与 AI 卡汇入同一池。

**Schema**：无新增（P0 已备）。

**验收标准**：a) A/B 对照——同一篇论文新旧卡片，新版水卡（模板兜话）占比降至 0，事实卡证据锚定率 100%；b) 批判器淘汰率 ≥50% 可观测；c) 注入画像后，`why_useful` 引用画像具体内容的卡占比可量化；d) 前端审核队列可改 / 弃 / 合并并贴手测核查单；e) `pytest` + `npm run build` 全绿。

**依赖**：P0（证据统一 + 状态机）。

---

### ── P2 汇聚：综合层上界面 + 规则升级 ──

**目标**：让 B 从孤儿变成可见、可信的「综合层」；让「读得越多越值钱」成真。补上**最大断点之一**（④综合无界面）。

**范围**：`research_discovery.py`（hybrid 验证 + 增量触发）、新增 `app/synthesis/`（或并入 `knowledge-spaces`）综合 / 冲突 / 想法视图、`api/papers.py`（discovery 端点改造）、`api.ts` + `types.ts`（前端消费）。

**设计要点**：
- **hybrid 验证**（ADR-7）：规则产候选关系 → LLM 验证填 `positive/negative_checks` + `counter_evidence_ids` → `status='verified'`。冲突类独立 adversarial 验证。
- **增量触发**（ADR-8）：新 `active` 卡触发局部维度重发现。
- **真正的 synthesis 卡**：综合节点落 `knowledge_cards` 的 `asset_level='synthesis'`、`supporting_card_ids` 指向被汇聚的单篇卡、`evidence_strength` 升级为 `multi-paper`。填上现在永远空的「综合卡」标签。
- **三个前端视图**：① 综合视图（按 dataset / 方法族 / 问题聚类）；② **冲突看板**（`conflicting_claim` 关系——两篇打架处是 idea 金矿）；③ 关系图谱（可选）。

**Schema**：`research_relation_edges` 增 `verified` 状态值（无结构变更）。

**验收标准**：a) hybrid 验证后 `conflicting_claim` 精度人工抽检 ≥80%（旧规则版作对照）；b) 「综合卡」标签不再为空，synthesis 卡 `supporting_card_ids` 非空且可点开溯源；c) 冲突看板可展示并点击到双方原文；d) 增量触发有单测（新卡→局部关系更新）。

**依赖**：P0（证据统一）、P1（高质量 active 卡作为汇聚原料）。

---

### ── P3 闭环：问答接图谱 + 想法看板 + 行为反哺 ──

**目标**：让系统自我增强——问答用上积累的知识、想法被持续追踪、阅读行为回流推荐。

**范围**：`corpus_qa.py` + `qa_retrieval.py`（检索源改造）、`research_gaps`（想法看板 UI）、`daily_recommendation_scoring.py`（行为反哺）、对应前端。

**设计要点**：
- **问答查图谱**（ADR-9）：检索先查 Claim+Evidence，与 Dify 融合，回答引用 `card_id`，可溯源 PDF 页。
- **想法看板**：`research_gaps` 带新颖性 / 可行性 / 成本评分上界面，人工 pursue/reject + 理由（`rejection_reason` 字段已有）。
- **新颖性追踪**：新论文命中已有 gap 时提醒「这个方向有人做了」（复用 daily 入库流水线做匹配）。
- **行为反哺**：读了哪些 / 产了多少卡 / 问答问了什么 → 回流 `daily_recommendation_scoring`，推荐个性化收敛；卡片「被引用 / 被检索」次数反馈批判器校准。

**Schema**：`research_gaps` 增行为信号字段（如 `hit_by_paper_ids`）；推荐评分增行为特征列。

**验收标准**：a) 跨论文问答回答中引用本地卡片的比例可观测、来源可点击溯源；b) 想法看板可 pursue/reject 并记录理由；c) 新论文命中 gap 的提醒有单测；d) 行为信号进入推荐评分有单测，推荐结果随阅读历史变化可复现。

**依赖**：P1（高质量卡作为检索 / 看板原料）、P2（综合与 gap 作为想法来源）。

---

### ── P4 产出：写作合成器 + 对比表 + 导出 + 同步 ──

**目标**：开门——把后端备好的产出层接到界面，兑现「从读懂到写出」。补上**最大断点之二**（⑥产出无界面）。

**范围**：`app/writing/`（新增写作 / 导出页）、`api/knowledge.py`（已有导出端点接前端）、`knowledge_assets.py`（对比表聚合 + 草稿合成）、Zotero/Obsidian 同步适配器（新增）。

**设计要点**：
- **导出按钮**：`/papers/export/bibtex`、`/papers/export/ris`、`/writing/export/markdown`（端点已就绪 `api/knowledge.py:320-332`）接前端按钮。
- **相关工作 / 草稿合成器**：选 Claim / Synthesis → LLM 生成带引用 prose → 落 `writing_snippets`（`citation_key` / `section_hint` 字段已有）。
- **跨论文对比表**：选论文 → 在其 dataset/metric/result 卡上自动出矩阵（结构化 Claim 让这步几乎免费）。
- **Zotero / Obsidian 同步**：本地论文库 + 卡片导出到外部工具，避免论文库成孤岛。

**Schema**：无新增（字段已备）。

**验收标准**：a) BibTeX/RIS/markdown 导出前端可下载并校验格式；b) 草稿合成器产出 prose 每句可溯源到 Claim+Evidence；c) 对比表选 3 篇论文自动出矩阵；d) Zotero 同步往返一致性测试。

**依赖**：P1（结构化 Claim）、P2（综合用于对比与草稿）。

---

## 6. 流程可控（治理模型）

卡片让人不信任、自动化让人不敢用，是同一个病：**没有检查点**。可控性的设计原则——**每次自动抽象只产生候选；沿脊柱向上晋级，要么过置信闸门、要么由人轻点一下**：

```
Evidence  自动抽取 → 必须过引用锚定(validate_card_source 已做) → 锚定成功即可信
Claim     LLM抽取 → 进 draft；高置信+锚定→自动active；否则入审核队列。人可改/弃/合并
Synthesis 只用 active 卡聚合 → 冲突与聚类作为候选浮出 → 人确认"这个综合成立"
Gap       从综合派生、评分 → 人标 pursue/reject + 理由(成为下一轮信号)
Draft     人发起、从选定 Claim 组装、全程带引用，可一路点回原文 PDF 页
```

研究者**永远不被强迫信任 LLM，但也不必事事手做**。系统提议、研究者裁决，每次裁决都是校准信号。三件可控基建（schema 已预埋，激活即可）：

- **全程可追溯**：任何 Draft 的任何一句 → Claim → Evidence → PDF 页码高亮，一路点到底。
- **版本与审计轨道**：`evidence_version` / `relation_version` / `gap_version` + `revision_history` 记录每次抽取 / 修订，可回滚、可问责（哪次生成、哪个 prompt 版本、谁改的）。
- **有界审核队列**：置信闸门让高质量卡自动晋级，每周需人工处理控制在 10 张内，审核不积成垃圾场。

---

## 7. 依赖与排期

```
P0 地基(数据模型统一) ──┬──▶ P1 卡片重做(止血)
                        │         │
                        │         ├──▶ P2 综合层(汇聚)
                        │         │         │
                        │         │         ├──▶ P3 闭环(问答/想法/反哺)
                        │         │         │
                        │         └─────────┴──▶ P4 产出(写作/对比/导出)
                        └──▶ (证据统一是 P2 综合的前提)
```

- **串行约束**：P0 必须最先（其余全依赖证据统一）；P1 是 P2/P3/P4 的原料来源；P2 是 P3 想法与 P4 对比的来源。
- **可并行**：P3 与 P4 在 P2 完成后可并行投放（互不冲突——P3 改问答 / 推荐，P4 改写作 / 导出）。
- **里程碑可见性**：P1 完成即用户可感知卡片质变；P2 完成即「综合卡」非空、冲突看板上线；P4 完成即闭环可演示。

---

## 8. 风险与回滚

| 风险 | 缓解 |
|------|------|
| P0 迁移破坏存量卡片 | 迁移前基线提交；存量卡 `source_quote` 回填失败的标记 `draft` 不删；迁移脚本可重入 |
| 两段式抽取增加 LLM 成本 | 分区抽取复用 Lens 已有 section 产出，不重读全文；批判器用小模型 / 低温 |
| hybrid 验证拖慢 discovery | 规则召回 + LLM 仅验证候选（非全量）；增量触发限定维度；全量批处理转为运维动作 |
| 问答改检索源引入回归 | Dify 融合而非替换，保留 Dify 兜底；灰度开关可回退 Dify-only |
| 删兜底后卡片数骤减引发"东西变少"错觉 | 文案说明"少而精"；审核队列展示被淘汰原因，让减少可解释 |
| 综合 / 想法前端工作量大 | P2 视图可先并入 `knowledge-spaces` 已有页面，不新建导航；冲突看板优先、关系图谱降级可选 |

---

## 9. Backlog（本期不做）

1. 自建向量库 / 本地 embedding 检索（先用 Dify 顶，P3 验证融合价值后再评估）
2. 多用户协作与权限（当前单机单用户定位）
3. 关系图谱可视化（force-directed graph）——P2 先做列表 / 看板，图谱视图按需
4. 移动端 / 响应式深度适配
5. 引文滚雪球的自动批量入库（P-发现期单列，依赖 `citation_graph` 已有能力，本总纲先聚焦知识脊柱）
6. 语义检索 pull 入口（Semantic Scholar / OpenAlex）——归入「发现期」独立方案

---

## 附录 A：现状证据索引（关键 file:line）

- 卡片单次抽取 / 截断：`knowledge_card_generator.py:286`（8000 字）、`:293`（80 block）
- 模板兜底：`knowledge_card_generator.py:388-432`
- 引用锚定校验（可复用）：`knowledge_card_generator.py:235 validate_card_source`
- 桥表仅手动写入：`knowledge_assets.py:685`；自动生成器不写
- 规则抽取：`research_discovery.py:26 EXTRACTOR="rule_v1"`、`:288 _match_rules`
- 关系类型：`research_discovery.py:580-654`；冲突检测 `:649 conflicting_claim`
- discovery 触发点：`api/papers.py:622 build_research_discovery`；前端零消费
- 问答 Dify-only：`corpus_qa.py:117 dify_client.search_records`
- synthesis 档空置：`app/knowledge/page.tsx:424`（前端有标签）；无后端产出
- 导出端点就绪：`api/knowledge.py:314-332`
- 可控审计字段（已建未用）：`database.py` 中 `evidence_version` / `relation_version` / `gap_version` / `revision_history`

## 附录 B：知识脊柱与子系统映射速查

| 脊柱层 | 落地表 | 由谁产出 | 在哪期 |
|---|---|---|---|
| Evidence | `research_evidence_items` + `research_evidence_cards` | 统一证据写入 | P0 |
| Claim | `knowledge_cards`(action) | 两段式抽取 | P1 |
| Synthesis | `knowledge_cards`(synthesis) + `research_relation_edges` | hybrid 发现 | P2 |
| Gap | `research_gaps` | 从综合派生 | P2→P3 |
| Draft | `writing_snippets` + 导出端点 | 写作合成器 | P4 |
