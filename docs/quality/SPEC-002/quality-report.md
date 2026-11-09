# Spec Quality Report

- Target: `docs/specs/SPEC-002-result-downloader/spec.md`
- Rubric: 1.1.0 (`1e6c4740ed85512b1657e6798e481c893fe015f4ce2a140665ff6ecb2ef7b29e`)
- Target SHA-256: `f921875b0a047daab6f4be188d797b005cacfc7b1d4216fb47314e81e2711fda`
- Reviewer session: `review-spec-002`

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
  - evidence `1.1 系统现状`: "'mineru-parser' 的四阶段链路中，下载器是第三阶段：客户端交付 'zip_url' 后，下载器把结果包读入 'io.BytesIO'，再交给提取器解析。下载器的上游是任意绝对 HTTP(S) URL（首个消费者是 MinerU 返回的 'zip_url'），下游统一交付内存流；它不解压、不校验哈希、不落盘。"
  - normalized: "'mineru-parser' 的四阶段链路中,下载器是第三阶段:客户端交付 'zip_url' 后,下载器把结果包读入 'io.BytesIO',再交给提取器解析。下载器的上游是任意绝对 HTTP(S) URL(首个消费者是 MinerU 返回的 'zip_url'),下游统一交付内存流;它不解压、不校验哈希、不落盘。"
  - evidence `1.1 系统现状`: "当前技术栈为 Python 3.12、'requests.Session'、'urllib3'、'idna'，同步阻塞、分块读取。组件已随 SPEC-004 私有化为 'mineru_parser._downloader'；外部用户通过 'parse()' 间接使用，行为契约仍由本文约束。"
  - normalized: "当前技术栈为 Python 3.12、'requests.Session'、'urllib3'、'idna',同步阻塞、分块读取。组件已随 SPEC-004 私有化为 'mineru_parser._downloader';外部用户通过 'parse()' 间接使用,行为契约仍由本文约束。"
  - rationale: 第 1.1 节写明模块在四阶段链路中的职责、上下游边界、技术栈，并以流程图给出核心流程。
- **bg.failure_chain** [core, level 2] — 1.2 是否有从触发到后果的分步失败链？
  - evidence `1.2 核心技术痛点`: "下载看似只是 'requests.get(url).content'，但结果包 URL 可能来自外部用户或不可信网络，失败链如下："
  - normalized: "下载看似只是 'requests.get(url).content',但结果包 URL 可能来自外部用户或不可信网络,失败链如下:"
  - evidence `1.2 核心技术痛点`: "1. **内存不可控**：'.content' 一次性读入完整响应；大文件、错误页或恶意 URL 可让进程 OOM。"
  - normalized: "1. **内存不可控**:'.content' 一次性读入完整响应;大文件、错误页或恶意 URL 可让进程 OOM。"
  - rationale: 第 1.2 节以编号列表从输入不可信出发，逐项给出触发条件与后果，构成失败链。
- **bg.trigger** [core, level 2] — 1.3 是否解释了为什么现在做？
  - evidence `1.3 重构/设计动机`: "1. **下载器成为每条 'parse()' 调用的必经阶段**：SPEC-004 落地后，下载失败会直接表现为管道第 3 阶段失败；组件契约必须在 0.1.0 发布前固化。"
  - normalized: "1. **下载器成为每条 'parse()' 调用的必经阶段**:SPEC-004 落地后,下载失败会直接表现为管道第 3 阶段失败;组件契约必须在 0.1.0 发布前固化。"
  - evidence `1.3 重构/设计动机`: "2. **安全评审已给出必须闭环的问题清单**：SSRF、逐跳重定向、IDNA、敏感头移除与签名 URL 脱敏都不能留到后续版本。"
  - normalized: "2. **安全评审已给出必须闭环的问题清单**:SSRF、逐跳重定向、IDNA、敏感头移除与签名 URL 脱敏都不能留到后续版本。"
  - rationale: 第 1.3 节以 SPEC-004 落地、安全评审闭环和 0.1.0 发布时点解释为什么现在做。
- **bg.non_goals** [core, level 2] — 1.4 是否写了不做的后果与本次非目标？
  - evidence `1.4 非目标`: "- **解压 ZIP、校验压缩包内部结构、防御 ZIP 炸弹**：本次不做；由提取器承担，下载器只负责传输。"
  - normalized: "- **解压 ZIP、校验压缩包内部结构、防御 ZIP 炸弹**:本次不做;由提取器承担,下载器只负责传输。"
  - evidence `1.4 非目标`: "**不做的后果**：不落盘意味着大文件只能受 'max_bytes' 约束；不做哈希校验意味着内容完整性由下游负责；不消除 DNS Rebinding 意味着强安全场景需要额外网络隔离；不做主动限流意味着 429 由服务端与重试策略共同约束。以上代价已写入第 5 章与第 7 章。"
  - normalized: "**不做的后果**:不落盘意味着大文件只能受 'max_bytes' 约束;不做哈希校验意味着内容完整性由下游负责;不消除 DNS Rebinding 意味着强安全场景需要额外网络隔离;不做主动限流意味着 429 由服务端与重试策略共同约束。以上代价已写入第 5 章与第 7 章。"
  - rationale: 第 1.4 节列出 14 条非目标，并单列“不做的后果”说明各项代价。

## 痛点证据 (pain_evidence)

