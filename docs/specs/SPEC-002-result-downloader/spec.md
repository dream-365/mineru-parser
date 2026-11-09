---
type: spec
status: In Review
owner: jackafx
depends_on:
  - docs/architecture/mineru-parser-architecture.md
updated_at: 2026-11-09
---

# 结果包下载器 安全流式下载与内存上限 技术方案

| 字段 | 内容 |
| --- | --- |
| 标题 | 结果包下载器 安全流式下载与内存上限 技术方案 |
| 主笔 | @jackafx |
| 评审人 | @jackafx（仓库维护者，兼下游依赖方负责人）；评审记录见 `changelog.md` |
| 创建日期 | 2026-10-21 |
| 目标版本 | 0.1.0 |
| 关联资源 | [全局架构](../../architecture/mineru-parser-architecture.md)、SPEC-001、SPEC-003、SPEC-004 |

## 1. 背景与上下文

### 1.1 系统现状

`mineru-parser` 的四阶段链路中，下载器是第三阶段：客户端交付 `zip_url` 后，下载器把结果包读入 `io.BytesIO`，再交给提取器解析。下载器的上游是任意绝对 HTTP(S) URL（首个消费者是 MinerU 返回的 `zip_url`），下游统一交付内存流；它不解压、不校验哈希、不落盘。

当前技术栈为 Python 3.12、`requests.Session`、`urllib3`、`idna`，同步阻塞、分块读取。组件已随 SPEC-004 私有化为 `mineru_parser._downloader`；外部用户通过 `parse()` 间接使用，行为契约仍由本文约束。

核心流程：

```mermaid
flowchart LR
    ZIPURL["zip_url"] --> DL["ResultDownloader.resolve(url)"]
    DL --> GUARD["URL 语法 / IDNA / DNS / IP 校验"]
    GUARD --> HTTP["GET（禁自动重定向）"]
    HTTP --> REDIRECT{"3xx？"}
    REDIRECT -->|"是"| GUARD
    REDIRECT -->|"否"| CT["Content-Type 白名单"]
    CT --> CL["Content-Length 预检"]
    CL --> STREAM["分块读取 / 累加 / 预算检查"]
    STREAM --> BUF["io.BytesIO（游标 0）"]
```

全局组件边界见 [全局架构](../../architecture/mineru-parser-architecture.md)；本文只描述下载器范围内的拓扑与契约。

### 1.2 核心技术痛点

下载看似只是 `requests.get(url).content`，但结果包 URL 可能来自外部用户或不可信网络，失败链如下：

1. **内存不可控**：`.content` 一次性读入完整响应；大文件、错误页或恶意 URL 可让进程 OOM。
2. **网络行为不一致**：连接 / 读取超时、5xx / 429 重试、`Retry-After`、重定向链、连接复用各自实现，故障难以定位。
3. **慢速滴流绕过总预算**：分块读取若只在 `iter_content` 的块边界检查 deadline，服务端可以用极慢的分块拖住整个调用。
4. **安全边界缺失**：内网地址、回环、云元数据端点、跨协议重定向、DNS Rebinding 都可能被利用；逐跳重定向复验与 IDNA 规范化缺一不可。
5. **错误不可分类**：配置、安全、超限、内容类型、HTTP、瞬态、超时混在一起，调用方无法决定重试、重新下载还是拒收。
6. **不可观测**：下载耗时、字节数、重试次数、最终状态没有统一出口，签名 URL 还可能被写进日志。

**证据（可核实事件）**：2026-10-21 的代码评审复现了四个具体问题——慢速滴流响应绕过总预算、body 阶段读取超时被误分类、超时异常链泄漏签名 URL、IPv6 过渡网段判断失效（见 `changelog.md`「代码评审修复（超时 / 异常链 / 校验边界）」，2026-10-21）。同日的架构评审又发现 SSRF 判据不足、DNS 重试时序矛盾、注入 Session 敏感头泄漏、IDNA 规范化缺失等问题。这些问题直接对应上面的失败链 2 ~ 5。

### 1.3 重构/设计动机

1. **下载器成为每条 `parse()` 调用的必经阶段**：SPEC-004 落地后，下载失败会直接表现为管道第 3 阶段失败；组件契约必须在 0.1.0 发布前固化。
2. **安全评审已给出必须闭环的问题清单**：SSRF、逐跳重定向、IDNA、敏感头移除与签名 URL 脱敏都不能留到后续版本。
3. **默认 50 MiB 假设需要被显式记录与校准**：该值来自当前样本与部署假设，尚无 P95/P99 统计；本期把它写成可覆盖的显式限额，而不是隐式常量。
4. **单次调用峰值内存与并发度的关系需要写清楚**：下载器只约束单次响应体，容器 OOM 风险由调用方的并发度决定；这一边界必须在上线前对齐。

### 1.4 非目标

- **解压 ZIP、校验压缩包内部结构、防御 ZIP 炸弹**：本次不做；由提取器承担，下载器只负责传输。
- **校验内容哈希 / 签名**：本次不做；调用方或提取器负责。
- **磁盘落盘、临时文件、流式落盘阈值切换**：本次不做；固定返回 `io.BytesIO`。
- **Range 请求、断点续传、分片下载**：本次不做。
- **缓存层与条件请求（`ETag` / `If-None-Match`）**：本次不做。
- **令牌桶 / 漏桶等主动限流**：本次不做；只通过重试与 `Retry-After` 响应服务端限流。
- **中间件 / 拦截器框架**：本次不做；调用方可注入 `requests.Session` 并使用其 hooks / adapters。
- **异步 / 并发下载、线程池调度、批量下载**：本次不做。
- **认证流程、Token 刷新、Cookie 管理**：本次不做；仅支持调用方通过 `headers` 传入。
- **浏览器行为模拟、反爬对抗、JavaScript 挑战**：本次不做。
- **基于魔数 / 内容嗅探的格式识别**：本次不做；仅支持可选 `Content-Type` 白名单。
- **代理配置**：本次不做；沿用 `requests` 环境变量或注入 Session。
- **DNS Pin 与 DNS Rebinding 的完全消除**：本次不做；残余风险见附录 A 的 Q-2。
- **多线程共享同一实例的线程安全承诺**：本次不做；并发场景每线程独立实例。

**不做的后果**：不落盘意味着大文件只能受 `max_bytes` 约束；不做哈希校验意味着内容完整性由下游负责；不消除 DNS Rebinding 意味着强安全场景需要额外网络隔离；不做主动限流意味着 429 由服务端与重试策略共同约束。以上代价已写入第 5 章与第 7 章。

## 2. 目标与非目标

### 2.1 目标

- **G1 - 统一入口与配置（架构级）**：`resolve(url) -> io.BytesIO` 是唯一入口；非法配置在构造期暴露。验收：AC-1.1 ~ AC-1.11 全部通过。
- **G2 - 流式读取与内存 / 总预算（性能级）**：默认 `max_bytes` 50 MiB、`chunk_size` 64 KiB、`total_timeout` 300 s；分块读取，超限不返回部分数据。验收：AC-2.1 ~ AC-2.8、AC-3.1 ~ AC-3.10、AC-5.1 ~ AC-5.7。
- **G3 - 重试、退避与错误分类（可靠性级）**：可重试状态码固定为 `{408, 429, 500, 502, 503, 504}`；默认最多 3 次尝试；`Retry-After` 优先且截断。验收：AC-4.1 ~ AC-4.12。
- **G4 - SSRF / 重定向 / 内容类型安全（安全级）**：仅 HTTP(S)、拒绝 userinfo、DNS 解析后逐 IP 校验公网性、逐跳复验重定向、默认拒绝 HTTPS 降级、默认最多 5 次重定向。验收：AC-6.1 ~ AC-6.13、AC-7.1 ~ AC-7.7。
- **G5 - 生命周期与可观测性（运维级）**：自建 Session 关闭、注入 Session 不接管；每次调用在 `finally` 中恰好上报一次指标；URL 脱敏。验收：AC-8.1 ~ AC-8.10、AC-9.1 ~ AC-9.6。
- **G6 - 可注入依赖与无网络测试（工程效率级）**：Session、DNS Resolver、时钟、随机源、指标钩子均可注入；`tests/test_downloader.py` 的 111 个测试函数无需网络。验收：AC-1.8、AC-8.5 + 测试文件。

### 2.2 非目标

