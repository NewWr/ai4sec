# 知识空间与 Dify Library 合并方案

日期：2026-06-08

## 结论

建议将 `/knowledge-spaces` 与 `/library` 合并为一个“知识库中心”，以本地知识空间作为主入口，Dify 数据集、文档、检索和问答作为每个知识空间的外部索引能力嵌入其中。`/library` 不再作为独立导航页面，保留为兼容重定向或隐藏入口。

这不是简单地把两个页面拼在一起，而是明确两层关系：

- 本地知识空间是系统的组织层和决策层，决定内容属于主研究库、每日推荐库、原文库还是解读库。
- Dify dataset 是外部检索索引层，只负责文档索引、检索、文档预览和 RAG 问答。

## 当前问题

### 页面职责重叠

`/knowledge-spaces` 当前负责：

- 展示本地空间：`main_source`、`main_analysis`、`daily_source`、`daily_analysis`
- 编辑空间名称、说明、`dify_dataset_id`
- 管理空间条目：移动、复制、移除、备注、重试同步
- 查看每个条目的本地论文、解读报告和同步状态

`/library` 当前负责：

- 展示 Dify datasets
- 浏览 Dify documents
- 预览 Dify 文档 markdown
- Dify 检索
- 本地检索：论文、片段、卡片、关系、写作素材
- Dify RAG 问答

用户视角下两者都叫“知识库”，但实际一个是本地组织关系，一个是外部索引服务，因此当前分裂会造成认知成本。

### 每日知识库没有出现在 Dify

当前 `.env` 只配置了：

- `DIFY_DEFAULT_DATASET_ID`
- `DIFY_ANALYSIS_DATASET_ID`

未配置：

- `DAILY_RECOMMENDATION_SOURCE_DATASET_ID`
- `DAILY_RECOMMENDATION_ANALYSIS_DATASET_ID`

代码中每日推荐空间如果没有专用 `dify_dataset_id`，会跳过 Dify 同步，不会回退到主库。这是为了避免“只是浏览的每日推荐论文”污染主研究库。这个隔离原则是正确的，但页面没有提供“创建/绑定每日 Dify dataset”的能力，导致用户只能看到本地每日空间，看不到 Dify datasets 中对应的每日知识库。

## 目标状态

统一入口建议为：

- 主路径：`/knowledge-spaces`
- 页面标题：`知识库中心`
- `/library`：重定向到 `/knowledge-spaces?view=search`，或保留隐藏兼容入口

统一页面按“空间优先”组织：

1. 左侧：知识空间列表
   - 主研究原文知识库
   - 主研究解读知识库
   - 每日推荐原文知识库
   - 每日推荐解读知识库

2. 右侧：当前空间详情，使用标签页
   - `内容`：本地空间条目管理
   - `Dify 索引`：绑定/创建 dataset、同步状态、Dify 文档列表
   - `检索`：当前空间范围内的本地检索和 Dify 检索
   - `问答`：基于当前空间绑定 dataset 的 RAG 问答
   - `设置`：空间名称、说明、dataset id、同步策略

这样用户先选择“我要看哪个知识库”，再决定“管理内容、看 Dify 文档、检索还是问答”。

## 信息架构设计

### 知识空间列表

每个空间卡片显示：

- 名称
- 空间类型：主库/每日推荐、原文/解读
- 本地条目数
- Dify dataset 绑定状态
- 同步统计：synced / pending / failed / skipped

每日推荐空间如果没有绑定 Dify dataset，应显示明确状态：

- `未绑定 Dify dataset`
- 操作：`创建 Dify 数据集`、`绑定已有 Dataset ID`

### 内容标签页

复用当前 `/knowledge-spaces` 的条目管理能力：

- 类型筛选：全部、论文原文、解读报告、知识卡片、写作素材、Dify 文档
- 条目列表
- 备注编辑
- 移动/复制到其他空间
- 移除关联
- 重试同步
- 跳转本地论文和解读结果

增强点：

- 条目列表增加分页，不再固定 `limit=200`
- 每个条目显示绑定的 Dify document id
- 同步失败时显示错误摘要和重试按钮

### Dify 索引标签页

这是合并后的关键新增部分。

空间未绑定 dataset 时：

- 显示说明：该本地空间还没有对应的 Dify dataset，因此不会出现在 `localhost:3080/datasets`
- 提供两个操作：
  - `创建 Dify 数据集并绑定`
  - `绑定已有 Dify Dataset ID`

空间已绑定 dataset 时：

- 显示 dataset id
- 显示 Dify 文档列表
- 支持文档 markdown 预览
- 支持打开 Dify 原始页面，如果能构造链接
- 支持对当前空间条目批量重试同步

### 检索标签页

