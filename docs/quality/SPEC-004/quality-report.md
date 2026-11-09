# Spec Quality Report

- Target: `docs/specs/SPEC-004-pipeline/spec.md`
- Rubric: 1.1.0 (`1e6c4740ed85512b1657e6798e481c893fe015f4ce2a140665ff6ecb2ef7b29e`)
- Target SHA-256: `0d531211d4b9157164c6edf74ccc8f9d90ce65fb0ce5382c438ce81e1c9e2e06`
- Reviewer session: `review-spec-004`

**Headline score (core): 100.0**  |  Diagnostic score (all): 100.0

> The auditor verifies evidence presence, section placement, and score arithmetic. It does not judge whether evidence is sufficient or true.

> Normalization covers full-width ASCII, NBSP, and ideographic space; it is not full Unicode NFKC.

| Dimension | Headline | Diagnostic | Weight |
|---|---:|---:|---:|
| 背景落地 | 100.0 | 100.0 | 2 |
| 痛点证据 | 100.0 | 100.0 | 3 |
| 目标可验收 | 100.0 | 100.0 | 3 |
| 非目标边界 | 100.0 | 100.0 | 2 |
| 架构自洽 | 100.0 | 100.0 | 2 |
| 详细设计完整 | 100.0 | 100.0 | 2 |
| NFR 可度量 | 100.0 | 100.0 | 2 |
| 上线可回滚 | 100.0 | 100.0 | 2 |
| 替代方案诚实 | 100.0 | 100.0 | 2 |
| 跨章自洽 | 100.0 | 100.0 | 2 |
| 证据卫生 | 100.0 | 100.0 | 3 |

## 背景落地 (background)

- **bg.current_state** [core, level 2] — 1.1 是否写清了模块职责、核心流程与当前技术栈？
  - evidence `1.1 系统现状`: "仓库已有三个各自独立、契约清晰的组件：客户端负责“提交 → 等待”并交付 'zip_url'；下载器负责把结果包流式读进 'io.BytesIO'；提取器负责把 ZIP 解析为 '{"pages", "images"}'。三个组件刻意不耦合彼此，带来了清晰的可测试边界，但把编排成本全部推给了调用方。"
  - normalized: "仓库已有三个各自独立、契约清晰的组件:客户端负责“提交 → 等待”并交付 'zip_url';下载器负责把结果包流式读进 'io.BytesIO';提取器负责把 ZIP 解析为 '{"pages", "images"}'。三个组件刻意不耦合彼此,带来了清晰的可测试边界,但把编排成本全部推给了调用方。"
  - evidence `1.1 系统现状`: "'''mermaid flowchart LR     URI["PDF URI"] --> CLIENT["client<br/>submit / wait"]     CLIENT --> ZIPURL["zip_url"]     ZIPURL --> DL["downloader<br/>resolve"]     DL --> MEM["io.BytesIO"]     MEM --> EX["extractor<br/>extract_result"]     EX --> RESULT["{pages, images}"] '''"
  - normalized: "'''mermaid flowchart LR URI["PDF URI"] --> CLIENT["client<br/>submit / wait"] CLIENT --> ZIPURL["zip_url"] ZIPURL --> DL["downloader<br/>resolve"] DL --> MEM["io.BytesIO"] MEM --> EX["extractor<br/>extract_result"] EX --> RESULT["{pages, images}"] '''"
  - rationale: §1.1 写清三个组件的职责与核心调用链，并给出 URI→client→zip_url→downloader→BytesIO→extractor→结果的数据流；'io.BytesIO'、Session 生命周期等要素交代了当前同步 Python 组件栈。
- **bg.failure_chain** [core, level 2] — 1.2 是否有从触发到后果的分步失败链？
  - evidence `1.2 核心技术痛点`: "6. **崩溃即孤儿任务**：任务提交成功即存在于服务端；进程在等待途中崩溃，该任务无人认领，而 'data_id' 不是幂等键。"
  - normalized: "6. **崩溃即孤儿任务**:任务提交成功即存在于服务端;进程在等待途中崩溃,该任务无人认领,而 'data_id' 不是幂等键。"
  - rationale: §1.2 以 6 条编号项给出从“组合无 owner”到孤儿任务的分步失败链，每条都写了触发动作与后果。
- **bg.trigger** [core, level 2] — 1.3 是否解释了为什么现在做？
  - evidence `1.3 重构/设计动机`: "1. **三个组件已落地，缺的是最后一个集成层**：SPEC-001 / 002 / 003 的契约稳定后，管道是 0.1.0 发布前唯一缺失的公共入口。"
  - normalized: "1. **三个组件已落地,缺的是最后一个集成层**:SPEC-001 / 002 / 003 的契约稳定后,管道是 0.1.0 发布前唯一缺失的公共入口。"
  - rationale: 四条动机说明为什么在 0.1.0 发布前一次性收敛：组件契约已稳定、顶层 API 面需一次收敛、端到端预算只能由编排层提供、README 已先行改写。
- **bg.non_goals** [core, level 2] — 1.4 是否写了不做的后果与本次非目标？
  - evidence `1.4 非目标`: "**不做的后果**：不做任务恢复意味着崩溃后由调用方按 'data_id' 对账；不做幂等意味着重复调用会重复计费；不做组件注入意味着测试只能依赖内部测试缝；不做异步意味着高并发由调用方用线程 / 进程池承接。以上代价已写入第 5 章与第 7 章。"
  - normalized: "**不做的后果**:不做任务恢复意味着崩溃后由调用方按 'data_id' 对账;不做幂等意味着重复调用会重复计费;不做组件注入意味着测试只能依赖内部测试缝;不做异步意味着高并发由调用方用线程 / 进程池承接。以上代价已写入第 5 章与第 7 章。"
  - evidence `1.4 非目标`: "- **任务恢复 / 崩溃续跑**：本次不做；管道无状态，不持有跨调用任务状态。"
  - normalized: "- **任务恢复 / 崩溃续跑**:本次不做;管道无状态,不持有跨调用任务状态。"
  - rationale: §1.4 先列出非目标清单，再以“不做的后果”段落逐项说明代价，并指出这些代价在第 5、7 章承接。

## 痛点证据 (pain_evidence)

- **bg.pain_evidence** [core, level 2] — 1.2 是否有至少一条可核实的证据（事故、度量或引述）？
  - evidence `1.2 核心技术痛点`: "**证据（度量）**：README 记录的 2026-10-21 真实运行中，13 页 PDF 的端到端耗时为 37.5 s，其中提交 0.22 s、等待 36.56 s、下载 0.67 s、解析 0.03 s；顶层导出约 40 个名字。等待阶段占 97.5%，说明“组合成本”主要落在等待与生命周期管理上，而不是解析本身。"
  - normalized: "**证据(度量)**:README 记录的 2026-10-21 真实运行中,13 页 PDF 的端到端耗时为 37.5 s,其中提交 0.22 s、等待 36.56 s、下载 0.67 s、解析 0.03 s;顶层导出约 40 个名字。等待阶段占 97.5%,说明“组合成本”主要落在等待与生命周期管理上,而不是解析本身。"
  - rationale: 证据含具体日期、样本页数、各阶段秒数与占比，可直接核对，并对应失败链中“组合成本与生命周期无人负责”的断言。

