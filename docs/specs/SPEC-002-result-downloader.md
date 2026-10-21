# [SPEC-002] ResultDownloader

| 属性 | 内容 |
| :--- | :--- |
| **状态** | In Review |
| **负责人** | @jackafx |
| **创建时间** | 2026-10-21 |
| **更新时间** | 2026-10-21 |
| **关联 Issue/PR** | —（待关联） |

---

## 1. 背景与目标 (Context & Objectives)

### 1.1 背景 (Context)

`MinerUApiClient` 的职责边界止于交付结果包的 `zip_url`（见 `SPEC-001` 的 Non-Goals 与 Q-4）。下游业务拿到 URL 后，仍需要把结果包读入内存，交给 `zipfile`、Pandas、Pillow 等库继续处理。当前常见做法是直接 `requests.get(url).content`，或写一次性脚本下载到临时文件。

这种做法的痛点集中在四个方面：

1. **内存不可控**：`.content` 会把完整响应体一次性读入内存；如果 URL 指向大文件或被错误配置，进程可能直接 OOM。
2. **网络行为不一致**：连接/读取超时、5xx / 429 重试、`Retry-After`、重定向链、连接复用各自实现，故障难以定位。
3. **安全边界缺失**：如果 URL 来自外部用户，内网地址、`file://`、云元数据端点、跨协议重定向都可能被利用；如果 URL 来自服务端，重定向目标同样不可信。
4. **不可测试、不可观测**：下载逻辑与业务代码耦合，无法在无网络环境下测试；下载耗时、字节数、重试次数没有统一出口。

`ResultDownloader` 因此被设计为一个独立的、通用的同步组件：上游是任意绝对 HTTP(S) URL（首个消费者是 MinerU 返回的 `zip_url`），下游统一交付 `io.BytesIO`。它不改变 `MinerUApiClient` 的契约，也不承担解压、校验、入库等业务职责。

> **场景假设**：调用方本身受信任，但传入的 URL 可能由外部用户提供，因此下载器将 URL、DNS 结果、重定向目标与响应头一律视为不可信输入；单次结果包默认不超过 50 MiB（该假设需用真实样本校准，见 R-17），并发度中低。高并发爬虫、大文件落盘、跨请求缓存等场景见 1.4 与 6.2。

```mermaid
flowchart LR
    subgraph UPSTREAM["上游"]
        API["MinerU API"]
        CDN["结果 CDN / 对象存储"]
    end

    subgraph LIB["mineru-parser（本库）"]
        CLIENT["MinerUApiClient<br/>submit / resume / wait"]
        DL["ResultDownloader<br/>resolve(url) → io.BytesIO"]
    end

    subgraph DOWNSTREAM["下游"]
        BIZ["业务后端 / 批处理 / 离线管线"]
        UNZIP["zipfile / 解压 / 入库"]
    end

    API -- "结果包地址" --> CLIENT
    CLIENT -- "MinerUTaskResult.zip_url" --> DL
    DL -- "GET / 重定向 / 重试" --> CDN
    CDN -- "响应体分块" --> DL
    DL -- "内存流（游标归零）" --> BIZ
    BIZ --> UNZIP

    style UPSTREAM fill:#fce4ec,stroke:#ad1457,stroke-width:1px
    style LIB fill:#e3f2fd,stroke:#1565c0,stroke-width:1px
    style DOWNSTREAM fill:#e8f5e9,stroke:#2e7d32,stroke-width:1px
```

> **信任边界**：CDN 与重定向目标均视为不可信网络输入；下载器必须在发出请求前和每次重定向前校验目标。

### 1.2 现状与差距分析 (Gap Analysis)

| 能力维度 | 裸 `requests.get(...).content` | 一次性下载脚本 | `ResultDownloader` |
| :--- | :---: | :---: | :---: |
| 统一入口 `resolve(url)` | ❌ | ⚠️ 形态不一 | ✅ |
| 连接池复用 | ⚠️ 易遗漏 | ⚠️ 易遗漏 | ✅ 共享 / 可注入 Session |
| 连接 / 读取超时 | ⚠️ 手工设置 | ⚠️ 手工设置 | ✅ 显式区分 |
| 端到端总预算 | ❌ | ❌ | ✅ `total_timeout` |
| 流式读取 + 内存上限 | ❌ | ⚠️ 常写 `.content` | ✅ 分块 + `max_bytes` |
| 重试状态码分类 | ❌ | ⚠️ 各自实现 | ✅ 固定集合 |
| 指数退避 + 随机抖动 | ❌ | ❌ | ✅ `DownloadRetryPolicy` |
| 服务端 `Retry-After` | ❌ | ❌ | ✅ 优先且截断 |
| SSRF / 非公网 IP 防护 | ❌ | ❌ | ✅ IDNA + DNS + `_is_public_ip` |
| 重定向逐跳校验 | ❌ | ❌ | ✅ 上限 + 每跳复验 |
| HTTPS 降级防护 | ❌ | ❌ | ✅ 默认拒绝 |
| Content-Type 白名单 | ❌ | ❌ | ✅ 可选 |
| 会话生命周期 | ⚠️ 易泄漏 | ⚠️ 易泄漏 | ✅ 自建负责关闭 |
| 可观测性（日志 / 指标） | ❌ | ❌ | ✅ 统一出口 + URL 脱敏 |
| 依赖注入 / 无网络测试 | ❌ | ❌ | ✅ Session / Resolver / 时钟 |
| 线程安全声明 | ❌ | ❌ | ✅ 明确不承诺 |

> **为什么不直接组合现有库？** `urllib3.Retry` 能覆盖状态码重试、退避与 `Retry-After`，`httpx` 提供超时与连接池，但它们不提供逐跳 SSRF 复验、大小上限、统一的异常体系与遥测出口。本组件的价值在于把这些约束收敛到一个可注入、可无网络测试的边界；代价是需要自行维护约 600–900 行实现与对应测试。

### 1.3 目标 (Goals)

- [ ] **Goal 1**：提供统一入口 `resolve(url) -> io.BytesIO`，返回内容完整、游标位于 0 的独立内存流。
- [ ] **Goal 2**：流式分块读取；以 `max_bytes` 为硬上限，超限时不返回任何部分数据。
- [ ] **Goal 3**：区分连接超时与读取超时，并提供覆盖整个 `resolve()` 调用的总预算 `total_timeout`。
- [ ] **Goal 4**：对幂等 GET 提供可配置重试：指数退避、随机抖动、`Retry-After` 优先、最大尝试次数。
- [ ] **Goal 5**：建立稳定的错误分类：配置、安全、超限、内容类型、HTTP、瞬态、超时。
- [ ] **Goal 6**：SSRF 防护：仅 HTTP(S)、拒绝 userinfo、解析并校验所有 DNS 结果的公网性（含多播 / site-local / NAT64 / 6to4 / Teredo 等过渡地址）、逐跳校验重定向、限制重定向次数、默认拒绝 HTTPS 降级。
- [ ] **Goal 7**：可选的 `Content-Type` 白名单，用于拒绝意外的二进制 / HTML 响应。
- [ ] **Goal 8**：复用 Session；自建 Session 由组件关闭，注入 Session 绝不接管；提供上下文管理器。
- [ ] **Goal 9**：日志 / 指标统一出口，URL 查询串与片段必须脱敏；支持 `correlation_id`。
- [ ] **Goal 10**：Session、DNS Resolver、时钟、随机源、指标钩子均可注入，测试无需访问网络。

### 1.4 非目标 (Non-Goals / Out of Scope)

> 明确本次迭代**不包含**的内容，防止需求范围膨胀（Scope Creep）。

- [ ] 解压 ZIP、校验压缩包内部结构、防御 ZIP 炸弹；下载器只负责传输。
- [ ] 校验内容哈希 / 签名（如 SHA-256、`Content-MD5`）。
- [ ] 磁盘落盘、临时文件、流式落盘阈值切换；本期固定返回 `io.BytesIO`。
- [ ] Range 请求、断点续传、分片下载。
- [ ] 缓存层（内存 LRU、Redis、本地磁盘）与条件请求（`ETag` / `If-None-Match`）。
- [ ] 令牌桶 / 漏桶等主动限流；仅通过重试与 `Retry-After` 响应服务端限流。
- [ ] 中间件 / 拦截器框架；调用方可注入 `requests.Session` 并使用其 hooks / adapters。
- [ ] 异步 / 并发下载、线程池调度、批量下载。
- [ ] 认证流程、Token 刷新、Cookie 管理；仅支持调用方通过 `headers` 传入。`requests.Session` 自带的 Cookie jar 行为由调用方 / Session 决定，下载器不做额外管理。
- [ ] 浏览器行为模拟、反爬对抗、JavaScript 挑战。
- [ ] 基于魔数 / 内容嗅探的格式识别；仅支持可选的 `Content-Type` 白名单。
- [ ] 代理配置；沿用 `requests` 的环境变量或注入 Session 的配置。
- [ ] 在代理或注入 Session 改变实际连接目标时仍保证 SSRF 防护；见 R-7、R-9、R-15。
- [ ] 自动清理注入 Session 的 Cookie jar / 全局认证状态；调用方必须满足 AC-8.8。
- [ ] DNS Pin（连接已校验 IP）与 DNS Rebinding 的完全消除；见 R-1 与 Q-2。
- [ ] 自动在 `MinerUApiClient.wait()` 内下载；由调用方组合 `resolve(result.zip_url)`。
- [ ] 多线程共享同一实例的线程安全承诺；见 3.3 与 R-6。

### 1.5 威胁模型 (Threat Model)

| 维度 | 内容 |
| :--- | :--- |
| **调用方** | 受信任的库使用者；其配置（`allowed_hosts`、`headers`、`Session`）由部署方负责。 |
| **URL 来源** | 可能由外部用户提供，也可能是 MinerU 返回的 `zip_url`；两者都按不可信输入处理。 |
| **受保护资产** | 内网 / 回环 / 链路本地 / 多播 / 云元数据端点、调用方凭据（`Authorization`、Cookie）、进程内存、签名 URL。 |
| **攻击者能力** | 控制 URL、DNS 记录、重定向链、响应头与响应体；可尝试 DNS Rebinding、IDNA 混淆、超大 / 压缩响应、慢速滴流。 |
| **主要控制** | 仅 HTTP(S)、拒绝 userinfo、IDNA 规范化、`allowed_hosts`、DNS 结果公网性校验、逐跳重定向复验、HTTPS 降级拒绝、敏感头移除、`max_bytes`、`total_timeout`、TLS 校验。 |
| **残余风险** | DNS Rebinding（R-1）、代理改变出口（R-7）、注入 Session 的 TLS / Cookie 行为（R-9、R-15）、path 中的令牌（R-11）。 |

