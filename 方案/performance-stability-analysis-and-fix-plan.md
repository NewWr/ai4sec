# AI4Sec 平台速度与稳定性问题分析报告及修复方案

> 日期：2026-06-12
> 范围：全栈代码审查（backend / frontend / dify-proxy / docker-compose）
> 目标：定位平台"卡顿、假死、加载不出、运行慢"的根因，并给出分批修复计划

---

## 总览

| 优先级 | 问题数 | 典型表现 |
|--------|--------|----------|
| 🔴 P0 | 6 | 429 风暴、页面永久转圈、分析时长翻倍、线程池饥饿、重复计费 |
| 🟠 P1 | 8 | 外部调用握手开销、刷新按钮挂起、SQLite 串行排队、运行页掉帧 |
| 🟡 P2 | 8 | 日志无限增长、死代码、事件表膨胀、SSE 重连耗尽 |

---

## 🔴 P0 — 高优先级（直接造成卡顿/假死/429 风暴）

### 1. 速率限制按"代理 IP"计数 → 所有浏览器共享同一限速桶

**位置**：`backend/app/rate_limit.py:8`

`get_remote_address` 作为限速 key，但前端所有 `/api` 请求都经 Next.js rewrite 代理（`frontend/next.config.ts`），后端看到的源 IP 永远是 frontend 容器 IP。

**后果**：默认 `60/minute` + 各端点限额（`/papers` 30/min、`/runs/recent` 30/min、`/runs/{id}` 30/min）是**全体用户共享**的。同时打开 2-3 个标签页就会触发 429，而前端 `catch(() => {})` 静默吞错 → 表现为"页面永久转圈、列表加载不出"。**这很可能就是"不稳定"的主因之一。**

**修复**：
- 限速 key 改为信任 `X-Forwarded-For`（Next.js 代理时附带真实 IP），或对内部代理来源放宽
- 把轮询类端点（`/runs/recent`、`/runs/{id}`）限额调大

---

### 2. 运行页双通道轮询 + SSE 叠加，放大请求量

**位置**：`frontend/src/app/paper/[paperId]/run/[runId]/page.tsx:263-286`、`frontend/src/components/RecentRuns.tsx:56`

SSE 正常连接时，5 秒一次的兜底轮询仍无条件运行（`getRun` + `getPaper` = 12-24 请求/分钟/标签页）；`RecentRuns.tsx:56` 又叠加 5s 轮询且页面不可见时不暂停。配合问题 #1，429 几乎必然出现。且 `setInterval` 不等待上一个请求完成，后端卡顿时请求会堆积。

**修复**：
- SSE `isConnected` 时把轮询间隔退避到 30s 或暂停
- 监听 `visibilitychange` 在后台标签页停止轮询
- fetch 加 `AbortController` 超时

---

### 3. Lens 模式 5 个 section 串行 LLM 调用 — 总时长 ≈ 5× 单次时延

**位置**：`backend/app/workflows/lens_subgraph.py:758-812`

`for spec in _lens_section_specs(...)` 逐个 `await llm.chat(...)`。5 个 section 的上下文互相独立，完全可并行。

**修复**：`asyncio.gather` + `Semaphore(3)` 并行，保持结果顺序拼接。Lens 模式总时长可缩短 **60-70%**。

---

### 4. 中文翻译逐 chunk 串行 — 翻译阶段时长翻倍

**位置**：`backend/app/workflows/translate.py:100-106`

长报告切成 5-10 个 chunk 后逐个 `await _translate_chunk(...)`。

**修复**：并行翻译（保序 gather + 信号量），zh 模式总时长可减 **30-50%**。

---

### 5. dismiss/取消后 MinerU 解析线程继续跑（重复解析 + 重复计费）

**位置**：`backend/app/api/runs.py:451-453`、`backend/app/adapters/mineru_adapter.py:323`

`task.cancel()` 无法中断 `asyncio.to_thread(_parse_pdf_sync, ...)` —— 底层线程会继续轮询直至 30 分钟超时。用户取消后重新提交同一论文，会再开一个解析线程：**双倍占用线程池 + 双倍消耗 MinerU Token**。

**修复**：
- 在 `_poll_until_done_sync` 的 `on_poll` 回调中检查取消标志（如 `threading.Event`，由 dismiss 设置）提前退出
- 或改用 `httpx.AsyncClient` 重写轮询为纯异步

---

### 6. MinerU 同步轮询长期占用默认线程池

**位置**：`backend/app/adapters/mineru_adapter.py:240-298`

每个解析任务在 `to_thread` 里 `time.sleep(6)` 轮询最长 1800s。默认线程池只有 `min(32, cpu+4)` 个线程，且 `paper_search/http_client.py` 的所有 HTTP、EasyScholar 查询（`llm_rank.py:299` `run_in_executor`，内含 `time.sleep` 重试）都共享这个池。5 个并发 run + sphere 检索时存在**线程池饥饿**风险，表现为所有 `to_thread` 调用排队、整体卡顿。