## 目标可验收 (goal_verifiability)

- **goal.verifiable** [core, level 2] — 2.1 每个 Goal 是否都有验收方式？
  - evidence `2.1 目标`: "- **G1 - 唯一顶层入口与四阶段编排（架构级）**：提供唯一的顶层函数 'parse(uri, ...) -> ParseResult'，依次完成 submit → wait → download → extract；顶层 '__all__' 只有一个函数。验收：AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。 - **G2 - 端到端预算与阶段归因（可靠性级）**：单一 'timeout' / 'deadline_epoch' 覆盖四阶段；预算耗尽在信封模式返回 'error.stage'，在异常模式抛 'PipelineTimeoutError(stage=...)'。验收：AC-4.1 ~ AC-4.9。 - **G3 - 生命周期与所有权（架构级）**：管道自建 client / downloader 并在返回前关闭；中间 ZIP 流在提取后立即关闭；返回结果独立于流。验收：AC-3.1 ~ AC-3.8。 - **G4 - 失败信封 / 异常双模式（可靠性级）**：已知异常封装为 'ErrorMessage'，兜不住的异常原样抛出；'raise_on_error=True' 时已知异常原样抛出（超时翻译）。验收：AC-1.11、AC-1.12、AC-5.1 ~ AC-5.14。 - **G5 - 可观测性与无网络可测试性（运维级）**：阶段耗时、指标与日志口径唯一；'correlation_id' 透传；全部行为可在无网络环境测试。验收：AC-5.7 ~ AC-5.12、AC-7.1 ~ AC-7.8。"
  - normalized: "- **G1 - 唯一顶层入口与四阶段编排(架构级)**:提供唯一的顶层函数 'parse(uri, ...) -> ParseResult',依次完成 submit → wait → download → extract;顶层 '__all__' 只有一个函数。验收:AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。 - **G2 - 端到端预算与阶段归因(可靠性级)**:单一 'timeout' / 'deadline_epoch' 覆盖四阶段;预算耗尽在信封模式返回 'error.stage',在异常模式抛 'PipelineTimeoutError(stage=...)'。验收:AC-4.1 ~ AC-4.9。 - **G3 - 生命周期与所有权(架构级)**:管道自建 client / downloader 并在返回前关闭;中间 ZIP 流在提取后立即关闭;返回结果独立于流。验收:AC-3.1 ~ AC-3.8。 - **G4 - 失败信封 / 异常双模式(可靠性级)**:已知异常封装为 'ErrorMessage',兜不住的异常原样抛出;'raise_on_error=True' 时已知异常原样抛出(超时翻译)。验收:AC-1.11、AC-1.12、AC-5.1 ~ AC-5.14。 - **G5 - 可观测性与无网络可测试性(运维级)**:阶段耗时、指标与日志口径唯一;'correlation_id' 透传;全部行为可在无网络环境测试。验收:AC-5.7 ~ AC-5.12、AC-7.1 ~ AC-7.8。"
  - rationale: G1–G5 每条末尾都给出验收对应的 AC 编号，验收方式由 §4.7 的测试/断言条目落实。
- **goal.quantified** [core, level 2] — 2.1 是否至少有一个 Goal 有数字/单位/明确阈值？
  - evidence `2.1 目标`: "- **G1 - 唯一顶层入口与四阶段编排（架构级）**：提供唯一的顶层函数 'parse(uri, ...) -> ParseResult'，依次完成 submit → wait → download → extract；顶层 '__all__' 只有一个函数。验收：AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。"
  - normalized: "- **G1 - 唯一顶层入口与四阶段编排(架构级)**:提供唯一的顶层函数 'parse(uri, ...) -> ParseResult',依次完成 submit → wait → download → extract;顶层 '__all__' 只有一个函数。验收:AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。"
  - rationale: G1 把“顶层 '__all__' 只有一个函数”写成明确的计数阈值（恰好 1 个），可由 AC-2.1 / AC-7.4 断言；其余 Goal 未给出性能数值。
- **goal.count** [extended, level 2] — 2.1 Goals 是否控制在 3–6 个？
  - evidence `2.1 目标`: "- **G1 - 唯一顶层入口与四阶段编排（架构级）**：提供唯一的顶层函数 'parse(uri, ...) -> ParseResult'，依次完成 submit → wait → download → extract；顶层 '__all__' 只有一个函数。验收：AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。 - **G2 - 端到端预算与阶段归因（可靠性级）**：单一 'timeout' / 'deadline_epoch' 覆盖四阶段；预算耗尽在信封模式返回 'error.stage'，在异常模式抛 'PipelineTimeoutError(stage=...)'。验收：AC-4.1 ~ AC-4.9。 - **G3 - 生命周期与所有权（架构级）**：管道自建 client / downloader 并在返回前关闭；中间 ZIP 流在提取后立即关闭；返回结果独立于流。验收：AC-3.1 ~ AC-3.8。 - **G4 - 失败信封 / 异常双模式（可靠性级）**：已知异常封装为 'ErrorMessage'，兜不住的异常原样抛出；'raise_on_error=True' 时已知异常原样抛出（超时翻译）。验收：AC-1.11、AC-1.12、AC-5.1 ~ AC-5.14。 - **G5 - 可观测性与无网络可测试性（运维级）**：阶段耗时、指标与日志口径唯一；'correlation_id' 透传；全部行为可在无网络环境测试。验收：AC-5.7 ~ AC-5.12、AC-7.1 ~ AC-7.8。"
  - normalized: "- **G1 - 唯一顶层入口与四阶段编排(架构级)**:提供唯一的顶层函数 'parse(uri, ...) -> ParseResult',依次完成 submit → wait → download → extract;顶层 '__all__' 只有一个函数。验收:AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。 - **G2 - 端到端预算与阶段归因(可靠性级)**:单一 'timeout' / 'deadline_epoch' 覆盖四阶段;预算耗尽在信封模式返回 'error.stage',在异常模式抛 'PipelineTimeoutError(stage=...)'。验收:AC-4.1 ~ AC-4.9。 - **G3 - 生命周期与所有权(架构级)**:管道自建 client / downloader 并在返回前关闭;中间 ZIP 流在提取后立即关闭;返回结果独立于流。验收:AC-3.1 ~ AC-3.8。 - **G4 - 失败信封 / 异常双模式(可靠性级)**:已知异常封装为 'ErrorMessage',兜不住的异常原样抛出;'raise_on_error=True' 时已知异常原样抛出(超时翻译)。验收:AC-1.11、AC-1.12、AC-5.1 ~ AC-5.14。 - **G5 - 可观测性与无网络可测试性(运维级)**:阶段耗时、指标与日志口径唯一;'correlation_id' 透传;全部行为可在无网络环境测试。验收:AC-5.7 ~ AC-5.12、AC-7.1 ~ AC-7.8。"
  - rationale: 共 5 个 Goal，落在 3–6 区间，且分别标注架构级、可靠性级、运维级分类。