> 本 Spec 的安全承诺以“直连、自建 Session、IDNA 规范化后的主机”为前提；代理或注入 Session 会改变该前提，必须按 R-7 / R-9 / R-15 的说明使用。

---

## 2. 用户故事与验收标准 (User Stories & Acceptance Criteria)

### US-1: 构造与配置

**As a** 服务集成方  
**I want to** 用一组显式参数构造 `ResultDownloader`，让非法配置在发起网络请求前暴露  
**So that** 我可以在启动阶段发现配置错误，而不是在业务流量中

#### 验收标准 (Acceptance Criteria)

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

### US-2: 基本下载与内存流交付

**As a** 业务调用方  
**I want to** 调用 `resolve(url)` 直接拿到可读取的内存流  
**So that** 我可以把结果交给 `zipfile`、Pandas 等库，而不关心 HTTP 细节

#### 验收标准 (Acceptance Criteria)

* **AC-2.1**: `resolve(url)` 必须使用 `GET`，携带 `stream=True`、`allow_redirects=False`、配置的 `request_timeout` 与请求头；成功时必须返回 `io.BytesIO`。
* **AC-2.2**: 返回的 `BytesIO` 必须包含最终响应体的完整字节，且游标必须位于 0；调用方可直接 `read()` / `seek()`。
* **AC-2.3**: 响应体必须流式分块读取：优先使用 `response.raw.read1(chunk_size, decode_content=True)`，使每个网络分块后都能检查 deadline；仅当响应对象没有可用的 `raw.read1` 时回退到 `iter_content(chunk_size=...)`。每块必须非空才写入；实现不得访问 `response.content`、`response.text` 或 `response.json`。
* **AC-2.4**: 无论成功、重试还是失败，响应对象必须在离开当前请求作用域前关闭；成功返回前必须已完成读取与关闭。
* **AC-2.5**: 最终响应为 `204 No Content` / `205 Reset Content`，或可用的 `Content-Length` 为 0 时，必须视为空响应、不读取响应体，并返回空 `BytesIO`（游标位于 0）。
* **AC-2.6**: 当 `url` 不是字符串、空白、非绝对 HTTP(S) URL、缺少 host、包含 userinfo、端口非法、包含控制字符或明显非法 host 字符（空白、反斜杠、`%`）时，必须在发出任何网络请求前抛出 `ResultDownloadConfigurationError`。控制字符（`\x00`–`\x1f`、`\x7f`）必须直接在**原始字符串**上检查，不能依赖 `urlsplit`（后者会静默移除 `\n`、`\r`、`\t`）。IDNA 规范化失败按 AC-6.1 / 3.7 处理为 `ResultDownloadSecurityError`。
* **AC-2.7**: 同一实例必须支持顺序重复调用；每次调用必须返回新的独立 `BytesIO`，不得复用或缓存上一次的缓冲区。
* **AC-2.8**: 返回后 `BytesIO` 的所有权归调用方；下载器不得在返回后关闭、读取或持有该对象。

---

### US-3: 流式读取与内存上限

**As a** 服务集成方  
**I want to** 在读取过程中强制限制响应体大小  
**So that** 错误 URL 或超大文件不会导致进程 OOM，也不会返回部分数据

#### 验收标准 (Acceptance Criteria)

* **AC-3.1**: 默认 `max_bytes` 必须为 $50 \times 1024 \times 1024$ 字节（50 MiB）。
* **AC-3.2**: 当最终响应存在“可用”的 `Content-Length` 且其值大于 `max_bytes` 时，必须在读取响应体前抛出 `ResultDownloadTooLargeError`。可用条件：不存在 `Transfer-Encoding`、`Content-Encoding` 缺失或为 `identity`、`Content-Length` 为单个合法非负整数。
* **AC-3.3**: 读取过程中必须按解码后的字节累加；一旦累计字节数超过 `max_bytes`，必须立即关闭响应与临时缓冲区，并抛出 `ResultDownloadTooLargeError`，不得返回部分数据。
* **AC-3.4**: `Content-Length` 缺失、非法、为负、存在 `Transfer-Encoding` 或存在非 `identity` 的 `Content-Encoding` 时，流式累加必须是唯一且最终的大小判据。
* **AC-3.5**: 当 `Content-Length` 可用、值大于 0，且响应体在 EOF 时的实际字节数小于声明值时，必须按“响应体不完整”处理为可重试错误；重试耗尽后抛出 `ResultDownloadTransientError`。
* **AC-3.6**: 大小超限属于终态错误，不得重试。
* **AC-3.7**: 在 `Content-Encoding: identity`（或缺失）下，设计目标是单次调用的峰值内存约为 $O(\text{max\_bytes} + \text{chunk\_size})$；实际峰值还会受读取层（`raw.read1` / `iter_content`）解码缓冲、urllib3 返回块大小与 `BytesIO` 扩容策略影响，必须通过内存测试记录实测上界；非 identity 编码下解码块可能放大，见 R-10。
* **AC-3.8**: 默认必须发送 `Accept-Encoding: identity`，且该 per-request 头必须覆盖注入 Session 的同名全局头；若服务端仍返回压缩内容，大小限制必须按读取层交付的解码后字节计数。调用方通过 `headers` 覆盖 `Accept-Encoding` 时，自行承担解码放大风险。
* **AC-3.9**: 未发起 Range 请求却收到 `206 Partial Content` 时，必须视为协议异常并抛出 `ResultDownloadHTTPError`，不得把部分内容当作完整结果返回。
* **AC-3.10**: 空响应体（`204` / `205`，或可用 `Content-Length` 为 0）必须返回空 `BytesIO` 并以 `bytes=0` 上报遥测；下载器不得把空流视为错误，但文档必须提示调用方：对结果包下载而言，空流通常意味着服务端异常或错误页，调用方应自行判定。

---

### US-4: 重试、退避与状态码

**As a** 服务集成方  
**I want to** 让下载器自动处理瞬时故障与限流  
**So that** 偶发 5xx、429 或网络抖动不会直接中断业务

#### 验收标准 (Acceptance Criteria)

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

### US-5: 超时与总预算

**As a** 服务集成方  
**I want to** 同时控制单次连接/读取超时与整个下载调用的总耗时  
**So that** 慢服务器或慢速滴流不会让线程无限期挂起

#### 验收标准 (Acceptance Criteria)

* **AC-5.1**: `request_timeout` 必须传递给每一次 HTTP 请求；默认值为 `(5.0, 30.0)`，即连接超时 5 秒、读取超时 30 秒。
* **AC-5.2**: `total_timeout` 必须是覆盖整个 `resolve()` 调用的单调时钟预算，包含所有重试、重定向与退避等待；默认值为 `300.0` 秒；传入 `None` 时禁用总预算。
* **AC-5.3**: 必须在每次尝试前、每次写入分块后、每次 sleep 前检查 deadline。若计算出的等待时间 $\ge$ 剩余预算，必须立即抛出 `ResultDownloadTimeoutError`，不得进行无意义 sleep；该异常必须携带 `last_status_code` 与 `retry_after`（若可得），以便区分“服务端要求等待超过预算”和“实际已耗时超限”。由于此规则已保证等待时间小于剩余预算，下载器不再执行“截断 sleep”。
* **AC-5.4**: 总预算耗尽时，必须关闭当前响应与临时缓冲区，并抛出 `ResultDownloadTimeoutError`，携带 `attempts`、`last_error`、`last_status_code` 与 `retry_after`（若可得）；不得返回部分数据。
* **AC-5.5**: 单次阻塞的 DNS 解析或 socket 读取可能越过 `total_timeout`，超出量分别受系统解析器行为与 `request_timeout` 的 read 分量约束；该限制必须在文档中说明。
* **AC-5.6**: 若未设置 `total_timeout` 且所有尝试均以超时结束，必须抛出 `ResultDownloadTimeoutError`；若最后一次失败不是超时，必须抛出 `ResultDownloadTransientError`。
* **AC-5.7**: `total_timeout` 的非法值必须在构造时拒绝；`total_timeout=None` 必须合法且明确表示不设总预算。

---

### US-6: SSRF、重定向与传输安全

**As a** 服务集成方  
**I want to** 阻止下载器访问内网、非 HTTP(S) 目标与恶意重定向  
**So that** 即使 URL 来自外部输入，也不会被用作 SSRF 跳板

#### 验收标准 (Acceptance Criteria)