**修复**：
- 最佳方案：把 MinerU 客户端改为 httpx 异步轮询（`asyncio.sleep` 不占线程）
- 过渡方案：给 MinerU 单独的 `ThreadPoolExecutor`

---

## 🟠 P1 — 中优先级（性能损耗 / 边界条件不稳）

### 7. 每次翻译请求新建 HTTP 连接

**位置**：`backend/app/services/translation_cache.py:148`

`async with httpx.AsyncClient(...)` 每次 DeepLX 调用都做 TCP+TLS 握手。每日推荐一次刷新 = 80 篇 × 2 字段 = **160 次握手**。

**同类问题**：`main_graph.py:301,342`、`sphere_subgraph.py:293,430,1052`、`publication_rank/tavily_search.py:85`

**修复**：复用 `http_clients.get_default_http_client()`。

---

### 8. dify-proxy 每请求新建 AsyncClient 且无重试

**位置**：`dify-proxy/app.py:40-48`、`181-194`

`_client()` 每请求新建；`get_markdown`（181-194）串行两次上游调用。每个 run 要做 2 次 Dify 同步，握手开销累积。

**修复**：模块级单例 client（lifespan 管理）+ 对 5xx 加一次重试。

---

### 9. /daily/refresh 同步等待全流程，请求可挂数分钟

**位置**：`backend/app/api/daily.py:66-79`

`await` 整个 `refresh_daily_recommendations`（多 topic × 80 篇 × 评分 × 串行翻译）。前端按钮长时间无响应，Next.js 代理可能先超时，但后端仍在跑 → 用户重复点击 → 重复刷新。

**修复**：
- 改为后台任务 + 返回 job id（复用 runs 的事件机制）
- 或至少把每篇的标题/摘要翻译 gather 并行

---

### 10. 全局单 aiosqlite 连接：读写全串行 + 事务期间脏读

**位置**：`backend/app/db/database.py:15,896-925`

所有读写共用一个连接（aiosqlite 内部串行执行）。`transaction()` 持有 `_write_lock` 期间，其他协程的 `fetch_one`/`fetch_all` 仍可通过同一连接读到未提交数据（同连接无隔离），若回滚则读到幻影数据。同时一个慢查询（如 `list_papers` 的 4 层子查询 JOIN，`papers.py:328-391`）会阻塞所有并发请求。

**修复**：读操作走独立的只读连接池（WAL 模式下读写并行是 SQLite 强项，当前架构完全没利用）；写保持单连接+锁。

---

### 11. persist_run_event 每个进度事件新开 SQLite 连接

**位置**：`backend/app/workflows/progress.py:21-35`

`connect → PRAGMA → BEGIN IMMEDIATE → MAX(seq)+1 → INSERT → close`，每事件一次；sphere 模式一个 run 几十个事件。且新连接未设 `busy_timeout`（仅靠 sqlite3 默认 5s），写争用高峰时事件可能**静默丢失**（except 后 return 0）→ 断线重连后进度回放缺失。

**修复**：复用主连接（在 `_write_lock` 内做 MAX+INSERT），或维护内存 seq 计数器。

---

### 12. paper_ir_json 在每个节点反复反序列化

**位置**：`backend/app/workflows/main_graph.py` — `detect_document_parts`(151)、`sync_dify_library`(213)、`_extract_doi_from_ir`(258)、`_extract_arxiv_id_from_ir`(280)、`enrich_metadata`(456)

各节点各自 `PaperIR.model_validate_json(...)`。大论文 IR 数 MB，每次 parse+validate 是纯 CPU（几十-几百 ms），**阻塞事件循环** → 表现为运行期间 SSE/接口间歇性卡顿。

**修复**：解析一次缓存在 state（LangGraph state 限 JSON 的话，可用模块级 `WeakValueDictionary` 按 run_id 缓存），或把 validate 放 `to_thread`。

---

### 13. MarkdownRenderer 无 memo，每次父渲染全量重解析

**位置**：`frontend/src/components/MarkdownRenderer.tsx:172-183`、`frontend/src/app/paper/[paperId]/run/[runId]/page.tsx:508-547`

`prepareCitationMarkdown(normalizeDisplayMath(content), ...)` 每次渲染重新执行，ReactMarkdown + KaTeX 全管道重跑。运行页每个 SSE 事件都触发父组件重渲染（`useRunStream` 的 `setEvents`），数万字符的报告会明显掉帧。

**修复**：
- `React.memo` 包裹 + `useMemo` 缓存 processed
- `run/[runId]/page.tsx:508-547` 的 `savedHighlights`/`progressSteps` 同理需 `useMemo`（目前每渲染重建数组/重 JSON.parse）

---

### 14. SSE 流每 2 秒 2 次 DB 查询/客户端

**位置**：`backend/app/api/runs.py:479-486`