- **bg.pain_evidence** [core, level 2] — 1.2 是否有至少一条可核实的证据（事故、度量或引述）？
  - evidence `1.2 核心技术痛点`: "**证据（可核实事件）**：2026-10-21 的代码评审复现了四个具体问题——慢速滴流响应绕过总预算、body 阶段读取超时被误分类、超时异常链泄漏签名 URL、IPv6 过渡网段判断失效（见 'changelog.md'「代码评审修复（超时 / 异常链 / 校验边界）」，2026-10-21）。同日的架构评审又发现 SSRF 判据不足、DNS 重试时序矛盾、注入 Session 敏感头泄漏、IDNA 规范化缺失等问题。这些问题直接对应上面的失败链 2 ~ 5。"
  - normalized: "**证据(可核实事件)**:2026-10-21 的代码评审复现了四个具体问题——慢速滴流响应绕过总预算、body 阶段读取超时被误分类、超时异常链泄漏签名 URL、IPv6 过渡网段判断失效(见 'changelog.md'「代码评审修复(超时 / 异常链 / 校验边界)」,2026-10-21)。同日的架构评审又发现 SSRF 判据不足、DNS 重试时序矛盾、注入 Session 敏感头泄漏、IDNA 规范化缺失等问题。这些问题直接对应上面的失败链 2 ~ 5。"
  - rationale: 给出日期、来源章节与四个具体复现问题，并与失败链 2~5 建立对应。

## 目标可验收 (goal_verifiability)

- **goal.verifiable** [core, level 2] — 2.1 每个 Goal 是否都有验收方式？
  - evidence `2.1 目标`: "- **G1 - 统一入口与配置（架构级）**：'resolve(url) -> io.BytesIO' 是唯一入口；非法配置在构造期暴露。验收：AC-1.1 ~ AC-1.11 全部通过。"
  - normalized: "- **G1 - 统一入口与配置(架构级)**:'resolve(url) -> io.BytesIO' 是唯一入口;非法配置在构造期暴露。验收:AC-1.1 ~ AC-1.11 全部通过。"
  - evidence `2.1 目标`: "- **G6 - 可注入依赖与无网络测试（工程效率级）**：Session、DNS Resolver、时钟、随机源、指标钩子均可注入；'tests/test_downloader.py' 的 111 个测试函数无需网络。验收：AC-1.8、AC-8.5 + 测试文件。"
  - normalized: "- **G6 - 可注入依赖与无网络测试(工程效率级)**:Session、DNS Resolver、时钟、随机源、指标钩子均可注入;'tests/test_downloader.py' 的 111 个测试函数无需网络。验收:AC-1.8、AC-8.5 + 测试文件。"
  - rationale: G1~G6 每条都附有验收标准编号或测试文件，验收方式具体可执行。
- **goal.quantified** [core, level 2] — 2.1 是否至少有一个 Goal 有数字/单位/明确阈值？
  - evidence `2.1 目标`: "- **G2 - 流式读取与内存 / 总预算（性能级）**：默认 'max_bytes' 50 MiB、'chunk_size' 64 KiB、'total_timeout' 300 s；分块读取，超限不返回部分数据。验收：AC-2.1 ~ AC-2.8、AC-3.1 ~ AC-3.10、AC-5.1 ~ AC-5.7。"
  - normalized: "- **G2 - 流式读取与内存 / 总预算(性能级)**:默认 'max_bytes' 50 MiB、'chunk_size' 64 KiB、'total_timeout' 300 s;分块读取,超限不返回部分数据。验收:AC-2.1 ~ AC-2.8、AC-3.1 ~ AC-3.10、AC-5.1 ~ AC-5.7。"
  - rationale: G2 给出 50 MiB、64 KiB、300 s 三个带单位的数值阈值。
- **goal.count** [extended, level 2] — 2.1 Goals 是否控制在 3–6 个？
  - evidence `2.1 目标`: "- **G1 - 统一入口与配置（架构级）**：'resolve(url) -> io.BytesIO' 是唯一入口；非法配置在构造期暴露。验收：AC-1.1 ~ AC-1.11 全部通过。"
  - normalized: "- **G1 - 统一入口与配置(架构级)**:'resolve(url) -> io.BytesIO' 是唯一入口;非法配置在构造期暴露。验收:AC-1.1 ~ AC-1.11 全部通过。"
  - evidence `2.1 目标`: "- **G3 - 重试、退避与错误分类（可靠性级）**：可重试状态码固定为 '{408, 429, 500, 502, 503, 504}'；默认最多 3 次尝试；'Retry-After' 优先且截断。验收：AC-4.1 ~ AC-4.12。"
  - normalized: "- **G3 - 重试、退避与错误分类(可靠性级)**:可重试状态码固定为 '{408, 429, 500, 502, 503, 504}';默认最多 3 次尝试;'Retry-After' 优先且截断。验收:AC-4.1 ~ AC-4.12。"
  - rationale: 共 6 个 Goal（G1~G6），处于 3–6 区间，并分别标注架构级、性能级、可靠性级、安全级、运维级、工程效率级分类。

## 非目标边界 (non_goal_boundary)

- **nongoal.labeled** [core, level 2] — 2.2 每条 Non-Goal 是否标了本次不做或 Deferred to Phase 2？
  - evidence `2.2 非目标`: "- **NG1 - 解压与 ZIP 结构校验**：由提取器承担（本次不做）。"
  - normalized: "- **NG1 - 解压与 ZIP 结构校验**:由提取器承担(本次不做)。"
  - evidence `2.2 非目标`: "- **NG12 - 自动在 'MinerUApiClient.wait()' 内下载**：由管道编排（Deferred to Phase 2）。"
  - normalized: "- **NG12 - 自动在 'MinerUApiClient.wait()' 内下载**:由管道编排(Deferred to Phase 2)。"
  - rationale: NG1~NG11 均标“本次不做”，NG12 单独标“Deferred to Phase 2”，全部有状态标注。
