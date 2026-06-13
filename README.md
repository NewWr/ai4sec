<p align="center">
  <img src="scholar.png" alt="AI4Sec logo" width="160" />
</p>

<h1 align="center">AI4Sec · 本地 AI 论文研究工作台</h1>

<p align="center">
  面向安全与 AI 研究的本地论文工作台，覆盖论文导入、PDF 解析、证据化精读、跨论文检索、知识卡片、综合发现、写作导出和知识库同步。
</p>

<p align="center">
  <a href="./README.en.md">English README</a>
</p>

## 当前能力

- **论文导入与解析**：上传 PDF 或从每日推荐导入论文，使用 MinerU 解析正文、公式、表格、图片和补充材料，并保存到本地 SQLite 与文件目录。
- **四类分析工作流**：Insight Snap 做快速价值判断，Logic Lens 做结构化深读，Research Sphere 扩展引用/相关工作图谱，Smart Q&A 自动判断问题并路由到摘要、深读、图谱或单篇问答。
- **证据化知识资产**：从分析结果生成 claim、method、dataset、metric、result、limitation、question、writing snippet 等知识卡片，保留页码、片段和来源关系。
- **本地论文库与知识空间**：管理论文元数据、分组、阅读状态、笔记、批注、AI review marks、Dify 同步状态，并把不同知识空间绑定到不同 Dify dataset。
- **每日 arXiv 推荐**：按主题抓取候选论文，打分、翻译、反馈、导入、提升到知识空间，并可直接启动后续分析。
- **跨论文检索与综合**：基于本地图谱和可选 Dify RAG 做语料检索、跨论文问答、冲突关系发现、研究 gap 候选和综合卡片沉淀。
- **写作与导出**：从已确认卡片生成 related work/method/experiment/limitation 片段，生成论文对比表，并导出 Markdown、Obsidian、BibTeX、RIS、Zotero CSL JSON。
- **运行维护**：提供 LLM 运行时设置、模型连通性测试、DeepLX 翻译、健康检查、缓存清理、限流和公开发布检查。

## 页面入口

| 页面 | 用途 |
|---|---|
| `/upload` | 上传 PDF 并创建论文记录 |
| `/daily` | 每日推荐、反馈、导入和提升 |
| `/papers` | 论文列表、分析入口、最近运行和 PDF 查看 |
| `/library` | 本地论文库、分组、状态、同步与删除 |
| `/knowledge` | 知识卡片、批量审核、合并和去重 |
| `/synthesis` | 综合卡、冲突关系和研究 gap 看板 |
| `/writing` | 草稿合成、对比表和外部导出 |
| `/knowledge-spaces` | 知识空间、dataset 绑定和 Dify 文档管理 |
| `/translate` | DeepLX 文本翻译 |
| `/health` | 解析、同步、知识资产和索引健康检查 |
| `/settings` | LLM Base URL、模型、API Key 和 reasoning effort |

## 架构

| 服务 | 技术栈 | 默认端口 | 说明 |
|---|---|---:|---|
| `frontend` | Next.js 15 / React 19 / Tailwind | `3001` | Web UI、PDF 查看、SSE 运行状态和 API 代理 |
| `backend` | FastAPI / LangGraph / SQLite | `8001` | 论文解析、LLM 工作流、知识资产、检索、导出和健康检查 |
| `dify-proxy` | FastAPI | `3002` | 可选服务，把 Dify Dataset API Key 留在服务端 |
| `ai4sec-dify-sync` | Python CLI / SQLite | - | 可选常驻服务，把已解析论文同步到 Dify Dataset |

默认只需要 `frontend` 和 `backend`。启用跨论文 RAG、Dify 文档同步或知识空间 dataset 绑定时，再启动 `dify-proxy`。

## 快速启动

需要 Docker 24+ 和 Docker Compose 2.20+。

```bash
git clone https://github.com/NewWr/ai4sec.git
cd ai4sec
cp .env.example .env
```

编辑 `.env`，至少填写：

```dotenv
LLM_BASEURL=https://api.openai.com/v1
LLM_APIKEY=
THINKING_MODELNAME=
MINERU_TOKEN=
```

如果不使用本机代理，请清空 `AI4SEC_BACKEND_PROXY`；如果使用本机代理，保持为实际代理地址。

```bash
./start_ai4sec.sh
```

访问：

- 前端：http://localhost:3001
- 后端：http://localhost:8001
- API 文档：http://localhost:8001/docs

停止服务：

```bash
docker compose --profile dify down
cd ai4sec-dify-sync && docker compose down
```

