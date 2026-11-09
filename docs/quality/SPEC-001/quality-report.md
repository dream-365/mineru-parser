# Spec Quality Report

- Target: `docs/specs/SPEC-001-mineru-api-client/spec.md`
- Rubric: 1.1.0 (`1e6c4740ed85512b1657e6798e481c893fe015f4ce2a140665ff6ecb2ef7b29e`)
- Target SHA-256: `2efdc7584afb40ac92da7fb3df47aa7693f712929d9ce869b7572dbae8692429`
- Reviewer session: `review-spec-001`

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
  - evidence `1.1 系统现状`: "'mineru-parser' 是对 MinerU 异步解析服务的 Python 封装。MinerU 只提供异步任务接口：调用方提交 PDF URL，拿到 'task_id' 后必须自行轮询到终态，才能取得结果包的 'zip_url'。库的四个组件按“提交 → 等待 → 下载 → 解析”串联，客户端（'_client'，原 'MinerUApiClient'）负责前两个阶段。"
  - normalized: "'mineru-parser' 是对 MinerU 异步解析服务的 Python 封装。MinerU 只提供异步任务接口:调用方提交 PDF URL,拿到 'task_id' 后必须自行轮询到终态,才能取得结果包的 'zip_url'。库的四个组件按“提交 → 等待 → 下载 → 解析”串联,客户端('_client',原 'MinerUApiClient')负责前两个阶段。"
  - evidence `1.1 系统现状`: "当前技术栈为 Python 3.12、'requests.Session'、'dataclasses' / 'Enum'，全部为同步阻塞模型。客户端对外的行为契约（组件已私有化，外部用户通过 'parse()' 间接使用）如下："
  - normalized: "当前技术栈为 Python 3.12、'requests.Session'、'dataclasses' / 'Enum',全部为同步阻塞模型。客户端对外的行为契约(组件已私有化,外部用户通过 'parse()' 间接使用)如下:"
  - rationale: 写清客户端负责提交与等待、四个组件的串联流程，并给出具体技术栈与同步阻塞模型。
- **bg.failure_chain** [core, level 2] — 1.2 是否有从触发到后果的分步失败链？
  - evidence `1.2 核心技术痛点`: "异步任务接口把“等待”这件事留给了调用方，失败链如下："
  - normalized: "异步任务接口把“等待”这件事留给了调用方,失败链如下:"
  - evidence `1.2 核心技术痛点`: "2. **限流与瞬时故障没有统一策略**：429、5xx、连接未建立、读超时各有不同的可重试语义；没有退避、抖动与 'Retry-After' 时，调用方容易重试风暴或过早放弃。"
  - normalized: "2. **限流与瞬时故障没有统一策略**:429、5xx、连接未建立、读超时各有不同的可重试语义;没有退避、抖动与 'Retry-After' 时,调用方容易重试风暴或过早放弃。"
  - rationale: 以编号 1–6 列出从触发条件到调用方后果的分步失败链，而非泛泛描述。
- **bg.trigger** [core, level 2] — 1.3 是否解释了为什么现在做？
  - evidence `1.3 重构/设计动机`: "1. **单函数门面落地后，客户端成为每个 'parse()' 调用的必经阶段**：客户端的行为回归会直接暴露给所有用户，契约需要在 0.1.0 发布前固化。"
  - normalized: "1. **单函数门面落地后,客户端成为每个 'parse()' 调用的必经阶段**:客户端的行为回归会直接暴露给所有用户,契约需要在 0.1.0 发布前固化。"
  - rationale: 三条动机说明 0.1.0 发布前固化契约、共享根异常与 97.5% 等待成本构成的当下触发点。
- **bg.non_goals** [core, level 2] — 1.4 是否写了不做的后果与本次非目标？
  - evidence `1.4 非目标`: "- **下载、解压、解析结果包**：本次不做；由下载器与提取器承担，客户端只交付 'zip_url'。"
  - normalized: "- **下载、解压、解析结果包**:本次不做;由下载器与提取器承担,客户端只交付 'zip_url'。"
  - evidence `1.4 非目标`: "**不做的后果**：不提供批量与幂等意味着调用方必须自己保存 'task_id'、按 'data_id' 对账，并自行避免重复提交；不提供异步轮询意味着高并发场景需要调用方用线程 / 进程池承接。这些代价已写入第 5 章与第 7 章，不在本期用隐式行为兜底。"
  - normalized: "**不做的后果**:不提供批量与幂等意味着调用方必须自己保存 'task_id'、按 'data_id' 对账,并自行避免重复提交;不提供异步轮询意味着高并发场景需要调用方用线程 / 进程池承接。这些代价已写入第 5 章与第 7 章,不在本期用隐式行为兜底。"
  - rationale: 先列本次非目标，再单列“不做的后果”说明调用方需承担的代价。

## 痛点证据 (pain_evidence)