检索范围默认跟随当前空间：

- 本地检索：优先限定当前空间关联的 `paper_id/run_id/card/snippet`
- Dify 检索：使用当前空间的 `dify_dataset_id`

如果当前空间没有 Dify dataset：

- Dify 检索按钮禁用
- 本地检索仍可用

检索模式：

- `本地论文`
- `本地片段`
- `知识卡片`
- `写作素材`
- `Dify 文档`

### 问答标签页

默认使用当前空间绑定的 Dify dataset。

如果当前空间没有 Dify dataset：

- 显示“需要先创建或绑定 Dify dataset”
- 不应静默回退到主库

如果用户确实想跨空间问答，可提供范围选择：

- 当前空间
- 主研究库
- 每日推荐库
- 全部已绑定 Dify dataset

第一阶段建议只做“当前空间”，避免引入多 dataset 聚合问答复杂度。

## 后端改造方案

### P0：补齐 Dify dataset 生命周期接口

新增或扩展接口：

- `POST /api/knowledge-spaces/{space_id}/dify-dataset`
  - 创建 Dify dataset
  - 成功后写入 `knowledge_spaces.dify_dataset_id`
  - 默认名称使用空间中文名，例如 `每日推荐原文知识库`

- `PATCH /api/knowledge-spaces/{space_id}`
  - 当前已支持更新 `dify_dataset_id`
  - 需要在前端形成“绑定已有 dataset”的明确流程

- `GET /api/knowledge-spaces/{space_id}/dify-documents`
  - 读取当前空间的 `dify_dataset_id`
  - 调用现有 `dify_client.list_documents(dataset_id=...)`

- `GET /api/knowledge-spaces/{space_id}/dify-documents/{document_id}/markdown`
  - 调用现有 `dify_client.get_markdown(document_id, dataset_id=...)`

- `POST /api/knowledge-spaces/{space_id}/dify-search`
  - 限定当前空间 dataset 检索
  - 不再要求前端手动选择 dataset

### P1：空间级同步统计

新增服务函数：

- `knowledge_spaces.space_sync_summary(space_id)`

统计：

- `total_items`
- `pending`
- `running`
- `synced`
- `failed`
- `skipped`
- `dify_dataset_id`
- `dify_bound`

可以合并到 `KnowledgeSpaceResponse`，减少前端额外请求。

### P1：空间级本地检索

当前 `localLibrarySearch(mode, query, top_k)` 是全局检索。合并后需要支持空间范围：

- `GET/POST /api/knowledge-spaces/{space_id}/local-search`
- 参数：`mode`、`query`、`top_k`
- 服务层根据 `knowledge_space_items` 限定 `paper_id/run_id/card/snippet`

第一阶段可以先保留全局本地检索，仅在 UI 文案标明“全局本地检索”。第二阶段再做空间过滤。

## 前端改造方案

### 页面路径

推荐：

- `/knowledge-spaces` 改名为“知识库中心”
- `/library` 改为重定向到 `/knowledge-spaces?view=search`
- 导航只保留一个入口：`知识库`

### 组件拆分

当前两个页面都偏大，合并前需要拆组件：

- `KnowledgeSpaceSidebar`
- `KnowledgeSpaceSettingsPanel`
- `KnowledgeSpaceItemsPanel`
- `KnowledgeSpaceDifyPanel`
- `KnowledgeSpaceSearchPanel`
- `KnowledgeSpaceAskPanel`
- `DifyDocumentPreview`

已有 `LibraryDocumentPreview`、`SplitPane` 可以复用。

### 推荐布局

保留工作台式布局，不做营销页：

- 顶部：标题、刷新、当前空间状态
- 左侧：空间列表
- 右侧：标签页内容
- Dify 文档预览使用右侧抽屉或 SplitPane，不要新开独立页面

## Dify dataset 创建/绑定策略

### 创建名称

默认 dataset 名称：

- `AI4Sec - 主研究原文`
- `AI4Sec - 主研究解读`
- `AI4Sec - 每日推荐原文`
- `AI4Sec - 每日推荐解读`

### 创建后的行为

创建成功后：

1. 保存 dataset id 到 `knowledge_spaces.dify_dataset_id`
2. 刷新空间列表
3. 将该空间中 `sync_status=skipped` 且 item_kind 为 `paper/run` 的条目标为 `pending`
4. 提供“立即批量同步”按钮，但不自动大规模同步，避免误触发大量请求

### 对 `.env` 的关系

`.env` 中的 `DIFY_DEFAULT_DATASET_ID` 和 `DIFY_ANALYSIS_DATASET_ID` 仍作为系统启动默认值。