- **nongoal.not_dumping_ground** [extended, level 2] — 2.2 非目标是否能追溯到痛点或边界？
  - evidence `2.2 非目标`: "- **NG6 - 主动限流**：只响应服务端限流（本次不做）。"
  - normalized: "- **NG6 - 主动限流**:只响应服务端限流(本次不做)。"
  - evidence `2.2 非目标`: "- **NG10 - DNS Rebinding 完全消除**：记录为残余风险（本次不做）。"
  - normalized: "- **NG10 - DNS Rebinding 完全消除**:记录为残余风险(本次不做)。"
  - rationale: 每条非目标都附有归属方、残余风险或成本理由，可追溯到职责边界或第 1.2 节痛点。

## 架构自洽 (architecture)

- **arch.solution_shape** [core, level 2] — 第 3 章是否有本次变更的拓扑或等价的模块/数据流描述？
  - evidence `3. 架构设计与核心方案`: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)（Approved）。下载器位于管道第 3 阶段，上游是客户端交付的 'zip_url'，下游是提取器的内存 ZIP 流。"
  - normalized: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)(Approved)。下载器位于管道第 3 阶段,上游是客户端交付的 'zip_url',下游是提取器的内存 ZIP 流。"
  - evidence `3. 架构设计与核心方案`: "本次变更范围内的拓扑："
  - normalized: "本次变更范围内的拓扑:"
  - rationale: 第 3 章给出本次变更范围的 mermaid 拓扑、模块职责表与 8 步数据流转，满足变更范围拓扑/数据流要求。
- **arch.topology** [extended, level 2] — 3.1 拓扑图是否让每个模块有一句职责？
  - evidence `3.2 核心模块职责`: "\| 'ResultDownloader' \| 配置校验、'resolve' 编排、Session 生命周期、重试与总预算 \| 不解压、不校验哈希、不落盘 \|"
  - normalized: "\| 'ResultDownloader' \| 配置校验、'resolve' 编排、Session 生命周期、重试与总预算 \| 不解压、不校验哈希、不落盘 \|"
  - evidence `3.2 核心模块职责`: "\| 'URL Guard' \| URL 语法、IDNA 规范化、DNS 解析、IP 公网性、逐跳重定向与降级检查、URL 脱敏 \| 不发起 HTTP 请求、不读取响应体 \|"
  - normalized: "\| 'URL Guard' \| URL 语法、IDNA 规范化、DNS 解析、IP 公网性、逐跳重定向与降级检查、URL 脱敏 \| 不发起 HTTP 请求、不读取响应体 \|"
  - rationale: 3.1 有拓扑图，3.2 表格为每个模块给出一句职责与明确不做的边界。
- **arch.change_set** [extended, level 2] — 第 3 章是否写清新增/改造/保持不变？
  - evidence `3. 架构设计与核心方案`: "- 新增：'MinerUParserError' 根异常在下载器侧的继承关系与断言。 - 改造：实现伪码收敛为契约条款；明确慢速滴流、逐跳复验与总预算的判定顺序。 - 不变：'resolve' 签名、默认限额、可重试状态码集合、异常体系、Session 所有权与遥测口径。"
  - normalized: "- 新增:'MinerUParserError' 根异常在下载器侧的继承关系与断言。 - 改造:实现伪码收敛为契约条款;明确慢速滴流、逐跳复验与总预算的判定顺序。 - 不变:'resolve' 签名、默认限额、可重试状态码集合、异常体系、Session 所有权与遥测口径。"
  - rationale: 第 3.1 节用新增/改造/保持不变三栏明确本次变更集。
- **arch.rationale** [extended, level 2] — 关键选型是否有理由，详细对比指向第 7 章？
  - evidence `3.4 关键选型与约束`: "- **流式分块而非 '.content'**：把内存上限变成硬约束，并允许在每个分块后检查 deadline。详细对比见第 7 章。"
  - normalized: "- **流式分块而非 '.content'**:把内存上限变成硬约束,并允许在每个分块后检查 deadline。详细对比见第 7 章。"
  - evidence `3.4 关键选型与约束`: "- **默认 50 MiB 与 300 s**：来自当前样本与部署假设，不是服务端承诺；调用方可通过参数覆盖。详细权衡见第 7 章。"
  - normalized: "- **默认 50 MiB 与 300 s**:来自当前样本与部署假设,不是服务端承诺;调用方可通过参数覆盖。详细权衡见第 7 章。"
  - rationale: 3.4 对四条关键选型给出理由，流式读取与默认限额明确指向第 7 章的详细对比。
- **arch.references_source** [extended, level 2] — 第 3 章是否引用 depends_on 架构文档，而不是自行展开其全局结构？
  - evidence `3. 架构设计与核心方案`: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)（Approved）。下载器位于管道第 3 阶段，上游是客户端交付的 'zip_url'，下游是提取器的内存 ZIP 流。"
  - normalized: "全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)(Approved)。下载器位于管道第 3 阶段,上游是客户端交付的 'zip_url',下游是提取器的内存 ZIP 流。"
  - evidence `3. 架构设计与核心方案`: "本次变更范围内的拓扑："
  - normalized: "本次变更范围内的拓扑:"
  - rationale: frontmatter 的 depends_on 指定架构文档，第 3 章引用它承载全局结构，并只展开下载器变更范围的拓扑与数据流。