- **bg.pain_evidence** [core, level 2] — 1.2 是否有至少一条可核实的证据（事故、度量或引述）？
  - evidence `1.2 核心技术痛点`: "**证据（度量）**：README 记录的 2026-10-21 真实运行中，同一份 13 页 PDF 的端到端耗时为 37.5 s，其中等待阶段 36.56 s、提交 0.22 s、下载 0.67 s、解析 0.03 s。等待阶段占总耗时 **97.5%**。这意味着客户端的轮询策略就是整条链路的主要成本；把轮询留给每个调用方各自实现，等于把 97.5% 的耗时行为交给不可控的重复代码。"
  - normalized: "**证据(度量)**:README 记录的 2026-10-21 真实运行中,同一份 13 页 PDF 的端到端耗时为 37.5 s,其中等待阶段 36.56 s、提交 0.22 s、下载 0.67 s、解析 0.03 s。等待阶段占总耗时 **97.5%**。这意味着客户端的轮询策略就是整条链路的主要成本;把轮询留给每个调用方各自实现,等于把 97.5% 的耗时行为交给不可控的重复代码。"
  - rationale: 给出带日期、来源与多项耗时的度量，且 97.5% 等待占比直接对应失败链首条。

## 目标可验收 (goal_verifiability)

- **goal.verifiable** [core, level 2] — 2.1 每个 Goal 是否都有验收方式？
  - evidence `2.1 目标`: "- **G1 - 统一入口与配置（架构级）**：用一组显式参数构造客户端，凭证、'base_url'、超时与轮询策略在发起网络请求前完成校验。验收：AC-1.1 ~ AC-1.6 全部通过 'tests/test_client.py'。"
  - normalized: "- **G1 - 统一入口与配置(架构级)**:用一组显式参数构造客户端,凭证、'base_url'、超时与轮询策略在发起网络请求前完成校验。验收:AC-1.1 ~ AC-1.6 全部通过 'tests/test_client.py'。"
  - evidence `2.1 目标`: "- **G5 - 生命周期、可观测与可测试性（运维级）**：Session 所有权明确；'on_update' / 'on_metric' 异常隔离；'correlation_id' 进入所有日志；时钟、随机源、Session 均可注入。验收：AC-7.1 ~ AC-10.3（AC-10.x 见 4.7 的“未实现”标注）+ 29 个无网络测试函数。"
  - normalized: "- **G5 - 生命周期、可观测与可测试性(运维级)**:Session 所有权明确;'on_update' / 'on_metric' 异常隔离;'correlation_id' 进入所有日志;时钟、随机源、Session 均可注入。验收:AC-7.1 ~ AC-10.3(AC-10.x 见 4.7 的“未实现”标注)+ 29 个无网络测试函数。"
  - rationale: G1–G5 每个 Goal 末尾都以 AC 编号与测试文件/测试函数作为验收方式。
- **goal.quantified** [core, level 2] — 2.1 是否至少有一个 Goal 有数字/单位/明确阈值？
  - evidence `2.1 目标`: "- **G3 - 稳健轮询与等待边界（可靠性级）**：默认间隔 3 s、上限 30 s、退避 1.5、抖动 0.5、连续错误上限 3 次；支持 'Retry-After' 与相对 / 绝对超时。验收：AC-4.1 ~ AC-5.6 全部通过；默认值由 AC-5.1 断言。"
  - normalized: "- **G3 - 稳健轮询与等待边界(可靠性级)**:默认间隔 3 s、上限 30 s、退避 1.5、抖动 0.5、连续错误上限 3 次;支持 'Retry-After' 与相对 / 绝对超时。验收:AC-4.1 ~ AC-5.6 全部通过;默认值由 AC-5.1 断言。"
  - rationale: G3 给出默认间隔 3 s、上限 30 s、退避 1.5、抖动 0.5、错误上限 3 次等带单位或阈值指标。
- **goal.count** [extended, level 2] — 2.1 Goals 是否控制在 3–6 个？
  - evidence `2.1 目标`: "- **G1 - 统一入口与配置（架构级）**：用一组显式参数构造客户端，凭证、'base_url'、超时与轮询策略在发起网络请求前完成校验。验收：AC-1.1 ~ AC-1.6 全部通过 'tests/test_client.py'。"
  - normalized: "- **G1 - 统一入口与配置(架构级)**:用一组显式参数构造客户端,凭证、'base_url'、超时与轮询策略在发起网络请求前完成校验。验收:AC-1.1 ~ AC-1.6 全部通过 'tests/test_client.py'。"
  - evidence `2.1 目标`: "- **G5 - 生命周期、可观测与可测试性（运维级）**：Session 所有权明确；'on_update' / 'on_metric' 异常隔离；'correlation_id' 进入所有日志；时钟、随机源、Session 均可注入。验收：AC-7.1 ~ AC-10.3（AC-10.x 见 4.7 的“未实现”标注）+ 29 个无网络测试函数。"
  - normalized: "- **G5 - 生命周期、可观测与可测试性(运维级)**:Session 所有权明确;'on_update' / 'on_metric' 异常隔离;'correlation_id' 进入所有日志;时钟、随机源、Session 均可注入。验收:AC-7.1 ~ AC-10.3(AC-10.x 见 4.7 的“未实现”标注)+ 29 个无网络测试函数。"
  - rationale: 共 5 个 Goal，分别标注架构级、可靠性级与运维级分类，数量处于 3–6 个区间。