## 非目标边界 (non_goal_boundary)

- **nongoal.labeled** [core, level 2] — 2.2 每条 Non-Goal 是否标了本次不做或 Deferred to Phase 2？
  - evidence `2.2 非目标`: "- **NG1 - 修改既有组件契约**：管道只增不改（本次不做）。"
  - normalized: "- **NG1 - 修改既有组件契约**:管道只增不改(本次不做)。"
  - evidence `2.2 非目标`: "- **NG16 - exactly-once**：重复调用可能重复计费（Deferred to Phase 2）。"
  - normalized: "- **NG16 - exactly-once**:重复调用可能重复计费(Deferred to Phase 2)。"
  - rationale: §2.2 的 NG1–NG16 每条尾部都标注“本次不做”，唯一延后项 NG16 标注“Deferred to Phase 2”。
- **nongoal.not_dumping_ground** [extended, level 2] — 2.2 非目标是否能追溯到痛点或边界？
  - evidence `2.2 非目标`: "- **NG4 - 任务恢复 / 崩溃续跑**：管道无状态（本次不做）。"
  - normalized: "- **NG4 - 任务恢复 / 崩溃续跑**:管道无状态(本次不做)。"
  - evidence `2.2 非目标`: "- **NG12 - 幂等提交 / 去重**：'data_id' 不是幂等键（本次不做）。"
  - normalized: "- **NG12 - 幂等提交 / 去重**:'data_id' 不是幂等键(本次不做)。"
  - rationale: NG4 / NG12 分别对应 §1.2 的崩溃孤儿任务与 'data_id' 非幂等；其余条目对应 §1.4 已写明的边界（组件契约不变、单函数门面、同步无状态等），不存在与痛点无关的垃圾桶条目。

## 架构自洽 (architecture)

- **arch.solution_shape** [core, level 2] — 第 3 章是否有本次变更的拓扑或等价的模块/数据流描述？
  - evidence `3. 架构设计与核心方案`: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)（Approved）。管道是唯一公开入口，位于三个私有组件之上；本次只改管道层与顶层导出面。"
  - normalized: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)(Approved)。管道是唯一公开入口,位于三个私有组件之上;本次只改管道层与顶层导出面。"
  - evidence `3. 架构设计与核心方案`: "3. 用剩余预算调用 'AsyncResult.wait'，取得 'MinerUTaskResult.zip_url'。 4. 下载器 'resolve(zip_url)' 得到 ZIP 'io.BytesIO'。 5. 提取器 'extract_result(stream, limits)' 得到 '{pages, images}'；提取后立即关闭 ZIP 流。"
  - normalized: "3. 用剩余预算调用 'AsyncResult.wait',取得 'MinerUTaskResult.zip_url'。 4. 下载器 'resolve(zip_url)' 得到 ZIP 'io.BytesIO'。 5. 提取器 'extract_result(stream, limits)' 得到 '{pages, images}';提取后立即关闭 ZIP 流。"
  - rationale: 第 3 章给出本次变更范围内的 mermaid 拓扑，并用 7 步数据流说明 submit→wait→download→extract 的模块交接。
- **arch.topology** [extended, level 2] — 3.1 拓扑图是否让每个模块有一句职责？
  - evidence `3.1 总体架构`: "'''mermaid flowchart LR     CALLER["调用方"] --> PARSE["parse(uri, ...)"]     PARSE --> ORCH["PipelineOrchestrator<br/>预算 / 阶段 / 归属"]     ORCH --> CLIENT["_client<br/>submit / wait"]     ORCH --> DL["_downloader<br/>resolve"]     ORCH --> EX["_extractor<br/>extract_result"]     ORCH --> ENV["ParseResult / ErrorMessage"]     ORCH --> TEL["Telemetry"]      style PARSE fill:#e3f2fd,stroke:#1565c0,stroke-width:1px     style ORCH fill:#fff3e0,stroke:#e65100,stroke-width:1px     style ENV fill:#e8f5e9,stroke:#2e7d32,stroke-width:1px '''"
  - normalized: "'''mermaid flowchart LR CALLER["调用方"] --> PARSE["parse(uri, ...)"] PARSE --> ORCH["PipelineOrchestrator<br/>预算 / 阶段 / 归属"] ORCH --> CLIENT["_client<br/>submit / wait"] ORCH --> DL["_downloader<br/>resolve"] ORCH --> EX["_extractor<br/>extract_result"] ORCH --> ENV["ParseResult / ErrorMessage"] ORCH --> TEL["Telemetry"] style PARSE fill:#e3f2fd,stroke:#1565c0,stroke-width:1px style ORCH fill:#fff3e0,stroke:#e65100,stroke-width:1px style ENV fill:#e8f5e9,stroke:#2e7d32,stroke-width:1px '''"
  - evidence `3.2 核心模块职责`: "\| 模块 \| 职责 \| 明确不做 \| \| :--- \| :--- \| :--- \| \| 'parse' \| 唯一公共入口；参数透传与结果返回 \| 不实现组件逻辑、不持有状态 \| \| 'PipelineOrchestrator' \| 四阶段编排、预算检查点、阶段归因、双模式失败处理、生命周期与所有权 \| 不新增解析能力、不重试整链 \|"
  - normalized: "\| 模块 \| 职责 \| 明确不做 \| \| :--- \| :--- \| :--- \| \| 'parse' \| 唯一公共入口;参数透传与结果返回 \| 不实现组件逻辑、不持有状态 \| \| 'PipelineOrchestrator' \| 四阶段编排、预算检查点、阶段归因、双模式失败处理、生命周期与所有权 \| 不新增解析能力、不重试整链 \|"
  - rationale: 拓扑图节点覆盖调用方、parse、PipelineOrchestrator、三个私有组件、结果信封与 Telemetry；§3.2 表为每个模块给出一句职责与“明确不做”。
- **arch.change_set** [extended, level 2] — 第 3 章是否写清新增/改造/保持不变？
  - evidence `3. 架构设计与核心方案`: "**新增 / 改造 / 保持不变**：  - 新增：'mineru_parser.pipeline' 包（阶段枚举、预算、结果类型、编排器）；顶层 'parse' 与管道异常家族。 - 改造：顶层 '__all__' 收缩为“一个函数 + 必要类型”；组件包改为私有 '_client' / '_downloader' / '_extractor'。 - 不变：三个组件的行为契约（SPEC-001 / 002 / 003）原样保留，作为内部实现继续成立。"
  - normalized: "**新增 / 改造 / 保持不变**: - 新增:'mineru_parser.pipeline' 包(阶段枚举、预算、结果类型、编排器);顶层 'parse' 与管道异常家族。 - 改造:顶层 '__all__' 收缩为“一个函数 + 必要类型”;组件包改为私有 '_client' / '_downloader' / '_extractor'。 - 不变:三个组件的行为契约(SPEC-001 / 002 / 003)原样保留,作为内部实现继续成立。"
  - rationale: §3.1 以独立的“新增 / 改造 / 保持不变”清单写清三类变更，没有遗漏“不变”项。