## 详细设计完整 (detailed_design)

- **design.contract** [core, level 2] — 第 4 章是否至少有一份数据模型或接口契约？
  - evidence `4. 详细设计`: "\| 'resolve' \| 'resolve(url: str) -> io.BytesIO' \| 同步阻塞；成功返回游标 0 的新缓冲区；失败不返回部分数据 \|"
  - normalized: "\| 'resolve' \| 'resolve(url: str) -> io.BytesIO' \| 同步阻塞;成功返回游标 0 的新缓冲区;失败不返回部分数据 \|"
  - rationale: 第 4 章包含构造参数表、请求头/返回契约表与公共 API 签名表，至少一份接口契约。
- **design.data_model** [extended, level 2] — 4.3 数据模型是否有字段类型、必填与校验？
  - evidence `4.3 数据模型与契约`: "\| 参数 \| 默认值 \| 类型 \| 必填 \| 校验 / 语义 \|"
  - normalized: "\| 参数 \| 默认值 \| 类型 \| 必填 \| 校验 / 语义 \|"
  - evidence `4.3 数据模型与契约`: "\| 'max_bytes' \| '52428800'（50 MiB） \| 'int' \| 否 \| 正整数（拒绝 'bool'）；单次响应体硬上限 \|"
  - normalized: "\| 'max_bytes' \| '52428800'(50 MiB) \| 'int' \| 否 \| 正整数(拒绝 'bool');单次响应体硬上限 \|"
  - rationale: 4.3 的字段表逐项给出默认值、类型、是否必填和校验语义。
- **design.interface** [extended, level 2] — 4.4 接口是否有请求/响应/状态码或方法签名？
  - evidence `4.4 接口与协议`: "\| 'resolve' \| 'resolve(url: str) -> io.BytesIO' \| 同步阻塞；成功返回游标 0 的新缓冲区；失败不返回部分数据 \|"
  - normalized: "\| 'resolve' \| 'resolve(url: str) -> io.BytesIO' \| 同步阻塞;成功返回游标 0 的新缓冲区;失败不返回部分数据 \|"
  - evidence `4.4 接口与协议`: "\| 'close' \| 'close() -> None' \| 只关闭自建 Session；可重复调用 \|"
  - normalized: "\| 'close' \| 'close() -> None' \| 只关闭自建 Session;可重复调用 \|"
  - rationale: 4.4 给出公共方法签名与语义，并附 7 条交付契约。
- **design.sequence** [extended, level 2] — 4.5 复杂流程是否有时序图或等价分步说明？
  - evidence `4.5 核心流程与时序`: "7. **重试**：可重试状态码固定集合；第 $n$ 次失败后的延迟为 $\\min(I_0 b^{n-1}, I_{\\max}) \\cdot ((1-j)+jU)$；'Retry-After' 优先且不叠加抖动；重试从原始 URL 重新开始。"
  - normalized: "7. **重试**:可重试状态码固定集合;第 $n$ 次失败后的延迟为 $\\min(I_0 b^{n-1}, I_{\\max}) \\cdot ((1-j)+jU)$;'Retry-After' 优先且不叠加抖动;重试从原始 URL 重新开始。"
  - evidence `4.5 核心流程与时序`: "8. **关闭**：每个响应在离开当前请求作用域前关闭；重定向响应不读取响应体。"
  - normalized: "8. **关闭**:每个响应在离开当前请求作用域前关闭;重定向响应不读取响应体。"
  - rationale: 4.5 同时提供 sequenceDiagram 与 8 步控制流契约，覆盖重试、超时与失败清理路径。
- **design.errors** [extended, level 2] — 4.6 每个错误码是否有触发场景与处理策略？
  - evidence `4.6 异常处理与错误码`: "\| 构造参数非法 \| 'ResultDownloadConfigurationError' \| 否 \|"
  - normalized: "\| 构造参数非法 \| 'ResultDownloadConfigurationError' \| 否 \|"
  - evidence `4.6 异常处理与错误码`: "\| 响应体超过 'max_bytes' \| 'ResultDownloadTooLargeError' \| 否 \|"
  - normalized: "\| 响应体超过 'max_bytes' \| 'ResultDownloadTooLargeError' \| 否 \|"
  - rationale: 4.6 的错误表把触发条件、异常类型与是否重试逐行对应，另补充匹配顺序与脱敏规则。

## NFR 可度量 (nfr)

- **nfr.measurable** [core, level 2] — 第 5 章每条 NFR 是否有数字、单位或验收方式？
  - evidence `5. 非功能性需求`: "- **响应体上限**：默认 50 MiB；读取块默认 64 KiB；超限立即终止且不返回部分数据。验收：AC-3.1 ~ AC-3.6。"
  - normalized: "- **响应体上限**:默认 50 MiB;读取块默认 64 KiB;超限立即终止且不返回部分数据。验收:AC-3.1 ~ AC-3.6。"
  - evidence `5. 非功能性需求`: "- **超时**：连接 5 s、读取 30 s；总预算默认 300 s。验收：AC-5.1 ~ AC-5.7。"
  - normalized: "- **超时**:连接 5 s、读取 30 s;总预算默认 300 s。验收:AC-5.1 ~ AC-5.7。"
  - rationale: 5.1~5.4 的每条 NFR 均带数值、单位或明确验收标准编号。