* **AC-6.1**: 原始 URL 与每个重定向目标必须使用 `http` 或 `https`；必须拒绝任何 userinfo（包括空用户名，如 `http://@host/`）、非法端口（不在 $[1, 65535]$）、控制字符，以及 host 中的空白、反斜杠与百分号（`%`）。控制字符必须在原始字符串上检查；host 必须通过 `idna` 包按 `host.lower(), strict=True, std3_rules=True` 规范化（与 urllib3 2.x 的 `_idna_encode` 一致），规范化失败必须拒绝。`allowed_hosts` 匹配、DNS 解析和最终传给 `requests` 的 URL 必须使用同一个规范化后的 ASCII host；禁止用非规范化 host 做校验却用另一形式发起连接。
* **AC-6.2**: 必须通过 `dns_resolver(host, port)` 解析主机；对返回的每一个 IP 都必须执行 3.6 定义的 `_is_public_ip` 检查，而不是仅检查 `ipaddress.ip_address(...).is_global`；只要存在任一非公网地址，必须抛出 `ResultDownloadSecurityError`。`allow_private_hosts=True` 仅跳过该 IP 检查，不免除 scheme、userinfo、`allowed_hosts`、IDNA、重定向与降级检查。
* **AC-6.3**: IP 字面量必须直接校验；IPv6 的 IPv4-mapped 地址必须先归一化为 IPv4 再校验；带 zone ID（如 `fe80::1%en0`）的地址必须拒绝；IPv6 过渡机制（至少 `64:ff9b::/96` NAT64、`2002::/16` 6to4、`2001::/32` Teredo）必须按 3.6 的 `_is_public_ip` 规则拒绝或归一化后校验。
* **AC-6.4**: DNS 解析失败（`socket.gaierror` / `OSError`）或 `dns_resolver` 返回空序列，必须按瞬态错误重试，**包括初始 URL 的首次解析**；`dns_resolver` 返回无效 IP 或非 IP 字符串时，必须失败关闭并抛出 `ResultDownloadSecurityError`。实现必须把“URL 语法校验”与“目标解析校验”分离：前者只执行一次并抛 `ResultDownloadConfigurationError`，后者在每次尝试、每一跳重定向中执行，并由重试循环把 DNS 瞬态异常转换为重试。
* **AC-6.5**: 当 `allowed_hosts` 非 `None` 时，每个请求目标的主机名必须与列表中的条目精确匹配（大小写不敏感、忽略尾部 `.`；Unicode 主机按 AC-6.1 规范化；IP 字面量使用压缩形式）；不匹配必须抛出 `ResultDownloadSecurityError`。该检查不得绕过 AC-6.2 的 IP 检查。本期不支持通配符；若实际 CDN 使用动态子域，调用方应枚举主机或依赖 IP 检查，见 Q-11。
* **AC-6.6**: 仅 `301`、`302`、`303`、`307`、`308` 必须被跟随；最多跟随 `max_redirects` 次（默认 5），即最多发出 `max_redirects + 1` 次请求。相对 `Location` 必须通过 `urljoin` 解析；每一跳都必须重新执行 AC-6.1 ~ AC-6.5 的校验。
* **AC-6.7**: 缺少或为空的 `Location` 必须抛出 `ResultDownloadHTTPError`（携带 3xx 状态码）；超过重定向上限、目标协议非 HTTP(S)、目标端口非法或目标 host 非法，必须抛出 `ResultDownloadSecurityError`。
* **AC-6.8**: 默认必须拒绝从 `https` 重定向到 `http`；仅当 `allow_https_downgrade=True` 时允许。`http` → `https` 不受限制。
* **AC-6.9**: 首次跨源重定向后，后续所有请求必须移除**下载器通过 `headers` 传入的** `Authorization`、`Proxy-Authorization`、`Cookie`、`Cookie2` 请求头，且不得在后续跳中重新加入；同源重定向可保留。自定义敏感头不在自动识别范围内，调用方应配合 `allowed_hosts` 使用。注入 Session 的全局敏感头与认证状态由 AC-8.8 约束；下载器不得声称能在不修改 Session 的前提下移除它们。
* **AC-6.10**: 自建 Session 必须使用 `requests` 默认的 TLS 校验（`verify=True`）；下载器不得暴露 `verify=False`。注入 Session 的 TLS 策略由调用方负责；`SSLError` 必须映射为 `ResultDownloadSecurityError`。
* **AC-6.11**: 每个重定向响应必须在发起下一跳前关闭，不得读取其响应体；重试必须从原始 URL 重新开始。
* **AC-6.12**: 必须明确记录 DNS Rebinding 的残余风险：预校验与 `requests` 的实际连接可能发生二次解析；IDNA 规范化已把“校验 host 与连接 host 不一致”从确定性风险降为残余风险；详见 R-1、R-16 与 Q-2。
* **AC-6.13**: 自建 Session 必须明确 `trust_env` 策略；本期沿用 `requests` 默认（`trust_env=True`），但文档必须声明：代理会重新解析目标，AC-6.1 ~ AC-6.5 的 SSRF 保证仅对直连语义成立；需要强保证的部署必须显式注入 `trust_env=False` 的 Session 或在代理层限制出站。

---

### US-7: Content-Type 白名单

**As a** 业务调用方  
**I want to** 只接受预期类型的内容  
**So that** 错误页面、HTML 或意外二进制内容不会进入后续解析流程

#### 验收标准 (Acceptance Criteria)

* **AC-7.1**: `allowed_content_types=None` 时不得进行任何内容类型过滤。
* **AC-7.2**: 白名单非 `None` 时，必须取最终响应 `Content-Type` 的分号前部分，去除空白并转小写；必须支持精确匹配、`type/*` 通配与 `*/*`；不匹配时必须抛出 `ResultDownloadContentTypeError`。
* **AC-7.3**: 白名单非 `None` 且最终响应缺少 `Content-Type` 或值为空时，必须抛出 `ResultDownloadContentTypeError`（`content_type=None`）。
* **AC-7.4**: `204` / `205` 或可用 `Content-Length` 为 0 的响应不适用内容类型白名单，不读取响应体，直接返回空流；该行为必须与 AC-3.10 一致，并在遥测中记录 `bytes=0`。
* **AC-7.5**: 内容类型检查只针对最终 2xx 响应，必须在读取响应体前完成；失败属于终态错误，不得重试。内容类型检查先于 `Content-Length` 预检；两者同时失败时以 `ResultDownloadContentTypeError` 为准。
* **AC-7.6**: 异常必须携带 `content_type` 与规范化后的 `allowed`，不得携带响应体内容。
* **AC-7.7**: 文档必须说明 `Content-Type` 不是安全边界，服务端可以伪造；它只用于路由与快速失败。

---

### US-8: 会话生命周期与可测试性

**As a** 服务集成方  
**I want to** 复用连接池，并在测试中完全替换网络、DNS 与时钟  
**So that** 生产环境高效、测试环境无网络且行为可断言

#### 验收标准 (Acceptance Criteria)

* **AC-8.1**: 未注入 `session` 时必须自建 `requests.Session`；`close()` 或退出上下文时必须关闭自建 Session。注入 `session` 时不得关闭它。
* **AC-8.2**: 同一实例的所有请求——包括重试与每一跳重定向——必须复用同一个 Session。
* **AC-8.3**: `close()` 必须可重复调用且不抛异常；`__enter__` 必须返回实例，`__exit__` 必须等价于 `close()`。
* **AC-8.4**: 不得通过 `session.headers.update(...)` 修改注入 Session 的全局请求头；默认头与自定义头必须按请求传入。
* **AC-8.5**: 注入的 `session`、`dns_resolver`、`sleep`、`monotonic`、`wall_clock`、`random_fn` 必须足以在无网络环境下覆盖成功、重试、重定向、超时与安全拒绝路径。
* **AC-8.6**: 实例必须支持顺序复用，但不得声明线程安全；同一实例的并发 `resolve()` 不受支持。并发场景必须每线程使用独立实例或线程局部 Session。
* **AC-8.7**: `close()` 后继续调用 `resolve()` 的行为未定义；调用方必须在关闭后停止使用实例。该约束必须在文档中说明。
* **AC-8.8**: 注入 Session 不得携带 `Authorization`、`Proxy-Authorization`、`Cookie`、`Cookie2` 全局头，且 `session.auth` 必须为 `None`；构造时发现任一条件不满足，必须抛出 `ResultDownloadConfigurationError`。需要认证时应通过构造参数 `headers` 传入，以便 AC-6.9 的跨源移除策略生效。Session 的 Cookie jar 由调用方负责，下载器不保证跨源 Cookie 隔离；需要强隔离时应注入干净的专用 Session。
* **AC-8.9**: 自建 Session 的 `trust_env` 行为必须按 AC-6.13 文档化；注入 Session 的 `trust_env` 由调用方负责；下载器不得在不说明的情况下改变 `requests` 的代理语义。

---

### US-9: 可观测性

**As a** 运维 / 服务集成方  
**I want to** 通过日志与指标观察下载耗时、字节数、重试与失败原因  
**So that** 我能定位慢请求、限流与安全拒绝，同时不泄漏签名 URL

#### 验收标准 (Acceptance Criteria)

* **AC-9.1**: 每次 `resolve()` 调用必须在 `finally` 中恰好上报一次 `mineru.download.total`、`mineru.download.duration_ms`、`mineru.download.bytes` 与 `mineru.download.attempts`，**包括 URL 校验失败、安全拒绝与未分类异常**；`outcome` 标签必须取自 3.8 定义的枚举。每次重试必须额外上报 `mineru.download.retry.total`。
* **AC-9.2**: 必须记录 `mineru.download`（成功）、`mineru.download.retry`（每次重试）与 `mineru.download.error`（终态失败，包含配置 / 安全 / 内容类型等校验失败）日志，字段符合 3.8 节定义。
* **AC-9.3**: `on_metric` 抛出的任何异常必须被吞掉并记录 `mineru.metric.failed` 警告日志，不得影响下载主流程。
* **AC-9.4**: 所有日志与异常消息中的 URL 必须移除 query 与 fragment；不得记录请求头、响应头全集或响应体。非法 URL 无法脱敏时必须以 `"<invalid-url>"` 代替。公共异常消息不得拼接 `str(requests_exception)`；`last_error` 必须是脱敏摘要；异常链不得把原始签名 URL 暴露给调用方（见 AC-4.12）。
* **AC-9.5**: 当提供 `correlation_id` 时，下载器发出的所有日志必须携带该字段。
* **AC-9.6**: 指标标签不得包含原始 URL、query、fragment 或 `correlation_id`；只允许低基数标签（`outcome`、`status_class`、`error_type`）。`outcome` 必须取自 3.8 的枚举，不得使用自由文本。

---

## 3. 技术方案设计 (Technical Design)

### 3.1 架构与数据流 (Architecture & Data Flow)

#### 组件职责与边界

`ResultDownloader` 是唯一公共入口；其余组件均为其内部协作者或纯数据对象。

| 组件 | 职责 | 明确不做 |
| :--- | :--- | :--- |
| `ResultDownloader` | 配置校验、Session 生命周期、重试循环、重定向编排、流式读取、错误映射 | 不解压、不校验内容、不缓存、不限流、不落盘 |
| `DownloadRetryPolicy` | 持有重试参数（尝试次数、退避、抖动、`Retry-After` 上限） | 不持有网络状态、不执行 sleep |
| `_UrlGuard`（内部） | URL 语法校验、IDNA 规范化、`allowed_hosts`、DNS 解析、`_is_public_ip` 检查、重定向目标校验、URL 脱敏 | 不发 HTTP、不读响应体、不依赖重试控制流 |
| `_StreamReader`（可选内部） | 分块读取、`Content-Length` 判定、字节累加、`Content-Type` 校验、响应体不完整检测 | 不决定重试节奏、不发新请求；实现可内联到 `ResultDownloader` |
| `Telemetry`（共享） | 日志 / 指标统一出口、回调异常隔离、`correlation_id` 注入 | 不影响主流程 |

#### 包结构