- **arch.rationale** [extended, level 2] — 关键选型是否有理由，详细对比指向第 7 章？
  - evidence `3.4 关键选型与约束`: "- **同步阻塞而非异步编排**：与三个组件的同步模型一致；异步留给调用方的线程 / 进程池。详细对比见第 7 章。"
  - normalized: "- **同步阻塞而非异步编排**:与三个组件的同步模型一致;异步留给调用方的线程 / 进程池。详细对比见第 7 章。"
  - rationale: 每条选型都附有理由；同步/异步的取舍明确指向第 7 章，§7.3 与 §7.5 矩阵给出详细比较。
- **arch.references_source** [extended, level 2] — 第 3 章是否引用 depends_on 架构文档，而不是自行展开其全局结构？
  - evidence `3. 架构设计与核心方案`: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)（Approved）。管道是唯一公开入口，位于三个私有组件之上；本次只改管道层与顶层导出面。"
  - normalized: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)(Approved)。管道是唯一公开入口,位于三个私有组件之上;本次只改管道层与顶层导出面。"
  - rationale: frontmatter 的 depends_on 指向 docs/architecture/mineru-parser-architecture.md，第 3 章以“全局结构见…”引用它，并只展开管道层变更范围内的拓扑与数据流。

## 详细设计完整 (detailed_design)

- **design.contract** [core, level 2] — 第 4 章是否至少有一份数据模型或接口契约？
  - evidence `4. 详细设计`: "\| 字段 \| 类型 \| 说明 \| \| :--- \| :--- \| :--- \| \| 'stage' \| 'PipelineStage' \| 失败发生的阶段 \| \| 'error_type' \| 'str' \| 异常类名；调用方据此分支 \| \| 'message' \| 'str' \| 脱敏后的可读摘要；不含正文、凭据、签名 URL 或异常链原文 \|"
  - normalized: "\| 字段 \| 类型 \| 说明 \| \| :--- \| :--- \| :--- \| \| 'stage' \| 'PipelineStage' \| 失败发生的阶段 \| \| 'error_type' \| 'str' \| 异常类名;调用方据此分支 \| \| 'message' \| 'str' \| 脱敏后的可读摘要;不含正文、凭据、签名 URL 或异常链原文 \|"
  - rationale: §4.3 给出 ParseResult / ErrorMessage 字段表与阶段枚举，§4.4 给出 'parse' 方法签名，满足至少一份数据模型或接口契约。
- **design.data_model** [extended, level 2] — 4.3 数据模型是否有字段类型、必填与校验？
  - evidence `4.3 数据模型与契约`: "\| 参数 \| 类型 \| 默认值 \| 语义 \| \| :--- \| :--- \| :--- \| :--- \| \| 'uri' \| 'str' \| 必填 \| PDF 的绝对 http(s) URI \|"
  - normalized: "\| 参数 \| 类型 \| 默认值 \| 语义 \| \| :--- \| :--- \| :--- \| :--- \| \| 'uri' \| 'str' \| 必填 \| PDF 的绝对 http(s) URI \|"
  - evidence `4.3 数据模型与契约`: "所有参数校验必须在创建任何组件实例之前完成。"
  - normalized: "所有参数校验必须在创建任何组件实例之前完成。"
  - rationale: 参数表给出类型与“必填/默认值”，'uri' 行明确绝对 http(s) URL 约束，并规定校验先于任何组件创建；ParseResult / ErrorMessage 字段表也给出类型与取值约束。
- **design.interface** [extended, level 2] — 4.4 接口是否有请求/响应/状态码或方法签名？
  - evidence `4.4 接口与协议`: "'''python def parse(     uri: str,     *,     model_version: str = "vlm",     data_id: str \| None = None,     timeout: float \| None = None,     deadline_epoch: float \| None = None,     limits: ExtractionLimits \| None = None,     raise_on_error: bool = False,     on_update: Callable[[MinerUTaskStatus], None] \| None = None,     on_error: Callable[[PipelineStage, BaseException], None] \| None = None,     on_metric: MetricHook \| None = None,     correlation_id: str \| None = None, ) -> ParseResult: ... '''"
  - normalized: "'''python def parse( uri: str, *, model_version: str = "vlm", data_id: str \| None = None, timeout: float \| None = None, deadline_epoch: float \| None = None, limits: ExtractionLimits \| None = None, raise_on_error: bool = False, on_update: Callable[[MinerUTaskStatus], None] \| None = None, on_error: Callable[[PipelineStage, BaseException], None] \| None = None, on_metric: MetricHook \| None = None, correlation_id: str \| None = None, ) -> ParseResult: ... '''"
  - evidence `4.4 接口与协议`: "2. **形状**：'ParseResult'，恰好 'status'、'data'、'task_id'、'data_id'、'zip_url'、'error' 六个键（AC-1.1）；'data' 是 'ExtractedResult'，与 'extract_result' 的返回值逐字相同。"
  - normalized: "2. **形状**:'ParseResult',恰好 'status'、'data'、'task_id'、'data_id'、'zip_url'、'error' 六个键(AC-1.1);'data' 是 'ExtractedResult',与 'extract_result' 的返回值逐字相同。"
  - rationale: §4.4 给出完整方法签名、输入契约、返回契约与所有权契约，请求参数、返回形状和失败语义均可核实。
- **design.sequence** [extended, level 2] — 4.5 复杂流程是否有时序图或等价分步说明？
  - evidence `4.5 核心流程与时序`: "'''mermaid sequenceDiagram     autonumber     participant C as 调用方     participant P as parse     participant O as Orchestrator     participant CL as client     participant DL as downloader     participant EX as extractor      C->>P: parse(uri, timeout, ...)     P->>O: 参数校验 + 预算建立     O->>CL: submit(uri)     CL-->>O: AsyncResult     O->>CL: wait(timeout=remaining)     CL-->>O: zip_url     O->>DL: resolve(zip_url)     DL-->>O: io.BytesIO     O->>EX: extract_result(stream, limits)     EX-->>O: {pages, images}     O->>O: 关闭 ZIP 流 + 组装 ParseResult     O->>CL: close（finally）     O->>DL: close（finally）     O-->>C: ParseResult / PipelineTimeoutError '''"
  - normalized: "'''mermaid sequenceDiagram autonumber participant C as 调用方 participant P as parse participant O as Orchestrator participant CL as client participant DL as downloader participant EX as extractor C->>P: parse(uri, timeout, ...) P->>O: 参数校验 + 预算建立 O->>CL: submit(uri) CL-->>O: AsyncResult O->>CL: wait(timeout=remaining) CL-->>O: zip_url O->>DL: resolve(zip_url) DL-->>O: io.BytesIO O->>EX: extract_result(stream, limits) EX-->>O: {pages, images} O->>O: 关闭 ZIP 流 + 组装 ParseResult O->>CL: close(finally) O->>DL: close(finally) O-->>C: ParseResult / PipelineTimeoutError '''"
  - evidence `4.5 核心流程与时序`: "'MinerUTimeoutError' → 'PipelineTimeoutError(stage="wait")'；其余原样"
  - normalized: "'MinerUTimeoutError' → 'PipelineTimeoutError(stage="wait")';其余原样"
  - rationale: 时序图给出四阶段调用链并以 PipelineTimeoutError 结束；编排阶段表为每个阶段列出失败结果（含超时翻译），覆盖异常路径。