- **NG1 - 解压与 ZIP 结构校验**：由提取器承担（本次不做）。
- **NG2 - 内容哈希 / 签名校验**：由调用方或提取器承担（本次不做）。
- **NG3 - 磁盘落盘与临时文件**：固定返回内存流（本次不做）。
- **NG4 - Range / 断点续传 / 分片下载**：当前结果包体积有限（本次不做）。
- **NG5 - 缓存与条件请求**：重新下载的成本可接受（本次不做）。
- **NG6 - 主动限流**：只响应服务端限流（本次不做）。
- **NG7 - 异步 / 并发 / 批量下载**：由调用方用线程或进程承接（本次不做）。
- **NG8 - 认证与 Cookie 管理**：通过 `headers` 或注入 Session 处理（本次不做）。
- **NG9 - 代理配置**：沿用 `requests` 环境变量（本次不做）。
- **NG10 - DNS Rebinding 完全消除**：记录为残余风险（本次不做）。
- **NG11 - 线程安全承诺**：并发场景每线程独立实例（本次不做）。
- **NG12 - 自动在 `MinerUApiClient.wait()` 内下载**：由管道编排（Deferred to Phase 2）。

## 3. 架构设计与核心方案

### 3.1 总体架构

全局结构见 [全局架构](../../architecture/mineru-parser-architecture.md)（Approved）。下载器位于管道第 3 阶段，上游是客户端交付的 `zip_url`，下游是提取器的内存 ZIP 流。

本次变更范围内的拓扑：

```mermaid
flowchart LR
    PIPE["pipeline.parse"] --> DL["ResultDownloader"]
    DL --> GUARD["URL Guard<br/>语法 / IDNA / DNS / IP"]
    GUARD --> RETRY["Retry / Budget"]
    RETRY --> HTTP["requests.Session<br/>GET, allow_redirects=False"]
    HTTP --> GUARD
    HTTP --> BODY["Streaming Reader<br/>分块 / 限额 / 完整性"]
    BODY --> TEL["Telemetry"]
    BODY --> OUT["io.BytesIO"]

    style DL fill:#e3f2fd,stroke:#1565c0,stroke-width:1px
    style GUARD fill:#fff3e0,stroke:#e65100,stroke-width:1px
    style BODY fill:#e8f5e9,stroke:#2e7d32,stroke-width:1px
```

**新增 / 改造 / 保持不变**：

- 新增：`MinerUParserError` 根异常在下载器侧的继承关系与断言。
- 改造：实现伪码收敛为契约条款；明确慢速滴流、逐跳复验与总预算的判定顺序。
- 不变：`resolve` 签名、默认限额、可重试状态码集合、异常体系、Session 所有权与遥测口径。

### 3.2 核心模块职责

| 模块 | 职责 | 明确不做 |
| :--- | :--- | :--- |
| `ResultDownloader` | 配置校验、`resolve` 编排、Session 生命周期、重试与总预算 | 不解压、不校验哈希、不落盘 |
| `URL Guard` | URL 语法、IDNA 规范化、DNS 解析、IP 公网性、逐跳重定向与降级检查、URL 脱敏 | 不发起 HTTP 请求、不读取响应体 |
| `Retry / Budget` | 可重试判定、退避与抖动、`Retry-After`、单调时钟总预算 | 不解释响应体、不改变安全判定 |
| `Streaming Reader` | 分块读取、`Content-Length` 预检、字节累加、完整性校验、响应关闭 | 不写入磁盘、不缓存上一次结果 |
| `Telemetry` | 日志 / 指标出口、`outcome` 枚举、`correlation_id`、回调异常隔离 | 不影响主流程 |

### 3.3 核心数据流转

1. `resolve(url)` 先做一次 URL 语法与配置校验；非法时抛 `ResultDownloadConfigurationError`，不发起网络。
2. 每次尝试开始前检查总预算；随后执行 IDNA 规范化、DNS 解析与逐 IP 公网性检查。
3. 以 `stream=True`、`allow_redirects=False` 发出 GET；每一跳重定向都重新执行目标校验。
4. 最终 2xx 响应先做 `Content-Type` 白名单检查，再做可用的 `Content-Length` 预检。
5. 以分块方式读取响应体，按解码后字节累加；每次写入后检查 deadline 与 `max_bytes`。
6. 完整读取并关闭响应后返回 `io.BytesIO`（游标 0）；任何失败都不返回部分数据。
7. 可重试失败按 `Retry-After` / 指数退避等待后从原始 URL 重新开始；重试耗尽抛瞬态或超时异常。
8. 每次调用在 `finally` 中恰好上报一次指标，URL 只以脱敏形式进入日志。

### 3.4 关键选型与约束

- **流式分块而非 `.content`**：把内存上限变成硬约束，并允许在每个分块后检查 deadline。详细对比见第 7 章。
- **`requests` 而非 `httpx` / `urllib3` 裸用**：与客户端保持一致、复用 Session 注入与连接池；`urllib3.Retry` 不理解安全与任务语义。
- **DNS 预校验 + 逐跳复验**：不假设服务端返回的 URL 可信；每一跳都重新做 scheme / host / IP / 降级检查。
- **默认 50 MiB 与 300 s**：来自当前样本与部署假设，不是服务端承诺；调用方可通过参数覆盖。详细权衡见第 7 章。

## 4. 详细设计

### 4.1 设计范围与术语

- **最终响应**：重定向链结束后的 2xx 响应。
- **可用 `Content-Length`**：不存在 `Transfer-Encoding`、`Content-Encoding` 缺失或为 `identity`、值为单个合法非负整数。
- **可重试失败**：连接错误、连接 / 读取超时、分块编码 / 解码错误、响应体不完整、集合内的 HTTP 状态。
- **总预算**：覆盖整个 `resolve()` 调用的单调时钟预算，包含重试、重定向与退避等待。

### 4.2 威胁模型与信任边界

| 维度 | 内容 |
| :--- | :--- |
| **调用方** | 受信任的库使用者；其配置（`allowed_hosts`、`headers`、Session）由部署方负责。 |
| **URL 来源** | 可能由外部用户提供，也可能是 MinerU 返回的 `zip_url`；两者都按不可信输入处理。 |
| **受保护资产** | 内网 / 回环 / 链路本地 / 多播 / 云元数据端点、调用方凭据、进程内存、签名 URL。 |
| **攻击者能力** | 控制 URL、DNS 记录、重定向链、响应头与响应体；可尝试 DNS Rebinding、IDNA 混淆、超大 / 压缩响应、慢速滴流。 |
| **主要控制** | 仅 HTTP(S)、拒绝 userinfo、IDNA 规范化、`allowed_hosts`、DNS 结果公网性校验、逐跳重定向复验、HTTPS 降级拒绝、敏感头移除、`max_bytes`、`total_timeout`、TLS 校验。 |
| **残余风险** | DNS Rebinding、代理改变出口、注入 Session 的 TLS / Cookie 行为、path 中的令牌。 |

### 4.3 数据模型与契约

**构造参数**

| 参数 | 默认值 | 类型 | 必填 | 校验 / 语义 |
| :--- | :--- | :--- | :---: | :--- |
| `max_bytes` | `52428800`（50 MiB） | `int` | 否 | 正整数（拒绝 `bool`）；单次响应体硬上限 |
| `chunk_size` | `65536`（64 KiB） | `int` | 否 | 正整数；实际块大小 $\min(\text{chunk\_size}, \text{max\_bytes})$ |
| `request_timeout` | `(5.0, 30.0)` | `float \| tuple` | 否 | 正有限数或 `(connect, read)` 正有限数二元组 |
| `total_timeout` | `300.0` | `float \| None` | 否 | 正有限数或 `None`；覆盖整个调用 |
| `retry_policy` | 默认策略 | `DownloadRetryPolicy \| None` | 否 | 必须是 `DownloadRetryPolicy` 实例 |
| `allowed_content_types` | `None` | `Collection[str] \| None` | 否 | `None` 禁用；否则规范化为小写 `type/subtype` 或 `type/*` |
| `allowed_hosts` | `None` | `Collection[str] \| None` | 否 | `None` 禁用；否则为精确主机名 / IP 字面量集合 |
| `allow_private_hosts` | `False` | `bool` | 否 | 为 `True` 时跳过所有非公网 IP 检查；高风险，仅建议测试使用 |
| `allow_https_downgrade` | `False` | `bool` | 否 | 是否允许 `https` → `http` 重定向 |
| `max_redirects` | `5` | `int` | 否 | 整数 $\ge 0$ |
| `headers` | `None` | `Mapping[str, str] \| None` | 否 | 构造时复制；保留头禁止 |
| `session` | `None` → 自建 | `requests.Session \| None` | 否 | 注入时下载器不接管生命周期 |
| `sleep` / `monotonic` / `wall_clock` / `random_fn` / `dns_resolver` | 系统实现 | `Callable` | 否 | 可注入假时钟 / 随机源 / DNS |
| `on_metric` / `correlation_id` | `None` | `MetricHook` / `str` | 否 | 指标回调与日志关联 ID |