```text
src/mineru_parser/
├── _telemetry.py              # 从 client/_telemetry.py 提取的共享实现
├── _http.py                   # 共享 HTTP 工具（Retry-After / status_class）
├── client/
│   └── ...
└── downloader/
    ├── __init__.py            # 公共再导出
    ├── downloader.py          # ResultDownloader
    ├── errors.py              # ResultDownloadError 体系
    ├── policy.py              # DownloadRetryPolicy / DEFAULT_DOWNLOAD_RETRY_POLICY
    └── security.py            # URL / IDNA / DNS / IP / 重定向校验与脱敏
```

> `client` 与 `downloader` 共同使用 `_telemetry.py`；`mineru_parser.__init__` 与 `mineru_parser.client.__init__` 的既有导出保持兼容。`downloader` 不依赖 `client` 的 wire 模型，避免把通用下载器绑定到 MinerU API。

#### 下载时序

```mermaid
sequenceDiagram
    autonumber
    actor Caller as 调用方
    participant DL as ResultDownloader
    participant Guard as _UrlGuard
    participant S as requests.Session
    participant CDN as CDN / 对象存储

    Caller->>DL: resolve(url)
    DL->>Guard: validate_url_syntax(url)
    Guard->>Guard: scheme / userinfo / host / port / 原始控制字符
    alt 语法校验失败
        Guard-->>Caller: ResultDownloadConfigurationError
    end

    loop 最多 max_attempts 次
        DL->>DL: 检查 total_timeout
        DL->>Guard: validate_target(current)
        Guard->>Guard: IDNA / allowed_hosts
        Guard->>Guard: dns_resolver(host, port) + _is_public_ip
        alt 校验失败 / DNS 瞬态
            Guard-->>DL: SecurityError / _DnsTransientError
        end
        DL->>S: GET current（stream=True, allow_redirects=False）
        S->>CDN: HTTP GET
        CDN-->>S: 3xx / 4xx / 5xx / 2xx
        alt 3xx 且 Location 合法
            DL->>Guard: validate_redirect(next_url)
            DL->>DL: 关闭响应，跳转次数 +1
        else 可重试状态 / 网络错误
            DL->>DL: 计算退避 / Retry-After / 剩余预算
            DL->>DL: 预算足够则 sleep；不足则立即 Timeout
        else 2xx
            DL->>DL: Content-Type 白名单
            DL->>DL: 可用 Content-Length 预检
            loop 每个分块
                S-->>DL: chunk
                DL->>DL: 累加字节，检查 max_bytes / deadline
            end
            DL-->>Caller: io.BytesIO（seek 0）
        else 终态错误
            DL-->>Caller: ResultDownloadHTTPError / Security / TooLarge / ContentType
        end
    end
    DL-->>Caller: ResultDownloadTransientError / ResultDownloadTimeoutError
```

### 3.2 数据模型 (Data Model)

#### 构造参数

| 构造参数 | 默认值 | 校验 / 语义 |
| :--- | :--- | :--- |
| `max_bytes` | `52428800`（50 MiB） | 正整数；单次响应体硬上限 |
| `chunk_size` | `65536`（64 KiB） | 正整数；实际块大小为 $\min(\text{chunk\_size}, \text{max\_bytes})$ |
| `request_timeout` | `(5.0, 30.0)` | 正有限数或 `(connect, read)` 正有限数二元组 |
| `total_timeout` | `300.0` | 正有限数或 `None`；覆盖整个 `resolve()` 调用 |
| `retry_policy` | `None` → `DEFAULT_DOWNLOAD_RETRY_POLICY` | 必须是 `DownloadRetryPolicy` |
| `allowed_content_types` | `None` | `None` 禁用；否则为规范化媒体类型集合 |
| `allowed_hosts` | `None` | `None` 禁用；否则为精确主机名集合 |
| `allow_private_hosts` | `False` | 跳过**所有**非公网 IP 检查（含回环、链路本地、多播、保留、site-local、NAT64）；高风险，仅建议测试使用 |
| `allow_https_downgrade` | `False` | 是否允许 `https` → `http` 重定向 |
| `max_redirects` | `5` | 整数 $\ge 0$；最多跟随的重定向次数 |
| `headers` | `None` | 字符串键值；构造时复制；保留头禁止 |
| `session` | `None` → 新建 `requests.Session()` | 注入时下载器不接管生命周期 |
| `sleep` | `time.sleep` | 退避等待函数，可注入假时钟 |
| `monotonic` | `time.monotonic` | 单调时钟，用于总预算与耗时 |
| `wall_clock` | `time.time` | 墙钟，用于 `Retry-After` HTTP-date |
| `random_fn` | `random.random` | 抖动随机源，返回值夹取到 $[0,1]$ |
| `dns_resolver` | `None` → 系统解析器 | `Callable[[str, int], Sequence[str]]` |
| `on_metric` | `None` | `MetricHook` |
| `correlation_id` | `None` | 附加到所有日志 |

#### 重试策略

`DownloadRetryPolicy` 为不可变 dataclass（`frozen=True, slots=True`）。

```python
@dataclass(frozen=True, slots=True)
class DownloadRetryPolicy:
    max_attempts: int = 3
    initial_interval: float = 0.5
    backoff: float = 2.0
    max_interval: float = 8.0
    jitter: float = 0.2
    max_retry_after: float = 60.0
```

| 参数 | 默认值 | 约束 | 语义 |
| :--- | :---: | :--- | :--- |
| `max_attempts` | `3` | 整数 $\ge 1$ | 总尝试次数，包含首次请求 |
| `initial_interval` | `0.5` | $> 0$ | 首次重试的基准间隔 $I_0$ |
| `backoff` | `2.0` | $\ge 1.0$ | 指数增长因子 $b$ |
| `max_interval` | `8.0` | $\ge$ `initial_interval` | 间隔上限 $I_{\max}$ |
| `jitter` | `0.2` | $[0, 1)$ | 抖动比例 $j$，延迟因子下界为 $1-j$ |
| `max_retry_after` | `60.0` | $\ge 0$ | `Retry-After` 截断上限 |

#### 内部状态

| 字段 | 类型 | 说明 |
| :--- | :--- | :--- |
| `_max_bytes` | `int` | 单次响应体上限 |
| `_chunk_size` | `int` | 请求的读取块大小 |
| `_request_timeout` | `float \| tuple[float, float]` | 连接 / 读取超时 |
| `_total_timeout` | `float \| None` | 整个调用的单调时钟预算 |
| `_retry_policy` | `DownloadRetryPolicy` | 重试参数 |
| `_allowed_content_types` | `frozenset[str] \| None` | 规范化后的内容类型白名单 |
| `_allowed_hosts` | `frozenset[str] \| None` | 规范化后的主机允许列表 |
| `_allow_private_hosts` | `bool` | 是否允许非全局 IP |
| `_allow_https_downgrade` | `bool` | 是否允许 HTTPS 降级 |
| `_max_redirects` | `int` | 重定向次数上限 |
| `_headers` | `Mapping[str, str]` | 合并后的请求头模板 |
| `_owns_session` | `bool` | 是否由下载器创建并负责关闭 Session |
| `_session` | `requests.Session` | 所有请求的共享会话 |
| `_runtime` | `_Runtime` | 注入的 sleep / monotonic / wall_clock / random_fn |
| `_guard` | `_UrlGuard` | URL / DNS / IP / 重定向校验与脱敏 |
| `_telemetry` | `Telemetry` | 日志与指标出口 |

> 实例不得保存任何单次调用状态（URL、缓冲区、重试计数、重定向链）；这些必须只存在于 `resolve()` 的局部变量中。

#### 内部结果对象

```python
@dataclass(frozen=True, slots=True)
class _BodyResult:
    buffer: io.BytesIO
    bytes_read: int


@dataclass(frozen=True, slots=True)
class _DownloadOutcome:
    buffer: io.BytesIO
    final_url: str
    status_code: int
    content_type: str | None
    redirects: int
    bytes_read: int
```

`_Retryable` 是内部异常，用于把可重试失败从 `_download_once` 传递给重试循环；`_IncompleteBody` 必须继承 `_Retryable`（或由 `_download_once` 统一包装），不得泄漏到公共 API。`_DownloadOutcome` 只用于在 `resolve()` 内完成遥测后交付 `buffer`，不得作为公共返回类型。

#### 异常体系

```text
ResultDownloadError
├── ResultDownloadConfigurationError   # 本地配置 / 初始 URL 非法
├── ResultDownloadSecurityError        # SSRF、非 HTTP(S)、TLS、重定向越界 / 降级
├── ResultDownloadTooLargeError        # 超过 max_bytes
├── ResultDownloadContentTypeError     # 内容类型白名单不匹配
├── ResultDownloadHTTPError            # 终态 HTTP 状态（含 206、未跟随的 3xx）
└── ResultDownloadTransientError       # 重试耗尽
    └── ResultDownloadTimeoutError     # 超时或总预算耗尽
```

| 异常 | 附加字段 | 说明 |
| :--- | :--- | :--- |
| `ResultDownloadTooLargeError` | `max_bytes`、`received_bytes`（可为 `None`）、`declared_bytes`（可为 `None`） | 触发来源可能是声明长度或流式累加 |
| `ResultDownloadContentTypeError` | `content_type`、`allowed` | `content_type=None` 表示响应缺失该头 |
| `ResultDownloadHTTPError` | `status_code`、`url`（已脱敏） | 不包含响应体 |
| `ResultDownloadTransientError` | `attempts`、`last_error`（脱敏摘要）、`last_status_code`（可为 `None`）、`retry_after`（可为 `None`） | 重试耗尽后的最终分类 |
| `ResultDownloadTimeoutError` | 继承上述字段 | 最后一次失败为超时，或总预算耗尽 |

> `ResultDownloadError` 独立于既有 `MinerUError` 体系；下载与 MinerU API 调用是两条可独立捕获的失败路径。本期不引入库级共享错误根；若未来需要“一网打尽”的捕获方式，可新增 `MinerUParserError` 并让 `MinerUError` / `ResultDownloadError` 同时继承它，该变更向后兼容。
>
> `ResultDownloadTimeoutError` 继承 `ResultDownloadTransientError`，便于调用方统一捕获超时类失败；它不表示同一次 `resolve()` 内部仍会继续重试。
>
> 公共异常的 `__str__`、`args` 与 `__cause__` 不得包含原始签名 URL；`last_error` 只保存脱敏摘要（例如 `ConnectionError: <redacted-url>`），不保存原始 `requests` 异常对象。

