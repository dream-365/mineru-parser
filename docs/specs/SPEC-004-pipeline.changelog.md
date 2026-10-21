# Changelog: SPEC-004 Pipeline

## [2026-10-21] - 评审修订：管道无状态、状态信封失败语义、组件私有化

- **修改类型**: Changed / Added
- **影响范围**: §1.1（痛点列表）、§1.2（差距表 / 迁移表）、§1.3（Goal 7 / 9 / 11 / 13）、§1.4（Non-Goals 新增三条）、§1.5（威胁模型）、§2（删除原 US-5，US-6 ~ US-8 顺延为 US-5 ~ US-7；AC 重编；新增 AC-1.11 / 1.12 / 2.10 / 5.13 / 5.14 / 7.8）、§3.1（组件表 / 包结构 / 时序图）、§3.2（参数表 / 输出 / 状态枚举）、§3.3（签名 / 稳定性表 / 返回契约 / 集成示例）、§3.4（编排阶段表 / 异常处理规则）、§4（边界表重写为"信封 / 异常"双列）、§5（Phase 2 ~ 4 / AC↔测试映射）、§6.1（R-2 / R-3 改写，新增 R-13 / R-14）、§6.2（Q-13 / Q-14 / Q-15 闭环）、§6.3（新增后续优化项 B-1）
- **变更原因**: 评审给出四项裁决，均改变公共契约：管道改为**无状态**（不提供任务恢复 / 崩溃续跑）；结果元数据与解析产物解耦为 `ParseResult.data` + 独立字段；失败改为**状态信封**语义；组件**不可注入且不对外暴露**。另按要求把"同一任务重复调用"登记为后续优化项。
- **具体内容**:
  - **无状态（Q-13）**：删除原 US-5"任务恢复与崩溃安全"及其 8 条 AC；移除 `on_task_created` 回调与 `task_id=` 恢复入口。管道不持有跨调用任务状态，也不接受外部任务标识续跑；崩溃后未完成的任务由调用方按 `data_id` 对账（R-7）。`uri` 由可选改为**必填**。
  - **`ParseResult` 重构（Q-5 修订）**：不再**继承** `ExtractedResult`，改为独立 `TypedDict`，解析产物收在 `data` 属性（类型仍是 `ExtractedResult`），元数据 `task_id` / `data_id` / `zip_url` 与之平级。`ExtractedResult` 的既有契约一字未改。
  - **状态信封与失败语义（Q-14）**：`ParseResult` 扩为六键信封（`status` / `data` / `task_id` / `data_id` / `zip_url` / `error`），新增 `ErrorMessage` 类型（`stage` / `error_type` / `message` / `cause_type`）。`parse()` **默认不抛异常**：已知异常（`MinerUParserError` 家族）封装为 `ErrorMessage` 并以 `status="failed"` 返回；**兜不住的异常**（未知类型 / `MemoryError` / `KeyboardInterrupt` / `SystemExit`）原样抛出。新增 `raise_on_error` 参数（默认 `False`）切换为异常模式，此时已知异常原样抛出、超时翻译为 `PipelineTimeoutError`。`PipelineStage` 增补 `config` 取值（参数校验阶段）。
  - **组件私有化（Q-15）**：`parse()` 签名**移除** `client` / `downloader` 参数（新增 AC-2.10 断言公共面无组件参数）；三个组件包改为私有 `mineru_parser._client` / `_downloader` / `_extractor`，公开导入路径 `mineru_parser.client` 等不再提供（AC-2.3）。测试缝保留在**内部**编排器（AC-7.8），不进入公共面。
  - **后续优化项 B-1**：R-3（重复调用即重复计费）转出风险表，登记为 §6.3 的待立项优化项——"同一任务的重复调用抑制"，给出三条候选方向。
  - **新增风险 R-13**（信封把业务失败与内部错误放进同一返回路径）、**R-14**（组件不可注入导致公共面无测试缝，依赖内部私有缝）。
  - AC 重新编号：删除原 US-5 的 8 条后，原 US-6 ~ US-8 顺延为 US-5 ~ US-7，其 AC 同步由 AC-6.x / 7.x / 8.x 改为 AC-5.x / 6.x / 7.x；总数 67 条，编号连续无缺口。
- **说明**: 本轮**未改变**四阶段编排、端到端预算与超时检查点、生命周期与所有权、遥测口径、端到端资源预算（290 MiB）与"不改 SPEC-001/002/003 任何契约"的立场。改动集中在**公共面**（返回值结构、失败语义、组件可见性）与**非目标清单**。§3.4 的异常处理规则与 §4 的边界表同步改为"信封 / 异常"双列，两种模式的信息量必须一致。
- **状态**: Draft。

## [2026-10-21] - 评审决议：引入 `ParseResult`，关闭 6 项待决事项