- **design.errors** [extended, level 2] — 4.6 每个错误码是否有触发场景与处理策略？
  - evidence `4.6 异常处理与错误码`: "\| 情形 \| 默认（信封模式，'raise_on_error=False'） \| 异常模式（'raise_on_error=True'） \| \| :--- \| :--- \| :--- \| \| 阶段抛出 'MinerUTimeoutError' \| 封装为 'error.error_type="PipelineTimeoutError"'、'error.stage="wait"'、'error.cause_type="MinerUTimeoutError"' \| 翻译为 'PipelineTimeoutError(stage="wait")'，原异常作为 '__cause__'，复制 'task_id' / 'last_status' \|"
  - normalized: "\| 情形 \| 默认(信封模式,'raise_on_error=False') \| 异常模式('raise_on_error=True') \| \| :--- \| :--- \| :--- \| \| 阶段抛出 'MinerUTimeoutError' \| 封装为 'error.error_type="PipelineTimeoutError"'、'error.stage="wait"'、'error.cause_type="MinerUTimeoutError"' \| 翻译为 'PipelineTimeoutError(stage="wait")',原异常作为 '__cause__',复制 'task_id' / 'last_status' \|"
  - rationale: §4.6 用表格逐类列出触发情形、信封模式封装结果与异常模式处理策略，并补充“已知 / 兜不住”的判定标准。

## NFR 可度量 (nfr)

- **nfr.measurable** [core, level 2] — 第 5 章每条 NFR 是否有数字、单位或验收方式？
  - evidence `5. 非功能性需求`: "- **端到端基线**：13 页真实样本 37.5 s；等待阶段 36.56 s（2026-10-21，README）。该数字是观测基线，不是 SLA；[estimated] P95 / P99 尚未统计。 - **单次峰值内存**：默认约 290 MiB（[estimated] 推导值，待 'tracemalloc' 实测校正）；$W=3$、1 GiB 容器可用；$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收：§4.3 公式 + README 数字。 - **预算检查**：四个阶段开始前与结束后检查；等待阶段把剩余预算传给 'wait'。验收：AC-4.2 ~ AC-4.9。"
  - normalized: "- **端到端基线**:13 页真实样本 37.5 s;等待阶段 36.56 s(2026-10-21,README)。该数字是观测基线,不是 SLA;[estimated] P95 / P99 尚未统计。 - **单次峰值内存**:默认约 290 MiB([estimated] 推导值,待 'tracemalloc' 实测校正);$W=3$、1 GiB 容器可用;$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收:§4.3 公式 + README 数字。 - **预算检查**:四个阶段开始前与结束后检查;等待阶段把剩余预算传给 'wait'。验收:AC-4.2 ~ AC-4.9。"
  - rationale: §5.1 给出 37.5 s、290 MiB、≤126 MiB 等带单位数字与验收引用；§5.2–§5.4 每条 NFR 也以 AC 编号作为明确验收方式。
- **nfr.coverage** [core, level 2] — 第 5 章是否覆盖性能、可靠性、可观测性、安全，或说明不适用？
  - evidence `5. 非功能性需求`: "- **端到端基线**：13 页真实样本 37.5 s；等待阶段 36.56 s（2026-10-21，README）。该数字是观测基线，不是 SLA；[estimated] P95 / P99 尚未统计。"
  - normalized: "- **端到端基线**:13 页真实样本 37.5 s;等待阶段 36.56 s(2026-10-21,README)。该数字是观测基线,不是 SLA;[estimated] P95 / P99 尚未统计。"
  - evidence `5. 非功能性需求`: "- **生命周期**：自建 client / downloader 在 'finally' 中关闭，顺序 downloader → client；中间 ZIP 流在提取后立即关闭。验收：AC-3.1 ~ AC-3.8。"
  - normalized: "- **生命周期**:自建 client / downloader 在 'finally' 中关闭,顺序 downloader → client;中间 ZIP 流在提取后立即关闭。验收:AC-3.1 ~ AC-3.8。"
  - evidence `5. 非功能性需求`: "- **指标标签**：只允许封闭枚举（'outcome'、'stage'）；不得包含 URI、'task_id'、'data_id'、'zip_url'、路径、成员名、异常消息或 'correlation_id'。验收：AC-5.9。"
  - normalized: "- **指标标签**:只允许封闭枚举('outcome'、'stage');不得包含 URI、'task_id'、'data_id'、'zip_url'、路径、成员名、异常消息或 'correlation_id'。验收:AC-5.9。"
  - evidence `5. 非功能性需求`: "- **凭据**：管道不读取、不记录 'MINERU_API_KEY'；凭证由 client 处理。验收：AC-5.9 + 代码评审。"
  - normalized: "- **凭据**:管道不读取、不记录 'MINERU_API_KEY';凭证由 client 处理。验收:AC-5.9 + 代码评审。"
  - rationale: 第 5 章分设性能与资源、可靠性与容灾、可观测性、安全与合规四节，四类均有实质内容，无需声明不适用。
- **nfr.honesty** [core, level 2] — 未实测的指标是否标了 [estimated] 或 未实现？
  - evidence `5. 非功能性需求`: "- **端到端基线**：13 页真实样本 37.5 s；等待阶段 36.56 s（2026-10-21，README）。该数字是观测基线，不是 SLA；[estimated] P95 / P99 尚未统计。"
  - normalized: "- **端到端基线**:13 页真实样本 37.5 s;等待阶段 36.56 s(2026-10-21,README)。该数字是观测基线,不是 SLA;[estimated] P95 / P99 尚未统计。"
  - evidence `5. 非功能性需求`: "- **单次峰值内存**：默认约 290 MiB（[estimated] 推导值，待 'tracemalloc' 实测校正）；$W=3$、1 GiB 容器可用；$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收：§4.3 公式 + README 数字。"
  - normalized: "- **单次峰值内存**:默认约 290 MiB([estimated] 推导值,待 'tracemalloc' 实测校正);$W=3$、1 GiB 容器可用;$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收:§4.3 公式 + README 数字。"
  - rationale: 未实测的 290 MiB 峰值在 §5.1 明标 [estimated] 推导值并注明待 'tracemalloc' 实测校正；P95 / P99 与观察窗口同样标了 [estimated]。

## 上线可回滚 (rollout)

