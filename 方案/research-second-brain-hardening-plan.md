# 科研第二大脑补强方案

> 日期：2026-06-13
> 项目根：`/media/dc/M2_DATA/Paper_read/AI4Sec`
> 定位：在现有论文阅读平台闭环基础上，补强为可信、可复用、可产出的科研第二大脑。

## 1. 总体判断

当前平台已经形成端到端 MVP 闭环：每日推荐 / 上传、解析阅读、摘录标注、证据锚定、知识卡片、综合与 Gap、跨库问答、写作素材、对比表、导出、Dify 同步和设置维护均已有前后端入口。

但它还不是严格意义上的研究级第二大脑。主要问题不是功能缺口，而是可信度、独立性、复用质量和产出质量不足：知识能生成，但质量闸门偏弱；图谱能检索，但仍依赖 Dify；综合和 Gap 能出现，但语义验证不够深；写作层能导出，但还停留在素材拼接。

闭合度估计：约 75%。后续补强应围绕“可信、可追溯、可检索、可验证、可写作、可反馈、可观测”七个目标推进。

## 2. 已闭合能力

- 阅读入口：上传、本地论文库、每日推荐、知识空间、Dify 数据集绑定。
- 阅读过程：PDF 查看、解析结果、精读运行、摘录、高亮、复核标记、人工笔记。
- 知识沉淀：AI / 人工知识卡、证据表、证据-卡片桥表、草稿 / 确认 / 废弃 / 合并状态。
- 跨论文层：综合卡、关系发现、冲突看板、Gap 候选、每日推荐对 Gap 命中反馈。
- 问答层：`/library/ask` 已融合本地卡片 / 证据结果与 Dify 结果。
- 产出层：写作素材、相关工作片段、对比表、Markdown / BibTeX / RIS / Obsidian / Zotero CSL 导出。
- 运维层：LLM 设置、健康维护、Dify 启动同步、Docker 正式实例。

## 3. 核心问题

### 3.1 知识质量闸门仍偏浅

当前卡片生成已经有证据锚定、缺字段拦截、画像匹配和规则批判，但质量判断仍主要依赖启发式规则。它能过滤明显差的卡片，但难以判断“这张卡是否真正有科研价值”。

需要补强的判断维度：

- 证据是否真的支持卡片结论。
- 卡片是否非平凡，是否超过普通摘要信息量。
- 是否与当前研究画像、问题或写作目标相关。
- 是否与已有卡片重复或只是在换说法。
- 是否能直接服务写作、实验设计、baseline 选择或 idea 推进。
- 是否存在明显反证或边界条件。

目标状态：卡片不是“生成后待用户筛”，而是经过清晰质量闸门后进入不同队列：可直接确认、需人工复核、证据不足、重复候选、低价值废弃。

### 3.2 证据链没有贯穿到所有产物

事实类卡片已经强制绑定 `research_evidence_items` 和 `research_evidence_cards`，但综合卡、Gap、写作素材仍需要更严格的证据链约束。

应补强的链路：

```text
writing_snippet
  -> source_card_id / supporting_card_ids
  -> research_evidence_cards
  -> research_evidence_items
  -> paper_id / page / quote / block_id
```

关键约束：

- verified 事实卡必须有证据。
- synthesis 卡必须有多个支撑卡和多个支撑证据。
- Gap 必须区分 support evidence 与 counter evidence。
- 写作片段每个关键句应能回溯到卡片和原文证据。
- `allow_untraceable` 只能作为人工例外，不应成为常规确认路径。

### 3.3 本地知识图谱不能完全脱离 Dify

当前 `/library/ask` 虽然先检索本地知识图谱，但 API 入口仍要求 Dify 启用，服务层也总会调用 Dify 检索。这样会导致本地结构化知识在 Dify 不可用时无法独立完成问答。

科研第二大脑应把本地知识图谱作为一级能力，Dify 只作为外部语义检索增强。

需要补强：