- **修改类型**: Changed
- **影响范围**: Header（更新时间）、§1.2（顶层 API 面迁移表）、§1.3 Goal 1、§1.4（Non-Goals 新增三条）、§2（AC-1.1 重写、新增 AC-1.9 / AC-1.10、AC-2.2、AC-3.4、AC-6.9）、§3.1（两处图 + 时序图）、§3.2（输出结构改为 `ParseResult`）、§3.3（签名 / 稳定性表 / 返回契约 / 集成示例）、§3.4（编排阶段表第 8 行）、§5（Phase 1 / Phase 4 / AC↔测试映射）、§6.2（Q-3 / Q-4 / Q-5 / Q-6 / Q-7 / Q-10 闭环，新增 Q-12）
- **变更原因**: 评审对 6 项待决事项给出裁决。其中 **Q-5 的结论改变了 `parse()` 的返回类型**——结果元数据（`task_id` / `data_id` / `zip_url`）改由新的管道层类型 `ParseResult` 承载，而非仅经回调与日志传递；其余裁决为"保持现状 / 不提供"，只落到 Non-Goals 与已闭环清单。
- **具体内容**:
  - **`ParseResult`（Q-5，P0）**：新增管道层 `TypedDict`，**结构化继承** `ExtractedResult`，新增 `task_id: str` / `data_id: str | None` / `zip_url: str` 三个键；`parse()` 的返回类型由 `ExtractedResult` 改为 `ParseResult`（AC-1.1）。**`ExtractedResult` 的既有契约一字未改**——"恰好两个键"约束（SPEC-003 AC-1.2）仍然只约束 `extract_result`，`ParseResult` 是扩展而非修改。取值来源固定为终态结果：`task_id` = `MinerUTaskResult.provider_task_id`（沿用 SPEC-001 AC-9.2 的优先级），`data_id` = `MinerUTaskResult.data_id`，`zip_url` = `MinerUTaskResult.zip_url`（AC-1.9）。运行时仍是普通 `dict`。
  - **`zip_url` 的敏感性（新增 AC-1.10）**：`ParseResult.zip_url` 逐字返回、**不做脱敏**（与 SPEC-001 / 002 的既有语义一致），但管道**不得**把它写入任何日志或指标标签；AC-6.9 的标签禁止清单同步加入 `zip_url`。
  - **AC-1.1 重写**：返回 `ParseResult`（恰好五个键），其中 `pages` / `images` 的形状与取值与 `extract_result` 逐字相同；明确管道层不得改变组件层契约。
  - **顶层导出（AC-2.2）**：保留清单加入 `ParseResult`。
  - **Q-3 闭环**：`PipelineTimeoutError` **保持独立**——只继承 `PipelineError`，四个异常家族继续互不继承。代价是"统一捕获超时"需显式列出 `PipelineTimeoutError` / `MinerUTimeoutError` / `ResultDownloadTimeoutError`，README 必须给出该写法。
  - **Q-4 闭环**：**不提供** `on_stage` 阶段回调；阶段信息只经 `on_error` 回调、日志与指标暴露。
  - **Q-6 闭环**：**不提供**"只提交不解析"的入口（`parse(submit_only=True)`）；批量作业由调用方直接使用 `mineru_parser.client`。已写入 §1.4 Non-Goals。
  - **Q-7 闭环**：**不提供**结果包的断点续传 / 本地缓存（结果包体积有限）。已写入 §1.4 Non-Goals。
  - **Q-10 闭环**：`mineru_parser.pipeline` **不作为公开子包**，管道实现保持内部。已写入 §1.4 Non-Goals。
  - 图与示例同步：§1.1 链路图与 §3.1 门面图的产出节点改为 `ParseResult`；§3.1 时序图的返回改为 `ParseResult {pages, images, task_id, data_id, zip_url}`；§3.3 集成示例改用 `result` 变量并演示元数据读取。
  - §5 任务拆解：Phase 1 增加"`ParseResult` 类型定义与顶层导出"；Phase 4 增加"README 补写 `ParseResult` 的五个键与 `zip_url` 敏感提示"；AC↔测试映射增加 `test_parse_result_metadata_provenance` 与 `test_zip_url_never_logged_or_labelled`。
- **说明**: 本轮**未改变**四阶段编排、端到端预算、超时翻译、异常原样透传、生命周期与所有权、遥测口径与端到端资源预算的既有契约；改动集中在**返回类型**（`ExtractedResult` → `ParseResult`）与顶层导出清单。剩余开放项：Q-8（`data_id` 幂等）、Q-9（跨调用 Session 复用）、Q-11（峰值内存实测校正）、Q-12（`ParseResult` 是否附加运行期字段）。
- **状态**: Draft。

## [2026-10-21] - 初始设计：唯一公共入口 `parse` 与端到端编排契约