### 3.3 接口契约 (API Contracts)

#### 公共 API

```python
class ResultDownloader:
    def __init__(
        self,
        *,
        max_bytes: int = 50 * 1024 * 1024,
        chunk_size: int = 64 * 1024,
        request_timeout: float | tuple[float, float] = (5.0, 30.0),
        total_timeout: float | None = 300.0,
        retry_policy: DownloadRetryPolicy | None = None,
        allowed_content_types: Collection[str] | None = None,
        allowed_hosts: Collection[str] | None = None,
        allow_private_hosts: bool = False,
        allow_https_downgrade: bool = False,
        max_redirects: int = 5,
        headers: Mapping[str, str] | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        random_fn: Callable[[], float] = random.random,
        dns_resolver: DnsResolver | None = None,
        on_metric: MetricHook | None = None,
        correlation_id: str | None = None,
    ) -> None: ...

    @property
    def max_bytes(self) -> int: ...

    @property
    def retry_policy(self) -> DownloadRetryPolicy: ...

    def resolve(self, url: str) -> io.BytesIO: ...

    def close(self) -> None: ...

    def __enter__(self) -> ResultDownloader: ...

    def __exit__(self, *exc_info: object) -> None: ...
```

> `sleep`、`monotonic`、`wall_clock`、`random_fn`、`dns_resolver` 同时是测试缝与高级扩展点；其中 `sleep` / `monotonic` / `wall_clock` / `random_fn` 与 `MinerUApiClient` 保持一致，`dns_resolver` 为本组件新增。它们的公共稳定性低于 `max_bytes` / `retry_policy` / `resolve`，版本升级时按“高级 API”处理。

#### 公共 API 稳定性

| 层级 | 名称 | 承诺 |
| :--- | :--- | :--- |
| **稳定** | `ResultDownloader`、`resolve`、`close`、`max_bytes`、`retry_policy`、`DownloadRetryPolicy`、`DEFAULT_DOWNLOAD_RETRY_POLICY`、异常体系 | 遵循 SemVer；大版本才允许破坏性变更 |
| **高级 / 测试缝** | `sleep`、`monotonic`、`wall_clock`、`random_fn`、`dns_resolver` | 签名可能随测试设计调整；生产代码优先注入 `session` |
| **可选扩展** | `allowed_content_types`、`allowed_hosts`、`on_metric`、`correlation_id` | 行为稳定，但不承诺未来不新增参数 |

所有公共名称必须通过 `mineru_parser.downloader.__all__` 与顶层 `mineru_parser.__all__` 导出；`MetricHook`、`DnsResolver` 等类型别名也必须从公共模块可导入。`User-Agent` 中的版本号必须来自 `importlib.metadata.version("mineru-parser")`（带 `PackageNotFoundError` fallback）或模块级 `__version__`，不得硬编码。

#### 方法语义

| 方法 | 网络行为 | 关键语义 |
| :--- | :--- | :--- |
| `resolve` | `GET` + 可选重试 / 重定向 | 同步阻塞；成功返回游标为 0 的新 `BytesIO`；失败不返回部分数据 |
| `close` | 无 | 仅关闭自建 Session；可重复调用 |
| `with` | — | 退出时等价于 `close()` |
| `max_bytes` | — | 只读；单次响应体上限 |
| `retry_policy` | — | 只读；不可变重试策略 |

#### 默认请求头

| 头 | 默认值 | 说明 |
| :--- | :--- | :--- |
| `User-Agent` | `mineru-parser/<version>` | 调用方可通过 `headers` 覆盖 |
| `Accept` | `*/*` | 调用方可通过 `headers` 覆盖 |
| `Accept-Encoding` | `identity` | 避免压缩放大；调用方可覆盖 |
| `Authorization` | 不设置 | 需要时由调用方传入；跨源重定向会被移除 |

`headers` 与默认头按大小写不敏感方式合并；保留头（`Host`、`Content-Length`、`Transfer-Encoding`、`Connection`、`Range`）不得覆盖。默认头必须以 per-request headers 传入，必须覆盖注入 Session 的同名全局头（尤其是 `Accept-Encoding` 与 `User-Agent`）。下载器不得通过 `session.headers.update(...)` 修改注入 Session 的全局请求头；注入 Session 不得携带敏感全局头或 `session.auth`（AC-8.8）。

#### `resolve` 的交付契约

1. **完整性**：只有完整读取并关闭响应后才返回；任何失败都不会返回部分缓冲区。
2. **独立性**：每次调用返回新的 `BytesIO`；游标位于 0；下载器返回后不持有引用。
3. **所有权**：调用方拥有返回的 `BytesIO`，可自行 `close()`；下载器不负责其生命周期。
4. **顺序复用**：实例可顺序复用；不承诺线程安全；并发调用需独立实例或注入线程局部 Session。
5. **超时语义**：`total_timeout` 是端到端预算，不是单次 socket 超时；单次阻塞读取与 DNS 解析的越界见 AC-5.5。
6. **安全语义**：URL、DNS 结果、重定向目标均按不可信输入处理；`allowed_hosts`、`_is_public_ip`、IDNA 规范化与 HTTPS 降级规则同时生效。代理或注入 Session 会改变保证前提，见 AC-6.13、AC-8.8、R-7。
7. **脱敏语义**：公共异常消息、`last_error` 与日志不得包含 query / fragment / 原始 `requests` 异常字符串；详见 AC-4.12、AC-9.4。

#### 集成示例

```python
import zipfile

from mineru_parser import MinerUApiClient, ResultDownloader

with (
    MinerUApiClient() as client,
    ResultDownloader(max_bytes=20 * 1024 * 1024) as downloader,
):
    result = client.submit(
        "https://example.com/paper.pdf",
        data_id="doc-42",
    ).wait(timeout=600)
    stream = downloader.resolve(result.zip_url)
    with zipfile.ZipFile(stream) as archive:
        ...
```

### 3.4 下载算法 (Download Algorithm)

以下伪代码描述控制流；异常转换与指标在实现中按 3.7 / 3.8 补齐。为便于阅读，伪代码将 `_StreamReader` 的逻辑内联为 `ResultDownloader` 的 `_read_body` / `_check_content_type` 方法；实现可保持内联，也可抽成独立内部类，行为契约不变。

```python
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_RETRYABLE_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def resolve(self, url: str) -> io.BytesIO:
    started = self._monotonic()
    deadline = (
        None
        if self._total_timeout is None
        else started + self._total_timeout
    )
    attempts = 0
    last_error = None
    last_status = None
    last_retry_after = None
    bytes_read = 0
    outcome = "unexpected"

    try:
        # 只做语法 / 配置校验；DNS 与 IP 校验在每次尝试内执行
        target = self._guard.validate_url_syntax(url)
        while attempts < self._retry_policy.max_attempts:
            self._check_deadline(deadline, attempts, last_error)
            attempts += 1
            try:
                result = self._download_once(target, deadline, attempts, last_error)
            except _Retryable as exc:
                last_error = exc.cause
                last_status = exc.status_code
                last_retry_after = exc.retry_after
                if attempts >= self._retry_policy.max_attempts:
                    break
                delay = self._retry_delay(attempts, exc.retry_after)
                self._sleep_with_deadline(delay, deadline, attempts, last_error)
                self._emit_retry(attempts, exc, delay)
                continue

            bytes_read = result.bytes_read
            outcome = "success"
            self._emit_success(result, started, attempts)
            return result.buffer

        raise self._exhausted(
            last_error, attempts, last_status, last_retry_after
        )
    except ResultDownloadError as exc:
        outcome = _outcome_for(exc)
        bytes_read = getattr(exc, "received_bytes", None) or bytes_read
        self._emit_error(exc, attempts)
        raise
    except BaseException as exc:
        outcome = "unexpected"
        self._emit_unexpected(exc, attempts)
        raise
    finally:
        self._emit_metrics(
            outcome=outcome,
            started=started,
            bytes_read=bytes_read,
            attempts=attempts,
        )


def _download_once(
    self,
    original_url: str,
    deadline: float | None,
    attempt: int,
    last_error: BaseException | None,
) -> _DownloadOutcome:
    current = original_url
    redirects = 0
    allow_sensitive = True

    for _ in range(self._max_redirects + 1):
        self._check_deadline(deadline, attempt, last_error)
        try:
            current = self._guard.validate_target(current)
        except _DnsTransientError as exc:
            # DNS 失败（包括初始 URL 的首次解析）进入统一重试路径
            raise _Retryable(cause=exc) from exc
        self._check_deadline(deadline, attempt, last_error)
        headers = self._headers_for(current, allow_sensitive=allow_sensitive)
        try:
            response = self._session.get(
                current,
                stream=True,
                allow_redirects=False,
                timeout=self._request_timeout,
                headers=headers,
            )
        except requests.RequestException as exc:
            # 不保留原始异常链，避免签名 URL 进入 traceback
            raise self._classify_transport(exc, url=current) from None

        try:
            status = response.status_code

            if status in _REDIRECT_STATUSES:
                if redirects >= self._max_redirects:
                    raise ResultDownloadSecurityError("too many redirects")
                location = (response.headers.get("Location") or "").strip()
                if not location:
                    raise ResultDownloadHTTPError(status, redact_url(current))
                try:
                    # guard 在 join 前检查 Location 原始控制字符
                    next_url = self._guard.validate_redirect(current, location)
                except _DnsTransientError as exc:
                    raise _Retryable(cause=exc) from exc
                if not same_origin(current, next_url):
                    allow_sensitive = False
                current = next_url
                redirects += 1
                continue

            if 200 <= status < 300:
                if status == 206:
                    raise ResultDownloadHTTPError(206, redact_url(current))
                if status in (204, 205) or usable_content_length(response) == 0:
                    return _DownloadOutcome(
                        buffer=io.BytesIO(),
                        final_url=current,
                        status_code=status,
                        content_type=response.headers.get("Content-Type"),
                        redirects=redirects,
                        bytes_read=0,
                    )
                self._check_content_type(response, status)
                body = self._read_body(response, deadline, attempt, last_error)
                return _DownloadOutcome(
                    buffer=body.buffer,
                    final_url=current,
                    status_code=status,
                    content_type=response.headers.get("Content-Type"),
                    redirects=redirects,
                    bytes_read=body.bytes_read,
                )

            if status in _RETRYABLE_STATUSES:
                raise _Retryable.from_response(response)

            raise ResultDownloadHTTPError(status, redact_url(current))
        finally:
            response.close()

    raise AssertionError("unreachable: redirect loop must return or raise")


def _read_body(
    self,
    response,
    deadline: float | None,
    attempt: int,
    last_error: BaseException | None,
) -> _BodyResult:
    declared = usable_content_length(response)
    if declared is not None and declared > self._max_bytes:
        raise ResultDownloadTooLargeError(
            max_bytes=self._max_bytes,
            declared_bytes=declared,
        )

    buffer = io.BytesIO()
    received = 0
    try:
        effective_chunk = min(self._chunk_size, self._max_bytes)
        for chunk in self._iter_body(response, effective_chunk):
            if not chunk:
                continue
            received += len(chunk)
            if received > self._max_bytes:
                raise ResultDownloadTooLargeError(
                    max_bytes=self._max_bytes,
                    received_bytes=received,
                    declared_bytes=declared,
                )
            buffer.write(chunk)
            self._check_deadline(deadline, attempt, last_error)

        if declared is not None and declared > 0 and received < declared:
            raise _IncompleteBody(declared=declared, received=received)

        buffer.seek(0)
        return _BodyResult(buffer=buffer, bytes_read=received)
    except BaseException:
        buffer.close()
        raise


def _iter_body(response, chunk_size):
    raw = getattr(response, "raw", None)
    read1 = getattr(raw, "read1", None)
    if raw is not None and callable(read1):
        while True:
            chunk = read1(chunk_size, decode_content=True)
            if not chunk:
                return
            yield chunk
    else:
        yield from response.iter_content(chunk_size=chunk_size)


def usable_content_length(response) -> int | None:
    transfer_encoding = (
        response.headers.get("Transfer-Encoding") or ""
    ).lower()
    if "chunked" in transfer_encoding:
        return None
    content_encoding = (
        response.headers.get("Content-Encoding") or "identity"
    ).lower()
    if content_encoding not in ("", "identity"):
        return None
    raw = response.headers.get("Content-Length")
    if raw is None:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def _check_content_type(self, response, status: int) -> None:
    if self._allowed_content_types is None:
        return
    if status in (204, 205) or usable_content_length(response) == 0:
        return
    raw = (response.headers.get("Content-Type") or "").split(";", 1)[0]
    normalized = raw.strip().lower()
    if not normalized:
        raise ResultDownloadContentTypeError(
            content_type=None,
            allowed=tuple(sorted(self._allowed_content_types)),
        )
    if not any(
        allowed == "*/*"
        or normalized == allowed
        or (
            allowed.endswith("/*")
            and normalized.startswith(allowed[:-1])
        )
        for allowed in self._allowed_content_types
    ):
        raise ResultDownloadContentTypeError(
            content_type=normalized,
            allowed=tuple(sorted(self._allowed_content_types)),
        )
```