## 非目标边界 (non_goal_boundary)

- **nongoal.labeled** [core, level 2] — 2.2 每条 Non-Goal 是否标了本次不做或 Deferred to Phase 2？
  - evidence `2.2 非目标`: "- **NG1 - 下载 / 解压 / 解析**：由下游组件承担（本次不做）。"
  - normalized: "- **NG1 - 下载 / 解压 / 解析**:由下游组件承担(本次不做)。"
  - evidence `2.2 非目标`: "- **NG10 - 任务恢复入口的持久化**：库不落盘，'task_id' 由调用方保存（Deferred to Phase 2）。"
  - normalized: "- **NG10 - 任务恢复入口的持久化**:库不落盘,'task_id' 由调用方保存(Deferred to Phase 2)。"
  - rationale: NG1–NG9 均标“本次不做”，NG10 单独标“Deferred to Phase 2”，每条都有标注。
- **nongoal.not_dumping_ground** [extended, level 2] — 2.2 非目标是否能追溯到痛点或边界？
  - evidence `2.2 非目标`: "- **NG3 - 提交幂等**：'data_id' 仅用于对账（本次不做）。"
  - normalized: "- **NG3 - 提交幂等**:'data_id' 仅用于对账(本次不做)。"
  - evidence `2.2 非目标`: "- **NG8 - 自动重试提交阶段未知结果**：避免重复建任务（本次不做）。"
  - normalized: "- **NG8 - 自动重试提交阶段未知结果**:避免重复建任务(本次不做)。"
  - rationale: 每条非目标都附下游归属、边界或痛点理由，例如幂等与自动重试均对应重复建任务风险。

## 架构自洽 (architecture)

- **arch.solution_shape** [core, level 2] — 第 3 章是否有本次变更的拓扑或等价的模块/数据流描述？
  - evidence `3. 架构设计与核心方案`: "    CALLER["调用方"] --> CLIENT["MinerUApiClient"]"
  - normalized: "CALLER["调用方"] --> CLIENT["MinerUApiClient"]"
  - evidence `3. 架构设计与核心方案`: "3. 调用方调用 'AsyncResult.wait(...)'；'Poller' 以 'AsyncResult.refresh()' 为 fetch，循环查询 'GET /extract/task/{task_id}'。"
  - normalized: "3. 调用方调用 'AsyncResult.wait(...)';'Poller' 以 'AsyncResult.refresh()' 为 fetch,循环查询 'GET /extract/task/{task_id}'。"
  - rationale: 第 3 章给出本次变更范围的 mermaid 拓扑与 6 步数据流，覆盖调用方到 API 的链路。
- **arch.topology** [extended, level 2] — 3.1 拓扑图是否让每个模块有一句职责？
  - evidence `3.1 总体架构`: "    CALLER["调用方"] --> CLIENT["MinerUApiClient"]"
  - normalized: "CALLER["调用方"] --> CLIENT["MinerUApiClient"]"
  - evidence `3.2 核心模块职责`: "\| 'MinerUApiClient' \| 配置校验、凭证解析、Session 生命周期、'submit' / 'resume'、内部状态查询 \| 不保存任务状态、不执行轮询、不解释终态、不提供业务编排 \|"
  - normalized: "\| 'MinerUApiClient' \| 配置校验、凭证解析、Session 生命周期、'submit' / 'resume'、内部状态查询 \| 不保存任务状态、不执行轮询、不解释终态、不提供业务编排 \|"
  - rationale: 拓扑图展示调用方、客户端、传输、结果、轮询与遥测节点的连接；3.2 表为每个模块给出一句职责与明确不做。
- **arch.change_set** [extended, level 2] — 第 3 章是否写清新增/改造/保持不变？
  - evidence `3. 架构设计与核心方案`: "- 新增：库级根异常 'MinerUParserError' 的客户端侧继承关系与断言。"
  - normalized: "- 新增:库级根异常 'MinerUParserError' 的客户端侧继承关系与断言。"
  - evidence `3. 架构设计与核心方案`: "- 改造：轮询算法与等待边界收敛为契约条款；不再在 Spec 中保留实现伪码。"
  - normalized: "- 改造:轮询算法与等待边界收敛为契约条款;不再在 Spec 中保留实现伪码。"
  - evidence `3. 架构设计与核心方案`: "- 不变：客户端公共方法签名、状态归一化、错误分类矩阵、Session 所有权与遥测口径。"
  - normalized: "- 不变:客户端公共方法签名、状态归一化、错误分类矩阵、Session 所有权与遥测口径。"
  - rationale: 以“新增 / 改造 / 保持不变”三组清单明确本次变更集。
- **arch.rationale** [extended, level 2] — 关键选型是否有理由，详细对比指向第 7 章？
  - evidence `3.4 关键选型与约束`: "- **同步阻塞而非 'asyncio'**：库的公共入口是同步函数，客户端必须与管道保持同一模型；异步收益留给调用方的线程 / 进程池。详细对比见第 7 章。"
  - normalized: "- **同步阻塞而非 'asyncio'**:库的公共入口是同步函数,客户端必须与管道保持同一模型;异步收益留给调用方的线程 / 进程池。详细对比见第 7 章。"
  - rationale: 同步阻塞选型给出与同步 parse 入口、注入测试的对应理由，并明确“详细对比见第 7 章”。