- 新增本地-only 问答路径：只依赖 `knowledge_cards`、`research_evidence_items`、`research_relation_edges`、`research_gaps`、`writing_snippets`。
- 本地检索从 LIKE 升级为 FTS5 / BM25 / embedding hybrid。
- 本地结果需要稳定排序：synthesis > verified action card > evidence > relation > snippet。
- Dify 异常时自动降级到本地问答，而不是直接 503 / 502。
- 回答来源要明确标注 `source_type=knowledge_graph|dify|snippet|relation`。

### 3.4 综合层语义验证不足

当前 synthesis 主要按 normalized key / tags 聚类；关系发现包含规则召回和可选 LLM 验证。这个基础可用，但研究结论层面的“可比性”还不够强。

需要补强的语义验证：

- same dataset：是否真是同一数据集，版本、子集、任务切分是否一致。
- same metric：指标是否同名同义，计算方向和设置是否一致。
- same problem：是否属于同一任务，而非只共享大领域词。
- method_variant：是否是同一方法族的变体，而非关键词相似。
- conflicting_claim：是否满足任务、数据集、指标、实验设置、结论方向均可比。
- transferable_method：是否有前提条件、约束和失败模式。

目标状态：综合卡和冲突关系不只是“发现相似”，而是能说明为什么可比、哪里不可比、还缺什么证据。

### 3.5 Gap 生命周期不完整

当前 Gap 已能从问题、限制和可迁移关系中生成，并能被每日推荐命中更新。但 Gap 仍像候选列表，还没有完整变成研究机会管理对象。

需要补强的字段和流程：

- 问题定义：研究问题、目标任务、约束条件。
- 假设：可检验的 hypothesis。
- 证据：support evidence、counter evidence、相关 synthesis。
- 新颖性：已有工作覆盖程度、被新论文命中记录。
- 可行性：最小实验、所需数据、baseline、预期成本。
- 价值：潜在论文贡献、适合投稿方向、风险。
- 状态流转：candidate -> reviewing -> pursue -> experiment_planned -> rejected / covered。
- 变更记录：每次被新论文覆盖、人工推进、拒绝理由都写入历史。

目标状态：`promoted_to_idea` 不是终点，而是进入可执行研究计划的入口。

### 3.6 写作层仍是素材拼接

当前 `compose_related_work_snippet` 基本按卡片内容拼接，跨论文对比表也只选每类最高分卡。它能快速产出素材，但还不能稳定生成论文级段落。

需要补强：

- 写作前先生成段落计划：主题、论证顺序、引用组。
- 相关工作按问题、方法、数据集、实验结果分组。
- 每句话绑定来源卡片和证据，不允许无来源事实句。
- 自动提示冲突和不可比结论，避免把不同设置下的结果硬放在一起。
- 对比表支持多卡合并、空缺提示、冲突标注，而不是每类取一条。
- 导出支持“带证据脚注版”和“投稿清洁版”两种格式。
- 写作素材被引用后反哺卡片优先级。

目标状态：写作层不是把卡片拼成段落，而是把 verified claims 和 synthesis 组织成可检查的学术论证。

### 3.7 行为反馈闭环还不够细

推荐已经使用部分阅读行为和 Gap 命中信号，但知识资产本身还缺少足够的使用反馈。

应记录的行为：

- 用户确认 / 废弃 / 合并了哪些卡片。
- 哪些卡片被加入写作素材。
- 哪些卡片被问答命中并被用户点击。
- 哪些 synthesis 被确认或废弃。
- 哪些 Gap 被推进、拒绝或被新论文覆盖。
- 哪些推荐最终被阅读、生成卡片、进入写作或实验计划。

这些信号应反哺：

- 卡片抽取批判器。
- 本地检索排序。
- 每日推荐评分。
- Gap 优先级。
- 写作素材排序。

### 3.8 缺少研究资产健康面板

目前系统是否健康主要靠用户体感。科研第二大脑需要持续暴露资产质量。

建议增加健康指标：

- 无证据 verified 卡数量。
- draft 卡积压数量和平均滞留时间。
- 低质量 AI 候选比例。
- synthesis 卡中 supporting papers < 2 的异常数量。
- Gap 中无 support evidence / 无 minimum experiment 的数量。
- 写作素材无 source_card_id / source_quote 的数量。
- Dify 同步失败数量。
- 本地问答命中本地图谱比例。
- 导出引用缺失率。
- 孤立 evidence 数量。