行为要点：

1. **先校验后请求**：初始 URL 与每一跳重定向目标都在发出请求前通过 `_UrlGuard`。
2. **响应必关闭**：重定向、错误与成功路径都通过 `finally` 关闭响应；重定向体不读取。
3. **重试从零开始**：每次尝试使用新的 `BytesIO` 与新的重定向预算。
4. **失败不交付**：任何异常路径都关闭临时缓冲区，不返回部分内容。
5. **流式判定**：`Content-Length` 只是快速失败手段；流式累加是最终判据。

> `_classify_transport` 按 3.7 将 `requests.RequestException` 映射为 `_Retryable` 或终态异常；`SSLError` 必须在一般 `ConnectionError` 之前匹配。`_classify_transport` 必须接收已脱敏的 `url`，不得把 `str(exc)` 拼进消息，也不得保留原始异常链。`_IncompleteBody` 必须继承 `_Retryable`；`_outcome_for` 负责把公共异常映射到 3.8 的 `outcome` 枚举，必须先判断 `ResultDownloadTimeoutError` 再判断其基类 `ResultDownloadTransientError`；`_emit_metrics` 必须在 `finally` 中恰好调用一次。

### 3.5 重试与超时算法 (Retry & Timeout)

#### 退避与抖动

第 $n$ 次尝试失败后（$n \ge 1$），下一次重试延迟：

$$d_n = \min(I_0 \cdot b^{n-1}, I_{\max}) \cdot \big((1-j) + j \cdot U\big)$$

其中：

- $I_0$ = `initial_interval`
- $b$ = `backoff`
- $I_{\max}$ = `max_interval`
- $j$ = `jitter`
- $U = \mathrm{clamp}(\text{random\_fn}(), 0, 1)$

$U$ 必须为有限值；`random_fn()` 返回 `NaN` / `±inf` 时按 0 处理，不得让非有限延迟进入 `sleep`（AC-1.10）。

`Retry-After` 存在时：

$$d_n = \min(\text{Retry-After}, \text{max\_retry\_after})$$

不叠加抖动。`Retry-After` 的秒数 / HTTP-date 解析必须复用 `client/transport.py` 的 `parse_retry_after`（或提取到共享 `_http.py`），不得在 downloader 内复制第二套实现。

#### 总预算

设 $T_{\text{budget}}$ 为 `total_timeout`，$t_{\text{mono}}$ 为注入的单调时钟：

$$\text{deadline} = \begin{cases}
t_{\text{mono}} + T_{\text{budget}}, & T_{\text{budget}} \ne \text{None} \\
\infty, & T_{\text{budget}} = \text{None}
\end{cases}$$

若 $d \ge \text{deadline} - t_{\text{mono}}$，说明剩余预算不足以完成下一次尝试，必须立即抛出 `ResultDownloadTimeoutError`，而不是先 sleep 再超时；因此不需要“截断 sleep”。异常必须携带 `last_status_code` 与 `retry_after`（若可得），以区分“服务端要求等待超过预算”和“实际已耗时超限”。

#### 尝试与重定向的计数

| 计数器 | 作用域 | 语义 |
| :--- | :--- | :--- |
| `attempts` | 单次 `resolve()` | 总尝试次数，包含首次请求；上限 `max_attempts` |
| `redirects` | 单次尝试 | 已跟随的重定向次数；上限 `max_redirects` |
| `received` | 单次尝试 | 已写入缓冲区的解码字节数；上限 `max_bytes` |

### 3.6 URL 安全校验与重定向 (URL Security & Redirects)

#### 目标校验顺序

```text
1. 字符串非空、外层空白去除；在原始字符串上检查 CR/LF/NUL 等控制字符（不能依赖 urlsplit）
2. scheme ∈ {http, https}
3. 无 userinfo（username/password 任一存在即拒绝）
4. host 非空；host 不含空白、反斜杠、% 或非法控制字符
5. 对 host 做 IDNA 规范化（`strict=True, std3_rules=True`，与 urllib3 2.x 一致）；失败则拒绝；后续步骤统一使用规范化后的 ASCII host
6. port ∈ [1, 65535]（缺省按 scheme 取 80/443）
7. allowed_hosts 匹配（若启用；使用规范化 host）
8. 逐个解析 IP；IPv4-mapped IPv6 归一化为 IPv4；拒绝 zone ID；拒绝 NAT64 / 6to4 / Teredo 等过渡地址
9. 每个 IP 必须通过 _is_public_ip（除非 allow_private_hosts=True）
```

#### 公网 IP 判定与主机规范化

`ipaddress.is_global` 在语义上接近“不是 private”，不能单独作为 SSRF 判据（多播、site-local、NAT64 等可能返回 `True`）。实现必须使用以下谓词：

```python
_TRANSITION_NETWORKS = (
    ipaddress.ip_network("64:ff9b::/96"),  # NAT64
    ipaddress.ip_network("2002::/16"),     # 6to4
    ipaddress.ip_network("2001::/32"),     # Teredo
)


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if not ip.is_global:
        return False
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        return False
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.is_site_local:
            return False
        if ip in _TRANSITION_NETWORKS:
            return False
    return True


def canonicalize_host(host: str) -> str:
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    host = host.rstrip(".")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return idna.encode(
            host.lower(), strict=True, std3_rules=True
        ).decode("ascii")
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.compressed
```

`canonicalize_host` 的结果必须同时用于 `allowed_hosts` 匹配、`dns_resolver` 调用和最终传给 `requests` 的 URL；禁止校验一个 host 却连接另一个 host。IPv4-mapped IPv6 必须归一化为 IPv4 压缩形式，确保 `allowed_hosts` 与 `_is_public_ip` 使用同一表示。`idna` 必须作为直接依赖写入 `pyproject.toml`，不能依赖 `requests` 的传递依赖。

#### 重定向规则

```text
301, 302, 303, 307, 308 → 跟随（GET 保持不变）
其他 3xx（含 300, 304, 305, 306）→ ResultDownloadHTTPError
缺少 / 空 Location → ResultDownloadHTTPError
Location 原始值必须先检查控制字符，再 urljoin；禁止先 join 后校验
已跟随次数达到 max_redirects 后再次收到 3xx → ResultDownloadSecurityError
下一跳非 HTTP(S) / host 非法 / port 非法 → ResultDownloadSecurityError
HTTPS → HTTP 且未开启 allow_https_downgrade → ResultDownloadSecurityError
首次跨源重定向后 → 移除下载器传入的敏感请求头，且后续不再恢复；注入 Session 的全局头见 AC-8.8
```

**同源判定**：比较 `(scheme.lower(), canonicalize_host(host), effective_port)`；默认端口归一化，canonical host 已包含大小写、尾部 `.` 与 IDNA 规范化。

#### DNS 解析器契约

```python
DnsResolver = Callable[[str, int], Sequence[str]]
```

- 默认实现：`socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)`，提取 `sockaddr[0]` 并去重；传入的 host 必须是 AC-6.1 规范化后的 ASCII host，禁止把 Unicode 原串直接交给解析器。
- 返回值必须是 IP 字符串；解析失败（`gaierror` / `OSError`）或返回空序列按瞬态错误处理（`_DnsTransientError`）；返回非法字符串按安全错误失败关闭。
- DNS 解析本身不受 `request_timeout` 控制，可能越过 `total_timeout`；见 AC-5.5。
- 预校验与实际连接使用两次解析，存在 DNS Rebinding 窗口；见 R-1。
- 实现可在**单次 attempt 内**缓存 `(host, port)` 的校验结果，避免初始校验与首次请求重复解析；缓存不得跨 attempt 或跨 `resolve()` 调用共享，以免瞬时 DNS 故障无法重试。

