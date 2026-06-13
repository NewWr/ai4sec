# AI4Sec 性能修复 — P9 实施方案与 Task Prompts

> 日期：2026-06-12
> 角色：P9 Tech Lead（只写 Prompt 不写代码，P8 agent 团队执行）
> 输入：`方案/performance-stability-analysis-and-fix-plan.md`（22 问题 / 6 批次）
> 项目根：`/media/dc/M2_DATA/Paper_read/AI4Sec`

---

## 0. 管理摘要

- **组织拓扑**：1 个 P9（本会话）+ 6 个 P8 执行 agent（A–F）+ 1 个集成验证 agent（G），按 3 个波次投放，波内并行、波间串行。
- **编排原则**：按**文件冲突矩阵**分波，不按原批次号分波——原批次①⑥都改 `run/[runId]/page.tsx`，批次③⑤都改 `runs.py`，直接并行必然冲突。
- **验收原则**：每个 agent 必须交付**运行证据**（pytest 输出 / npm build 输出 / curl 结果），空口"已完成"按未完成处理。
- **降级范围**：#22（papers/page.tsx 2024 行拆分）**降级为 backlog**——预防性重构、高风险低收益，不进本期。MinerU 全异步重写（#6 最佳方案）降级为 backlog，本期走低风险的独立线程池 + 取消令牌方案。

## 1. 架构决策记录（ADR）

### ADR-1 对分析报告的事实修正
- **MinerU 适配器真实路径是 `backend/app/services/mineru_adapter.py`**（报告误写为 `adapters/`）。
- `_poll_until_done_sync`（`mineru_adapter.py:240`）**已有 `sleep_fn`/`time_fn`/`on_poll` 注入参数**，且 `tests/test_mineru_timeout.py` 已示范注入测试。取消机制直接利用此接缝：`cancel_event.wait(sleep_s)` 替换 `time.sleep`，改动极小。
- `hasattr(subscribers, "put")` 死代码共 **3 处**：`runs.py:128`、`runs.py:144`、`progress.py:66`。

### ADR-2 限速 key（#1）
自定义 `key_func`：仅当 `request.client.host` 属于可信代理网段（env `TRUSTED_PROXY_CIDRS`，默认 docker 私网 + 127.0.0.1）时取 `X-Forwarded-For` 最左 IP，否则取 remote address。**不无条件信任 XFF**（伪造头绕过限速）。同时把轮询型端点限额调到与前端轮询节奏匹配（`/runs/recent`、`/runs/{id}` ≥ 120/min）。

### ADR-3 Lens / 翻译并行化（#3/#4）
`asyncio.gather` + `Semaphore(3)`，**按索引回填保序**。Lens 的强约束：progress 事件将从"顺序 running→done"变为"乱序并发"——前端 progressSteps 按 step 名 key 渲染需先核实兼容，agent 必须先读前端再动后端。任一 section 失败需取消兄弟任务（TaskGroup 或 gather 后统一抛错）。

### ADR-4 MinerU（#5/#6）
本期两件事：① 模块级 `threading.Event` 取消注册表（`parse_id → Event`），dismiss 端点查 run→parse 映射并 set；轮询用 `event.wait(sleep_s)` 即取消即醒。② MinerU 专用 `ThreadPoolExecutor`（如 max_workers=8），与默认线程池隔离。全异步 httpx 重写进 backlog。

### ADR-5 SQLite 读写分离（#10/#11/#14）
- 写：维持单连接 + `_write_lock`（不动）。
- 读：新增只读连接池（`file:...?mode=ro&immutable=0` URI，WAL 下读写并行），`fetch_one/fetch_all` 走读池。**消除"读到写连接未提交数据"的脏读**。
- `persist_run_event`：不再每事件新建连接，改走主写连接（`_write_lock` 内 MAX+1 + INSERT 同事务）。
- SSE 循环：DB 回放只做一次（连接建立时），之后纯内存队列驱动 + 30s 低频状态兜底。