- **nfr.coverage** [core, level 2] — 第 5 章是否覆盖性能、可靠性、可观测性、安全，或说明不适用？
  - evidence `5. 非功能性需求`: "- **响应体上限**：默认 50 MiB；读取块默认 64 KiB；超限立即终止且不返回部分数据。验收：AC-3.1 ~ AC-3.6。"
  - normalized: "- **响应体上限**:默认 50 MiB;读取块默认 64 KiB;超限立即终止且不返回部分数据。验收:AC-3.1 ~ AC-3.6。"
  - evidence `5. 非功能性需求`: "- **可重试集合**：'{408, 429, 500, 502, 503, 504}'；其他 4xx / 5xx 不重试。验收：AC-4.1 ~ AC-4.4。"
  - normalized: "- **可重试集合**:'{408, 429, 500, 502, 503, 504}';其他 4xx / 5xx 不重试。验收:AC-4.1 ~ AC-4.4。"
  - evidence `5. 非功能性需求`: "- **'outcome' 枚举**：'success' / 'config_error' / 'security_error' / 'too_large' / 'content_type_error' / 'http_error' / 'transient' / 'timeout' / 'unexpected'；禁止自由文本。验收：AC-9.6。"
  - normalized: "- **'outcome' 枚举**:'success' / 'config_error' / 'security_error' / 'too_large' / 'content_type_error' / 'http_error' / 'transient' / 'timeout' / 'unexpected';禁止自由文本。验收:AC-9.6。"
  - evidence `5. 非功能性需求`: "- **SSRF**：仅 HTTP(S)、拒绝 userinfo、拒绝控制字符与非法 host 字符、DNS 结果逐 IP 校验、IPv6 过渡地址处理。验收：AC-6.1 ~ AC-6.5。"
  - normalized: "- **SSRF**:仅 HTTP(S)、拒绝 userinfo、拒绝控制字符与非法 host 字符、DNS 结果逐 IP 校验、IPv6 过渡地址处理。验收:AC-6.1 ~ AC-6.5。"
  - rationale: 第 5 章分四节覆盖性能、可靠性、可观测性与安全，无类别缺失。
- **nfr.honesty** [core, level 2] — 未实测的指标是否标了 [estimated] 或 未实现？
  - evidence `5. 非功能性需求`: "- **延迟基线**：[estimated] 单次 50 MiB 下载的 P95 尚未统计；当前以真实结果包（约 1 MiB）与单元测试作为功能基线，不把它当作 SLA。"
  - normalized: "- **延迟基线**:[estimated] 单次 50 MiB 下载的 P95 尚未统计;当前以真实结果包(约 1 MiB)与单元测试作为功能基线,不把它当作 SLA。"
  - rationale: 未实测的 P95 延迟明确标 [estimated] 并说明不作为 SLA。

## 上线可回滚 (rollout)

- **rollout.release** [core, level 2] — 6.1 是否有发布策略与灰度节奏？
  - evidence `6.1 发布与灰度`: "下载器随 'mineru-parser' 包发布，采用“候选版 → 正式版”两阶段："
  - normalized: "下载器随 'mineru-parser' 包发布,采用“候选版 → 正式版”两阶段:"
  - evidence `6.1 发布与灰度`: "1. **Phase 1（候选）**：发布 '0.1.0rcN'；在真实 'zip_url'、13 页样本与 111 个下载器测试上验证；观察 7 天。 2. **Phase 2（正式）**：无 P0/P1 问题后发布 '0.1.0'。 3. **观察期**：发布后 14 天；安全类问题按 6.4 立即回滚。"
  - normalized: "1. **Phase 1(候选)**:发布 '0.1.0rcN';在真实 'zip_url'、13 页样本与 111 个下载器测试上验证;观察 7 天。 2. **Phase 2(正式)**:无 P0/P1 问题后发布 '0.1.0'。 3. **观察期**:发布后 14 天;安全类问题按 6.4 立即回滚。"
  - rationale: 6.1 给出候选版到正式版的两阶段发布策略及 7/14 天观察节奏。
- **rollout.migration** [core, level 2] — 6.2 是否有迁移/兼容方案，或说明无需迁移？
  - evidence `6.2 数据迁移与兼容性`: "- **无数据迁移**：下载器不落盘、不缓存；返回的 'BytesIO' 由调用方持有。"
  - normalized: "- **无数据迁移**:下载器不落盘、不缓存;返回的 'BytesIO' 由调用方持有。"
  - evidence `6.2 数据迁移与兼容性`: "- **兼容性**：组件已私有化；外部用户通过 'parse()' 使用，无迁移动作。"
  - normalized: "- **兼容性**:组件已私有化;外部用户通过 'parse()' 使用,无迁移动作。"
  - rationale: 6.2 明确说明无需数据迁移，并说明对外兼容与内部导入路径迁移。
- **rollout.smoke** [core, level 2] — 6.3 是否有冒烟清单与观察指标？
  - evidence `6.3 上线验证与冒烟`: "\| 冒烟项 \| 步骤 \| 观察指标 \|"
  - normalized: "\| 冒烟项 \| 步骤 \| 观察指标 \|"
  - evidence `6.3 上线验证与冒烟`: "\| 单元回归 \| 'python -m pytest tests/test_downloader.py -q' \| 111 个测试函数全通过 \|"
  - normalized: "\| 单元回归 \| 'python -m pytest tests/test_downloader.py -q' \| 111 个测试函数全通过 \|"
  - rationale: 6.3 的冒烟表列出五项冒烟步骤与对应观察指标。