> **代理环境**：自建 Session 默认 `trust_env=True`，`HTTP(S)_PROXY` / `NO_PROXY` 会改变实际连接路径；AC-6.1 ~ AC-6.5 的 SSRF 保证基于本地解析与直连语义。需要强保证时注入 `trust_env=False` 的 Session 或在代理层限制出站，见 AC-6.13 与 R-7。

### 3.7 错误分类 (Error Classification)

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

### 3.8 遥测 (Telemetry)

`MetricHook = Callable[[str, float, Mapping[str, str]], None]`；指标回调异常必须被吞掉并记录 `mineru.metric.failed`；`correlation_id` 必须附加到所有日志。

| 类型 | 名称 | 标签 / 字段 |
| :--- | :--- | :--- |
| 日志 | `mineru.download` | `url`（脱敏）、`final_url`（脱敏）、`status_code`、`content_type`、`bytes`、`duration_ms`、`attempts`、`redirects`、`outcome` |
| 日志 | `mineru.download.retry` | `url`（脱敏）、`attempt`、`error_type`、`status_code`、`delay_ms` |
| 日志 | `mineru.download.error` | `url`（脱敏）、`error_type`、`status_code`、`attempts` |
| 日志 | `mineru.metric.failed` | `metric_name`、`error_type` |
| 指标 | `mineru.download.total` | `outcome` |
| 指标 | `mineru.download.duration_ms` | `outcome` |
| 指标 | `mineru.download.bytes` | `outcome` |
| 指标 | `mineru.download.attempts` | `outcome` |
| 指标 | `mineru.download.retry.total` | `error_type`、`status_class`（`2xx` / `3xx` / `4xx` / `5xx` / `error`） |

`outcome` 枚举（低基数，禁止自由文本）：

| outcome | 触发 |
| :--- | :--- |
| `success` | 成功返回 `BytesIO` |
| `config_error` | 构造 / URL 语法 / 保留头 / 注入依赖非法 / 注入 Session 敏感头 |
| `security_error` | SSRF、IDNA、非 HTTP(S)、TLS、重定向越界 / 降级 |
| `too_large` | 超过 `max_bytes` |
| `content_type_error` | 白名单不匹配或缺失 |
| `http_error` | 终态 HTTP 状态（含 206、未跟随 3xx） |
| `transient` | 重试耗尽且最后失败非超时 |
| `timeout` | 超时或总预算耗尽 |
| `unexpected` | 未知非 `RequestException` 异常 |

- `total` / `retry.total` 按 counter 语义使用（每次调用 / 每次重试值 1）；`duration_ms` / `bytes` / `attempts` 按分布量使用，单位分别为毫秒、字节、次数。
- 指标必须在 `resolve()` 的 `finally` 中恰好上报一次；`on_metric` 异常按 AC-9.3 吞掉。

> `mineru.download.bytes` 记录本次调用成功写入返回缓冲区的字节数；失败时取异常上的 `received_bytes`（若可得），否则为 0。`attempts` 为总尝试次数，`redirects` 为成功尝试中跟随的重定向次数。失败日志只记录异常类名与脱敏 URL，不记录异常消息或原始响应内容。

**脱敏规则**：

```python
def redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    if (
        not parsed.scheme
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        return "<invalid-url>"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
```

- `redact_url(url)` 必须移除 query 与 fragment，仅保留 scheme、netloc 与 path；无法解析或包含 userinfo 时返回 `"<invalid-url>"`。
- 日志与异常消息不得包含请求头值、完整响应头、响应体或 `str(requests_exception)`；`last_error` 必须是脱敏摘要，异常链不得暴露原始签名 URL。
- 指标标签不得包含 URL；避免高基数与签名泄漏。
- path 中的敏感信息不在自动脱敏范围内；调用方应避免把令牌放在 path 中，见 R-11。

---

## 4. 边界条件与异常处理 (Edge Cases & Error Handling)

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
| 代理环境 | `HTTP_PROXY` / `HTTPS_PROXY` 生效 | `resolve` | 遵循 `requests` 行为；SSRF 校验基于本地解析，代理环境下的保证见 AC-6.13 / R-7 | — |
| 异常链泄漏 | `str(requests_exception)` / `__cause__` 含签名 URL | 所有失败路径 | 公共消息与 `last_error` 脱敏；必要时 `from None` | — |
| 注入依赖不可调用 | `sleep` / `dns_resolver` 等非 callable | 构造 | 拒绝 | `ResultDownloadConfigurationError` |
| `random_fn` 返回非有限值 | `NaN` / `±inf` | 重试计算 | 按 0 处理，不传给 `sleep` | — |

---

## 5. 任务拆解与实施步骤 (Task Breakdown)

* [ ] **Phase 1: 公共契约与共享遥测**
* [ ] 定义 `ResultDownloadError` 异常体系与 `DownloadRetryPolicy` / `DEFAULT_DOWNLOAD_RETRY_POLICY`
* [ ] 将 `MetricHook` / `Telemetry` 提取到共享 `mineru_parser/_telemetry.py`，保持既有导入兼容
* [ ] 将 `parse_retry_after` / `_status_class` 提取到共享 `_http.py`（或从 `client/transport.py` 复用），避免重复实现
* [ ] 实现构造参数校验（数值、策略、白名单、主机列表、保留请求头、callable、`bool` 拒绝、header token）
* [ ] 定义公共 API 稳定性分层与版本号来源（`importlib.metadata` / `__version__`）
* [ ] 在 `pyproject.toml` 增加 `idna` 直接依赖（与 urllib3 2.x 的 `_idna_encode` 一致）
* [ ] 在 `mineru_parser/downloader/__init__.py` 与顶层 `mineru_parser/__init__.py` 导出公共 API

* [ ] **Phase 2: URL 安全与传输**
* [ ] 实现原始字符串控制字符校验、userinfo / 端口拒绝
* [ ] 实现 IDNA 主机规范化（`strict=True, std3_rules=True`），并确保校验、DNS、请求 URL 使用同一 canonical host
* [ ] 实现 `allowed_hosts`、DNS 解析器注入、IPv4 / IPv6 / IPv4-mapped / zone ID 校验
* [ ] 实现 `_is_public_ip`（私网 / 回环 / 链路本地 / 多播 / 保留 / site-local / NAT64 / 6to4 / Teredo）
* [ ] 实现 `redact_url` 与安全错误分类
* [ ] 实现注入 Session 敏感全局头 / `session.auth` 校验（AC-8.8）
* [ ] 实现手动重定向循环、逐跳复验、HTTPS 降级拒绝与敏感头移除

* [ ] **Phase 3: 流式读取、重试与超时**
* [ ] 实现 `raw.read1` / `iter_content` 流式分块读取、`BytesIO` 写入、`seek(0)` 交付
* [ ] 实现 `Content-Length` 可用性判定、预检、流式累加与不完整响应检测
* [ ] 确保 `_IncompleteBody` 继承 `_Retryable`（或统一包装），不得逃逸公共 API
* [ ] 实现 `Content-Type` 白名单与 204/205/空响应体分支
* [ ] 实现退避 / 抖动 / `Retry-After` / 最大尝试次数；`random_fn` 非有限值按 0 处理
* [ ] 实现 `total_timeout`、deadline 检查与“等待超过预算立即超时”
* [ ] 实现终态 / 瞬态错误映射与异常字段填充；公共消息与 `last_error` 脱敏

* [ ] **Phase 4: 生命周期、遥测与测试**
* [ ] 实现 Session 所有权、`close()`、上下文管理器
* [ ] 接入日志 / 指标 / `correlation_id` / URL 脱敏；指标在 `finally` 中恰好上报一次
* [ ] 实现 `outcome` 枚举与指标类型 / 单位（counter vs 分布量）
* [ ] 针对 AC-1.1 ~ AC-9.6 编写无网络测试（假 Session / 假 Resolver / 假时钟）
* [ ] 覆盖 SSRF、IDNA、多播 / NAT64、重定向、超限、不完整响应、白名单与重试耗尽等边界
* [ ] 覆盖注入 Session 敏感头、异常消息脱敏、`_IncompleteBody` 分类、`finally` 指标与内存上界
* [ ] 更新 README：说明下载器是可选组件，`MinerUApiClient` 仍只交付 `zip_url`
* [ ] 回写 SPEC-001 的 R-5 / Q-4 引用 SPEC-002，避免文档矛盾
* [ ] 全量测试通过并更新 Spec 状态

#### AC 与测试映射

> 当前 Spec 为 In Review，以下为计划测试名；实现完成后在 PR 中补齐实际映射。

| 验收标准 | 计划测试 |
| :--- | :--- |
| AC-1.1 ~ AC-1.11 | `test_downloader_config_*`、`test_downloader_retry_policy_defaults`、`test_non_callable_injection_rejected` |
| AC-2.1 ~ AC-2.8 | `test_resolve_returns_bytesio_at_start`、`test_invalid_url_fails_before_http`、`test_control_chars_checked_before_urlsplit`、`test_sequential_calls_return_independent_buffers` |
| AC-3.1 ~ AC-3.10 | `test_content_length_over_limit_fails_early`、`test_streamed_size_limit_aborts`、`test_incomplete_body_is_retried`、`test_partial_content_is_rejected`、`test_memory_bound_with_tracemalloc` |
| AC-4.1 ~ AC-4.12 | `test_retryable_statuses_retry`、`test_terminal_4xx_not_retried`、`test_retry_after_honored_and_capped`、`test_retry_exhaustion_reports_last_error`、`test_error_messages_redacted` |
| AC-5.1 ~ AC-5.7 | `test_total_timeout_bounds_call`、`test_read_timeout_retries`、`test_timeout_does_not_return_partial_buffer`、`test_retry_after_exceeds_budget_raises_timeout` |
| AC-6.1 ~ AC-6.13 | `test_ssrf_blocks_private_ip`、`test_ssrf_blocks_multicast_and_nat64`、`test_ssrf_blocks_mapped_ipv6`、`test_idna_host_canonicalized`、`test_redirect_revalidates_target`、`test_redirect_limit`、`test_https_downgrade_rejected`、`test_cross_origin_drops_sensitive_headers`、`test_allowed_hosts` |
| AC-7.1 ~ AC-7.7 | `test_content_type_whitelist_exact_and_wildcard`、`test_missing_content_type_rejected`、`test_empty_body_skips_content_type` |
| AC-8.1 ~ AC-8.9 | `test_session_ownership`、`test_session_with_global_auth_rejected`、`test_injected_dependencies_are_used`、`test_close_is_idempotent` |
| AC-9.1 ~ AC-9.6 | `test_telemetry_redacts_query`、`test_metric_hook_failure_is_swallowed`、`test_metrics_do_not_include_url`、`test_metrics_emitted_once_in_finally`、`test_exception_cause_does_not_leak_url` |