### ADR-6 daily 后台化（#9）
POST `/daily/refresh` 改为：启动 `asyncio.Task` + 立即返回 `{job_id, status:"started"}`；新增 GET 状态端点；进行中重复 POST 返回当前 job（幂等防重复刷新）。前端按钮改轮询状态。每篇翻译 gather 并行（Semaphore 4）。

### ADR-7 IR 缓存（#12）
模块级 `dict[run_id] → (digest, PaperIR)`，容量上限 8 条 LRU，run 终态时清除。各节点经 `get_cached_paper_ir(state)` 取用。不用 WeakValueDictionary（缓存是唯一持有者，立即被回收，无效）。

## 2. 波次编排与文件冲突矩阵

| 波次 | Agent | 覆盖问题 | 文件集（互斥） |
|------|-------|---------|---------------|
| **W1** 并行 | **A** 后端限速 | #1 | `backend/app/rate_limit.py`、`backend/app/config.py`、各 api/*.py 的 limit 装饰器 |
| **W1** 并行 | **B** 前端治理 | #2 #13 #20 #21 | `frontend/src/**`（独占全部前端文件） |
| **W1** 并行 | **C** 工作流并行化 | #3 #4 | `backend/app/workflows/lens_subgraph.py`、`translate.py` |
| **W2** 并行 | **D** MinerU | #5 #6 + #17(runs.py 死代码) | `backend/app/services/mineru_adapter.py`、`backend/app/api/runs.py`(dismiss 段) |
| **W2** 并行 | **E** 连接复用+daily | #7 #8 #9 + #15 #18 | `translation_cache.py`、`main_graph.py`(仅 client 段)、`sphere_subgraph.py`(仅 client 段)、`tavily_search.py`、`dify-proxy/app.py`、`api/daily.py`、`api/papers.py`、`docker-compose.yml` |
| **W3** 串行 | **F** SQLite+IR 缓存 | #10 #11 #12 #14 + #16 #19 + #17(progress.py) | `db/database.py`、`workflows/progress.py`、`api/runs.py`(SSE 段)、`main_graph.py`(IR 段)、`services/paper_ir.py` |
| **W4** 串行 | **G** 集成验证 | 全部 | 只读 + docker 操作 |

冲突消解：`runs.py` D(W2)→F(W3) 串行；`main_graph.py` E(W2)→F(W3) 串行；`page.tsx` 全归 B 一人。

**W0（投放前置，P9 亲自执行）**：确认 AI4Sec 是 git 仓库且工作区干净（或先建基线提交/备份）。无版本控制不投放任何写代码的 agent。

---

## 3. Task Prompts（六要素，可直接投放）

### ── Task Prompt A：后端限速修复 ──

**①背景**：所有前端请求经 Next.js rewrite 代理（`frontend/next.config.ts:11-18`），后端 slowapi 以 `get_remote_address` 为限速 key（`backend/app/rate_limit.py:8`），所有真实用户共享 frontend 容器 IP 的同一个桶，2-3 个标签页即触发 429。
**②目标**：限速按真实客户端 IP 计数；轮询端点限额与前端节奏匹配；429 不再在正常使用中出现。
**③范围**：`backend/app/rate_limit.py`、`backend/app/config.py`（新增 `TRUSTED_PROXY_CIDRS` 设置，默认 `127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`）、`backend/app/api/runs.py`/`papers.py` 等文件中轮询类端点的 `@limiter.limit` 值（先 grep `limiter.limit` 全量盘点再改）。
**④约束**：仅当直连 IP 在可信网段才信任 `X-Forwarded-For` 最左值，否则用 remote address（防伪造头绕过）；不得改动任何业务逻辑；`/runs/recent`、`/runs/{run_id}` 调至 ≥120/min，`/runs/{id}/stream` 保持低限额但确认单页面双标签不超限。
**⑤验收标准**：a) 新增/修改的 key_func 有单元测试（伪造 XFF + 可信/不可信源 IP 两组用例）；b) `cd backend && pytest` 全绿并贴输出；c) 用 curl 携带 `X-Forwarded-For` 对运行中服务打 >60 req/min 验证不同 IP 不互相挤兑（如无运行环境，用 TestClient 写集成测试代替并说明）。
**⑥交付物**：`[P8-COMPLETION]` 汇报：改动文件清单+diff 摘要、测试输出原文、限额盘点表（端点→旧值→新值→理由）、风险声明。