**`DownloadRetryPolicy`**

| 参数 | 默认值 | 约束 | 语义 |
| :--- | :---: | :--- | :--- |
| `max_attempts` | `3` | 整数 $\ge 1$ | 总尝试次数，包含首次请求 |
| `initial_interval` | `0.5` | $> 0$ | 首次重试基准间隔 $I_0$ |
| `backoff` | `2.0` | $\ge 1.0$ | 指数增长因子 $b$ |
| `max_interval` | `8.0` | $\ge$ `initial_interval` | 间隔上限 $I_{\max}$ |
| `jitter` | `0.2` | $[0,1)$ | 抖动比例 $j$ |
| `max_retry_after` | `60.0` | $\ge 0$ | `Retry-After` 截断上限 |

**结果与请求头契约**

- `resolve` 成功返回 `io.BytesIO`；内容完整、游标为 0；每次调用返回新的独立缓冲区。
- 默认请求头：`User-Agent: mineru-parser/<version>`、`Accept: */*`、`Accept-Encoding: identity`；`Authorization` 不默认设置。
- `headers` 与默认头按大小写不敏感方式合并；保留头（`Host`、`Content-Length`、`Transfer-Encoding`、`Connection`、`Range`）不得覆盖。

### 4.4 接口与协议

**公共 API（内部组件，行为契约仍成立）**

| 成员 | 签名 / 取值 | 语义 |
| :--- | :--- | :--- |
| `resolve` | `resolve(url: str) -> io.BytesIO` | 同步阻塞；成功返回游标 0 的新缓冲区；失败不返回部分数据 |
| `close` | `close() -> None` | 只关闭自建 Session；可重复调用 |
| `__enter__` / `__exit__` | — | 退出时等价于 `close()` |
| `max_bytes` | 只读 `int` | 单次响应体上限 |
| `retry_policy` | 只读 `DownloadRetryPolicy` | 不可变重试策略 |

**交付契约**

1. **完整性**：只有完整读取并关闭响应后才返回；任何失败都不会返回部分缓冲区。
2. **独立性**：每次调用返回新的 `BytesIO`；游标位于 0；下载器返回后不持有引用。
3. **所有权**：调用方拥有返回的 `BytesIO`，可自行 `close()`。
4. **顺序复用**：实例可顺序复用；不承诺线程安全。
5. **超时语义**：`total_timeout` 是端到端预算，不是单次 socket 超时。
6. **安全语义**：URL、DNS 结果、重定向目标均按不可信输入处理。
7. **脱敏语义**：公共异常消息、`last_error` 与日志不得包含 query / fragment / 原始 `requests` 异常字符串。

### 4.5 核心流程与时序

```mermaid
sequenceDiagram
    autonumber
    participant P as pipeline.parse
    participant D as ResultDownloader
    participant G as URL Guard
    participant S as requests.Session
    participant R as Remote

    P->>D: resolve(url)
    D->>G: validate_url_syntax(url)
    loop 每次尝试（最多 max_attempts）
        D->>D: 检查总预算
        D->>G: 规范化 host + DNS + IP 公网性
        D->>S: GET（stream=True, allow_redirects=False）
        S->>R: 请求
        R-->>S: 3xx / 2xx / 错误
        alt 3xx
            D->>G: 逐跳复验 Location
        else 2xx
            D->>D: Content-Type 白名单
            D->>D: Content-Length 预检
            D->>S: 分块读取（每块检查 deadline / max_bytes）
            D->>S: 关闭响应
            D-->>P: io.BytesIO
        end
    end
```

**控制流契约（不含实现代码）**

1. **语法校验只做一次**：scheme、host、userinfo、端口、控制字符、保留 host 字符；失败立即抛配置错误。
2. **每次尝试独立校验目标**：IDNA 规范化、DNS 解析、逐 IP 公网性检查；DNS 瞬态失败进入重试。
3. **重定向逐跳复验**：仅跟随 301/302/303/307/308；最多 `max_redirects` 次；每一跳重新执行 scheme / host / IP / 降级检查；跨源重定向移除下载器传入的敏感头。
4. **响应预检顺序**：`Content-Type` 白名单 → 可用 `Content-Length` > `max_bytes` → 流式读取。`Content-Type` 失败优先于大小失败。
5. **流式读取**：按解码后字节累加；每块非空才写入；累计超过 `max_bytes` 立即关闭并抛超限；`Content-Length` 可用时，EOF 实际字节少于声明值按“响应体不完整”重试。
6. **预算检查点**：每次尝试前、每次写入分块后、每次 sleep 前；若等待时间 $\ge$ 剩余预算，立即抛超时，不做无意义 sleep。
7. **重试**：可重试状态码固定集合；第 $n$ 次失败后的延迟为 $\min(I_0 b^{n-1}, I_{\max}) \cdot ((1-j)+jU)$；`Retry-After` 优先且不叠加抖动；重试从原始 URL 重新开始。
8. **关闭**：每个响应在离开当前请求作用域前关闭；重定向响应不读取响应体。

### 4.6 异常处理与错误码

| 触发条件 | 异常类型 | 是否重试 |
| :--- | :--- | :---: |
| 构造参数非法 | `ResultDownloadConfigurationError` | 否 |
| 初始 URL 非法（scheme / host / userinfo / port / 控制字符） | `ResultDownloadConfigurationError` | 否 |
| `allowed_hosts` 不匹配 | `ResultDownloadSecurityError` | 否 |
| host IDNA 规范化失败，或校验 host 与实际连接 host 不一致 | `ResultDownloadSecurityError` | 否 |
| 解析到非公网 IP（私网 / 回环 / 链路本地 / 多播 / 保留 / site-local / NAT64 / 6to4 / Teredo）、IPv4-mapped 私网或 zone ID | `ResultDownloadSecurityError` | 否 |
| DNS 解析失败（`gaierror` / `OSError`）或解析器返回空序列（**包括初始 URL 的首次解析**） | 瞬态；耗尽后 `ResultDownloadTransientError` | 是 |
| DNS 解析器返回非法结果 | `ResultDownloadSecurityError` | 否 |
| 注入 Session 携带敏感全局头 / `session.auth` 非空 | `ResultDownloadConfigurationError` | 否 |
| TLS 证书 / 握手校验失败（`SSLError`） | `ResultDownloadSecurityError` | 否 |
| `requests.InvalidURL` / `MissingSchema` / `InvalidSchema` / `InvalidHeader` | `ResultDownloadConfigurationError` | 否 |
| `requests.TooManyRedirects`（不应出现，重定向由下载器手动处理） | `ResultDownloadSecurityError` | 否 |
| 重定向越界、目标非 HTTP(S)、HTTPS 降级 | `ResultDownloadSecurityError` | 否 |
| 缺少 `Location` | `ResultDownloadHTTPError` | 否 |
| HTTP 408 / 429 / 500 / 502 / 503 / 504 | 瞬态；耗尽后 `ResultDownloadTransientError` | 是 |
| 未列入可重试集合的其他 4xx / 5xx、未被跟随的 3xx、1xx | `ResultDownloadHTTPError` | 否 |
| `206 Partial Content` | `ResultDownloadHTTPError` | 否 |
| 连接错误 / 读取超时 / 分块编码错误 / 解码错误 | 瞬态；耗尽后 `ResultDownloadTransientError` 或 `ResultDownloadTimeoutError` | 是 |
| 响应体不完整（`_IncompleteBody`） | 瞬态；耗尽后 `ResultDownloadTransientError` | 是 |
| 未归类的 `requests.RequestException` | 瞬态；耗尽后 `ResultDownloadTransientError` | 是 |
| 未知非 `RequestException` 异常 | 原样抛出；遥测 `outcome=unexpected` | 否 |
| 响应体超过 `max_bytes` | `ResultDownloadTooLargeError` | 否 |
| `Content-Type` 白名单不匹配 / 缺失 | `ResultDownloadContentTypeError` | 否 |
| `total_timeout` 耗尽 | `ResultDownloadTimeoutError` | 否 |

> **最后一次失败优先**：若重试耗尽时最后一次失败为超时，使用 `ResultDownloadTimeoutError`；否则使用 `ResultDownloadTransientError`。
>
> **匹配顺序**：必须先匹配 `SSLError`，再匹配一般 `ConnectionError` 与 `RequestException`，避免 TLS 失败被误判为瞬态。
>
> **脱敏**：所有公共异常消息与 `last_error` 必须使用 `redact_url` 或 `<invalid-url>`；不得拼接 `str(requests_exception)`，也不得保留包含原始签名 URL 的异常链（AC-4.12、AC-9.4）。