网页绑定后的 `knowledge_spaces.dify_dataset_id` 应作为运行时配置优先级更高的来源。这样每日推荐 dataset 可以不写入 `.env`，也能稳定保存在 SQLite 中。

## 兼容策略

### `/library`

保留三种选择：

1. P0 推荐：导航隐藏 `/library`，但路径继续可访问
2. P1：访问 `/library` 自动跳转 `/knowledge-spaces?view=search`
3. P2：完全移除旧页面

建议采用 P0，风险最低。

### 已有 Dify 链接

已有报告中可能有 `/library?doc=<document_id>` 链接。

合并后需要兼容：

- `/library?doc=xxx` 仍能打开旧页面，或重定向到 `/knowledge-spaces?view=dify&doc=xxx`
- 如果没有 dataset id，使用默认 dataset 查找

## 分阶段实施计划

### P0：统一入口与 dataset 绑定

目标：解决“每日知识库不在 Dify datasets 里”的直接问题。

任务：

- 新增空间级创建 Dify dataset API
- 在 `/knowledge-spaces` 空间设置区增加：
  - 绑定已有 dataset id
  - 创建 Dify dataset
  - dataset 绑定状态
- 导航中将 `知识空间` 改为 `知识库`
- 暂时保留 `/library`

验收：

- 每日推荐原文/解读空间可以一键创建 Dify dataset
- 创建后能在 `localhost:3080/datasets` 看到对应 dataset
- 空间 `dify_dataset_id` 自动保存
- 每日空间未绑定时不会回退到主库

### P1：把 Dify 文档浏览合并进知识空间

任务：

- 在 `/knowledge-spaces` 增加 `Dify 索引` 标签页
- 展示当前空间 dataset 的文档列表
- 支持 markdown 预览
- 支持按当前空间 dataset 重试同步

验收：

- 用户不进入 `/library` 也能查看 Dify 文档
- 每个空间只显示自己绑定 dataset 的文档
- 未绑定 dataset 时提示明确，不报错

### P2：合并检索与问答

任务：

- 将 `/library` 的 Dify 检索迁移到 `/knowledge-spaces` 的 `检索` 标签页
- 将 `/library` 的 RAG 问答迁移到 `问答` 标签页
- 默认 dataset 使用当前空间绑定 dataset
- 保留本地检索能力

验收：

- 当前空间内可以直接检索 Dify 文档
- 当前空间内可以直接问答
- 未绑定 Dify dataset 时，本地检索可用，Dify 检索和问答禁用

### P3：收敛旧 `/library`

任务：

- 从导航移除 `/library`
- `/library` 保留兼容跳转或隐藏入口
- 更新报告中的文档引用链接生成逻辑

验收：

- 主导航只剩一个“知识库”
- 旧链接不失效
- 用户路径不再出现两个相似知识库页面

## 风险与取舍

### 风险 1：合并页面过重

如果把空间管理、文档浏览、检索、问答全部放在一个页面，页面状态会复杂。

控制方式：

- 必须拆成面板组件
- 标签页懒加载
- Dify 文档预览独立组件

### 风险 2：Dify dataset 创建失败

Dify proxy 可能没有创建 dataset 权限或配置不完整。

控制方式：

- 创建失败返回清晰错误
- 仍允许手动粘贴 dataset id
- 本地空间功能不依赖 Dify

### 风险 3：每日推荐污染主库

如果合并时为了方便检索而默认回退主库，会破坏原隔离设计。

控制方式：

- 每日空间无 dataset 时必须跳过 Dify，不得回退主库
- UI 明确提示“未绑定，不同步”

### 风险 4：旧链接失效

报告中可能引用 `/library?doc=...`。

控制方式：

- P0/P1 保留旧页面
- P3 再做重定向

## 推荐最终设计

最终只保留一个用户入口：`知识库`。

用户流程：

1. 进入 `/knowledge-spaces`
2. 选择空间：主研究原文、主研究解读、每日推荐原文、每日推荐解读
3. 在同一空间中完成：
   - 本地内容管理
   - Dify dataset 创建/绑定
   - 同步重试
   - Dify 文档浏览
   - 检索
   - 问答

这个设计能保留当前本地知识空间的安全边界，又能消除 `/library` 与 `/knowledge-spaces` 的概念重复。

## 最小可执行版本

如果只做一轮实现，建议优先完成：

1. `/knowledge-spaces` 页面增加“创建 Dify dataset 并绑定”
2. 每个空间显示 Dify dataset 绑定状态
3. 每个空间增加 Dify 文档列表与预览
4. 导航将“知识空间”改为“知识库”，暂时隐藏“Library”

这能直接解决当前最困扰的问题：每日推荐知识库在本地存在，但 Dify datasets 中没有对应数据集，且用户需要在两个页面之间来回理解。