- **rollout.release** [core, level 2] — 6.1 是否有发布策略与灰度节奏？
  - evidence `6.1 发布与灰度`: "管道随 'mineru-parser' 包发布，采用“候选版 → 正式版”两阶段：  1. **Phase 1（候选）**：发布 '0.1.0rcN'；在真实 13 页样本、66 个管道测试与全量回归上验证；观察 7 天。 2. **Phase 2（正式）**：无 P0/P1 问题后发布 '0.1.0'。 3. **观察期**：发布后 14 天；破坏性变更相关问题按 6.4 回滚。"
  - normalized: "管道随 'mineru-parser' 包发布,采用“候选版 → 正式版”两阶段: 1. **Phase 1(候选)**:发布 '0.1.0rcN';在真实 13 页样本、66 个管道测试与全量回归上验证;观察 7 天。 2. **Phase 2(正式)**:无 P0/P1 问题后发布 '0.1.0'。 3. **观察期**:发布后 14 天;破坏性变更相关问题按 6.4 回滚。"
  - rationale: §6.1 给出候选版到正式版的两阶段发布策略、进入条件与 7 / 14 天观察节奏，并说明库形态以候选版替代按流量灰度。
- **rollout.migration** [core, level 2] — 6.2 是否有迁移/兼容方案，或说明无需迁移？
  - evidence `6.2 数据迁移与兼容性`: "- **无数据迁移**：管道无状态、不落盘；结果只存在于本次返回值。 - **破坏性变更**：顶层 '__all__' 收缩为 14 个条目；组件 API 与三族具体异常类不再可从顶层导入。迁移对照见下表。"
  - normalized: "- **无数据迁移**:管道无状态、不落盘;结果只存在于本次返回值。 - **破坏性变更**:顶层 '__all__' 收缩为 14 个条目;组件 API 与三族具体异常类不再可从顶层导入。迁移对照见下表。"
  - rationale: §6.2 明确说明无需数据迁移及理由，并给出破坏性变更的迁移指南与“旧顶层导入 → 新公共面”对照表。
- **rollout.smoke** [core, level 2] — 6.3 是否有冒烟清单与观察指标？
  - evidence `6.3 上线验证与冒烟`: "\| 冒烟项 \| 步骤 \| 观察指标 \| \| :--- \| :--- \| :--- \| \| 单元回归 \| 'python -m pytest tests/test_pipeline.py -q' \| 66 个测试函数全通过 \| \| 全量回归 \| 'python -m pytest -q' \| 四组件测试全部通过 \|"
  - normalized: "\| 冒烟项 \| 步骤 \| 观察指标 \| \| :--- \| :--- \| :--- \| \| 单元回归 \| 'python -m pytest tests/test_pipeline.py -q' \| 66 个测试函数全通过 \| \| 全量回归 \| 'python -m pytest -q' \| 四组件测试全部通过 \|"
  - rationale: §6.3 的冒烟表同时给出可执行步骤与对应观察指标（测试通过数、状态、页/块/图片数与耗时）。
- **rollout.rollback_trigger** [core, level 2] — 6.4 回滚触发条件是否是可观测数字？
  - evidence `6.4 回滚与熔断`: "- 管道单测或全量回归失败数 $\\ge 1$。 - 真实样本 'parse()' 失败率连续 10 分钟 > 1%。 - 单次调用峰值内存超过 290 MiB 的 150%（即 > 435 MiB），出现 $\\ge 1$ 次。 - 顶层 API 面回归：'__all__' 出现第二个函数或保留名单缺失，$\\ge 1$ 次。"
  - normalized: "- 管道单测或全量回归失败数 $\\ge 1$。 - 真实样本 'parse()' 失败率连续 10 分钟 > 1%。 - 单次调用峰值内存超过 290 MiB 的 150%(即 > 435 MiB),出现 $\\ge 1$ 次。 - 顶层 API 面回归:'__all__' 出现第二个函数或保留名单缺失,$\\ge 1$ 次。"
  - rationale: 四条触发条件都是可观测数字或比例：失败数 ≥1、失败率连续 10 分钟 >1%、内存 >435 MiB、API 回归 ≥1 次。
- **rollout.rollback_steps** [core, level 2] — 6.4 回滚步骤是否可执行？
  - evidence `6.4 回滚与熔断`: "1. yank 当前版本；通知使用者固定到上一稳定版本。 2. 回退发布提交；重新打上一版本标签。 3. 恢复上一版顶层 '__all__' 与组件公开路径；重跑 'tests/test_pipeline.py' 与全量回归。 4. 用真实样本复跑，确认 'status=success' 与 README 基线一致后解除熔断。"
  - normalized: "1. yank 当前版本;通知使用者固定到上一稳定版本。 2. 回退发布提交;重新打上一版本标签。 3. 恢复上一版顶层 '__all__' 与组件公开路径;重跑 'tests/test_pipeline.py' 与全量回归。 4. 用真实样本复跑,确认 'status=success' 与 README 基线一致后解除熔断。"
  - rationale: 回滚步骤是 4 条可执行动作，包含版本 yank、提交回退、标签重打、API 面恢复与回归验证，不止写“可以回滚”。

## 替代方案诚实 (alternatives)

- **alts.status_quo** [core, level 2] — 第 7 章是否有 Status Quo 及其成本/风险？
  - evidence `7. 替代方案与权衡`: "- **思路**：调用方自己构造 client / downloader、按顺序调用、自己关闭资源、自己翻译三族异常。 - **成本**：每个调用点重复编排样板；顶层约 40 个名字；生命周期与预算无人统一负责。 - **风险**：忘记关流、重复关闭、失败阶段不可归因、三段超时之和远超预期；崩溃后孤儿任务无人对账。 - **触发阈值**：当第二个调用方开始复制同一段编排代码时，Status Quo 的成本已超过收敛成本。"
  - normalized: "- **思路**:调用方自己构造 client / downloader、按顺序调用、自己关闭资源、自己翻译三族异常。 - **成本**:每个调用点重复编排样板;顶层约 40 个名字;生命周期与预算无人统一负责。 - **风险**:忘记关流、重复关闭、失败阶段不可归因、三段超时之和远超预期;崩溃后孤儿任务无人对账。 - **触发阈值**:当第二个调用方开始复制同一段编排代码时,Status Quo 的成本已超过收敛成本。"
  - rationale: §7.1 完整给出 Status Quo 的思路、成本、风险与触发阈值，成本与风险均可与本 Spec 的痛点对应。