### ── Task Prompt B：前端请求治理 + 渲染优化 ──

**①背景**：运行页 SSE 与 5s 兜底轮询无条件叠加（`frontend/src/app/paper/[paperId]/run/[runId]/page.tsx:262-286`），`RecentRuns.tsx:39-61` 再叠 5s 轮询且后台标签不停；`MarkdownRenderer.tsx:172-190` 无 memo 每渲染全管道重跑；`useRunStream.ts:106` 重连上限 5 次；`i18n.tsx:481` Provider value 每渲染新对象。
**②目标**：单标签页稳态请求量降为原来的 ~1/6；后台标签零轮询；SSE 断线在 2 分钟时间窗内持续重连；大报告渲染不掉帧。
**③范围**：仅 `frontend/src/**`：上述 4 文件 + `page.tsx:508-547` 的 `savedHighlights`/`progressSteps` useMemo 化。
**④约束**：a) SSE `isConnected` 时轮询退避到 30s（不是停——SSE 静默失败仍需兜底），断开时恢复 5s；b) 监听 `visibilitychange`，hidden 时暂停所有轮询，可见时立即触发一次；c) 轮询 fetch 加 AbortController（超时 10s），且上一请求未返回不发下一个（in-flight 标志）；d) API 层对 429 不再静默吞——节流地 console.warn + 指数退避；e) `MarkdownRenderer` 用 `React.memo` + `useMemo(processed, [content, evidenceAnchors])`，**不得改变渲染输出 HTML**；f) `useRunStream` 重连改为时间窗预算（2 分钟内不限次，指数退避封顶 8s 不变）；g) 不引入新依赖。
**⑤验收标准**：a) `cd frontend && npm run build` 通过并贴输出；b) 现有 lint 通过；c) 提供手测核查单：打开运行页 DevTools Network，稳态 1 分钟内 `/api/runs` 请求 ≤4 次、切后台 1 分钟 0 次（如无法运行容器，给出逐文件行为变更说明供人工复核）。
**⑥交付物**：`[P8-COMPLETION]`：文件清单+每文件行为变更前后对比表、build/lint 输出原文、手测核查单。

### ── Task Prompt C：Lens 与翻译并行化 ──

**①背景**：`backend/app/workflows/lens_subgraph.py:758-812` 5 个独立 section 串行 `await llm.chat`（总时长≈5×单次）；`backend/app/workflows/translate.py:100-106` 翻译 chunk 串行。
**②目标**：Lens 总时长降 60%+，zh 翻译阶段降 40%+，输出 markdown 与串行版**逐字节等价**（顺序保持）。
**③范围**：仅 `lens_subgraph.py`、`translate.py`，及对应测试文件（`tests/test_lens_segmented.py` 扩展）。
**④约束**：a) `asyncio.Semaphore(3)` 控并发（LLM 网关限流保护），并发度提为模块常量；b) 结果按原索引回填保序拼接；c) 任一任务失败→取消未完成兄弟任务→抛原异常（保持现有 `_emit_progress(failed)` + raise 语义）；d) **动手前先读** `frontend` 中消费 progress 事件的渲染逻辑（grep step 名），确认乱序 running/done 事件不破坏进度 UI——若有顺序假设，在 prompt 汇报中说明并保持每 section 的 running→done 成对完整；e) 翻译失败维持"保留英文原文"的现有降级行为；f) 单 chunk ≤`_MAX_CHUNK_CHARS` 时仍走单次调用快路径。
**⑤验收标准**：a) 新增单测：mock llm.chat（不同延迟乱序返回）断言输出顺序正确、断言并发峰值 ≤3、断言失败传播；b) `cd backend && pytest` 全绿贴输出；c) 汇报中给出前端 progress 兼容性核查结论（引用具体前端代码行）。
**⑥交付物**：`[P8-COMPLETION]`：diff 摘要、测试输出、并发安全论证（哪里共享状态、为何无竞态）、前端兼容核查结论。