### 4.7 验收标准

#### US-1: 构造与配置

**As a** 服务集成方  
**I want to** 用一组显式参数构造 `ResultDownloader`，让非法配置在发起网络请求前暴露  
**So that** 我可以在启动阶段发现配置错误，而不是在业务流量中


* **AC-1.1**: `max_bytes` 必须为正整数（拒绝 `bool`），`chunk_size` 必须为正整数（拒绝 `bool`）；非法时必须在构造时抛出 `ResultDownloadConfigurationError`。实际读取块大小必须为 $\min(\text{chunk\_size}, \text{max\_bytes})$。
* **AC-1.2**: `request_timeout` 必须为正有限数，或 `(connect, read)` 的正有限数二元组；`total_timeout` 必须为正有限数或 `None`；必须显式拒绝 `bool`（`bool` 是 `int` 的子类）；非法时必须在构造时抛出 `ResultDownloadConfigurationError`。
* **AC-1.3**: `retry_policy` 必须是 `DownloadRetryPolicy` 实例；未传入时必须使用 `DEFAULT_DOWNLOAD_RETRY_POLICY`；必须暴露只读属性 `retry_policy`。
* **AC-1.4**: `allowed_content_types` 为 `None` 时禁用白名单；非 `None` 时每个条目必须规范化为小写 `type/subtype` 或 `type/*`（允许 `*/*`，禁止 `*/subtype`），空集合或非法条目必须在构造时抛出 `ResultDownloadConfigurationError`。
* **AC-1.5**: `allowed_hosts` 为 `None` 时禁用主机允许列表；非 `None` 时每个条目必须是非空主机名或 IP 字面量（大小写不敏感、忽略尾部 `.`、按 AC-6.1 规范化），不得包含 scheme、端口、路径或通配符；IPv6 字面量可用方括号或裸形式传入，必须规范化为压缩形式，其中的冒号不得误判为端口；空集合或非法条目必须在构造时抛出 `ResultDownloadConfigurationError`。
* **AC-1.6**: `max_redirects` 必须为整数 $\ge 0$（拒绝 `bool`）；`allow_private_hosts` 与 `allow_https_downgrade` 必须为 `bool`；`allow_private_hosts=True` 表示跳过**所有**非公网 IP 检查（不仅 RFC1918，还包括回环、链路本地、多播、保留、site-local 与 NAT64 等），属于高风险配置，必须在文档中显著警告；非法时必须在构造时抛出 `ResultDownloadConfigurationError`。
* **AC-1.7**: `headers` 的键与值必须为字符串，且不得包含 CR / LF；键必须是合法的 HTTP token（不得含空白、冒号、控制字符），大小写不敏感重复键必须在构造时拒绝；`Host`、`Content-Length`、`Transfer-Encoding`、`Connection`、`Range` 为保留头（大小写不敏感），传入时必须在构造时抛出 `ResultDownloadConfigurationError`；构造时必须复制该映射，后续外部修改不得影响实例。
* **AC-1.8**: `session`、`sleep`、`monotonic`、`wall_clock`、`random_fn`、`dns_resolver`、`on_metric` 必须可注入；注入后必须直接使用这些对象，不得回退到系统默认实现。
* **AC-1.9**: 必须暴露只读属性 `max_bytes` 与 `retry_policy`；属性返回的对象不得允许外部修改内部状态。
* **AC-1.10**: 所有注入 callable（`sleep`、`monotonic`、`wall_clock`、`random_fn`、`dns_resolver`、`on_metric`）必须在构造时通过 `callable(...)` 校验，否则抛出 `ResultDownloadConfigurationError`；`random_fn()` 的返回值必须夹取到 $[0,1]$，非有限值（`NaN` / `±inf`）必须按 0 处理，不得把非有限延迟传给 `sleep`。
* **AC-1.11**: `correlation_id` 必须为字符串或 `None`；非字符串必须在构造时抛出 `ResultDownloadConfigurationError`。

---

#### US-2: 基本下载与内存流交付

**As a** 业务调用方  
**I want to** 调用 `resolve(url)` 直接拿到可读取的内存流  
**So that** 我可以把结果交给 `zipfile`、Pandas 等库，而不关心 HTTP 细节


* **AC-2.1**: `resolve(url)` 必须使用 `GET`，携带 `stream=True`、`allow_redirects=False`、配置的 `request_timeout` 与请求头；成功时必须返回 `io.BytesIO`。
* **AC-2.2**: 返回的 `BytesIO` 必须包含最终响应体的完整字节，且游标必须位于 0；调用方可直接 `read()` / `seek()`。
* **AC-2.3**: 响应体必须流式分块读取：优先使用 `response.raw.read1(chunk_size, decode_content=True)`，使每个网络分块后都能检查 deadline；仅当响应对象没有可用的 `raw.read1` 时回退到 `iter_content(chunk_size=...)`。每块必须非空才写入；实现不得访问 `response.content`、`response.text` 或 `response.json`。
* **AC-2.4**: 无论成功、重试还是失败，响应对象必须在离开当前请求作用域前关闭；成功返回前必须已完成读取与关闭。
* **AC-2.5**: 最终响应为 `204 No Content` / `205 Reset Content`，或可用的 `Content-Length` 为 0 时，必须视为空响应、不读取响应体，并返回空 `BytesIO`（游标位于 0）。
* **AC-2.6**: 当 `url` 不是字符串、空白、非绝对 HTTP(S) URL、缺少 host、包含 userinfo、端口非法、包含控制字符或明显非法 host 字符（空白、反斜杠、`%`）时，必须在发出任何网络请求前抛出 `ResultDownloadConfigurationError`。控制字符（`\x00`–`\x1f`、`\x7f`）必须直接在**原始字符串**上检查，不能依赖 `urlsplit`（后者会静默移除 `\n`、`\r`、`\t`）。IDNA 规范化失败按 AC-6.1 处理为 `ResultDownloadSecurityError`。
* **AC-2.7**: 同一实例必须支持顺序重复调用；每次调用必须返回新的独立 `BytesIO`，不得复用或缓存上一次的缓冲区。
* **AC-2.8**: 返回后 `BytesIO` 的所有权归调用方；下载器不得在返回后关闭、读取或持有该对象。

---

#### US-3: 流式读取与内存上限

**As a** 服务集成方  
**I want to** 在读取过程中强制限制响应体大小  
**So that** 错误 URL 或超大文件不会导致进程 OOM，也不会返回部分数据


* **AC-3.1**: 默认 `max_bytes` 必须为 $50 \times 1024 \times 1024$ 字节（50 MiB）。
* **AC-3.2**: 当最终响应存在“可用”的 `Content-Length` 且其值大于 `max_bytes` 时，必须在读取响应体前抛出 `ResultDownloadTooLargeError`。可用条件：不存在 `Transfer-Encoding`、`Content-Encoding` 缺失或为 `identity`、`Content-Length` 为单个合法非负整数。
* **AC-3.3**: 读取过程中必须按解码后的字节累加；一旦累计字节数超过 `max_bytes`，必须立即关闭响应与临时缓冲区，并抛出 `ResultDownloadTooLargeError`，不得返回部分数据。
* **AC-3.4**: `Content-Length` 缺失、非法、为负、存在 `Transfer-Encoding` 或存在非 `identity` 的 `Content-Encoding` 时，流式累加必须是唯一且最终的大小判据。
* **AC-3.5**: 当 `Content-Length` 可用、值大于 0，且响应体在 EOF 时的实际字节数小于声明值时，必须按“响应体不完整”处理为可重试错误；重试耗尽后抛出 `ResultDownloadTransientError`。
* **AC-3.6**: 大小超限属于终态错误，不得重试。
* **AC-3.7**: 在 `Content-Encoding: identity`（或缺失）下，设计目标是单次调用的峰值内存约为 $O(\text{max\_bytes} + \text{chunk\_size})$；实际峰值还会受读取层（`raw.read1` / `iter_content`）解码缓冲、urllib3 返回块大小与 `BytesIO` 扩容策略影响，必须通过内存测试记录实测上界；非 identity 编码下解码块可能放大，见 §5.4 的残余风险说明。
* **AC-3.8**: 默认必须发送 `Accept-Encoding: identity`，且该 per-request 头必须覆盖注入 Session 的同名全局头；若服务端仍返回压缩内容，大小限制必须按读取层交付的解码后字节计数。调用方通过 `headers` 覆盖 `Accept-Encoding` 时，自行承担解码放大风险。
* **AC-3.9**: 未发起 Range 请求却收到 `206 Partial Content` 时，必须视为协议异常并抛出 `ResultDownloadHTTPError`，不得把部分内容当作完整结果返回。
* **AC-3.10**: 空响应体（`204` / `205`，或可用 `Content-Length` 为 0）必须返回空 `BytesIO` 并以 `bytes=0` 上报遥测；下载器不得把空流视为错误，但文档必须提示调用方：对结果包下载而言，空流通常意味着服务端异常或错误页，调用方应自行判定。