- **修改类型**: Added
- **影响范围**: 全文（1.1 ~ 6.2）
- **变更原因**: SPEC-001（client）、SPEC-002（downloader）、SPEC-003（extractor）三个组件契约清晰但彼此解耦，编排成本、生命周期责任、失败阶段归因与端到端预算全部落在调用方；库的顶层同时导出约 40 个名字，使用者无法判断"该用哪个入口"。本期新增 SPEC-004 作为门面：把三者串成一条流水线，并把"整个项目对外只暴露一个 `parse` 函数"固化为可断言的契约。
- **具体内容**:
  - 新增 `docs/specs/SPEC-004-pipeline.md`，状态标记为 `Draft`。
  - **唯一公共入口**：顶层 `mineru_parser.__all__` 收缩为**一个函数** `parse` + 签名/返回值所需的类型（`ExtractedResult` / `ExtractedImage` / `ExtractionLimits` / `MetricHook` / `PipelineStage` / `MinerUParserError` / `__version__`）。`MinerUApiClient`、`AsyncResult`、`ResultDownloader`、`extract_result`、`canonicalize_member_path` 与三族具体异常类移出顶层，仍可从 `mineru_parser.client` / `mineru_parser.downloader` / `mineru_parser.extractor` 子模块导入，行为契约不变（属**破坏性变更**，项目版本 0.1.0）。
  - **公共 API 契约**：`parse(uri, *, task_id=None, model_version="vlm", data_id=None, timeout=None, deadline_epoch=None, limits=None, client=None, downloader=None, on_update=None, on_task_created=None, on_error=None, on_metric=None, correlation_id=None) -> ExtractedResult`。`client` / `downloader` 为明确标注的"高级 / 测试缝"，是签名中唯一允许出现的组件级参数。
  - **四阶段编排**：submit → wait → download → extract；任一阶段失败即中止后续阶段（失败于 submit / wait 时不得发起下载）。恢复路径（`task_id=`）跳过 submit 阶段，阶段序列为 wait → download → extract。
  - **端到端预算**：单一 `timeout` / `deadline_epoch` 覆盖全部四个阶段；等待阶段把剩余预算下传给 `AsyncResult.wait(timeout=remaining)`；预算检查点为"每阶段开始前 + 提取结束后"。
  - **超时统一**：`MinerUTimeoutError`（等待）与 `ResultDownloadTimeoutError`（下载）翻译为 `PipelineTimeoutError(stage=...)`，原始异常以 `__cause__` 保留；**其余阶段异常一律原样透传**（同一对象，`is` 相同），保持三个组件既有的捕获语义。
  - **异常体系**：新增 `PipelineError` → `PipelineConfigurationError` / `PipelineTimeoutError`，继承库级根 `MinerUParserError`，与 `MinerUError` / `ResultDownloadError` / `ResultExtractionError` 互不继承。
  - **所有权与生命周期**：管道拥有自建的 client / downloader 与中间 ZIP 流并在返回前按"流 → downloader → client"顺序关闭；注入的实例不得关闭；返回值与流生命周期解耦。
  - **崩溃安全**：提交成功后、进入等待前调用 `on_task_created(task_id)`（异常被隔离并记录 `mineru.pipeline.on_task_created.failed`）。
  - **阶段归因**：封闭枚举 `PipelineStage`（submit / wait / download / extract）；失败时经 `on_error(stage, 原始异常)` 回调、日志与指标标签暴露。
  - **端到端资源预算**：给出含压缩侧 ZIP 缓冲的峰值公式 $M_{\text{peak}} \approx \texttt{max\_bytes} + \texttt{max\_total\_image\_bytes} + \texttt{max\_manifest\_bytes}\times(1+k) + M_{\text{zipinfo}} + M_{\text{result}}$；默认档位约 **290 MiB**（SPEC-003 的 240 MiB 未计入压缩侧 50 MiB）；在 1 GiB 容器中默认并发度 **≤ 3**，并发 4 需把 `max_total_image_bytes` 降到 ≤ 126 MiB。
  - **遥测**：`mineru.pipeline.total` / `duration_ms` / `stage.duration_ms` / `pages` / `images` / `image_bytes`，`outcome` ∈ {success, config_error, timeout, stage_error, unexpected}，`stage` 取自封闭枚举；`correlation_id` 透传三组件。
  - **不改动 SPEC-001 / 002 / 003 的任何契约**；组件的独立测试继续覆盖它们。
  - 任务拆解分四阶段（契约与骨架 / 编排实现 / 测试与验收 / 文档与迁移），并给出 AC ↔ 计划测试名映射。
  - 登记 R-1 ~ R-12 风险与 Q-3 ~ Q-11 待决事项（Q-0 ~ Q-2 已闭环：顶层 API 面收敛、端到端预算归属、超时统一）。
- **说明**: 本 Spec **不新增**任何解析能力，也不改变三个组件的行为契约；它只负责编排、所有权、预算、归因与顶层 API 面的收敛。所有"内部"表述（`mineru_parser.pipeline` 包、组件子模块导入）均为**高级 / 内部**层，不获得 SemVer 保证；唯一稳定公共函数是 `parse`。
- **状态**: Draft。