### ── Task Prompt D：MinerU 取消令牌 + 独立线程池 ──

**①背景**：dismiss 仅 `task.cancel()`（`backend/app/api/runs.py:451-453`），无法中断 `asyncio.to_thread(_parse_pdf_sync,...)`（`backend/app/services/mineru_adapter.py:323`）内 `time.sleep(6)` 轮询（最长 3600s）——取消后线程照跑，重提交即双倍解析双倍计费；且占用全局默认线程池引发饥饿。注意：`_poll_until_done_sync`（240 行）**已有 `sleep_fn`/`on_poll` 注入参数**，`tests/test_mineru_timeout.py`、`tests/test_run_cancellation.py` 已有测试基建。
**②目标**：dismiss 后 ≤6s 内解析线程退出；MinerU 轮询不再占用默认线程池。
**③范围**：`mineru_adapter.py`、`runs.py`（仅 dismiss 端点段 + 顺手删 `runs.py:128,144` 的 `hasattr(subscribers,"put")` 死代码）、新增测试。
**④约束**：a) 取消机制：模块级注册表 `dict[parse_id, threading.Event]`，`parse_pdf` 进入时注册、finally 注销；轮询等待用 `if cancel_event.wait(sleep_s): raise MinerUCancelledError(...)` 替换 `sleep_fn(sleep_s)` 默认实现（保留参数注入兼容现有测试）；b) dismiss 端点：查该 run 关联的进行中 parse_id（先读 schema/`mineru_parses` 表确认关联方式）并 set 事件；c) 取消后 `mineru_parses` 状态写 `failed` + error_msg='Cancelled by user'；d) 独立 `ThreadPoolExecutor(max_workers=8, thread_name_prefix="mineru")` 模块级单例，`parse_pdf` 用 `loop.run_in_executor(_mineru_pool,...)` 替换 `asyncio.to_thread`；e) 不改 MinerU API 调用协议。
**⑤验收标准**：a) 新增单测：注入假 client + 真 Event，set 后断言 1 个 sleep 周期内抛 Cancelled；b) 现有 `test_mineru_timeout.py`/`test_run_cancellation.py` 不回归；c) `cd backend && pytest` 全绿贴输出。
**⑥交付物**：`[P8-COMPLETION]`：diff 摘要、测试输出、取消链路时序说明（dismiss→Event→线程退出→DB 状态）、线程池容量选择依据。

### ── Task Prompt E：连接复用 + daily 后台化 + 运维配置 ──