---

#### US-4: 重试、退避与状态码

**As a** 服务集成方  
**I want to** 让下载器自动处理瞬时故障与限流  
**So that** 偶发 5xx、429 或网络抖动不会直接中断业务


* **AC-4.1**: 可重试 HTTP 状态码必须精确为 $\{408, 429, 500, 502, 503, 504\}$；其他状态码不得重试。
* **AC-4.2**: 除 408 / 429 外的 4xx 必须立即抛出 `ResultDownloadHTTPError`，不得重试。
* **AC-4.3**: 未被跟随的 3xx、1xx，以及未列入 AC-4.1 可重试集合的 4xx / 5xx，必须抛出 `ResultDownloadHTTPError`。
* **AC-4.4**: 除 `206` 外的 2xx 必须视为成功；其中 `204` / `205` 返回空流。
* **AC-4.5**: 连接错误、连接/读取超时、分块编码错误、解码错误与响应体不完整必须按可重试处理；TLS 证书校验失败（`SSLError`）必须立即抛出 `ResultDownloadSecurityError`，不得重试。
* **AC-4.6**: 第 $n$ 次尝试失败后（$n$ 从 1 开始），下一次重试延迟必须为
  $$d_n = \min(I_0 \cdot b^{n-1}, I_{\max}) \cdot \big((1-j) + j \cdot U\big)$$
  其中 $I_0$ 为 `initial_interval`，$b$ 为 `backoff`，$I_{\max}$ 为 `max_interval`，$j$ 为 `jitter`，$U$ 为 `random_fn()` 夹取到 $[0,1]$ 后的值。
* **AC-4.7**: 当可重试响应携带合法 `Retry-After` 时，必须优先使用 $d_n = \min(\text{Retry-After}, \text{max\_retry\_after})$，且不叠加抖动；`Retry-After` 必须同时支持秒数与 HTTP-date；非法值必须忽略；负值按 0 处理；超过上限必须截断。
* **AC-4.8**: 每次重试必须从原始 URL 重新开始，丢弃上一次的部分字节；重定向预算按单次尝试独立计算。
* **AC-4.9**: 重试次数耗尽后，必须抛出 `ResultDownloadTransientError`；若最后一次失败为超时，则必须抛出其子类 `ResultDownloadTimeoutError`。异常必须携带 `attempts`、`last_error`（已脱敏的错误摘要，不是原始异常对象）、`last_status_code` 与 `retry_after`；字段缺失时使用 `None`。
* **AC-4.10**: 注入的 `Session` 若自身配置了重试，调用方必须自行将其重试次数设为 0；下载器的 `DownloadRetryPolicy` 是唯一权威重试层。该约束必须在文档中说明。
* **AC-4.11**: 未归类的 `requests.RequestException`，以及 `raw.read1` 直接抛出的 urllib3 传输异常，必须按瞬态错误处理并重试；未知的其他异常必须原样抛出，不得吞掉或伪装成 `ResultDownloadError`，但遥测仍必须在 `finally` 中以 `outcome=unexpected` 记录。
* **AC-4.12**: 任何公共异常消息都不得包含原始 URL、query、fragment 或 `str(requests_exception)`；异常链（`__cause__`）也不得泄漏签名 URL，必要时使用 `from None` 或构造脱敏后的 cause。详见 AC-9.4。

---

#### US-5: 超时与总预算

**As a** 服务集成方  
**I want to** 同时控制单次连接/读取超时与整个下载调用的总耗时  
**So that** 慢服务器或慢速滴流不会让线程无限期挂起


* **AC-5.1**: `request_timeout` 必须传递给每一次 HTTP 请求；默认值为 `(5.0, 30.0)`，即连接超时 5 秒、读取超时 30 秒。
* **AC-5.2**: `total_timeout` 必须是覆盖整个 `resolve()` 调用的单调时钟预算，包含所有重试、重定向与退避等待；默认值为 `300.0` 秒；传入 `None` 时禁用总预算。
* **AC-5.3**: 必须在每次尝试前、每次写入分块后、每次 sleep 前检查 deadline。若计算出的等待时间 $\ge$ 剩余预算，必须立即抛出 `ResultDownloadTimeoutError`，不得进行无意义 sleep；该异常必须携带 `last_status_code` 与 `retry_after`（若可得），以便区分“服务端要求等待超过预算”和“实际已耗时超限”。由于此规则已保证等待时间小于剩余预算，下载器不再执行“截断 sleep”。
* **AC-5.4**: 总预算耗尽时，必须关闭当前响应与临时缓冲区，并抛出 `ResultDownloadTimeoutError`，携带 `attempts`、`last_error`、`last_status_code` 与 `retry_after`（若可得）；不得返回部分数据。
* **AC-5.5**: 单次阻塞的 DNS 解析或 socket 读取可能越过 `total_timeout`，超出量分别受系统解析器行为与 `request_timeout` 的 read 分量约束；该限制必须在文档中说明。
* **AC-5.6**: 若未设置 `total_timeout` 且所有尝试均以超时结束，必须抛出 `ResultDownloadTimeoutError`；若最后一次失败不是超时，必须抛出 `ResultDownloadTransientError`。
* **AC-5.7**: `total_timeout` 的非法值必须在构造时拒绝；`total_timeout=None` 必须合法且明确表示不设总预算。

---

#### US-6: SSRF、重定向与传输安全

**As a** 服务集成方  
**I want to** 阻止下载器访问内网、非 HTTP(S) 目标与恶意重定向  
**So that** 即使 URL 来自外部输入，也不会被用作 SSRF 跳板


* **AC-6.1**: 原始 URL 与每个重定向目标必须使用 `http` 或 `https`；必须拒绝任何 userinfo（包括空用户名，如 `http://@host/`）、非法端口（不在 $[1, 65535]$）、控制字符，以及 host 中的空白、反斜杠与百分号（`%`）。控制字符必须在原始字符串上检查；host 必须通过 `idna` 包按 `host.lower(), strict=True, std3_rules=True` 规范化（与 urllib3 2.x 的 `_idna_encode` 一致），规范化失败必须拒绝。`allowed_hosts` 匹配、DNS 解析和最终传给 `requests` 的 URL 必须使用同一个规范化后的 ASCII host；禁止用非规范化 host 做校验却用另一形式发起连接。
* **AC-6.2**: 必须通过 `dns_resolver(host, port)` 解析主机；对返回的每一个 IP 都必须执行 AC-6.3 定义的公网 IP 检查，而不是仅检查 `ipaddress.ip_address(...).is_global`；只要存在任一非公网地址，必须抛出 `ResultDownloadSecurityError`。`allow_private_hosts=True` 仅跳过该 IP 检查，不免除 scheme、userinfo、`allowed_hosts`、IDNA、重定向与降级检查。
* **AC-6.3**: IP 字面量必须直接校验；IPv6 的 IPv4-mapped 地址必须先归一化为 IPv4 再校验；带 zone ID（如 `fe80::1%en0`）的地址必须拒绝；IPv6 过渡机制（至少 `64:ff9b::/96` NAT64、`2002::/16` 6to4、`2001::/32` Teredo）必须按 AC-6.2 / AC-6.3 的公网 IP 规则拒绝或归一化后校验。
* **AC-6.4**: DNS 解析失败（`socket.gaierror` / `OSError`）或 `dns_resolver` 返回空序列，必须按瞬态错误重试，**包括初始 URL 的首次解析**；`dns_resolver` 返回无效 IP 或非 IP 字符串时，必须失败关闭并抛出 `ResultDownloadSecurityError`。实现必须把“URL 语法校验”与“目标解析校验”分离：前者只执行一次并抛 `ResultDownloadConfigurationError`，后者在每次尝试、每一跳重定向中执行，并由重试循环把 DNS 瞬态异常转换为重试。
* **AC-6.5**: 当 `allowed_hosts` 非 `None` 时，每个请求目标的主机名必须与列表中的条目精确匹配（大小写不敏感、忽略尾部 `.`；Unicode 主机按 AC-6.1 规范化；IP 字面量使用压缩形式）；不匹配必须抛出 `ResultDownloadSecurityError`。该检查不得绕过 AC-6.2 的 IP 检查。本期不支持通配符；若实际 CDN 使用动态子域，调用方应枚举主机或依赖 IP 检查，见 Q-11。
* **AC-6.6**: 仅 `301`、`302`、`303`、`307`、`308` 必须被跟随；最多跟随 `max_redirects` 次（默认 5），即最多发出 `max_redirects + 1` 次请求。相对 `Location` 必须通过 `urljoin` 解析；每一跳都必须重新执行 AC-6.1 ~ AC-6.5 的校验。
* **AC-6.7**: 缺少或为空的 `Location` 必须抛出 `ResultDownloadHTTPError`（携带 3xx 状态码）；超过重定向上限、目标协议非 HTTP(S)、目标端口非法或目标 host 非法，必须抛出 `ResultDownloadSecurityError`。
* **AC-6.8**: 默认必须拒绝从 `https` 重定向到 `http`；仅当 `allow_https_downgrade=True` 时允许。`http` → `https` 不受限制。
* **AC-6.9**: 首次跨源重定向后，后续所有请求必须移除**下载器通过 `headers` 传入的** `Authorization`、`Proxy-Authorization`、`Cookie`、`Cookie2` 请求头，且不得在后续跳中重新加入；同源重定向可保留。自定义敏感头不在自动识别范围内，调用方应配合 `allowed_hosts` 使用。注入 Session 的全局敏感头与认证状态由 AC-8.8 约束；下载器不得声称能在不修改 Session 的前提下移除它们。
* **AC-6.10**: 自建 Session 必须使用 `requests` 默认的 TLS 校验（`verify=True`）；下载器不得暴露 `verify=False`。注入 Session 的 TLS 策略由调用方负责；`SSLError` 必须映射为 `ResultDownloadSecurityError`。
* **AC-6.11**: 每个重定向响应必须在发起下一跳前关闭，不得读取其响应体；重试必须从原始 URL 重新开始。
* **AC-6.12**: 必须明确记录 DNS Rebinding 的残余风险：预校验与 `requests` 的实际连接可能发生二次解析；IDNA 规范化已把“校验 host 与连接 host 不一致”从确定性风险降为残余风险；详见附录 A 的 Q-2。
* **AC-6.13**: 自建 Session 必须明确 `trust_env` 策略；本期沿用 `requests` 默认（`trust_env=True`），但文档必须声明：代理会重新解析目标，AC-6.1 ~ AC-6.5 的 SSRF 保证仅对直连语义成立；需要强保证的部署必须显式注入 `trust_env=False` 的 Session 或在代理层限制出站。