- **alts.rejected** [core, level 2] — 第 7 章是否至少有一个被否决方案，且淘汰原因对应当前约束？
  - evidence `7. 替代方案与权衡`: "- **思路**：保留三个组件的顶层导入，另加一个 'parse' 便捷函数。 - **优点**：不破坏既有用户；迁移平滑。 - **淘汰原因**：顶层 API 面仍然过宽，使用者仍需判断“该用哪个入口”；组件公开意味着公共契约还要继续维护，与“单函数门面”的目标冲突。项目未到 1.0，一次性收敛更干净。"
  - normalized: "- **思路**:保留三个组件的顶层导入,另加一个 'parse' 便捷函数。 - **优点**:不破坏既有用户;迁移平滑。 - **淘汰原因**:顶层 API 面仍然过宽,使用者仍需判断“该用哪个入口”;组件公开意味着公共契约还要继续维护,与“单函数门面”的目标冲突。项目未到 1.0,一次性收敛更干净。"
  - evidence `7. 替代方案与权衡`: "- **思路**：用 'asyncio' 并发等待多个任务，或引入任务队列。 - **优点**：高并发、吞吐更高。 - **淘汰原因**：三个组件都是同步阻塞模型；引入事件循环会改变调用方编程模型，并把取消传播、线程安全与资源生命周期问题带入本期。异步留作后续独立评估。"
  - normalized: "- **思路**:用 'asyncio' 并发等待多个任务,或引入任务队列。 - **优点**:高并发、吞吐更高。 - **淘汰原因**:三个组件都是同步阻塞模型;引入事件循环会改变调用方编程模型,并把取消传播、线程安全与资源生命周期问题带入本期。异步留作后续独立评估。"
  - rationale: §7.2–§7.4 给出三个否决方案，淘汰原因分别对应当前约束：顶层 API 面收敛、同步组件模型、零额外依赖与单进程。
- **alts.matrix** [core, level 2] — 第 7 章是否有与约束对应的权衡矩阵？
  - evidence `7. 替代方案与权衡`: "\| 维度 \| Status Quo \| 组件公开 + helper \| 异步编排 \| 外部框架 \| 选定方案 \| \| :--- \| :--- \| :--- \| :--- \| :--- \| :--- \| \| 顶层 API 面收敛 \| 差 \| 中 \| 中 \| 中 \| 强 \| \| 生命周期与所有权 \| 差 \| 中 \| 中 \| 强 \| 强 \| \| 与同步组件的兼容 \| 强 \| 强 \| 差 \| 弱 \| 强 \|"
  - normalized: "\| 维度 \| Status Quo \| 组件公开 + helper \| 异步编排 \| 外部框架 \| 选定方案 \| \| :--- \| :--- \| :--- \| :--- \| :--- \| :--- \| \| 顶层 API 面收敛 \| 差 \| 中 \| 中 \| 中 \| 强 \| \| 生命周期与所有权 \| 差 \| 中 \| 中 \| 强 \| 强 \| \| 与同步组件的兼容 \| 强 \| 强 \| 差 \| 弱 \| 强 \|"
  - rationale: §7.5 的权衡矩阵以顶层 API 面收敛、生命周期、同步兼容、端到端预算、额外依赖等维度对应 G1–G5 与关键约束。
- **alts.consistency** [core, level 2] — 第 7 章结论是否与 Goals、架构选型一致？
  - evidence `7. 替代方案与权衡`: "结论：选定方案与 G1 ~ G5 一致；最关键的约束是“唯一入口、无状态、同步、零额外依赖”，这四项决定了不能保留组件公开面，也不适合引入异步或外部编排框架。"
  - normalized: "结论:选定方案与 G1 ~ G5 一致;最关键的约束是“唯一入口、无状态、同步、零额外依赖”,这四项决定了不能保留组件公开面,也不适合引入异步或外部编排框架。"
  - rationale: 结论明确对齐 G1–G5，并把“唯一入口、无状态、同步、零额外依赖”与第 3 章的选型约束对应起来。

## 跨章自洽 (cross_consistency)

- **x.goals_trace** [core, level 2] — 后续章节是否逐条回应 Goals？
  - evidence `全文`: "- **G1 - 唯一顶层入口与四阶段编排（架构级）**：提供唯一的顶层函数 'parse(uri, ...) -> ParseResult'，依次完成 submit → wait → download → extract；顶层 '__all__' 只有一个函数。验收：AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。 - **G2 - 端到端预算与阶段归因（可靠性级）**：单一 'timeout' / 'deadline_epoch' 覆盖四阶段；预算耗尽在信封模式返回 'error.stage'，在异常模式抛 'PipelineTimeoutError(stage=...)'。验收：AC-4.1 ~ AC-4.9。 - **G3 - 生命周期与所有权（架构级）**：管道自建 client / downloader 并在返回前关闭；中间 ZIP 流在提取后立即关闭；返回结果独立于流。验收：AC-3.1 ~ AC-3.8。 - **G4 - 失败信封 / 异常双模式（可靠性级）**：已知异常封装为 'ErrorMessage'，兜不住的异常原样抛出；'raise_on_error=True' 时已知异常原样抛出（超时翻译）。验收：AC-1.11、AC-1.12、AC-5.1 ~ AC-5.14。 - **G5 - 可观测性与无网络可测试性（运维级）**：阶段耗时、指标与日志口径唯一；'correlation_id' 透传；全部行为可在无网络环境测试。验收：AC-5.7 ~ AC-5.12、AC-7.1 ~ AC-7.8。"
  - normalized: "- **G1 - 唯一顶层入口与四阶段编排(架构级)**:提供唯一的顶层函数 'parse(uri, ...) -> ParseResult',依次完成 submit → wait → download → extract;顶层 '__all__' 只有一个函数。验收:AC-1.1 ~ AC-1.3、AC-2.1 ~ AC-2.10。 - **G2 - 端到端预算与阶段归因(可靠性级)**:单一 'timeout' / 'deadline_epoch' 覆盖四阶段;预算耗尽在信封模式返回 'error.stage',在异常模式抛 'PipelineTimeoutError(stage=...)'。验收:AC-4.1 ~ AC-4.9。 - **G3 - 生命周期与所有权(架构级)**:管道自建 client / downloader 并在返回前关闭;中间 ZIP 流在提取后立即关闭;返回结果独立于流。验收:AC-3.1 ~ AC-3.8。 - **G4 - 失败信封 / 异常双模式(可靠性级)**:已知异常封装为 'ErrorMessage',兜不住的异常原样抛出;'raise_on_error=True' 时已知异常原样抛出(超时翻译)。验收:AC-1.11、AC-1.12、AC-5.1 ~ AC-5.14。 - **G5 - 可观测性与无网络可测试性(运维级)**:阶段耗时、指标与日志口径唯一;'correlation_id' 透传;全部行为可在无网络环境测试。验收:AC-5.7 ~ AC-5.12、AC-7.1 ~ AC-7.8。"
  - evidence `全文`: "结论：选定方案与 G1 ~ G5 一致；最关键的约束是“唯一入口、无状态、同步、零额外依赖”，这四项决定了不能保留组件公开面，也不适合引入异步或外部编排框架。"
  - normalized: "结论:选定方案与 G1 ~ G5 一致;最关键的约束是“唯一入口、无状态、同步、零额外依赖”,这四项决定了不能保留组件公开面,也不适合引入异步或外部编排框架。"
  - rationale: G1 由 §3.1 拓扑与 §4.2 / §4.4 公共面落地，G2 由 §4.5 预算检查点与 §4.6 落地，G3 由 §4.4 所有权契约与 AC-3 系列落地，G4 由 §4.6 双模式表落地，G5 由 §5.3 遥测表与 AC-7 系列落地。