- **rollout.rollback_trigger** [core, level 2] — 6.4 回滚触发条件是否是可观测数字？
  - evidence `6.4 回滚与熔断`: "- 真实下载失败率连续 10 分钟 > 2%。"
  - normalized: "- 真实下载失败率连续 10 分钟 > 2%。"
  - evidence `6.4 回滚与熔断`: "- 单次下载 OOM 或内存峰值超过 'max_bytes' 的 2 倍，出现 $\\ge 1$ 次。"
  - normalized: "- 单次下载 OOM 或内存峰值超过 'max_bytes' 的 2 倍,出现 $\\ge 1$ 次。"
  - rationale: 回滚触发条件均为可观测数字：失败率/时间窗、OOM 次数、内存倍数与安全用例失败次数。
- **rollout.rollback_steps** [core, level 2] — 6.4 回滚步骤是否可执行？
  - evidence `6.4 回滚与熔断`: "1. yank 当前版本；通知使用者固定到上一稳定版本。 2. 回退发布提交；重新打上一版本标签。 3. 恢复默认 'max_bytes' / 'total_timeout' / 重试策略；重跑 'tests/test_downloader.py' 与 'tests/test_pipeline.py'。 4. 用真实 'zip_url' 复跑，确认 'outcome=success' 且字节数与 ZIP 大小一致后解除熔断。"
  - normalized: "1. yank 当前版本;通知使用者固定到上一稳定版本。 2. 回退发布提交;重新打上一版本标签。 3. 恢复默认 'max_bytes' / 'total_timeout' / 重试策略;重跑 'tests/test_downloader.py' 与 'tests/test_pipeline.py'。 4. 用真实 'zip_url' 复跑,确认 'outcome=success' 且字节数与 ZIP 大小一致后解除熔断。"
  - rationale: 6.4 给出四步可执行回滚操作，包含发布回退、配置恢复与回归验证。

## 替代方案诚实 (alternatives)

- **alts.status_quo** [core, level 2] — 第 7 章是否有 Status Quo 及其成本/风险？
  - evidence `7. 替代方案与权衡`: "- **成本**：内存不可控；无法在分块间检查 deadline；重试、重定向、SSRF 与内容类型各自实现。"
  - normalized: "- **成本**:内存不可控;无法在分块间检查 deadline;重试、重定向、SSRF 与内容类型各自实现。"
  - evidence `7. 替代方案与权衡`: "- **风险**：大文件 / 错误页 OOM；慢速滴流拖死调用；签名 URL 进入日志；跨源重定向泄漏凭据。"
  - normalized: "- **风险**:大文件 / 错误页 OOM;慢速滴流拖死调用;签名 URL 进入日志;跨源重定向泄漏凭据。"
  - rationale: 7.1 完整描述 Status Quo 的思路、成本、风险与触发阈值。
- **alts.rejected** [core, level 2] — 第 7 章是否至少有一个被否决方案，且淘汰原因对应当前约束？
  - evidence `7. 替代方案与权衡`: "- **淘汰原因**：它不理解 SSRF、逐跳重定向、'max_bytes' 与内容类型白名单；这些安全约束仍要在外层重建，且无法保证“预检先于读取”。"
  - normalized: "- **淘汰原因**:它不理解 SSRF、逐跳重定向、'max_bytes' 与内容类型白名单;这些安全约束仍要在外层重建,且无法保证“预检先于读取”。"
  - rationale: 7.2/7.3 分别否决 urllib3.Retry 与 httpx，淘汰原因对应 SSRF、预检顺序、Session 测试缝等当前约束。
- **alts.matrix** [core, level 2] — 第 7 章是否有与约束对应的权衡矩阵？
  - evidence `7. 替代方案与权衡`: "\| 维度 \| Status Quo \| 'urllib3.Retry' \| 'httpx' \| 选定方案 \| \| :--- \| :--- \| :--- \| :--- \| :--- \| \| 内存上限可控 \| 差 \| 中 \| 中 \| 强 \| \| SSRF / 重定向安全 \| 差 \| 弱 \| 中 \| 强 \|"
  - normalized: "\| 维度 \| Status Quo \| 'urllib3.Retry' \| 'httpx' \| 选定方案 \| \| :--- \| :--- \| :--- \| :--- \| :--- \| \| 内存上限可控 \| 差 \| 中 \| 中 \| 强 \| \| SSRF / 重定向安全 \| 差 \| 弱 \| 中 \| 强 \|"
  - rationale: 7.4 的矩阵按内存上限、SSRF/重定向、Session 一致性、重试、可观测性等约束维度比较四方案。
- **alts.consistency** [core, level 2] — 第 7 章结论是否与 Goals、架构选型一致？
  - evidence `7. 替代方案与权衡`: "结论：选定方案与 G1 ~ G6 一致；最关键的约束是“预检先于读取、逐跳复验、内存硬上限”，这三项决定了不能只依赖通用重试库。"
  - normalized: "结论:选定方案与 G1 ~ G6 一致;最关键的约束是“预检先于读取、逐跳复验、内存硬上限”,这三项决定了不能只依赖通用重试库。"
  - rationale: 结论显式对齐 G1~G6，并与第 3.4 节选型理由一致。

## 跨章自洽 (cross_consistency)