---

#### US-7: Content-Type 白名单

**As a** 业务调用方  
**I want to** 只接受预期类型的内容  
**So that** 错误页面、HTML 或意外二进制内容不会进入后续解析流程


* **AC-7.1**: `allowed_content_types=None` 时不得进行任何内容类型过滤。
* **AC-7.2**: 白名单非 `None` 时，必须取最终响应 `Content-Type` 的分号前部分，去除空白并转小写；必须支持精确匹配、`type/*` 通配与 `*/*`；不匹配时必须抛出 `ResultDownloadContentTypeError`。
* **AC-7.3**: 白名单非 `None` 且最终响应缺少 `Content-Type` 或值为空时，必须抛出 `ResultDownloadContentTypeError`（`content_type=None`）。
* **AC-7.4**: `204` / `205` 或可用 `Content-Length` 为 0 的响应不适用内容类型白名单，不读取响应体，直接返回空流；该行为必须与 AC-3.10 一致，并在遥测中记录 `bytes=0`。
* **AC-7.5**: 内容类型检查只针对最终 2xx 响应，必须在读取响应体前完成；失败属于终态错误，不得重试。内容类型检查先于 `Content-Length` 预检；两者同时失败时以 `ResultDownloadContentTypeError` 为准。
* **AC-7.6**: 异常必须携带 `content_type` 与规范化后的 `allowed`，不得携带响应体内容。
* **AC-7.7**: 文档必须说明 `Content-Type` 不是安全边界，服务端可以伪造；它只用于路由与快速失败。

---

#### US-8: 会话生命周期与可测试性

**As a** 服务集成方  
**I want to** 复用连接池，并在测试中完全替换网络、DNS 与时钟  
**So that** 生产环境高效、测试环境无网络且行为可断言


* **AC-8.1**: 未注入 `session` 时必须自建 `requests.Session`；`close()` 或退出上下文时必须关闭自建 Session。注入 `session` 时不得关闭它。
* **AC-8.2**: 同一实例的所有请求——包括重试与每一跳重定向——必须复用同一个 Session。
* **AC-8.3**: `close()` 必须可重复调用且不抛异常；`__enter__` 必须返回实例，`__exit__` 必须等价于 `close()`。
* **AC-8.4**: 不得通过 `session.headers.update(...)` 修改注入 Session 的全局请求头；默认头与自定义头必须按请求传入。
* **AC-8.5**: 注入的 `session`、`dns_resolver`、`sleep`、`monotonic`、`wall_clock`、`random_fn` 必须足以在无网络环境下覆盖成功、重试、重定向、超时与安全拒绝路径。
* **AC-8.6**: 实例必须支持顺序复用，但不得声明线程安全；同一实例的并发 `resolve()` 不受支持。并发场景必须每线程使用独立实例或线程局部 Session。
* **AC-8.7**: `close()` 后继续调用 `resolve()` 的行为未定义；调用方必须在关闭后停止使用实例。该约束必须在文档中说明。
* **AC-8.8**: 注入 Session 不得携带 `Authorization`、`Proxy-Authorization`、`Cookie`、`Cookie2` 全局头，且 `session.auth` 必须为 `None`；构造时发现任一条件不满足，必须抛出 `ResultDownloadConfigurationError`。需要认证时应通过构造参数 `headers` 传入，以便 AC-6.9 的跨源移除策略生效。Session 的 Cookie jar 由调用方负责，下载器不保证跨源 Cookie 隔离；需要强隔离时应注入干净的专用 Session。
* **AC-8.9**: 自建 Session 的 `trust_env` 行为必须按 AC-6.13 文档化；注入 Session 的 `trust_env` 由调用方负责；下载器不得在不说明的情况下改变 `requests` 的代理语义。
* **AC-8.10**: `ResultDownloadError` 必须继承库级根异常 `MinerUParserError`（定义于 `mineru_parser/errors.py`，由 `mineru_parser` 顶层导出）；`MinerUError` 同样继承该根，但两者**互不继承**——捕获其一不得捕获另一方的任何子类。该继承关系必须由 `issubclass` 断言覆盖。

---

#### US-9: 可观测性

**As a** 运维 / 服务集成方  
**I want to** 通过日志与指标观察下载耗时、字节数、重试与失败原因  
**So that** 我能定位慢请求、限流与安全拒绝，同时不泄漏签名 URL


* **AC-9.1**: 每次 `resolve()` 调用必须在 `finally` 中恰好上报一次 `mineru.download.total`、`mineru.download.duration_ms`、`mineru.download.bytes` 与 `mineru.download.attempts`，**包括 URL 校验失败、安全拒绝与未分类异常**；`outcome` 标签必须取自 §5.3 定义的枚举。每次重试必须额外上报 `mineru.download.retry.total`。
* **AC-9.2**: 必须记录 `mineru.download`（成功）、`mineru.download.retry`（每次重试）与 `mineru.download.error`（终态失败，包含配置 / 安全 / 内容类型等校验失败）日志，字段符合 §5.3 定义。
* **AC-9.3**: `on_metric` 抛出的任何异常必须被吞掉并记录 `mineru.metric.failed` 警告日志，不得影响下载主流程。
* **AC-9.4**: 所有日志与异常消息中的 URL 必须移除 query 与 fragment；不得记录请求头、响应头全集或响应体。非法 URL 无法脱敏时必须以 `"<invalid-url>"` 代替。公共异常消息不得拼接 `str(requests_exception)`；`last_error` 必须是脱敏摘要；异常链不得把原始签名 URL 暴露给调用方（见 AC-4.12）。
* **AC-9.5**: 当提供 `correlation_id` 时，下载器发出的所有日志必须携带该字段。
* **AC-9.6**: 指标标签不得包含原始 URL、query、fragment 或 `correlation_id`；只允许低基数标签（`outcome`、`status_class`、`error_type`）。`outcome` 必须取自 §5.3 的枚举，不得使用自由文本。

---

### 4.8 边界条件