- **arch.references_source** [extended, level 2] — 第 3 章是否引用 depends_on 架构文档，而不是自行展开其全局结构？
  - evidence `3. 架构设计与核心方案`: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)（Approved）。本文只改客户端的契约与内部协作，不改变下载器、提取器与管道的边界。"
  - normalized: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)(Approved)。本文只改客户端的契约与内部协作,不改变下载器、提取器与管道的边界。"
  - rationale: frontmatter depends_on 指向全局架构文档，第 3 章引用它承载全局结构并声明本文只描述客户端范围。

## 详细设计完整 (detailed_design)

- **design.contract** [core, level 2] — 第 4 章是否至少有一份数据模型或接口契约？
  - evidence `4. 详细设计`: "\| 'api_key' \| 'None' \| 'str \\\| None' \| 否 \| 显式提供时去空白且不得为空；'None' 时延迟到首次请求读取 'MINERU_API_KEY' \|"
  - normalized: "\| 'api_key' \| 'None' \| 'str \\\| None' \| 否 \| 显式提供时去空白且不得为空;'None' 时延迟到首次请求读取 'MINERU_API_KEY' \|"
  - evidence `4. 详细设计`: "\| 'submit(uri, *, model_version="vlm", data_id=None)' \| 'POST /extract/task' \| 请求 '{url, model_version, data_id?}'；响应 '{code, data: {task_id}}' \| 请求模型校验在 HTTP 异常处理之外；成功返回未查询过的 'AsyncResult' \|"
  - normalized: "\| 'submit(uri, *, model_version="vlm", data_id=None)' \| 'POST /extract/task' \| 请求 '{url, model_version, data_id?}';响应 '{code, data: {task_id}}' \| 请求模型校验在 HTTP 异常处理之外;成功返回未查询过的 'AsyncResult' \|"
  - rationale: 4.3 的构造参数表与 4.4 的 API 表构成字段级数据模型与接口契约。
- **design.data_model** [extended, level 2] — 4.3 数据模型是否有字段类型、必填与校验？
  - evidence `4.3 数据模型与契约`: "\| 参数 \| 默认值 \| 类型 \| 必填 \| 校验 / 语义 \|"
  - normalized: "\| 参数 \| 默认值 \| 类型 \| 必填 \| 校验 / 语义 \|"
  - evidence `4.3 数据模型与契约`: "\| 'api_key' \| 'None' \| 'str \\\| None' \| 否 \| 显式提供时去空白且不得为空；'None' 时延迟到首次请求读取 'MINERU_API_KEY' \|"
  - normalized: "\| 'api_key' \| 'None' \| 'str \\\| None' \| 否 \| 显式提供时去空白且不得为空;'None' 时延迟到首次请求读取 'MINERU_API_KEY' \|"
  - rationale: 字段表列出类型、必填与校验/语义，构造参数与 wire/领域模型均有对应表。
- **design.interface** [extended, level 2] — 4.4 接口是否有请求/响应/状态码或方法签名？
  - evidence `4.4 接口与协议`: "\| 'submit(uri, *, model_version="vlm", data_id=None)' \| 'POST /extract/task' \| 请求 '{url, model_version, data_id?}'；响应 '{code, data: {task_id}}' \| 请求模型校验在 HTTP 异常处理之外；成功返回未查询过的 'AsyncResult' \|"
  - normalized: "\| 'submit(uri, *, model_version="vlm", data_id=None)' \| 'POST /extract/task' \| 请求 '{url, model_version, data_id?}';响应 '{code, data: {task_id}}' \| 请求模型校验在 HTTP 异常处理之外;成功返回未查询过的 'AsyncResult' \|"
  - evidence `4.4 接口与协议`: "- 'POST /extract/task' 请求头：'Authorization: Bearer <api_key>'、'Accept: application/json'；响应 200 成功信封。"
  - normalized: "- 'POST /extract/task' 请求头:'Authorization: Bearer <api_key>'、'Accept: application/json';响应 200 成功信封。"
  - rationale: 公共 API 表给出方法签名、网络行为与请求/响应；HTTP 契约补充请求头与 200 成功信封。
- **design.sequence** [extended, level 2] — 4.5 复杂流程是否有时序图或等价分步说明？
  - evidence `4.5 核心流程与时序`: "3. 查询抛瞬态错误：连续错误计数加一；达到 'max_consecutive_errors' 时抛 'MinerUExecutionError'；否则按退避推进间隔，并优先采用 'Retry-After'。"
  - normalized: "3. 查询抛瞬态错误:连续错误计数加一;达到 'max_consecutive_errors' 时抛 'MinerUExecutionError';否则按退避推进间隔,并优先采用 'Retry-After'。"
  - evidence `4.5 核心流程与时序`: "1. 首次查询前检查 deadline；若已耗尽，立即抛 'MinerUTimeoutError'（'last_status=None'）。"
  - normalized: "1. 首次查询前检查 deadline;若已耗尽,立即抛 'MinerUTimeoutError'('last_status=None')。"
  - rationale: 4.5 以 6 步控制流契约覆盖首次 deadline 检查、瞬态错误、终态、sleep 截断与重复 wait 等异常路径。