- **x.goals_trace** [core, level 2] — 后续章节是否逐条回应 Goals？
  - evidence `全文`: "\| 'ResultDownloader' \| 配置校验、'resolve' 编排、Session 生命周期、重试与总预算 \| 不解压、不校验哈希、不落盘 \|"
  - normalized: "\| 'ResultDownloader' \| 配置校验、'resolve' 编排、Session 生命周期、重试与总预算 \| 不解压、不校验哈希、不落盘 \|"
  - evidence `全文`: "\| 'Streaming Reader' \| 分块读取、'Content-Length' 预检、字节累加、完整性校验、响应关闭 \| 不写入磁盘、不缓存上一次结果 \|"
  - normalized: "\| 'Streaming Reader' \| 分块读取、'Content-Length' 预检、字节累加、完整性校验、响应关闭 \| 不写入磁盘、不缓存上一次结果 \|"
  - evidence `全文`: "\| 'Retry / Budget' \| 可重试判定、退避与抖动、'Retry-After'、单调时钟总预算 \| 不解释响应体、不改变安全判定 \|"
  - normalized: "\| 'Retry / Budget' \| 可重试判定、退避与抖动、'Retry-After'、单调时钟总预算 \| 不解释响应体、不改变安全判定 \|"
  - evidence `全文`: "\| 'URL Guard' \| URL 语法、IDNA 规范化、DNS 解析、IP 公网性、逐跳重定向与降级检查、URL 脱敏 \| 不发起 HTTP 请求、不读取响应体 \|"
  - normalized: "\| 'URL Guard' \| URL 语法、IDNA 规范化、DNS 解析、IP 公网性、逐跳重定向与降级检查、URL 脱敏 \| 不发起 HTTP 请求、不读取响应体 \|"
  - evidence `全文`: "\| 'Telemetry' \| 日志 / 指标出口、'outcome' 枚举、'correlation_id'、回调异常隔离 \| 不影响主流程 \|"
  - normalized: "\| 'Telemetry' \| 日志 / 指标出口、'outcome' 枚举、'correlation_id'、回调异常隔离 \| 不影响主流程 \|"
  - evidence `全文`: "\| 'sleep' / 'monotonic' / 'wall_clock' / 'random_fn' / 'dns_resolver' \| 系统实现 \| 'Callable' \| 否 \| 可注入假时钟 / 随机源 / DNS \|"
  - normalized: "\| 'sleep' / 'monotonic' / 'wall_clock' / 'random_fn' / 'dns_resolver' \| 系统实现 \| 'Callable' \| 否 \| 可注入假时钟 / 随机源 / DNS \|"
  - rationale: G1/G5 对应 ResultDownloader 与 Telemetry，G2 对应 Streaming Reader，G3 对应 Retry/Budget 与 4.6，G4 对应 URL Guard，G6 对应注入参数表。
- **x.nfr_arch** [core, level 2] — NFR 与架构、选型是否一致？
  - evidence `全文`: "\| 'Streaming Reader' \| 分块读取、'Content-Length' 预检、字节累加、完整性校验、响应关闭 \| 不写入磁盘、不缓存上一次结果 \|"
  - normalized: "\| 'Streaming Reader' \| 分块读取、'Content-Length' 预检、字节累加、完整性校验、响应关闭 \| 不写入磁盘、不缓存上一次结果 \|"
  - evidence `全文`: "- **响应体上限**：默认 50 MiB；读取块默认 64 KiB；超限立即终止且不返回部分数据。验收：AC-3.1 ~ AC-3.6。"
  - normalized: "- **响应体上限**:默认 50 MiB;读取块默认 64 KiB;超限立即终止且不返回部分数据。验收:AC-3.1 ~ AC-3.6。"
  - evidence `全文`: "- **TLS**：自建 Session 使用 'verify=True'；不暴露关闭校验的参数；'SSLError' 映射为安全错误。验收：AC-6.10。"
  - normalized: "- **TLS**:自建 Session 使用 'verify=True';不暴露关闭校验的参数;'SSLError' 映射为安全错误。验收:AC-6.10。"
  - rationale: 内存/超时 NFR 对应 Streaming Reader 与 Retry/Budget，TLS 与 SSRF 约束对应 URL Guard 和 Session 设计，未见矛盾。
- **x.rollback_release** [core, level 2] — 回滚与发布策略是否一致？
  - evidence `全文`: "1. **Phase 1（候选）**：发布 '0.1.0rcN'；在真实 'zip_url'、13 页样本与 111 个下载器测试上验证；观察 7 天。"
  - normalized: "1. **Phase 1(候选)**:发布 '0.1.0rcN';在真实 'zip_url'、13 页样本与 111 个下载器测试上验证;观察 7 天。"
  - evidence `全文`: "1. yank 当前版本；通知使用者固定到上一稳定版本。"
  - normalized: "1. yank 当前版本;通知使用者固定到上一稳定版本。"
  - rationale: 发布采用候选版→正式版，回滚对应 yank 当前版本、回退发布提交并固定上一稳定版，二者节奏一致。

## 证据卫生 (evidence_hygiene)

- **x.no_placeholders** [core, level 2] — 是否没有把 无 / ... / 待补充 / TBD 当作实质回答？
  - evidence `全文`: "\| 私网 / 回环 / 链路本地 \| '10/8'、'127/8'、'169.254/16'、'::1' 等 \| 'resolve' / 重定向 \| '_is_public_ip' 拒绝 \| 'ResultDownloadSecurityError' \|"
  - normalized: "\| 私网 / 回环 / 链路本地 \| '10/8'、'127/8'、'169.254/16'、'::1' 等 \| 'resolve' / 重定向 \| '_is_public_ip' 拒绝 \| 'ResultDownloadSecurityError' \|"
  - rationale: 全文未发现“...”/“待补充”/“TBD”占位；“无数据迁移”等表述带具体语义，表格中的“—”仅表示不抛异常。
