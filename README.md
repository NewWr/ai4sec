<p align="center">
  <img src="scholar.png" alt="AI4Sec logo" width="160" />
</p>

<h1 align="center">AI4Sec · 本地 AI 论文研究工作台</h1>

<p align="center">
  面向安全与 AI 研究的本地论文工作台：论文发现、PDF 解析、证据化精读、跨论文检索、知识卡片、翻译、知识库同步与维护检查。
</p>

<p align="center">
  <a href="./README.en.md">English README</a>
</p>

## 当前能力

- **论文上传与精读**：上传 PDF 后调用 MinerU 解析正文、公式、表格和图片，生成带页码证据引用的 AI 解读。
- **四种分析模式**：Insight Snap 快速判断价值，Logic Lens 深入公式/算法/实验，Research Sphere 梳理引用网络和研究空白，Smart Q&A 自动判断问题意图并路由。
- **本地论文库**：管理论文元数据、分类、阅读状态、分析历史、Dify 同步状态和删除/重试等维护动作。
- **每日推荐**：从 arXiv 拉取候选论文，按主题评分、翻译、反馈、导入本地论文库，并可启动后续分析。
- **知识空间与知识卡片**：沉淀观点、方法、数据集、指标、结果、局限、问题和写作片段；知识空间可绑定不同 Dify dataset。
- **语料检索与跨论文问答**：通过 Dify 知识库代理检索本地语料，并基于召回片段生成带来源的回答。
- **翻译与运行时设置**：支持 DeepLX 翻译；前端可配置 OpenAI 兼容 LLM Base URL、模型列表、API Key 和 reasoning effort。
- **健康检查**：检查解析、同步、元数据、知识资产和索引状态，辅助维护本地研究语料。

## 架构

AI4Sec 由三个可独立理解的服务组成：

| 服务 | 说明 | 默认端口 |
|---|---|---|
| `frontend` | Next.js 前端，提供上传、论文库、每日推荐、知识空间、知识卡片、翻译和设置页面 | `3001` |
| `backend` | FastAPI 后端，负责 PDF 解析、LLM 工作流、SQLite 数据、SSE 流式输出和知识资产管理 | `8001` |
| `dify-proxy` | 可选代理，隔离 Dify Dataset API Key，给后端提供数据集、文档、检索和同步接口 | `3002` |

默认部署只启动 `frontend` 和 `backend`，不要求 Dify。需要跨论文 RAG、Dify 同步或知识空间绑定 dataset 时，再启用 `dify-proxy`。

## 快速部署

### 1. 准备环境

需要 Docker 24+ 和 Docker Compose 2.20+。
下文使用 `docker compose`；如果系统只安装了独立命令，请把命令中的 `docker compose` 替换为 `docker-compose`。

```bash
git clone https://github.com/NewWr/ai4sec.git
cd ai4sec
cp .env.example .env
```

编辑 `.env`，至少填写：

```bash
LLM_BASEURL=https://api.openai.com/v1
LLM_APIKEY=你的 OpenAI 兼容 API Key
THINKING_MODELNAME=你的模型名
MINERU_TOKEN=你的 MinerU Token
```

### 2. 启动基础版

```bash
docker compose up -d --build
```

- 前端：http://localhost:3001
- 后端：http://localhost:8001
- API 文档：http://localhost:8001/docs

基础版可使用上传分析、论文库、每日推荐、知识卡片、翻译、设置和健康检查。Dify 相关页面会显示未配置或不可用。

### 3. 停止服务

```bash
docker compose down
```

上传 PDF、SQLite 数据库和生成内容保存在 `./docker-data/`，该目录不会提交到 Git。

## 配置 Dify RAG

`dify-rag/` 是开发者本机的 Dify 部署目录，不随本项目发布。公开用户应单独部署 Dify，然后让 AI4Sec 通过 `dify-proxy` 访问 Dify Dataset API。

### 方案 A：使用独立 Dify 仓库

```bash
git clone https://github.com/langgenius/dify.git dify-rag
cd dify-rag/docker
cp .env.example .env
docker compose up -d
```

Dify 默认通过 http://localhost 访问。首次打开后创建管理员账号，并在 Dify 控制台中创建或准备知识库 dataset。

