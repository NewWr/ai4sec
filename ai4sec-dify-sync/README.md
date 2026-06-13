# AI4Sec Dify Sync

AI4Sec 内置同步工具：扫描已完成 MinerU/PaperIR 解析的论文，生成 Markdown/text，上传到 Dify Dataset，并在独立 SQLite 状态库中记录去重和失败状态。

## 设计取舍

- 作为 `AI4Sec/ai4sec-dify-sync/` 子目录随主仓库发布。
- 不写入 AI4Sec 的 `app.db`，默认状态库为 `./state/dify_syncs.db`。
- 读取顺序优先使用 `paper_ir.json`，缺失时回退到 AI4Sec `blocks` 表。
- 去重键为 `paper_id + dataset_id + source_hash`；内容未变化且已同步则跳过。
- Dify 上传失败只影响本工具状态，不影响 AI4Sec 解析、阅读和问答流程。

## 安装

```bash
cd ai4sec-dify-sync
python -m venv .venv
. .venv/bin/activate
pip install -e .
```

## 配置

```bash
export AI4SEC_DATA_DIR=../docker-data
export AI4SEC_APP_DB=../docker-data/app.db

# 直接连 Dify API：
export DIFY_BASE_URL=http://localhost
export DIFY_DATASET_API_KEY='dataset-api-key'
export DIFY_DATASET_ID='dataset-id'

# 或者连 dify-proxy：
# export DIFY_PROXY_BASE_URL=http://localhost:3002
# export DIFY_DATASET_ID='dataset-id'
```

Docker 常驻运行：

```bash
cd ai4sec-dify-sync
cp .env.example .env
# 编辑 .env 中的 DIFY_DATASET_API_KEY / DIFY_DATASET_ID
docker compose up -d --build
```

## 使用

同步一次：

```bash
ai4sec-dify-sync once
```

常驻轮询：

```bash
ai4sec-dify-sync watch --interval 30
```

查看状态：

```bash
ai4sec-dify-sync status
ai4sec-dify-sync status --paper-id <paper_id>
```

重试失败项：

```bash
ai4sec-dify-sync retry
ai4sec-dify-sync retry --paper-id <paper_id>
```

只打印待上传内容，不调用 Dify：

```bash
ai4sec-dify-sync once --dry-run
```

## 状态表

工具会在自己的状态库中创建：

```sql
CREATE TABLE IF NOT EXISTS dify_syncs (
  paper_id TEXT NOT NULL,
  dataset_id TEXT NOT NULL,
  dify_document_id TEXT DEFAULT '',
  source_hash TEXT DEFAULT '',
  status TEXT DEFAULT 'pending',
  error_msg TEXT DEFAULT '',
  attempts INTEGER DEFAULT 0,
  last_synced_at TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (paper_id, dataset_id)
);
```