- **design.errors** [extended, level 2] — 4.6 每个错误码是否有触发场景与处理策略？
  - evidence `4.6 异常处理与错误码`: "\| HTTP 429 \| 'MinerUTransientError'（携带 'Retry-After'） \| 是 \|"
  - normalized: "\| HTTP 429 \| 'MinerUTransientError'(携带 'Retry-After') \| 是 \|"
  - evidence `4.6 异常处理与错误码`: "\| 'auth' \| 'A0202'、'A0211'、'-60013' \| 'MinerUAuthenticationError' \|"
  - normalized: "\| 'auth' \| 'A0202'、'A0211'、'-60013' \| 'MinerUAuthenticationError' \|"
  - rationale: 提交/查询映射表为每类触发条件给出异常类型与是否可重试；业务错误码表按类别映射到具体异常。

## NFR 可度量 (nfr)

- **nfr.measurable** [core, level 2] — 第 5 章每条 NFR 是否有数字、单位或验收方式？
  - evidence `5. 非功能性需求`: "- **等待预算**：'timeout' 与 'deadline_epoch' 必须覆盖整个轮询；sleep 永不越过 deadline。验收：AC-4.2 ~ AC-4.4。"
  - normalized: "- **等待预算**:'timeout' 与 'deadline_epoch' 必须覆盖整个轮询;sleep 永不越过 deadline。验收:AC-4.2 ~ AC-4.4。"
  - evidence `5. 非功能性需求`: "- **单请求超时**：默认 'request_timeout=10.0' s；可配置为 '(connect, read)' 二元组。验收：AC-1.4。"
  - normalized: "- **单请求超时**:默认 'request_timeout=10.0' s;可配置为 '(connect, read)' 二元组。验收:AC-1.4。"
  - rationale: 每条 NFR 附数字或验收项，例如等待预算引用 AC-4.2~AC-4.4、单请求超时给出 10.0 s。
- **nfr.coverage** [core, level 2] — 第 5 章是否覆盖性能、可靠性、可观测性、安全，或说明不适用？
  - evidence `5. 非功能性需求`: "- **等待预算**：'timeout' 与 'deadline_epoch' 必须覆盖整个轮询；sleep 永不越过 deadline。验收：AC-4.2 ~ AC-4.4。"
  - normalized: "- **等待预算**:'timeout' 与 'deadline_epoch' 必须覆盖整个轮询;sleep 永不越过 deadline。验收:AC-4.2 ~ AC-4.4。"
  - evidence `5. 非功能性需求`: "- **连续瞬态错误上限**：默认 3 次；达到上限抛 'MinerUExecutionError'，避免无限重试。验收：AC-5.5。"
  - normalized: "- **连续瞬态错误上限**:默认 3 次;达到上限抛 'MinerUExecutionError',避免无限重试。验收:AC-5.5。"
  - evidence `5. 非功能性需求`: "- **可测试性**：时钟、随机源、Session、指标钩子均可注入；29 个客户端测试函数全部无网络。验收：'tests/test_client.py'。"
  - normalized: "- **可测试性**:时钟、随机源、Session、指标钩子均可注入;29 个客户端测试函数全部无网络。验收:'tests/test_client.py'。"
  - evidence `5. 非功能性需求`: "- **凭证**：'api_key' 只从显式参数或 'MINERU_API_KEY' 读取；不得写入日志、异常消息或指标标签。验收：AC-1.1 / AC-1.2 + 代码评审。"
  - normalized: "- **凭证**:'api_key' 只从显式参数或 'MINERU_API_KEY' 读取;不得写入日志、异常消息或指标标签。验收:AC-1.1 / AC-1.2 + 代码评审。"
  - rationale: 第 5 章分设性能与资源、可靠性与容灾、可观测性、安全与合规四节，覆盖四类。
- **nfr.honesty** [core, level 2] — 未实测的指标是否标了 [estimated] 或 未实现？
  - evidence `5. 非功能性需求`: "- **端到端基线**：13 页真实样本端到端 37.5 s，其中等待 36.56 s（2026-10-21，README）；该数字是观测基线，不是 SLA。[estimated] P95 / P99 尚未统计。"
  - normalized: "- **端到端基线**:13 页真实样本端到端 37.5 s,其中等待 36.56 s(2026-10-21,README);该数字是观测基线,不是 SLA。[estimated] P95 / P99 尚未统计。"
  - evidence `5. 非功能性需求`: "- **日志**：'mineru.submit'、'mineru.poll'、'mineru.poll.error'、'mineru.succeeded'、'mineru.failed'、'mineru.timeout'、'mineru.on_update.failed'、'mineru.metric.failed'；'correlation_id' 附加到所有日志。验收：AC-10.3 **未实现**（缺少独立测试）。"
  - normalized: "- **日志**:'mineru.submit'、'mineru.poll'、'mineru.poll.error'、'mineru.succeeded'、'mineru.failed'、'mineru.timeout'、'mineru.on_update.failed'、'mineru.metric.failed';'correlation_id' 附加到所有日志。验收:AC-10.3 **未实现**(缺少独立测试)。"
  - rationale: 未统计的 P95/P99 标 [estimated]；AC-10.1~AC-10.3 与相关日志/指标验收明确标“未实现”。