- **x.nfr_arch** [core, level 2] — NFR 与架构、选型是否一致？
  - evidence `全文`: "- **单次峰值内存**：默认约 290 MiB（[estimated] 推导值，待 'tracemalloc' 实测校正）；$W=3$、1 GiB 容器可用；$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收：§4.3 公式 + README 数字。"
  - normalized: "- **单次峰值内存**:默认约 290 MiB([estimated] 推导值,待 'tracemalloc' 实测校正);$W=3$、1 GiB 容器可用;$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收:§4.3 公式 + README 数字。"
  - evidence `全文`: "- **AC-6.2**: 单次 'parse()' 的峰值内存必须按 §4.3 的公式估算，并在 **README 中写明默认档位的峰值上界**（≈ 290 MiB，[estimated] 推导值）。该数字必须与 SPEC-003 §4.3 的推导口径保持自洽。"
  - normalized: "- **AC-6.2**: 单次 'parse()' 的峰值内存必须按 §4.3 的公式估算,并在 **README 中写明默认档位的峰值上界**(≈ 290 MiB,[estimated] 推导值)。该数字必须与 SPEC-003 §4.3 的推导口径保持自洽。"
  - rationale: NFR 的 290 MiB 峰值与 §4.3 公式、AC-6.2 同口径（均标 [estimated] 推导值），W=3 并发与 1 GiB 容器结论一致；“无额外拷贝”对应 AC-6.5，同步模型对应 §3.4。
- **x.rollback_release** [core, level 2] — 回滚与发布策略是否一致？
  - evidence `全文`: "库形态无法按流量比例灰度；以候选版与内部集成验证替代。[estimated] 观察窗口按当前维护者规模设定。"
  - normalized: "库形态无法按流量比例灰度;以候选版与内部集成验证替代。[estimated] 观察窗口按当前维护者规模设定。"
  - evidence `全文`: "1. yank 当前版本；通知使用者固定到上一稳定版本。 2. 回退发布提交；重新打上一版本标签。 3. 恢复上一版顶层 '__all__' 与组件公开路径；重跑 'tests/test_pipeline.py' 与全量回归。 4. 用真实样本复跑，确认 'status=success' 与 README 基线一致后解除熔断。"
  - normalized: "1. yank 当前版本;通知使用者固定到上一稳定版本。 2. 回退发布提交;重新打上一版本标签。 3. 恢复上一版顶层 '__all__' 与组件公开路径;重跑 'tests/test_pipeline.py' 与全量回归。 4. 用真实样本复跑,确认 'status=success' 与 README 基线一致后解除熔断。"
  - rationale: 发布采用候选版→正式版两阶段与观察期，回滚步骤正是 yank 当前版本、回退发布提交、重打标签并重跑回归，二者衔接一致。

## 证据卫生 (evidence_hygiene)

- **x.no_placeholders** [core, level 2] — 是否没有把 无 / ... / 待补充 / TBD 当作实质回答？
  - evidence `全文`: "- **AC-1.12**: 失败信封必须满足：'status == "failed"'、'data is None'、'error' 非 'None'；'error.stage' 必须是 'config' / 'submit' / 'wait' / 'download' / 'extract' 之一；'error.error_type' 必须是该异常的**类名**；'error.cause_type' 必须是异常链首因的类名或 'None'；'task_id' / 'data_id' / 'zip_url' 按"**当时已知**"填充——提交成功即知 'task_id'，等待完成后才知 'zip_url'，未知的取 'None'。"
  - normalized: "- **AC-1.12**: 失败信封必须满足:'status == "failed"'、'data is None'、'error' 非 'None';'error.stage' 必须是 'config' / 'submit' / 'wait' / 'download' / 'extract' 之一;'error.error_type' 必须是该异常的**类名**;'error.cause_type' 必须是异常链首因的类名或 'None';'task_id' / 'data_id' / 'zip_url' 按"**当时已知**"填充——提交成功即知 'task_id',等待完成后才知 'zip_url',未知的取 'None'。"
  - rationale: 全文未出现 TBD / 待补充；'...' 仅出现在 Python 签名或示例的省略号中，表格中的 '—' 均有括号解释，不构成以占位代替实质回答。
- **x.no_code** [core, level 2] — 是否没有堆砌实现代码、测试日志或偶发报错？
  - evidence `全文`: "本节描述**控制流契约**：每个阶段做什么、用什么判据、失败时抛出什么。实现方式（函数划分、异常捕获顺序、内部数据结构）由实现者决定。"
  - normalized: "本节描述**控制流契约**:每个阶段做什么、用什么判据、失败时抛出什么。实现方式(函数划分、异常捕获顺序、内部数据结构)由实现者决定。"
  - rationale: 代码块仅为公共签名与调用示例，没有测试日志、堆栈或实现代码堆砌；正文明确把实现细节留给实现者。
- **x.numbers_sourced** [core, level 2] — 关键数字是否有出处，或标了 [estimated]？
  - evidence `全文`: "- **端到端基线**：13 页真实样本 37.5 s；等待阶段 36.56 s（2026-10-21，README）。该数字是观测基线，不是 SLA；[estimated] P95 / P99 尚未统计。"
  - normalized: "- **端到端基线**:13 页真实样本 37.5 s;等待阶段 36.56 s(2026-10-21,README)。该数字是观测基线,不是 SLA;[estimated] P95 / P99 尚未统计。"
  - evidence `全文`: "- **单次峰值内存**：默认约 290 MiB（[estimated] 推导值，待 'tracemalloc' 实测校正）；$W=3$、1 GiB 容器可用；$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收：§4.3 公式 + README 数字。"
  - normalized: "- **单次峰值内存**:默认约 290 MiB([estimated] 推导值,待 'tracemalloc' 实测校正);$W=3$、1 GiB 容器可用;$W=4$ 时需下调 'max_total_image_bytes' 到 ≤ 126 MiB。验收:§4.3 公式 + README 数字。"
  - rationale: 37.5 s 等真实运行数字有 README 出处，P95 / P99 标 [estimated]；290 MiB 峰值也标 [estimated] 推导值并注明待实测校正。
- **x.no_fabricated_refs** [core, level 2] — 是否没有捏造 SPEC 引用、depends_on 目标或 M<N>？
  - evidence `全文`: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)（Approved）。管道是唯一公开入口，位于三个私有组件之上；本次只改管道层与顶层导出面。"
  - normalized: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)(Approved)。管道是唯一公开入口,位于三个私有组件之上;本次只改管道层与顶层导出面。"
  - rationale: frontmatter 的 depends_on 目标与 §1.1、§3.1 的引用一致，SPEC-001 / 002 / 003 的引用前后一致，未出现 M<N> 形式；AC-2.9 的“Goal 7 / Q-13”在本 Spec 内无对应条目，属陈旧内部编号，但不属于本项所指的 SPEC / depends_on 捏造。

## Audit failures

None.