`event_generator` 每轮 `_fetch_run_event_messages` + `fetch_one(status)`，与内存队列收到的消息重复。N 个观看者 = 2N 查询/2s，全部在单连接上排队（叠加问题 #10）。

**修复**：DB 回放只做一次（连接建立时），之后只依赖内存队列 + 低频（30s）状态兜底检查。

---

## 🟡 P2 — 低优先级（健壮性/运维）

### 15. docker-compose.yml 缺少运维配置

- frontend/dify-proxy 无 healthcheck
- 三个服务都没有 logging 轮转配置（json-file 默认无限增长，backend 日志量大，长期会吃满磁盘）
- 无内存限制（MinerU 解压 2GB zip 上限 + PDF 缓冲可能瞬时高内存）

**修复**：加 `logging: {driver: json-file, options: {max-size: 10m, max-file: "3"}}` 和 `mem_limit`。

### 16. init_db 大量 `except Exception: pass`

**位置**：`database.py:127-150` 等

列迁移失败与"列已存在"不区分，真实 schema 错误被吞掉。

**修复**：至少 `logger.debug` 区分错误类型。

### 17. runs.py 死代码

**位置**：`runs.py:128/144`

`subscribers` 是 set，`hasattr(subscribers, "put")` 永远为 False（疑似旧接口残留），可删。

### 18. 上传哈希/写盘在事件循环内

**位置**：`papers.py:221-235`

100MB 文件累计 ~400ms 事件循环阻塞。

**修复**：chunk 处理放 `to_thread`。

### 19. run_progress_events 无 TTL 清理

只在删除论文时清理，长期膨胀。

**修复**：启动时清理 7 天前的事件。

### 20. useRunStream 重连上限 5 次

**位置**：`useRunStream.ts:106`

后端重启超过 ~15s 后 SSE 永久断开，仅靠轮询兜底（进度步骤不再更新）。

**修复**：重连预算改为时间窗（如 2 分钟内不限次数）。

### 21. i18n Provider value 每渲染新对象

**位置**：`i18n.tsx:481`

`value={{ locale, setLocale, t }}` 建议 `useMemo`，避免全树消费者无谓重渲染。

### 22. papers/page.tsx 2024 行单组件、30+ useState

任何筛选输入都整页重渲染。

**修复**：拆分 + 列表行 memo（当前 200 篇上限尚可接受，属预防性）。

---

## 建议修复顺序

| 批次 | 内容 | 预期收益 |
|------|------|----------|
| ① | #1 限速 key + #2 前端轮询治理 | 消除 429 假死，稳定性立竿见影 |
| ② | #3 Lens 并行 + #4 翻译并行 | 分析时长缩短 40-60% |
| ③ | #5/#6 MinerU 取消与异步化 | 消除线程池饥饿与重复计费 |
| ④ | #7/#8 连接复用 + #9 daily 后台化 | 外部调用延迟下降、刷新不阻塞 |
| ⑤ | #10/#11/#14 SQLite 读写分离 | 高并发下查询不再排队 |
| ⑥ | #12/#13 序列化与渲染优化 | 运行页流畅度 |

> 执行建议：从批次①开始（改动小、风险低、收益最大），每批修完重启容器验证后再进行下一批。

---

## 附录：问题与文件映射速查

| # | 文件 | 行号 |
|---|------|------|
| 1 | `backend/app/rate_limit.py` | 8 |
| 2 | `frontend/src/app/paper/[paperId]/run/[runId]/page.tsx` / `RecentRuns.tsx` | 263-286 / 56 |
| 3 | `backend/app/workflows/lens_subgraph.py` | 758-812 |
| 4 | `backend/app/workflows/translate.py` | 100-106 |
| 5 | `backend/app/api/runs.py` / `mineru_adapter.py` | 451-453 / 323 |
| 6 | `backend/app/adapters/mineru_adapter.py` | 240-298 |
| 7 | `backend/app/services/translation_cache.py` 等 | 148 |
| 8 | `dify-proxy/app.py` | 40-48, 181-194 |
| 9 | `backend/app/api/daily.py` | 66-79 |
| 10 | `backend/app/db/database.py` | 15, 896-925 |
| 11 | `backend/app/workflows/progress.py` | 21-35 |
| 12 | `backend/app/workflows/main_graph.py` | 151, 213, 258, 280, 456 |
| 13 | `frontend/src/components/MarkdownRenderer.tsx` | 172-183 |
| 14 | `backend/app/api/runs.py` | 479-486 |
| 15 | `docker-compose.yml` | — |
| 16 | `backend/app/db/database.py` | 127-150 |
| 17 | `backend/app/api/runs.py` | 128, 144 |
| 18 | `backend/app/api/papers.py` | 221-235 |
| 19 | DB: `run_progress_events` 表 | — |
| 20 | `frontend/src/hooks/useRunStream.ts` | 106 |
| 21 | `frontend/src/lib/i18n.tsx` | 481 |
| 22 | `frontend/src/app/papers/page.tsx` | 全文件 |