- **x.no_code** [core, level 2] — 是否没有堆砌实现代码、测试日志或偶发报错？
  - evidence `全文`: "**控制流契约（不含实现代码）**"
  - normalized: "**控制流契约(不含实现代码)**"
  - rationale: 全文代码块仅为 mermaid 拓扑/时序图与数学公式，没有实现代码、测试日志或偶发报错堆砌。
- **x.numbers_sourced** [core, level 2] — 关键数字是否有出处，或标了 [estimated]？
  - evidence `全文`: "- **默认 50 MiB 与 300 s**：来自当前样本与部署假设，不是服务端承诺；调用方可通过参数覆盖。详细权衡见第 7 章。"
  - normalized: "- **默认 50 MiB 与 300 s**:来自当前样本与部署假设,不是服务端承诺;调用方可通过参数覆盖。详细权衡见第 7 章。"
  - evidence `全文`: "- **延迟基线**：[estimated] 单次 50 MiB 下载的 P95 尚未统计；当前以真实结果包（约 1 MiB）与单元测试作为功能基线，不把它当作 SLA。"
  - normalized: "- **延迟基线**:[estimated] 单次 50 MiB 下载的 P95 尚未统计;当前以真实结果包(约 1 MiB)与单元测试作为功能基线,不把它当作 SLA。"
  - rationale: 50 MiB/300 s 说明来自样本与部署假设，未实测的 P95 延迟标 [estimated] 并声明非 SLA。
- **x.no_fabricated_refs** [core, level 2] — 是否没有捏造 SPEC 引用、depends_on 目标或 M<N>？
  - evidence `全文`: "\| 关联资源 \| [全局架构](../../architecture/mineru-parser-architecture.md)、SPEC-001、SPEC-003、SPEC-004 \|"
  - normalized: "\| 关联资源 \| [全局架构](../../architecture/mineru-parser-architecture.md)、SPEC-001、SPEC-003、SPEC-004 \|"
  - evidence `全文`: "* **AC-9.6**: 指标标签不得包含原始 URL、query、fragment 或 'correlation_id'；只允许低基数标签（'outcome'、'status_class'、'error_type'）。'outcome' 必须取自 §5.3 的枚举，不得使用自由文本。"
  - normalized: "* **AC-9.6**: 指标标签不得包含原始 URL、query、fragment 或 'correlation_id';只允许低基数标签('outcome'、'status_class'、'error_type')。'outcome' 必须取自 §5.3 的枚举,不得使用自由文本。"
  - evidence `全文`: "* **AC-6.3**: IP 字面量必须直接校验；IPv6 的 IPv4-mapped 地址必须先归一化为 IPv4 再校验；带 zone ID（如 'fe80::1%en0'）的地址必须拒绝；IPv6 过渡机制（至少 '64:ff9b::/96' NAT64、'2002::/16' 6to4、'2001::/32' Teredo）必须按 AC-6.2 / AC-6.3 的公网 IP 规则拒绝或归一化后校验。"
  - normalized: "* **AC-6.3**: IP 字面量必须直接校验;IPv6 的 IPv4-mapped 地址必须先归一化为 IPv4 再校验;带 zone ID(如 'fe80::1%en0')的地址必须拒绝;IPv6 过渡机制(至少 '64:ff9b::/96' NAT64、'2002::/16' 6to4、'2001::/32' Teredo)必须按 AC-6.2 / AC-6.3 的公网 IP 规则拒绝或归一化后校验。"
  - evidence `全文`: "* **AC-3.7**: 在 'Content-Encoding: identity'（或缺失）下，设计目标是单次调用的峰值内存约为 $O(\\text{max\\_bytes} + \\text{chunk\\_size})$；实际峰值还会受读取层（'raw.read1' / 'iter_content'）解码缓冲、urllib3 返回块大小与 'BytesIO' 扩容策略影响，必须通过内存测试记录实测上界；非 identity 编码下解码块可能放大，见 §5.4 的残余风险说明。"
  - normalized: "* **AC-3.7**: 在 'Content-Encoding: identity'(或缺失)下,设计目标是单次调用的峰值内存约为 $O(\\text{max\\_bytes} + \\text{chunk\\_size})$;实际峰值还会受读取层('raw.read1' / 'iter_content')解码缓冲、urllib3 返回块大小与 'BytesIO' 扩容策略影响,必须通过内存测试记录实测上界;非 identity 编码下解码块可能放大,见 §5.4 的残余风险说明。"
  - evidence `全文`: "- **编码放大**：非 identity 编码下解码块可能放大；'max_bytes' 按解码后字节计数，调用方覆盖 'Accept-Encoding' 时自行承担放大风险。验收：AC-3.7。"
  - normalized: "- **编码放大**:非 identity 编码下解码块可能放大;'max_bytes' 按解码后字节计数,调用方覆盖 'Accept-Encoding' 时自行承担放大风险。验收:AC-3.7。"
  - evidence `全文`: "IDNA 规范化失败按 AC-6.1 处理为 'ResultDownloadSecurityError'。"
  - normalized: "IDNA 规范化失败按 AC-6.1 处理为 'ResultDownloadSecurityError'。"
  - rationale: depends_on 目标与关联的 SPEC-001/003/004 均存在；AC-2.6、AC-6.3、AC-9.1/9.2/9.6 与 AC-3.7 的交叉引用已改为存在的 AC、§5.3 或 §5.4，§5.4 含“编码放大”条目；AC-6.3 的 AC-6.2 / AC-6.3 引用虽略循环，但均指向本文件存在的条目，不构成捏造或失效引用。

## Audit failures

None.