---

## 6. 风险与待决事项 (Risks & Open Questions)

### 6.1 风险评估表 (Risk Register)

| 编号 | 风险 / 问题描述 | 潜在影响 | 缓解 / 规避方案 | 状态 / 负责人 |
| :--- | :--- | :--- | :--- | :--- |
| `[R-1]` | DNS Rebinding：预校验与 `requests` 实际连接是两次解析 | 攻击者可在校验后把域名指向私网，绕过 SSRF 检查 | 逐跳预校验 + `allowed_hosts` + 出口网络策略；IDNA 规范化消除“校验 host 与连接 host 不一致”的确定性风险；彻底修复需 DNS Pin（Q-2） | 待评估 / @jackafx |
| `[R-2]` | `zip_url` 有时效或一次性签名 | 重试时 URL 已失效，下载失败 | 调用方在失败后重新 `wait()` / 获取新 URL；不缓存过期 URL | 待评估 / @jackafx |
| `[R-3]` | 并发下载的内存放大 | 50 MiB × N 并发可能 OOM | 调用方限制并发；按任务调低 `max_bytes`；大文件落盘见 Q-4 | 待评估 / @jackafx |
| `[R-4]` | `Content-Length` 缺失 / 撒谎 | 预检不可靠，可能浪费带宽 | 流式累加为最终判据；不完整响应重试 | 已缓解 / @jackafx |
| `[R-5]` | `Content-Type` 可伪造 | 白名单不是安全边界 | 仅作快速失败；必要时调用方自行校验魔数 / 结构 | 已缓解 / @jackafx |
| `[R-6]` | `requests.Session` 非线程安全 | 多线程共享实例行为不确定 | 文档声明不承诺线程安全；每线程独立实例 / 线程局部 Session | 已缓解 / @jackafx |
| `[R-7]` | 代理重新解析目标 | 本地 SSRF 校验与实际出口不一致 | 在代理层限制出站；文档说明本地校验边界；强保证场景使用 `trust_env=False`（AC-6.13） | 待评估 / @jackafx |
| `[R-8]` | 慢速滴流（slowloris） | 单次 read timeout 无法限制总时长 | `total_timeout` 默认 300s + 每块 deadline 检查 | 已缓解 / @jackafx |
| `[R-9]` | 注入 Session 关闭 TLS 校验 | MITM 风险 | 下载器不暴露 `verify=False`；文档说明注入 Session 的安全责任 | 待评估 / @jackafx |
| `[R-10]` | 压缩炸弹 / 解码放大 | 单块解码后可能超过 `chunk_size`，峰值内存短暂放大 | 默认 `Accept-Encoding: identity`；流式计数超限即中止；严格隔离需独立进程 / 容器 | 待评估 / @jackafx |
| `[R-11]` | URL path 中可能含签名 / 令牌 | 日志脱敏只移除 query / fragment，path 仍可能泄漏 | 文档建议令牌放 query；避免记录 path 中的敏感段 | 待评估 / @jackafx |
| `[R-12]` | 注入 Session 自带重试 | 与下载器重试叠加，放大请求量 | 文档要求注入 Session 将重试次数设为 0；默认自建 Session 无额外重试 | 已缓解 / @jackafx |
| `[R-13]` | DNS 解析不受 `request_timeout` 控制 | `total_timeout` 可能被系统解析器拖长 | 文档说明；生产环境使用可控的 `dns_resolver` | 待评估 / @jackafx |
| `[R-14]` | `Retry-After` HTTP-date 受本地墙钟偏差影响 | 等待过短或过长 | 对解析结果做非负截断与 `max_retry_after` 截断；非法值忽略 | 已缓解 / @jackafx |
| `[R-15]` | 注入 Session 携带全局 `Authorization` / `Cookie` / `session.auth` | 跨源重定向泄漏凭据 | 构造时拒绝（AC-8.8）；文档要求注入干净 Session；Cookie jar 由调用方负责 | 已缓解 / @jackafx |
| `[R-16]` | IDNA2003 与 IDNA2008 映射差异 | 校验 host 与实际连接 host 不同，绕过 `allowed_hosts` 或 SSRF 检查 | 统一使用 `idna` 的 `strict=True, std3_rules=True` 规范化，并把 canonical host 同时用于 DNS 与请求 URL | 已缓解 / @jackafx |
| `[R-17]` | 50 MiB 默认 `max_bytes` 未必覆盖真实结果包 | 大文档频繁 `TooLarge`，迫使调用方调大上限或要求落盘 | 用真实样本统计 P50/P95/P99 后再定默认值；大文件落盘见 Q-4 | 待评估 / @jackafx |
| `[R-18]` | `requests` 异常字符串或异常链包含签名 URL | 日志 / traceback 泄漏 query token | 公共消息只拼接异常类名与脱敏 URL；`last_error` 为脱敏摘要；必要时 `from None` | 已缓解 / @jackafx |
| `[R-19]` | 空 200 / `Content-Length: 0` 被当作成功 | 调用方把错误页或空结果当成完整结果 | AC-3.10 明确遥测与文档提示；调用方需自行检查空流 | 待评估 / @jackafx |

### 6.2 待决事项 (Open Questions)

> **已闭环（划线/归档）：**
> * [x] ~~`[Q-0]`：下载器是否应内置解压与入库？~~
>   * **决策结论**：不内置。下载器只负责网络到 `io.BytesIO`；解压、校验与入库属于下游业务。

#### 1. 核心架构与契约 (Architecture & Contract)

* [x] **`[Q-1]`**：`resolve()` 是否应返回带元数据的子类（如 `DownloadedContent(io.BytesIO)`，携带 `content_type`、`final_url`、`size`），而不是裸 `io.BytesIO`？
  * **决策结论**：v1 选 **方案 A**，返回裸 `io.BytesIO`。当前消费者是 `zipfile`，不需要元数据；未来若返回 `BytesIO` 子类，`isinstance(..., io.BytesIO)` 仍兼容，可按 SemVer 小版本追加。
  * **备选方案**：
    * **方案 A**：保持裸 `io.BytesIO`，元数据不交付。
    * **方案 B**：返回 `io.BytesIO` 子类，保持 `isinstance(..., io.BytesIO)` 兼容。

* [x] **`[Q-2]`**：是否实现 DNS Pin（校验后连接已解析 IP）以消除 R-1？
  * **决策结论**：v1 选 **方案 A**。预校验 + `allowed_hosts` + 出口网络策略已能覆盖主要场景；自定义 Adapter 需要同时维护 SNI / Host / 连接池 / 代理语义，复杂度与回归风险过高。残余风险写入 R-1 与安全文档。
  * **备选方案**：
    * **方案 A**：保持现状，依赖 `allowed_hosts` 与出口网络策略。
    * **方案 B**：自定义 `HTTPAdapter` / 连接池，将 host 映射到已校验 IP，并保留 Host / SNI。

* [x] **`[Q-3]`**：是否需要每次调用的策略覆盖（如 `resolve(url, *, max_bytes=..., total_timeout=...)`）？
  * **现状 / 影响**：当前策略全部在构造期固定；不同 URL 需要不同限额时需创建多个实例。
  * **结论**：暂不纳入当前目标；优先保持实例配置简单、可预测。

#### 2. 业务边界与扩展性 (Scope & Extensibility)

* [x] **`[Q-4]`**：是否支持超过 `max_bytes` 时落盘或流式交给调用方？
  * **结论**：暂不纳入当前目标；本期固定 `io.BytesIO`。大文件场景需要重新设计交付契约。
* [x] **`[Q-5]`**：是否引入缓存、主动限流与中间件/拦截器？
  * **结论**：暂不纳入当前目标。缓存涉及失效与多租户隔离；限流属于编排层；中间件可通过注入 `requests.Session` 的 hooks / adapters 实现。
* [x] **`[Q-6]`**：是否提供 `resolve(MinerUTaskResult)` 或 `client.download(result)` 的便捷入口？
  * **结论**：暂不提供；调用方显式传入 `result.zip_url`，保持客户端与下载器的边界清晰。
* [x] **`[Q-7]`**：是否需要 `on_progress(downloaded_bytes, total_bytes | None)` 进度回调？
  * **结论**：暂不纳入当前目标；50 MiB 上限下收益有限。若支持大文件落盘再评估。

#### 3. 性能与运行时 (Performance & Runtime)

* [x] **`[Q-8]`**：`total_timeout` 默认 300s 是否合适，还是应默认 `None` 或按 `max_bytes` 推导？
  * **决策结论**：选 **方案 A**，保留 300s。300s 对应 50 MiB 约 170 KiB/s 的最低吞吐假设；慢链路调用方必须显式覆盖或设 `None`，文档需写明该假设。
  * **备选方案**：
    * **方案 A**：保持 300s，调用方可显式覆盖或关闭。
    * **方案 B**：默认 `None`，由调用方负责设置预算。

* [x] **`[Q-9]`**：是否需要显式声明并发模型（每线程实例 vs 线程局部 Session）并提供辅助工厂？
  * **结论**：v1 明确“每线程独立实例”即可，不提供辅助工厂；优先保证单实例顺序语义正确。并发封装属于调用方编排层。

#### 4. API 细节 (API Details)

* [x] **`[Q-10]`**：是否引入库级共享错误根（如 `MinerUParserError`）？
  * **结论**：本期不引入。`MinerUError` 与 `ResultDownloadError` 保持独立；若未来需要统一捕获，可新增共享根并让两者继承，向后兼容。
* [x] **`[Q-11]`**：`allowed_hosts` 是否支持 `*.example.com` 通配符？
  * **结论**：本期不支持。通配符会扩大 SSRF 面并引入标签匹配歧义；动态 CDN 场景由调用方枚举主机或依赖 `_is_public_ip` 检查。
* [x] **`[Q-12]`**：`resolve` 是否改名为 `download` / `fetch`？
  * **结论**：保留 `resolve`。它表达“把 URL 解析为内存流”，且与 `MinerUApiClient` 的 `submit` / `resume` 命名不冲突；若后续更名，按 SemVer 主版本处理。