### 方案 B：使用已有 Dify

只要 AI4Sec 的 `dify-proxy` 能访问你的 Dify API 地址即可。若 Dify 与 AI4Sec 都用 Docker Compose，推荐让 `dify-proxy` 加入 Dify 的 Compose 网络。

### 取得必要配置

需要三类信息：

| 变量 | 含义 |
|---|---|
| `DIFY_BASE_URL` | `dify-proxy` 访问 Dify API 的地址。同一 Docker 网络内通常是 `http://nginx`；从宿主机访问通常是 `http://host.docker.internal` 或 Dify 服务器地址 |
| `DIFY_DATASET_API_KEY` | Dify 的 Dataset / Knowledge API Key，保存在 `.env`，不要提交 |
| `DIFY_DEFAULT_DATASET_ID` / `DIFY_ANALYSIS_DATASET_ID` | 默认论文原文 dataset 和分析结果 dataset 的 ID；也可以在“知识空间”页面为不同空间绑定不同 dataset |

如果使用上面的独立 Dify Compose，查看网络名：

```bash
docker network ls | grep dify
```

常见网络名是 `docker_default` 或 `dify_default`，填入 AI4Sec 的 `.env`：

```bash
DIFY_DOCKER_NETWORK=docker_default
DIFY_API_BASE=http://dify-proxy:3002
DIFY_BASE_URL=http://nginx
DIFY_DATASET_API_KEY=你的 Dify Dataset API Key
DIFY_DEFAULT_DATASET_ID=你的论文原文 dataset id
DIFY_ANALYSIS_DATASET_ID=你的分析结果 dataset id
DIFY_SEARCH_METHOD=keyword_search
```

然后用 Dify profile 启动 AI4Sec：

```bash
docker compose --profile dify up -d --build
```

检查代理：

```bash
curl http://localhost:3002/health
curl http://localhost:8001/api/library/status
```

返回 `enabled: true` 后，前端“知识库”“知识空间”“Research Sphere 库内匹配”和论文/分析同步功能即可使用。

## 常用配置

| 变量 | 作用 |
|---|---|
| `LLM_BASEURL` / `LLM_APIKEY` / `THINKING_MODELNAME` | OpenAI 兼容 LLM 地址、密钥和模型列表，多个模型用逗号分隔 |
| `MINERU_TOKEN` | PDF 解析必需 |
| `EASYSCHOLAR_SECRET_KEY` | 期刊/会议分级 |
| `TAVILY_KEY` | 期刊分级和研究全景的 Web 兜底检索 |
| `UNPAYWALL_EMAIL` / `CORE_API_KEY` / `ELSEVIER_API_KEY` / `WILEY_TDM_TOKEN` | Research Sphere 参考文献全文获取 |
| `DEEPLX_API_BASE` / `DEEPLX_API_KEY` | 翻译页面和每日推荐翻译 |
| `DAILY_RECOMMENDATION_*` | 每日推荐主题、数量、评分阈值、自动刷新时间 |
| `AUTO_KNOWLEDGE_CARDS_ENABLED` | 分析后自动生成知识卡片 |
| `ADMIN_API_TOKEN` | 保护 `/api/admin/*` 和运行时设置写入接口 |
| `ENABLE_DOCS=false` | 生产环境关闭 Swagger/OpenAPI |

完整变量见 [`.env.example`](./.env.example)。

## 本地开发

后端：

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## 项目结构

```text
ai4sec/
├── backend/          # FastAPI、LangGraph 工作流、SQLite、PDF/LLM/Dify/知识资产服务
├── frontend/         # Next.js 前端页面和组件
├── dify-proxy/       # 可选 Dify Dataset API 代理
├── docker-compose.yml
├── .env.example
├── scripts/          # 公开发布检查脚本
└── docs/             # 发布与部署说明
```

## 公开发布与隐私

不要提交 `.env`、`docker-data/`、`backend/data/`、`dify-rag/`、PDF、数据库或任何 API Key。本仓库提供 `scripts/check_public_release.sh` 做发布前检查：

```bash
scripts/check_public_release.sh
```

## 许可证

本项目以 [MIT License](./LICENSE) 开源。