目标状态：用户能一眼知道知识库是“在生长”还是“在堆垃圾”。

## 4. 优先级路线

### P0：本地知识独立问答与降级

优先级最高。因为 Dify 依赖会削弱第二大脑的本地可用性。

任务：

- `/library/ask` 支持 `graph_only` 或自动 Dify fallback。
- Dify disabled 时仍允许本地卡片 / 证据 / 关系问答。
- 本地检索从 LIKE 抽象成独立 retrieval service。
- 返回来源中明确区分本地图谱和 Dify。

验收：

- 关闭 Dify 后，本地 verified 卡仍能被问答检索并回答。
- 单测覆盖 Dify 正常、Dify 不可用、本地无结果三种路径。

### P1：证据链贯穿写作与综合

任务：

- synthesis 卡强制保留 supporting evidence。
- writing snippet 支持多个 source card / evidence。
- 导出 Markdown 可附带 evidence trace。
- 禁止无证据 synthesis 被 verified。

验收：

- 任意写作片段能回溯到至少一张卡片和原文 quote。
- synthesis 卡 supporting_card_ids、supporting_paper_ids、evidence_ids 非空且一致。

### P2：语义验证增强

任务：

- 为 relation verifier 增加可比性 schema：task、dataset、metric、setting、claim_direction。
- `conflicting_claim` 默认必须经过 LLM 或人工确认才能进入 verified。
- synthesis 卡显示 positive_checks / negative_checks。

验收：

- 冲突关系人工抽检准确率明显高于纯规则版。
- 不可比关系进入 `needs_more_evidence`，并说明缺失项。

### P3：Gap 生命周期升级

任务：

- 增加 Gap 详情页或详情抽屉。
- 增加 pursue / experiment_planned 状态。
- Gap 关联 synthesis、cards、evidence、hit papers。
- 新论文命中 Gap 时追加历史记录。

验收：

- 一个 Gap 能从候选推进到最小实验计划。
- 被新论文覆盖时能更新 coverage_status 和历史记录。

### P4：写作层升级

任务：

- 写作前生成 outline / paragraph plan。
- 相关工作按主题组装，不再简单拼接卡片。
- 对比表支持多证据单元、冲突标注和缺失项提示。
- 导出分为 clean / traceable 两种模式。

验收：

- 生成段落中每个事实句都有来源卡或证据。
- 对比表能显示空缺、冲突和引用来源。

### P5：健康面板与反馈闭环

任务：

- 新增研究资产健康 API 和页面。
- 记录卡片使用、问答点击、写作引用、Gap 推进等行为。
- 将行为信号接入推荐、检索排序和卡片优先级。

验收：

- 健康面板能定位无证据卡、孤立证据、积压 draft、同步失败。
- 用户行为能改变推荐和本地检索排序。

## 5. 设计约束

- 不新增第四套知识系统，继续沿 `Evidence -> Claim -> Synthesis -> Gap -> Draft` 脊柱演进。
- Dify 是增强源，不是本地结构化知识能力的前置条件。
- 所有事实性产物都必须可回溯到 `paper_id / page / quote`。
- 自动生成只产候选，高风险抽象必须有验证或人工确认。
- 页面可以简化，但状态和错误不能隐藏。
- 检索、导出、状态流转必须可测试。

## 6. 最终目标

平台应从“能读论文并生成知识卡”升级为：

```text
读入论文
  -> 提取可信证据
  -> 形成高价值 Claim
  -> 跨论文验证和综合
  -> 产生可追踪 Gap
  -> 支撑问答、推荐和写作
  -> 用户行为反哺下一轮知识生长
```

衡量标准不是功能数量，而是：

- 知识是否可信。
- 证据是否可追溯。
- 检索是否可独立运行。
- 综合是否可解释。
- Gap 是否能推进研究。
- 写作是否能产出可检查文本。
- 系统是否能暴露自身健康状态。