| 场景描述 | 触发条件 | 涉及接口 | 预期处理逻辑 | 返回异常 |
| :--- | :--- | :--- | :--- | :--- |
| URL 为空 / 非字符串 | `url` 为空、空白或非 `str` | `resolve` | 发出请求前拒绝 | `ResultDownloadConfigurationError` |
| 非 HTTP(S) 协议 | `file://`、`ftp://`、`data:`、`javascript:` | `resolve` / 重定向 | 发出请求前拒绝 | `ResultDownloadConfigurationError`（初始）/ `ResultDownloadSecurityError`（重定向） |
| URL 含 userinfo | `http://user:pass@host/` 或 `http://@host/` | `resolve` / 重定向 | 拒绝，避免凭据泄漏与歧义 | `ResultDownloadConfigurationError`（初始）/ `ResultDownloadSecurityError`（重定向） |
| host 非法 | 含空白、反斜杠、`%`、控制字符 | `resolve` / 重定向 | 拒绝 | `ResultDownloadConfigurationError` / `ResultDownloadSecurityError` |
| 端口非法 | `0`、`> 65535`、非数字 | `resolve` / 重定向 | 拒绝 | `ResultDownloadConfigurationError` / `ResultDownloadSecurityError` |
| 私网 / 回环 / 链路本地 | `10/8`、`127/8`、`169.254/16`、`::1` 等 | `resolve` / 重定向 | `_is_public_ip` 拒绝 | `ResultDownloadSecurityError` |
| 多播 / site-local / NAT64 / 6to4 / Teredo | `224.0.0.1`、`ff02::1`、`fec0::1`、`64:ff9b::a00:1` 等 | `resolve` / 重定向 | 显式拒绝，不能仅依赖 `is_global` | `ResultDownloadSecurityError` |
| 云元数据端点 | `169.254.169.254`、`fd00:ec2::254` 等 | `resolve` / 重定向 | `_is_public_ip` 拒绝 | `ResultDownloadSecurityError` |
| DNS 混合结果 | 同一主机解析出公网 + 私网 IP | `resolve` / 重定向 | 任一非公网即拒绝 | `ResultDownloadSecurityError` |
| DNS 解析失败 | `gaierror` / 临时解析失败，包括初始 URL 首次解析 | `resolve` | 按瞬态重试；耗尽后失败 | `ResultDownloadTransientError` |
| IDNA 主机 | Unicode / punycode / 尾部点混用 | `resolve` / 重定向 | 统一 IDNA 规范化后再校验与连接 | `ResultDownloadSecurityError`（规范化失败） |
| 非法 IP 字面量 / 过渡地址 | 非规范 IPv4 写法、NAT64、zone ID | `resolve` / 重定向 | 解析或归一化后按 `_is_public_ip` 拒绝 | `ResultDownloadSecurityError` |
| DNS 解析器返回空结果 | 空序列 | `resolve` | 按 DNS 失败处理，重试；耗尽后失败 | `ResultDownloadTransientError` |
| DNS 解析器返回非法值 | 非 IP 字符串 | `resolve` | 失败关闭 | `ResultDownloadSecurityError` |
| `allowed_hosts` 不匹配 | 主机不在允许列表 | `resolve` / 重定向 | 拒绝 | `ResultDownloadSecurityError` |
| 重定向过多 | 超过 `max_redirects` | `resolve` | 拒绝 | `ResultDownloadSecurityError` |
| 重定向缺少 `Location` | 3xx 但无 `Location` | `resolve` | 视为协议异常 | `ResultDownloadHTTPError` |
| HTTPS 降级 | `https` → `http` 且未允许 | `resolve` | 拒绝 | `ResultDownloadSecurityError` |
| 跨源重定向 | 目标 origin 与当前不同 | `resolve` | 移除敏感头，继续 | — |
| 401 / 403 / 404 | 鉴权失败 / 资源不存在 | `resolve` | 不重试 | `ResultDownloadHTTPError` |
| 408 / 429 / 500 / 502 / 503 / 504 | 限流 / 瞬时故障 | `resolve` | 按策略重试；耗尽后失败 | `ResultDownloadTransientError` |
| `Retry-After` 非法 | 非数字且非 HTTP-date | `resolve` | 忽略，使用退避 | — |
| `Retry-After` 过大 | 超过 `max_retry_after` | `resolve` | 截断 | — |
| 连接超时 | 连接阶段超时 | `resolve` | 重试；耗尽后失败 | `ResultDownloadTimeoutError` |
| 读取超时 | 读取阶段超时 | `resolve` | 重试；耗尽后失败 | `ResultDownloadTimeoutError` |
| 总预算耗尽 | `total_timeout` 到期 | `resolve` | 立即中止，不返回部分数据 | `ResultDownloadTimeoutError` |
| TLS 校验失败 | 证书过期 / 主机名不匹配 | `resolve` | 不重试 | `ResultDownloadSecurityError` |
| 响应体不完整 | `Content-Length` 大于实际字节 | `resolve` | 重试；耗尽后失败 | `ResultDownloadTransientError` |
| 声明长度超限 | `Content-Length > max_bytes` | `resolve` | 读取前拒绝 | `ResultDownloadTooLargeError` |
| 流式累加超限 | 实际字节 > `max_bytes` | `resolve` | 中止并关闭缓冲区 | `ResultDownloadTooLargeError` |
| 206 Partial Content | 未请求 Range 却收到 206 | `resolve` | 视为协议异常 | `ResultDownloadHTTPError` |
| 204 / 205 | 无响应体 | `resolve` | 返回空 `BytesIO` | — |
| Content-Type 不匹配 | 白名单不含响应类型 | `resolve` | 读取前拒绝 | `ResultDownloadContentTypeError` |
| Content-Type 缺失 | 白名单启用但无该头 | `resolve` | 读取前拒绝 | `ResultDownloadContentTypeError` |
| 空响应体 + 白名单 | `Content-Length: 0` | `resolve` | 跳过类型检查，返回空流 | — |
| 指标回调异常 | `on_metric` 抛异常 | 所有路径 | 吞掉并记录 `mineru.metric.failed` | 不抛出 |
| 日志 URL 含 query | 签名 URL | 所有路径 | 日志 / 异常消息移除 query 与 fragment | — |
| 注入 Session | 调用方提供 Session | 构造 / `close` | 不关闭、不修改其全局请求头；不得携带敏感全局头或 `session.auth` | `ResultDownloadConfigurationError` |
| 注入 Session 全局鉴权 | `Authorization` / `Cookie` 全局头或 `session.auth` | 构造 | 拒绝，避免跨源重定向泄漏凭据 | `ResultDownloadConfigurationError` |
| 自建 Session | 未注入 Session | `close` / `with` | 由下载器关闭 | — |
| `close()` 重复调用 | 连续调用 `close()` | `close` | 幂等 | — |
| 并发 `resolve()` | 多线程共享实例 | `resolve` | 不支持；文档要求每线程独立实例 | — |
| 关闭后继续使用 | `close()` 后调用 `resolve()` | `resolve` | 未定义；文档禁止 | — |
| 压缩炸弹 | 服务端无视 identity 返回高压缩比内容 | `resolve` | 解码块可能放大；计数超限后中止 | `ResultDownloadTooLargeError`（最终） |
| 签名 URL 过期 | `zip_url` 有时效 / 一次性 | `resolve` | 重试可能失败；调用方需重新获取 URL | `ResultDownloadHTTPError` / `ResultDownloadTransientError` |
| 代理环境 | `HTTP_PROXY` / `HTTPS_PROXY` 生效 | `resolve` | 遵循 `requests` 行为；SSRF 校验基于本地解析，代理环境下的保证见 AC-6.13 | — |
| 异常链泄漏 | `str(requests_exception)` / `__cause__` 含签名 URL | 所有失败路径 | 公共消息与 `last_error` 脱敏；必要时 `from None` | — |
| 注入依赖不可调用 | `sleep` / `dns_resolver` 等非 callable | 构造 | 拒绝 | `ResultDownloadConfigurationError` |
| `random_fn` 返回非有限值 | `NaN` / `±inf` | 重试计算 | 按 0 处理，不传给 `sleep` | — |

---

## 5. 非功能性需求

### 5.1 性能与资源

- **响应体上限**：默认 50 MiB；读取块默认 64 KiB；超限立即终止且不返回部分数据。验收：AC-3.1 ~ AC-3.6。
- **单次调用内存**：在 `Content-Encoding: identity` 下，峰值约为 $O(\text{max\_bytes} + \text{chunk\_size})$；非 identity 编码可能放大。验收：`test_memory_bound_with_tracemalloc`。
- **超时**：连接 5 s、读取 30 s；总预算默认 300 s。验收：AC-5.1 ~ AC-5.7。
- **延迟基线**：[estimated] 单次 50 MiB 下载的 P95 尚未统计；当前以真实结果包（约 1 MiB）与单元测试作为功能基线，不把它当作 SLA。