**①背景**：`translation_cache.py:148` 等 6 处每请求新建 `httpx.AsyncClient`（TCP+TLS 握手 ×160/天）；`dify-proxy/app.py:40-48` 同病且无重试；`api/daily.py:66-79` 同步 await 全量刷新可挂数分钟（用户重复点击→重复刷新）；`api/papers.py:221-235` 上传哈希在事件循环内；docker-compose 无日志轮转/部分无 healthcheck。后端已有现成单例 `backend/app/services/http_clients.py:51 get_default_http_client()`。
**②目标**：外部 HTTP 调用全部复用连接池；daily 刷新非阻塞且幂等；容器日志有界。
**③范围**：`translation_cache.py`、`main_graph.py`（**仅** httpx client 调用点 301/342 附近，不碰其他）、`sphere_subgraph.py`（仅 293/430/1052 client 点）、`publication_rank/tavily_search.py:85`、`dify-proxy/app.py`、`api/daily.py` + `services/daily_recommendations.py`（翻译 gather 并行段）、`api/papers.py:221-235`、`docker-compose.yml`。
**④约束**：a) 后端各处改用 `get_default_http_client()`，**不得 close 共享 client**；个别调用点超时与默认 30s 不同的，用 `client.request(..., timeout=...)` 每请求覆盖，不新建 client；b) dify-proxy：模块级单例 client + FastAPI lifespan 关闭 + 对 5xx/网络错误重试 1 次（幂等 GET 才重试，POST 不重试）；c) daily：POST 启动后台 `asyncio.Task`、立即返回 job 状态，进行中重复 POST 返回同一 job（幂等）；新增 GET 状态端点；每篇标题/摘要翻译 `gather`+`Semaphore(4)`；**检查前端 daily 页面调用处并同步适配**（按钮 loading + 轮询状态）；d) papers.py 上传哈希/写盘移入 `asyncio.to_thread`；e) compose：三服务加 `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}`，frontend/dify-proxy 补 healthcheck，backend 加 `mem_limit`（读 .env 评估合理值并说明依据）。
**⑤验收标准**：a) `grep -rn "httpx.AsyncClient(" backend/app dify-proxy` 输出中除 `http_clients.py` 和测试外为 0 处新建（贴 grep 输出）；b) `cd backend && pytest` 全绿（daily 相关测试 `test_daily_recommendations.py` 不回归，必要时更新）；c) `docker compose config` 校验通过贴输出；d) daily 幂等性有单测覆盖。
**⑥交付物**：`[P8-COMPLETION]`：调用点改造清单（文件:行→改法）、测试与 grep 输出、daily 前后端协议说明、compose 变更 diff。

### ── Task Prompt F：SQLite 读写分离 + 事件持久化收敛 + IR 缓存 ──

**①背景**：全局单 aiosqlite 连接（`db/database.py:15-16`），`fetch_one/fetch_all`(896-925) 无锁直用写连接——慢查询阻塞一切且事务期间脏读；`workflows/progress.py:21-38` 每个进度事件新建连接（BEGIN IMMEDIATE，无 busy_timeout，失败静默 return 0）；SSE 循环每轮 2 次 DB 查询/客户端（`api/runs.py:479-486`）；`main_graph.py` 5+ 节点重复 `PaperIR.model_validate_json`（数 MB JSON，阻塞事件循环）。
**②目标**：读写并行（WAL 真正生效）；进度事件零新建连接零静默丢失；SSE 稳态零重复 DB 轮询；IR 每 run 只反序列化一次。
**③范围**：`db/database.py`、`workflows/progress.py`（含 66-70 死代码清理）、`api/runs.py`（仅 SSE generator 段——注意 agent D 已改过此文件，先 git diff 看清现状）、`main_graph.py`（仅 IR 反序列化点：151/213/258/280/456 附近）、`services/paper_ir.py`（或新建缓存模块）、`docker` 不碰。另捎带：`database.py:127-150` 迁移 `except Exception: pass` 改为区分"列已存在"与真实错误（logger.debug/warning）；启动时清理 7 天前 `run_progress_events`（#19）。
**④约束**：a) 写路径**完全不动**（单连接+`_write_lock` 语义保持）；b) 读池：3-4 条只读连接（URI `mode=ro`）round-robin，每条配 WAL/busy_timeout/row_factory，`fetch_one/fetch_all` 改走读池；**逐一核查现有调用方**是否有"写后立读自己未提交数据"的依赖（事务内读必须仍走写连接——给 `transaction()` 返回的 conn 上的读保持原样）；c) `persist_run_event` 改走主写连接 `_write_lock` 内同事务 MAX+1+INSERT，失败改 `logger.warning`（不再 debug 级静默）；d) SSE：连接建立时回放一次 DB 历史，此后只消费内存队列（`asyncio.wait_for(queue.get(), timeout=...)`），每 30s 兜底查一次 status（防 done 事件丢失），保持现有终态/timeout 帧协议不变（`test_run_stream_resume.py` 不回归）；e) IR 缓存按 ADR-7：`run_id→(digest,ir)` LRU≤8，run 终态清除，digest 不匹配即重建；f) **此任务动核心基建，每完成一个子项立即跑全量 pytest，不许攒**。
**⑤验收标准**：a) 新增单测：读池并发读不被写锁阻塞（写事务挂起期间读可返回）、事务内读写一致、persist_run_event 序号单调且并发安全、IR 缓存命中/失效；b) `cd backend && pytest` 全绿贴输出（尤其 `test_run_stream_resume.py`、`test_run_cancellation.py`）；c) 汇报 SSE 改造前后每客户端 DB 查询次数对比。
**⑥交付物**：`[P8-COMPLETION]`：diff 摘要、全量测试输出、读写分离设计说明（连接生命周期/异常回收）、调用方核查清单（哪些地方依赖写后立读、如何处置）。