## 上线可回滚 (rollout)

- **rollout.release** [core, level 2] — 6.1 是否有发布策略与灰度节奏？
  - evidence `6.1 发布与灰度`: "1. **Phase 1（候选）**：发布 '0.1.0rcN' 到测试索引；在 13 页真实样本与全部单测上跑通；观察 7 天。"
  - normalized: "1. **Phase 1(候选)**:发布 '0.1.0rcN' 到测试索引;在 13 页真实样本与全部单测上跑通;观察 7 天。"
  - evidence `6.1 发布与灰度`: "3. **观察期**：正式发布后 14 天内，任何客户端回归按 6.4 回滚。"
  - normalized: "3. **观察期**:正式发布后 14 天内,任何客户端回归按 6.4 回滚。"
  - rationale: 两阶段候选版到正式版，并给出 7 天候选观察与 14 天正式观察期；说明库形态下以候选版+内部集成验证替代流量灰度。
- **rollout.migration** [core, level 2] — 6.2 是否有迁移/兼容方案，或说明无需迁移？
  - evidence `6.2 数据迁移与兼容性`: "- **无数据迁移**：客户端不落盘、不持有任务状态；'task_id' 由调用方保存。"
  - normalized: "- **无数据迁移**:客户端不落盘、不持有任务状态;'task_id' 由调用方保存。"
  - evidence `6.2 数据迁移与兼容性`: "- **回退兼容**：行为契约与异常层级保持不变；'MinerUParserError' 为纯加性根异常，既有 'except MinerUError' 不受影响。"
  - normalized: "- **回退兼容**:行为契约与异常层级保持不变;'MinerUParserError' 为纯加性根异常,既有 'except MinerUError' 不受影响。"
  - rationale: 明确无数据迁移及理由，并说明公共导入路径已私有化、异常层级保持兼容。
- **rollout.smoke** [core, level 2] — 6.3 是否有冒烟清单与观察指标？
  - evidence `6.3 上线验证与冒烟`: "\| 冒烟项 \| 步骤 \| 观察指标 \|"
  - normalized: "\| 冒烟项 \| 步骤 \| 观察指标 \|"
  - evidence `6.3 上线验证与冒烟`: "\| 单元回归 \| 'pytest tests/test_client.py -q' \| 29 个测试函数全通过 \|"
  - normalized: "\| 单元回归 \| 'pytest tests/test_client.py -q' \| 29 个测试函数全通过 \|"
  - evidence `6.3 上线验证与冒烟`: "\| 真实样本 \| 按 README 运行 13 页示例 PDF \| 'status=success'；端到端耗时、等待阶段耗时、'poll_count' \|"
  - normalized: "\| 真实样本 \| 按 README 运行 13 页示例 PDF \| 'status=success';端到端耗时、等待阶段耗时、'poll_count' \|"
  - rationale: 6.3 表列出单元回归、管道回归、真实样本、异常路径与可观测性冒烟项及对应观察指标。
- **rollout.rollback_trigger** [core, level 2] — 6.4 回滚触发条件是否是可观测数字？
  - evidence `6.4 回滚与熔断`: "- 真实样本端到端耗时连续 3 次超过基线 37.5 s 的 150%（即 > 56.25 s）。"
  - normalized: "- 真实样本端到端耗时连续 3 次超过基线 37.5 s 的 150%(即 > 56.25 s)。"
  - evidence `6.4 回滚与熔断`: "- 客户端相关异常率连续 10 分钟 > 1%。"
  - normalized: "- 客户端相关异常率连续 10 分钟 > 1%。"
  - rationale: 回滚触发条件为可观测数字：单测失败数、耗时超基线 150%、429 比例 >10%、异常率 >1%。
- **rollout.rollback_steps** [core, level 2] — 6.4 回滚步骤是否可执行？
  - evidence `6.4 回滚与熔断`: "1. 在 PyPI 上 yank 当前版本，保留元数据；通知使用者固定到上一稳定版本。"
  - normalized: "1. 在 PyPI 上 yank 当前版本,保留元数据;通知使用者固定到上一稳定版本。"
  - evidence `6.4 回滚与熔断`: "2. 回退发布提交（'git revert <release-commit>'），重新打上一版本标签。"
  - normalized: "2. 回退发布提交('git revert <release-commit>'),重新打上一版本标签。"
  - rationale: 给出 yank、git revert 打标签、恢复策略并重跑测试、复跑样本解除熔断等可执行编号步骤。

## 替代方案诚实 (alternatives)