### 5.2 可靠性与容灾

- **可重试集合**：`{408, 429, 500, 502, 503, 504}`；其他 4xx / 5xx 不重试。验收：AC-4.1 ~ AC-4.4。
- **重试边界**：默认最多 3 次尝试；重试耗尽抛瞬态或超时异常，携带 `attempts` / `last_error` / `last_status_code` / `retry_after`。验收：AC-4.9。
- **不完整响应**：声明长度大于实际 EOF 时按可重试处理；耗尽后抛瞬态错误。验收：AC-3.5。
- **TLS 失败**：`SSLError` 映射为安全错误，不重试。验收：AC-4.5、AC-6.10。
- **总预算**：包含重试、重定向与退避；预算耗尽关闭响应与临时缓冲区。验收：AC-5.2 ~ AC-5.4。

### 5.3 可观测性

- **日志**：`mineru.download`、`mineru.download.retry`、`mineru.download.error`、`mineru.metric.failed`；`correlation_id` 附加到所有日志。验收：AC-9.2、AC-9.5。
- **指标**：`mineru.download.total`、`mineru.download.duration_ms`、`mineru.download.bytes`、`mineru.download.attempts`、`mineru.download.retry.total`；每次调用在 `finally` 中恰好上报一次。验收：AC-9.1。
- **`outcome` 枚举**：`success` / `config_error` / `security_error` / `too_large` / `content_type_error` / `http_error` / `transient` / `timeout` / `unexpected`；禁止自由文本。验收：AC-9.6。
- **脱敏**：日志与异常消息移除 query / fragment；指标标签不含 URL 与 `correlation_id`。验收：AC-9.4、AC-9.6。
- **回调隔离**：`on_metric` 异常被吞掉并记录 `mineru.metric.failed`。验收：AC-9.3。

### 5.4 安全与合规

- **SSRF**：仅 HTTP(S)、拒绝 userinfo、拒绝控制字符与非法 host 字符、DNS 结果逐 IP 校验、IPv6 过渡地址处理。验收：AC-6.1 ~ AC-6.5。
- **重定向**：逐跳复验、最多 5 次、默认拒绝 HTTPS 降级、跨源移除敏感头。验收：AC-6.6 ~ AC-6.9。
- **TLS**：自建 Session 使用 `verify=True`；不暴露关闭校验的参数；`SSLError` 映射为安全错误。验收：AC-6.10。
- **敏感信息**：公共异常与日志不包含签名 URL；异常链不得泄漏原始 URL；指标标签低基数。验收：AC-4.12、AC-9.4、AC-9.6。
- **注入 Session**：拒绝携带全局敏感头或 `session.auth` 的 Session；`trust_env` 语义必须文档化。验收：AC-8.8、AC-8.9、AC-6.13。
- **编码放大**：非 identity 编码下解码块可能放大；`max_bytes` 按解码后字节计数，调用方覆盖 `Accept-Encoding` 时自行承担放大风险。验收：AC-3.7。

## 6. 上线与迁移计划

### 6.1 发布与灰度

下载器随 `mineru-parser` 包发布，采用“候选版 → 正式版”两阶段：

1. **Phase 1（候选）**：发布 `0.1.0rcN`；在真实 `zip_url`、13 页样本与 111 个下载器测试上验证；观察 7 天。
2. **Phase 2（正式）**：无 P0/P1 问题后发布 `0.1.0`。
3. **观察期**：发布后 14 天；安全类问题按 6.4 立即回滚。

库形态无法按流量比例灰度；以候选版与内部集成验证替代。[estimated] 观察窗口按当前维护者规模设定。

### 6.2 数据迁移与兼容性

- **无数据迁移**：下载器不落盘、不缓存；返回的 `BytesIO` 由调用方持有。
- **兼容性**：组件已私有化；外部用户通过 `parse()` 使用，无迁移动作。
- **内部迁移**：导入路径统一为 `mineru_parser._downloader`；行为契约不变。
- **限额校准**：50 MiB 是当前假设，需用真实样本统计 P95/P99 后回写；在此之前调用方可显式覆盖 `max_bytes`。

### 6.3 上线验证与冒烟

| 冒烟项 | 步骤 | 观察指标 |
| :--- | :--- | :--- |
| 单元回归 | `python -m pytest tests/test_downloader.py -q` | 111 个测试函数全通过 |
| 管道回归 | `python -m pytest tests/test_pipeline.py -q` | 66 个测试函数全通过 |
| 真实下载 | 用 MinerU 返回的 `zip_url` 调用 `resolve` | 返回缓冲区大小、游标 0、耗时、`attempts` |
| 安全路径 | 注入内网 URL / 跨协议重定向 / 超大 `Content-Length` | 分别抛安全 / HTTP / 超限错误，且不发起请求 |
| 可观测性 | 检查日志与指标 | `outcome`、`bytes`、`attempts`、`correlation_id` 齐全；URL 已脱敏 |

### 6.4 回滚与熔断

**触发条件（可观测数字）**：

- 下载器单测失败数 $\ge 1$。
- 真实下载失败率连续 10 分钟 > 2%。
- 单次下载 OOM 或内存峰值超过 `max_bytes` 的 2 倍，出现 $\ge 1$ 次。
- 安全路径回归：任意 SSRF / 降级 / 敏感头移除用例失败 $\ge 1$ 次。

**回滚步骤**：

1. yank 当前版本；通知使用者固定到上一稳定版本。
2. 回退发布提交；重新打上一版本标签。
3. 恢复默认 `max_bytes` / `total_timeout` / 重试策略；重跑 `tests/test_downloader.py` 与 `tests/test_pipeline.py`。
4. 用真实 `zip_url` 复跑，确认 `outcome=success` 且字节数与 ZIP 大小一致后解除熔断。

## 7. 替代方案与权衡

### 7.1 Status Quo：`requests.get(url).content`

- **思路**：调用方直接读取完整响应体。
- **成本**：内存不可控；无法在分块间检查 deadline；重试、重定向、SSRF 与内容类型各自实现。
- **风险**：大文件 / 错误页 OOM；慢速滴流拖死调用；签名 URL 进入日志；跨源重定向泄漏凭据。
- **触发阈值**：当第二个调用方开始复制同一段下载与重试代码时，Status Quo 的成本已超过收敛成本。

### 7.2 被否决方案：仅使用 `urllib3.Retry`

- **思路**：把重试、退避与 `Retry-After` 交给 `urllib3.Retry`。
- **优点**：成熟、少写代码。
- **淘汰原因**：它不理解 SSRF、逐跳重定向、`max_bytes` 与内容类型白名单；这些安全约束仍要在外层重建，且无法保证“预检先于读取”。

### 7.3 被否决方案：`httpx` 同步客户端

- **思路**：用 `httpx.Client` 替代 `requests`。
- **优点**：超时模型更清晰、HTTP/2 支持。
- **淘汰原因**：与客户端现有的 Session 注入、连接池与测试缝不一致；引入第二套 HTTP 栈会增加依赖与迁移成本，而当前瓶颈不在协议层。

### 7.4 最终选型与权衡矩阵

**选定方案**：`requests` + 流式 `raw.read1` + 预校验 URL Guard + 显式 `DownloadRetryPolicy` + 端到端总预算。

| 维度 | Status Quo | `urllib3.Retry` | `httpx` | 选定方案 |
| :--- | :--- | :--- | :--- | :--- |
| 内存上限可控 | 差 | 中 | 中 | 强 |
| SSRF / 重定向安全 | 差 | 弱 | 中 | 强 |
| 与现有 Session / 测试缝一致 | 强 | 中 | 弱 | 强 |
| 重试与 `Retry-After` | 差 | 强 | 强 | 强 |
| 可观测性与脱敏 | 差 | 弱 | 中 | 强 |
| 契合当前阶段 | 否 | 否 | 否 | **是** |

结论：选定方案与 G1 ~ G6 一致；最关键的约束是“预检先于读取、逐跳复验、内存硬上限”，这三项决定了不能只依赖通用重试库。

## 附录 A：未决问题

- **Q-1**：默认 50 MiB 是否足够覆盖真实结果包？需统计 manifest / 图片 / 总 ZIP 的 P50/P95/P99 后回写。
- **Q-2**：如何进一步降低 DNS Rebinding 残余风险？候选方向：连接前固定 IP、在代理层限制出站；当前不做 DNS Pin。
- **Q-11**：`allowed_hosts` 是否需要通配符？当前要求精确匹配；CDN 动态子域需枚举或依赖 IP 检查。
- **Q-12**：是否把 `max_bytes` 改为按调用覆盖？当前为构造期参数，调用方需为不同结果包创建独立实例。