### ── Task Prompt G：集成验证（W4） ──

**①背景**：A–F 已合入，需端到端证伪。
**②目标**：容器环境下全链路冒烟通过，无 429、无回归。
**③范围**：只读代码 + docker compose 操作 + curl/浏览器验证，发现问题**只汇报不修**（回派原 agent）。
**④约束**：按 `start_ai4sec.sh` / compose 流程构建启动；验证模式真实环境（需 MinerU/LLM key 的链路如不可用，验证到可达边界并明确标注）。
**⑤验收标准**：核查单逐项贴证据——a) `docker compose build` 三镜像成功；b) 全部容器 healthy；c) 双标签页同开 papers 列表 + 运行页 2 分钟无 429（后端日志 grep）；d) 提交一个 run：进度事件顺序正常、dismiss 后后端日志确认 MinerU 轮询 ≤6s 停止；e) daily refresh 立即返回 job id 且状态可查；f) `pytest` 全绿 + `npm run build` 通过。
**⑥交付物**：`[P8-COMPLETION]`：核查单（项→命令→输出摘录→结论）、发现的问题列表（severity + 归属 agent）。

---

## 4. 汇报与升级协议

- 统一格式：`[P8-COMPLETION] agent / 任务 / 改动文件 / 验证证据(原文) / 风险与遗留 / 自审三问（根因消除了吗？同类问题排查了吗？验证充分吗？）`
- 失败 2 次 → 按 PUA 协议升级 L1，换本质不同方案；L2+ 上报 P9 重新决策。
- 任何 agent 不得越界改非自己范围的文件；发现范围外问题→记录上报，P9 重新分派。

## 5. 风险与回滚

| 风险 | 缓解 |
|------|------|
| W0 前置：项目无 git 基线 | **投放前必须确认**：AI4Sec 是 git 仓库且 `git status` 干净，否则先 `git init` + 基线提交 |
| F 动 database.py 引发广泛回归 | 独占 W3 串行执行；写路径零改动；逐子项跑全量测试 |
| Lens 并行触发 LLM 网关限流 | Semaphore(3) 起步，常量可调；失败即取消兄弟任务 |
| daily 前后端协议变更不同步 | E 的范围明确含前端适配 + 幂等单测 |
| dify-proxy 重试造成重复写 | 仅幂等 GET 重试，POST 不重试 |

## Backlog（本期不做）

1. #22 papers/page.tsx 拆分（预防性，等列表规模增长再做）
2. MinerU httpx 全异步重写（取消令牌方案已消除主要痛点）
3. SSE 多 worker 跨进程事件总线（当前单进程部署，无需）