- **alts.status_quo** [core, level 2] — 第 7 章是否有 Status Quo 及其成本/风险？
  - evidence `7. 替代方案与权衡`: "- **成本**：等待阶段占端到端 97.5%（36.56 s / 37.5 s）；固定间隔无法同时满足“不过密”和“不过慢”。"
  - normalized: "- **成本**:等待阶段占端到端 97.5%(36.56 s / 37.5 s);固定间隔无法同时满足“不过密”和“不过慢”。"
  - evidence `7. 替代方案与权衡`: "- **触发阈值**：当第二个调用方开始复制同一段轮询代码时，Status Quo 的成本已超过收敛成本。"
  - normalized: "- **触发阈值**:当第二个调用方开始复制同一段轮询代码时,Status Quo 的成本已超过收敛成本。"
  - rationale: 7.1 给出 Status Quo 的思路、成本（97.5% 等待耗时）、风险与触发阈值。
- **alts.rejected** [core, level 2] — 第 7 章是否至少有一个被否决方案，且淘汰原因对应当前约束？
  - evidence `7. 替代方案与权衡`: "- **淘汰原因**：库的公共入口是同步 'parse()'；引入事件循环会改变调用方的编程模型，并把线程安全、取消传播、资源生命周期问题带入当前阶段。与 G1 / G5 的“同步、可注入、无网络测试”约束不对应。"
  - normalized: "- **淘汰原因**:库的公共入口是同步 'parse()';引入事件循环会改变调用方的编程模型,并把线程安全、取消传播、资源生命周期问题带入当前阶段。与 G1 / G5 的“同步、可注入、无网络测试”约束不对应。"
  - evidence `7. 替代方案与权衡`: "- **淘汰原因**：它不理解任务语义——无法区分“提交阶段结果未知”与“查询阶段可重试”，也无法提供 'resume()'、终态解释、错误分类与等待预算；仍需在其上重建一层客户端契约。"
  - normalized: "- **淘汰原因**:它不理解任务语义——无法区分“提交阶段结果未知”与“查询阶段可重试”,也无法提供 'resume()'、终态解释、错误分类与等待预算;仍需在其上重建一层客户端契约。"
  - rationale: 两个被否决方案均给出思路、优点与淘汰原因，且淘汰原因对应同步 parse 入口与任务语义约束。
- **alts.matrix** [core, level 2] — 第 7 章是否有与约束对应的权衡矩阵？
  - evidence `7. 替代方案与权衡`: "\| 维度 \| Status Quo \| 'asyncio' 方案 \| 'urllib3.Retry' 方案 \| 选定方案 \|"
  - normalized: "\| 维度 \| Status Quo \| 'asyncio' 方案 \| 'urllib3.Retry' 方案 \| 选定方案 \|"
  - evidence `7. 替代方案与权衡`: "\| 实现与维护成本 \| 低（但重复） \| 高 \| 中 \| 中 \|"
  - normalized: "\| 实现与维护成本 \| 低(但重复) \| 高 \| 中 \| 中 \|"
  - rationale: 权衡矩阵以实现成本、轮询正确性、同步兼容、可测试性、错误分类与阶段契合度为维度对比四方案。
- **alts.consistency** [core, level 2] — 第 7 章结论是否与 Goals、架构选型一致？
  - evidence `7. 替代方案与权衡`: "结论：选定方案与 G1 ~ G5 一致——把 97.5% 的等待成本收敛到一个可注入、可测试、可观测的同步客户端；异步与第三方重试库留作后续评估。"
  - normalized: "结论:选定方案与 G1 ~ G5 一致——把 97.5% 的等待成本收敛到一个可注入、可测试、可观测的同步客户端;异步与第三方重试库留作后续评估。"
  - rationale: 结论明确与 G1~G5 一致，并复述同步、可注入、可测试、可观测的选型主张。

## 跨章自洽 (cross_consistency)

- **x.goals_trace** [core, level 2] — 后续章节是否逐条回应 Goals？
  - evidence `全文`: "- **G1 - 统一入口与配置（架构级）**：用一组显式参数构造客户端，凭证、'base_url'、超时与轮询策略在发起网络请求前完成校验。验收：AC-1.1 ~ AC-1.6 全部通过 'tests/test_client.py'。"
  - normalized: "- **G1 - 统一入口与配置(架构级)**:用一组显式参数构造客户端,凭证、'base_url'、超时与轮询策略在发起网络请求前完成校验。验收:AC-1.1 ~ AC-1.6 全部通过 'tests/test_client.py'。"
  - evidence `全文`: "- **G5 - 生命周期、可观测与可测试性（运维级）**：Session 所有权明确；'on_update' / 'on_metric' 异常隔离；'correlation_id' 进入所有日志；时钟、随机源、Session 均可注入。验收：AC-7.1 ~ AC-10.3（AC-10.x 见 4.7 的“未实现”标注）+ 29 个无网络测试函数。"
  - normalized: "- **G5 - 生命周期、可观测与可测试性(运维级)**:Session 所有权明确;'on_update' / 'on_metric' 异常隔离;'correlation_id' 进入所有日志;时钟、随机源、Session 均可注入。验收:AC-7.1 ~ AC-10.3(AC-10.x 见 4.7 的“未实现”标注)+ 29 个无网络测试函数。"
  - rationale: G1~G5 分别由 4.3/4.4、4.5、4.6、5.3/5.4 及 AC-1.x~AC-10.x 承接，G5 未实现项也在 4.7/5.3 标注。