运行数据保存在 `./docker-data/`，该目录不会提交到 Git。

## 配置 Dify RAG

`dify-rag/` 是本地开发目录，不随本项目发布。公开部署时请单独部署 Dify，再让 AI4Sec 通过 `dify-proxy` 访问 Dify Dataset API。

示例：

```bash
git clone https://github.com/langgenius/dify.git dify-rag
cd dify-rag/docker
cp .env.example .env
docker compose up -d
```

在 AI4Sec 的 `.env` 中配置：

```dotenv
DIFY_DOCKER_NETWORK=docker_default
DIFY_API_BASE=http://dify-proxy:3002
DIFY_BASE_URL=http://nginx
DIFY_DATASET_API_KEY=
DIFY_DATASET_ID=
DIFY_DEFAULT_DATASET_ID=
DIFY_ANALYSIS_DATASET_ID=
DIFY_SEARCH_METHOD=keyword_search
```

启动完整服务：

```bash
./start_ai4sec.sh
```

检查集成状态：

```bash
curl http://localhost:3002/health
curl http://localhost:8001/api/library/status
```

后端返回 `enabled: true` 后，知识库页面、知识空间、Research Sphere 库内匹配、论文同步和分析同步即可使用。

`ai4sec-dify-sync/` 已内置在仓库中。一键启动脚本会使用根目录 `.env`，构建并启动该同步服务；它读取 `./docker-data/app.db` 和 PaperIR 文件，把已解析论文上传到 `DIFY_DATASET_ID`，同步状态写入 `ai4sec-dify-sync/state/dify_syncs.db`。

## 常用配置

| 变量 | 作用 |
|---|---|
| `LLM_BASEURL` / `LLM_APIKEY` / `THINKING_MODELNAME` | OpenAI 兼容 LLM 地址、密钥和可选模型列表，多个模型用逗号分隔 |
| `MINERU_TOKEN` | PDF 解析必需 |
| `EASYSCHOLAR_SECRET_KEY` / `TAVILY_KEY` | 期刊/会议分级和 Web 兜底检索 |
| `UNPAYWALL_EMAIL` / `CORE_API_KEY` / `ELSEVIER_API_KEY` / `WILEY_TDM_TOKEN` | Research Sphere 参考文献全文获取 |
| `DIFY_*` | Dify RAG、同步和知识空间 dataset 绑定 |
| `DEEPLX_API_BASE` / `DEEPLX_API_KEY` | 翻译页面和每日推荐翻译 |
| `DAILY_RECOMMENDATION_*` | 每日推荐主题、数量、阈值、自动刷新时间和目标知识空间 |
| `AUTO_KNOWLEDGE_CARDS_ENABLED` | 分析完成后自动生成知识卡片 |
| `RESEARCH_DISCOVERY_LLM_VERIFY_ENABLED` | 是否用 LLM 复核跨论文关系候选 |
| `DOCUMENT_PARTITION_ENABLED` / `SUPPLEMENTARY_INDEX_ENABLED` | 大文档分段和补充材料索引 |
| `ADMIN_API_TOKEN` | 保护 `/api/admin/*` 和运行时设置写入接口 |
| `ENABLE_DOCS=false` | 生产环境关闭 Swagger/OpenAPI |

完整变量见 [`.env.example`](./.env.example)。

## 本地开发

后端：

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
uv run pytest
```

前端：

```bash
cd frontend
npm install
npm run dev
npm run build
```

## 项目结构

```text
ai4sec/
├── backend/          # FastAPI、LangGraph 工作流、SQLite、PDF/LLM/Dify/知识资产服务
├── frontend/         # Next.js 页面、组件、PDF 查看和 API 客户端
├── dify-proxy/       # 可选 Dify Dataset API 代理
├── ai4sec-dify-sync/ # 可选 PaperIR 到 Dify Dataset 的常驻同步服务
├── docs/             # 发布与部署说明
├── scripts/          # 公开发布检查脚本
├── start_ai4sec.sh   # 一键启动 Dify、AI4Sec 和同步服务
├── docker-compose.yml
└── .env.example
```

## 隐私与公开发布

不要提交 `.env`、`docker-data/`、`.local-dev-data/`、`backend/data/`、`dify-rag/`、`ai4sec-dify-sync/state/*.db`、PDF、数据库、解析产物或任何 API Key。本仓库提供发布前检查：

```bash
scripts/check_public_release.sh
```

如果本地 Git 历史曾包含私有文件，请使用干净历史快照发布，或先用 `git filter-repo`/BFG 清理历史。

## 许可证

本项目以 [MIT License](./LICENSE) 开源。