- **x.nfr_arch** [core, level 2] — NFR 与架构、选型是否一致？
  - evidence `全文`: "- **轮询节奏**：默认初始间隔 3 s、上限 30 s、退避 1.5、抖动 0.5；状态变化重置间隔。验收：AC-5.1 ~ AC-5.3。"
  - normalized: "- **轮询节奏**:默认初始间隔 3 s、上限 30 s、退避 1.5、抖动 0.5;状态变化重置间隔。验收:AC-5.1 ~ AC-5.3。"
  - rationale: 5.1 的轮询节奏默认值与 4.3 PollPolicy、4.5 公式一致；5.2 的连续错误上限与 4.5/4.6 一致。
- **x.rollback_release** [core, level 2] — 回滚与发布策略是否一致？
  - evidence `全文`: "3. **观察期**：正式发布后 14 天内，任何客户端回归按 6.4 回滚。"
  - normalized: "3. **观察期**:正式发布后 14 天内,任何客户端回归按 6.4 回滚。"
  - evidence `全文`: "1. 在 PyPI 上 yank 当前版本，保留元数据；通知使用者固定到上一稳定版本。"
  - normalized: "1. 在 PyPI 上 yank 当前版本,保留元数据;通知使用者固定到上一稳定版本。"
  - rationale: 6.1 规定正式发布后回归按 6.4 回滚，6.4 的 yank/revert 步骤与该发布形态对应。

## 证据卫生 (evidence_hygiene)

- **x.no_placeholders** [core, level 2] — 是否没有把 无 / ... / 待补充 / TBD 当作实质回答？
  - evidence `全文`: "未识别的原始状态不进入领域状态机，按瞬时错误处理，交由轮询继续尝试。"
  - normalized: "未识别的原始状态不进入领域状态机,按瞬时错误处理,交由轮询继续尝试。"
  - rationale: 全文检索未见 TBD/待补充/... 作为实质回答；“无数据迁移”“—”等均表示真实不适用。
- **x.no_code** [core, level 2] — 是否没有堆砌实现代码、测试日志或偶发报错？
  - evidence `全文`: "- **契约优先**：Spec 只规定“必须如何判定”，不规定实现代码；轮询公式与状态映射见 4.5 / 4.6。"
  - normalized: "- **契约优先**:Spec 只规定“必须如何判定”,不规定实现代码;轮询公式与状态映射见 4.5 / 4.6。"
  - rationale: 全文只有 mermaid 图、公式与异常层级文本块，无实现代码、测试日志或偶发报错堆砌。
- **x.numbers_sourced** [core, level 2] — 关键数字是否有出处，或标了 [estimated]？
  - evidence `全文`: "- **端到端基线**：13 页真实样本端到端 37.5 s，其中等待 36.56 s（2026-10-21，README）；该数字是观测基线，不是 SLA。[estimated] P95 / P99 尚未统计。"
  - normalized: "- **端到端基线**:13 页真实样本端到端 37.5 s,其中等待 36.56 s(2026-10-21,README);该数字是观测基线,不是 SLA。[estimated] P95 / P99 尚未统计。"
  - evidence `全文`: "**证据（度量）**：README 记录的 2026-10-21 真实运行中，同一份 13 页 PDF 的端到端耗时为 37.5 s，其中等待阶段 36.56 s、提交 0.22 s、下载 0.67 s、解析 0.03 s。等待阶段占总耗时 **97.5%**。这意味着客户端的轮询策略就是整条链路的主要成本；把轮询留给每个调用方各自实现，等于把 97.5% 的耗时行为交给不可控的重复代码。"
  - normalized: "**证据(度量)**:README 记录的 2026-10-21 真实运行中,同一份 13 页 PDF 的端到端耗时为 37.5 s,其中等待阶段 36.56 s、提交 0.22 s、下载 0.67 s、解析 0.03 s。等待阶段占总耗时 **97.5%**。这意味着客户端的轮询策略就是整条链路的主要成本;把轮询留给每个调用方各自实现,等于把 97.5% 的耗时行为交给不可控的重复代码。"
  - rationale: 关键性能数字注明 README 与日期，未统计的 P95/P99 标 [estimated]，观察窗口也标 [estimated]。
- **x.no_fabricated_refs** [core, level 2] — 是否没有捏造 SPEC 引用、depends_on 目标或 M<N>？
  - evidence `全文`: "\| 关联资源 \| [全局架构](../../architecture/mineru-parser-architecture.md)、SPEC-002、SPEC-003、SPEC-004 \|"
  - normalized: "\| 关联资源 \| [全局架构](../../architecture/mineru-parser-architecture.md)、SPEC-002、SPEC-003、SPEC-004 \|"
  - evidence `全文`: "全局组件边界见 [全局架构](../../architecture/mineru-parser-architecture.md)；本文只描述客户端范围内的拓扑与契约。"
  - normalized: "全局组件边界见 [全局架构](../../architecture/mineru-parser-architecture.md);本文只描述客户端范围内的拓扑与契约。"
  - rationale: depends_on、关联资源与正文链接一致指向全局架构文档；SPEC-002/003/004 仅作关联引用，未出现 M<N> 占位。

## Audit failures

None.
