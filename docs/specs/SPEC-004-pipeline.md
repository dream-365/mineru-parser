# \[SPEC-004\] Pipeline


| 属性              | 内容         |
| :--------------- | :---------- |
| **状态**          | In Review  |
| **负责人**         | @jackafx   |
| **创建时间**        | 2026-10-21 |
| **更新时间**        | 2026-10-21 |
| **关联 Issue/PR** | —（待关联）     |


> **评审指引**：本 Spec 的**唯一契约源是 §2 的验收标准（AC）**。评审以 AC 清单为准，逐条确认"可断言 / 可测试"；§3 给出的是**契约**（公共 API、参数语义、阶段判定规则、错误映射、遥测口径），**不包含具体代码实现**——实现方式由实现者决定，§3 只约束"必须做什么"与"必须如何判定"。实现与 §3 契约不一致时以 AC 为准，并回写本 Spec。
>
> **本 Spec 的定位**：它是**库的门面（facade）**，不新增任何解析能力。SPEC-001（client）、SPEC-002（downloader）、SPEC-003（extractor）的契约**一字不改**；本 Spec 只负责把三者串成一条流水线，并把"整个项目对外只暴露一个 `parse` 函数"这件事固化为可断言的契约。

---

## 1. 背景与目标 (Context &amp; Objectives)

### 1.1 背景 (Context)

仓库目前有三个各自独立、契约清晰的组件：SPEC-001 的 `MinerUApiClient` 负责"提交 → 等待"并交付 `zip_url`；SPEC-002 的 `ResultDownloader` 负责把结果包流式读进 `io.BytesIO`；SPEC-003 的 `extract_result` 负责把 ZIP 内存流解析为 `{"pages", "images"}`。三个组件都刻意**不耦合**彼此——这带来了清晰的可测试边界，但也把编排成本全部推给了调用方。

调用方今天必须自己写这段样板：

```python
with MinerUApiClient() as client, ResultDownloader() as downloader:
    task = client.submit(uri, data_id=data_id)
    result = task.wait(timeout=600, on_update=on_update)
    stream = downloader.resolve(result.zip_url)
    extracted = extract_result(stream)
```

痛点集中在六个方面，且**没有一个能靠"再调一次某个组件的参数"解决**：

1. **编排样板与顺序知识外泄**：三个组件的调用顺序、参数透传、生命周期关闭分散在每个调用点；调用方需要知道"谁产生什么、谁消费什么"，这是编排契约而非组件契约。
2. **顶层 API 面过宽**：库的顶层 `mineru_parser` 当前导出约 40 个名字（3 个组件类 + 1 个函数 + 全部异常类 + 全部类型）。使用者要判断"我到底该用哪个入口"，实际答案永远是"三个都用"。
3. **生命周期与所有权无人负责**：中间产物（ZIP `BytesIO`）的所有权在样板代码里是模糊的——谁负责 `close()`？异常路径上谁负责？实践中"忘记关流"与"重复关闭"都会出现。
4. **失败不可归因**：三个组件抛三族互不继承的异常（`MinerUError` / `ResultDownloadError` / `ResultExtractionError`）。调用方能区分异常**类型**，但拿不到"是哪一个阶段失败"的结构化信息——只能靠猜或翻日志。
5. **预算不闭合**：三个组件各有自己的超时与字节上限（等待轮询超时、下载总预算、下载 `max_bytes`、提取解压限额），但**没有任何一层负责把它们合成一个端到端预算**。结果最坏情况下是三段超时之和，远超调用方的心智预期。
6. **崩溃即孤儿任务**：任务一旦提交成功就存在于服务端。若进程在"提交成功、task\_id 落库之前"崩溃，任务永远无人认领——因为 `data_id` 按 SPEC-001 的语义**不是幂等键**。

此外还有一处**跨组件才看得见的资源问题**：SPEC-003 的峰值内存推导（单次 ≈ 240 MiB）只覆盖了解压侧，**没有计入压缩侧仍然驻留的 ZIP 缓冲**（默认 ≤ 50 MiB）。真实峰值是两者之和（≈ 290 MiB），在 SPEC-003 的默认形态（$W = 4$、1 GiB 容器）下会超限。这个问题只有编排层能看见。

链路概览（本期要串起来的正是这条链）：

```mermaid
flowchart LR
    classDef io fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c;
    classDef mod fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;
    classDef out fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;
    classDef srv fill:#fce4ec,stroke:#ad1457,stroke-width:2px,color:#880e4f;

    URI["PDF URI"]:::io
    CLIENT["client<br/>MinerUApiClient · AsyncResult"]:::mod
    API["MinerU API Server"]:::srv
    ZIPURL["zip_url"]:::io
    DL["downloader<br/>ResultDownloader"]:::mod
    MEM["io.BytesIO<br/>ZIP 内存流"]:::io
    EX["extractor<br/>extract_result"]:::mod
    RESULT["ParseResult<br/>{pages, images, task_id, data_id, zip_url}"]:::out

    URI -->|"① 提交"| CLIENT
    CLIENT -->|"POST /extract/task"| API
    API -->|"task_id"| CLIENT
    CLIENT -->|"GET /extract/task/{id}"| API
    API -->|"full_zip_url"| ZIPURL
    ZIPURL -->|"② 下载"| DL
    DL --> MEM
    MEM -->|"③ 解析"| EX
    EX --> RESULT
```

### 1.2 现状与差距分析 (Gap Analysis)

#### 能力维度对比


| 能力维度            | 手写三段编排（今天）            | 分阶段库调用 | 本期目标（`parse` 门面）                     |
| :--------------- | :---------------------: | :------: | :------------------------------------: |
| 一次调用完成端到端       | ❌                     | ❌      | ✅                                    |
| 顶层只需一个入口        | ❌（顶层导出约 40 个名字）       | ❌      | ✅（仅 `parse` 一个函数）                    |
| 阶段顺序由库保证        | ❌                     | ❌      | ✅                                    |
| 中间产物所有权明确       | ⚠️ 模糊                 | ⚠️ 模糊  | ✅（管道负责关闭）                            |
| 失败阶段可结构化归因      | ❌                     | ❌      | ✅（`PipelineStage`）                   |
| 端到端统一预算         | ❌                     | ❌      | ✅（单一 `timeout` / `deadline_epoch`）   |
| 超时语义单一          | ❌（三族超时异常）             | ❌      | ✅（统一 `PipelineTimeoutError`）         |
| 崩溃后任务可恢复        | ⚠️ 需调用方自己接住 `task_id` | ⚠️ 同左  | ✅（`on_task_created` + `task_id=` 恢复） |
| 压缩侧 + 解压侧联合内存预算 | ❌                     | ❌      | ✅（§3.6 公式 + README 数字）               |
| 组件可独立替换 / 独立测试  | ✅                     | ✅      | ✅（注入契约，组件契约不变）                       |
| 组件契约可独立演进       | ✅                     | ✅      | ✅（SPEC-001/002/003 一字不改）             |


#### 顶层 API 面的变化（本 Spec 的破坏性影响）


| 名称                                                                                       | 现状   | 本期后                                 | 迁移方式                                                    |
| :---------------------------------------------------------------------------------------- | :---- | :----------------------------------- | :------------------------------------------------------- |
| —                                                                                        | —    | ✅ `mineru_parser.parse`（**唯一稳定函数**） | 直接使用                                                    |
| `MinerUApiClient` / `AsyncResult`                                                        | 顶层导出 | 移出顶层                                | `from mineru_parser.client import MinerUApiClient`      |
| `ResultDownloader`                                                                       | 顶层导出 | 移出顶层                                | `from mineru_parser.downloader import ResultDownloader` |
| `extract_result` / `canonicalize_member_path`                                            | 顶层导出 | 移出顶层                                | `from mineru_parser.extractor import extract_result`    |
| 三族具体异常类                                                                                  | 顶层导出 | 移出顶层                                | 从各子模块导入                                                 |
| `MinerUParserError`                                                                      | 顶层导出 | **保留**（捕获全库失败所需）                    | 无需改动                                                    |
| `ExtractedResult` / `ExtractedImage` / `ExtractionLimits` / `MetricHook` / `__version__` | 顶层导出 | **保留**（`parse` 签名/返回值所需类型）          | 无需改动                                                    |
| `PipelineStage`（新增）                                                                      | —    | **保留**（`on_error` 回调参数类型）           | —                                                       |
| `ParseResult`（新增）                                                                        | —    | **保留**（`parse` 的返回类型）               | —                                                       |


> **破坏性变更登记**：顶层 `__all__` 收缩是**有意的破坏性变更**，项目版本为 `0.1.0`（未到 1.0），本期一次性完成比"分阶段弃用"更干净。README 必须同步改写（§5 Phase 4），changelog 必须记录迁移路径。
>
> **不导出的理由**：组件 API 仍然存在于子模块中，并且**仍然是 SPEC-001/002/003 的契约**——本 Spec 只是把它们从"顶层门面"降级为"可组合的内部实现"。它们不获得 SemVer 保证（未来可自由调整签名），但**行为契约不变**；组件的独立测试继续覆盖它们。

> **样本基线（2026-10-21）**：编排层没有独立样本，沿用 SPEC-003 已核对过的真实结果包 `tests/data/result_001.zip`（7 成员、manifest 4,803 B、1 页 6 块、1 张图 13,936 B）与 SPEC-002 的下载器契约测试作为组件级基线；编排层的**预算数字**（§3.6）是由两个组件的既有默认值推导而来，**不是实测值**——真实并发峰值仍需在部署环境标定，见 R-6。

### 1.3 目标 (Goals)

- [ ] **Goal 1**：提供**唯一**的顶层公共函数 `mineru_parser.parse(uri, ...) -> ParseResult`，一次调用完成"提交 → 等待 → 下载 → 解析"，并把任务元数据（`task_id` / `data_id` / `zip_url`）随解析产物一并交付。
- [ ] **Goal 2**：顶层 `mineru_parser.__all__` 中**只有一个可调用对象**（`parse`）；其余导出只能是类型与常量（AC-2.1 可断言）。
- [ ] **Goal 3**：把三组件的编排契约固化为库责任：阶段顺序、参数透传、生命周期关闭、中间产物所有权。
- [ ] **Goal 4**：提供**单一端到端预算**（`timeout` / `deadline_epoch`），覆盖四个阶段；预算耗尽统一表现为 `PipelineTimeoutError(stage=...)`。
- [ ] **Goal 5**：失败**阶段可归因**：以封闭枚举 `PipelineStage` 标识，通过 `on_error` 回调、日志与指标标签暴露。
- [ ] **Goal 6**：除超时外，阶段异常**原样透传**（不包装、不翻译、不吞掉），保持三个组件既有的异常语义与捕获方式。
- [ ] **Goal 7**：崩溃安全：提交成功后立即通过 `on_task_created` 回调交出 `task_id`；支持以 `task_id=` 恢复等待，不重复提交。
- [ ] **Goal 8**：生命周期与所有权明确：管道自建 client / downloader 并在返回前关闭；中间 ZIP 流由管道关闭；结果对象独立于流。
- [ ] **Goal 9**：压缩侧与解压侧的**联合内存预算**显式化（§3.6 公式 + README 峰值数字），并给出并发度与限额的关系。
- [ ] **Goal 10**：可观测性统一：`correlation_id` 透传三组件；管道自身的指标与阶段耗时日志口径唯一。
- [ ] **Goal 11**：全流程可在**无网络**环境下测试（注入 client / downloader 替身与假时钟），CI 不依赖真实 MinerU 服务。
- [ ] **Goal 12**：**不改动** SPEC-001 / SPEC-002 / SPEC-003 的任何契约；本 Spec 只增不改。

### 1.4 非目标 (Non-Goals / Out of Scope)

> 明确本次迭代**不包含**的内容，防止需求范围膨胀（Scope Creep）。

- [ ] 改动 SPEC-001 / SPEC-002 / SPEC-003 的任何公共契约、参数默认值、异常层次或限额默认值。
- [ ] 批处理、并发调度、线程池 / 异步 / `asyncio` 版本；本期只有一个同步函数。
- [ ] "只提交不解析"的入口（如 `parse(submit_only=True)`）：批量先提交、稍后再解析的作业模式由调用方直接使用 `mineru_parser.client` 实现，管道不提供该分支。
- [ ] 结果包的断点续传 / 本地缓存（缓存已下载的 ZIP）：结果包体积有限，重新下载的成本可接受，缓存带来的状态与失效复杂度不划算。
- [ ] 把 `mineru_parser.pipeline` 作为**公开**子包（允许第三方插入或扩展阶段）：公开会引入插件契约与版本耦合成本，管道实现保持内部。
- [ ] 阶段级重试（重试是各组件内部的责任）；管道不做整链重放。
- [ ] 结果缓存（内存 LRU、Redis、本地磁盘）与条件请求。
- [ ] 自动持久化 `task_id`、任务注册表、任务对账 API、孤儿任务自动清理或取消。
- [ ] 断路器、限流、熔断、排队与背压。
- [ ] 结果上传 / 入库 / 对象存储落盘。
- [ ] 分布式追踪（OpenTelemetry / trace context 传播）；`correlation_id` 只是字符串透传。
- [ ] 图片解码、格式嗅探、缩略图、`image_source.path` 与 `images` 的交叉校验（属 SPEC-003 的明确非目标）。
- [ ] 阅读顺序重建、跨页合并、版面块重排。
- [ ] 幂等提交 / 去重：相同 `uri` + `data_id` 的两次 `parse()` 会产生两个任务（继承 SPEC-001 语义）。
- [ ] 把 `parse` 拆成多个可组合的顶层函数（`submit_and_wait` / `download_and_extract` 等）；顶层保持**只有一个函数**。
- [ ] 顶层再导出组件类或组件异常类（见 §1.2 迁移表）。
- [ ] 流式 / 懒加载输出；`parse()` 一次性交付完整 `ParseResult`。
- [ ] 端到端 exactly-once 语义；重复调用可能重复计费（见 R-3）。
- [ ] 为 `parse()` 提供"无限等待"的默认值之外的隐式兜底（如服务端侧兜底取消）。

### 1.5 威胁模型 (Threat Model)


| 维度        | 内容                                                                                                                                                                            |
| :--------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **输入来源**  | `uri`（PDF 地址）与 `task_id` 由调用方提供，可能来自外部用户；`zip_url` 来自服务端，按不可信网络输入处理。                                                                                                          |
| **受保护资产** | API 凭据（`MINERU_API_KEY`）、进程内存、下游磁盘（若调用方把 `images[].path` 落盘）、下游图片渲染器、服务端配额与费用。                                                                                                |
| **攻击者能力** | 控制 `uri` 与 `task_id` 的取值；控制结果包内容（经由上游或伪造的 `zip_url`）；诱导重定向到内网 / 元数据端点；构造超大或恶意的 ZIP。                                                                                           |
| **主要控制**  | client 侧 URL 语法校验与 Bearer 鉴权；downloader 侧 SSRF 防护（仅 HTTP(S)、IDNA、DNS 公网性、逐跳重定向复验、HTTPS 降级拒绝、`max_bytes`）；extractor 侧 manifest 唯一性、Schema 校验、canonical path、解压后限额；管道层统一预算与所有权。 |
| **残余风险**  | `zip_url` 若被劫持，下载器仍会执行 SSRF 校验（纵深防御）；`correlation_id` 若由用户可控，不得进入指标标签（AC-6.9）；`on_task_created` / `on_error` 回调由调用方提供，其异常已被隔离但不构成安全边界。                                        |


> 本 Spec **不新增**安全控制，只把三个组件既有的控制**串起来**并保证"任一阶段的控制都不可被管道绕过"——例如管道不得为了"少一次往返"而跳过下载器的 URL 校验，也不得为了"省内存"而把 ZIP 交给 extractor 之外的解析路径。

---

## 2. 用户故事与验收标准 (User Stories &amp; Acceptance Criteria)

### US-1: 单函数端到端解析

**As a** 业务调用方
**I want to** 只调用一个函数就拿到解析结果
**So that** 我不必了解三个组件的调用顺序、参数透传与生命周期

#### 验收标准 (Acceptance Criteria)

- **AC-1.1**: `parse(uri, *, ...)` 必须接受一个绝对 http(s) 的 PDF URI，并返回 `ParseResult`——一个**恰好**包含 `"pages"`、`"images"`、`"task_id"`、`"data_id"`、`"zip_url"` 五个键的普通 `dict`。其中 `pages` 与 `images` 的**形状与取值**必须与 `extract_result` 的返回值逐字相同：`pages` 必须是 Pydantic 模型实例，`images[].bytes` 必须是不可变 `bytes`，`images` 按 canonical path 字典序升序（继承 SPEC-003 AC-1.2 / AC-1.3 / AC-4.6）。`ParseResult` **不得**改变 `ExtractedResult` 的既有契约——`extract_result` 仍只返回两个键（SPEC-003 AC-1.2 不变）。
- **AC-1.2**: `parse()` 必须依次完成四个阶段：**submit → wait → download → extract**。任一阶段失败必须**中止**后续阶段：失败于 submit / wait 时不得发起下载请求，失败于 download 时不得调用提取器。
- **AC-1.3**: `parse()` 不得要求调用方构造 `MinerUApiClient` / `ResultDownloader` / `extractor`；未注入时必须自建（AC-3.1）。注入仅作为高级 / 测试缝存在（AC-2.5）。
- **AC-1.4**: 每次调用必须返回**全新**对象；不得缓存、复用或跨调用共享上一次的结果、页模型实例或图片字节。
- **AC-1.5**: 成功时必须上报 `mineru.pipeline.total{outcome="success"}` 与 `mineru.pipeline.duration_ms{outcome="success"}`，并记录四个阶段的耗时（AC-6.7）。
- **AC-1.6**: `parse()` 必须是**无状态**函数：不得持有跨调用的可变状态；并发调用不同实例之间不得共享可变状态（同一进程内两次并发 `parse()` 各自自建 client / downloader，互不干扰）。
- **AC-1.7**: `parse()` 不得改变三个组件的语义：`submit` 的请求体、`wait` 的轮询语义、`resolve` 的重试与 SSRF 规则、`extract_result` 的定位与限额规则全部按各自 SPEC 执行（AC-4.9）。
- **AC-1.8**: `parse()` 返回后不得再持有对 ZIP 流、HTTP 响应体、Session 或结果的引用（AC-3.5）。
- **AC-1.9**: `ParseResult` 的元数据字段必须取自本次调用的终态结果：`task_id` 必须等于 `MinerUTaskResult.provider_task_id`（沿用 SPEC-001 AC-9.2 的取值优先级——服务端返回优先、句柄 id 兜底），`data_id` 必须等于 `MinerUTaskResult.data_id`（服务端与提交参数都缺失时为 `None`），`zip_url` 必须等于 `MinerUTaskResult.zip_url`（不得为空串）。
- **AC-1.10**: `ParseResult.zip_url` 属于**敏感值**（可能携带签名凭据）：管道不得把它写入任何日志或指标标签（AC-6.9）；调用方把它落盘或打日志前必须自行评估。管道不得对其做任何脱敏改写——`ParseResult.zip_url` 必须与 `MinerUTaskResult.zip_url` 逐字相同（AC-1.9）。

---

### US-2: 唯一公共 API 与契约面

**As a** 库使用者
**I want to** 面对一个明确的入口面
**So that** 我不必在几十个导出名里猜"该用哪个"

#### 验收标准 (Acceptance Criteria)

- **AC-2.1**: `mineru_parser.__all__` 中**有且只有一个可调用对象**——`parse`。其余条目必须是非可调用对象（类型、类常量、`__version__`）。该约束必须由测试断言（AC-8.4）。
- **AC-2.2**: 顶层**必须**继续导出：`MinerUParserError`（捕获全库失败）、`ParseResult`、`ExtractedResult`、`ExtractedImage`、`ExtractionLimits`、`MetricHook`、`PipelineStage`、`__version__`。其中 `ParseResult` / `ExtractedResult` / `ExtractedImage` / `ExtractionLimits` / `MetricHook` / `PipelineStage` 是 `parse` 的签名或返回值所引用的类型。
- **AC-2.3**: `MinerUApiClient`、`AsyncResult`、`ResultDownloader`、`extract_result`、`canonicalize_member_path`、三族具体异常类与其他组件级名称**必须**从顶层 `__all__` 移除，但**必须**继续可从 `mineru_parser.client` / `mineru_parser.downloader` / `mineru_parser.extractor` 子模块导入，且其行为契约不变（继承 SPEC-001 / 002 / 003）。
- **AC-2.4**: 本变更属于**破坏性变更**，必须在 README 的迁移说明与本 Spec 的 changelog 中显式登记，并在 changelog 中给出"旧顶层导入 → 新子模块导入"的对照。
- **AC-2.5**: `parse` 的**签名与返回类型**遵循 SemVer；大版本才允许破坏性变更。组件 API 标注为"内部 / 高级"，**不**遵循 SemVer（未来可调整签名而不升大版本），但行为契约由各自 SPEC 约束。
- **AC-2.6**: 顶层**不得**出现第二个函数（包括别名、私有重导出、`parse` 的变体）；不得提供 `parse_async` / `parse_sync` 之类的并列入口（异步不在本期范围，见 Non-Goals）。
- **AC-2.7**: `parse` 必须从 `mineru_parser.pipeline`（内部实现模块）实现并在顶层再导出；顶层**不得**包含编排逻辑实现（编排代码必须位于 `mineru_parser.pipeline` 包内）。
- **AC-2.8**: `mineru_parser.pipeline` 包**必须**是内部实现层：不通过顶层 `__all__` 暴露其内部名称（`PipelineOrchestrator` 等实现细节不得出现在顶层）。

---

### US-3: 生命周期与资源所有权

**As a** 服务集成方
**I want to** 每一次调用都干净地收尾
**So that** 我不会泄漏连接、流或内存

#### 验收标准 (Acceptance Criteria)

- **AC-3.1**: 未注入时，`parse()` 必须自建 `MinerUApiClient` 与 `ResultDownloader`，并在**返回前**关闭它们——包括成功路径与所有失败路径（`finally` 语义）。关闭必须幂等。
- **AC-3.2**: 注入的 client / downloader **不得**被 `parse()` 关闭；其生命周期完全归调用方（对齐 SPEC-001 AC-8.2 / SPEC-002 AC-8.1）。
- **AC-3.3**: 下载得到的 ZIP `io.BytesIO` 由 `parse()` 拥有：必须在提取结束后关闭（成功与失败路径都关闭），且**不得**出现在返回值中。调用方无法取得该流。
- **AC-3.4**: 返回的 `ParseResult` 必须**独立于**已关闭的流：关闭流之后 `pages` 与 `images[].bytes` 仍可正常使用（提取器已复制字节，见 SPEC-003 AC-1.3）。
- **AC-3.5**: `parse()` 返回后不得持有对 ZIP 流、HTTP 响应体、Session、页模型或图片字节的引用；除返回值外不得保留任何对象。
- **AC-3.6**: 每次 `parse()` 调用必须创建**新的** client / downloader 实例；不得跨调用复用实例、Session 或缓冲区（AC-1.6）。
- **AC-3.7**: `parse()` 不得关闭调用方持有的任何对象；除自建的两个组件与中间 ZIP 流外，管道不拥有、不创建、不销毁任何资源。
- **AC-3.8**: 关闭顺序必须是"先关流、后关组件"：中间 ZIP 流在提取结束后立即关闭；client 与 downloader 在函数返回前的 `finally` 中关闭，顺序为 downloader → client（依赖方向：先停止下载，再停止 API 会话）。

---

### US-4: 端到端预算与超时

**As a** 服务集成方
**I want to** 用一个预算约束整条流水线
**So that** 我能预测最坏耗时，而不是三段超时之和

#### 验收标准 (Acceptance Criteria)

- **AC-4.1**: `timeout`（相对秒数）与 `deadline_epoch`（绝对 Unix 时间戳）**互斥**；同时提供必须抛出 `PipelineConfigurationError`，且**不得**发起任何网络请求、不得创建任何组件实例。两者都不提供表示不设端到端上限（等待阶段沿用客户端的无限等待语义，见 AC-4.8）。
- **AC-4.2**: 端到端预算必须覆盖**全部四个阶段**（submit / wait / download / extract），必须在每个阶段**开始前**与**结束后**检查。剩余预算必须按单调时钟计算（`deadline_epoch` 仅在入口处换算一次为单调预算）。
- **AC-4.3**: 预算耗尽时必须抛出 `PipelineTimeoutError`，其 `stage` 字段标识耗尽时所处阶段；不得返回部分结果，不得返回空结果冒充成功。
- **AC-4.4**: 等待阶段必须把**剩余预算**传给 `AsyncResult.wait(timeout=remaining)`（继承 SPEC-001 AC-4.1 \~ AC-4.3 的预算语义）。等待阶段自身抛出的 `MinerUTimeoutError` 必须被翻译为 `PipelineTimeoutError(stage="wait")`，原始异常必须作为 `__cause__` 保留，`last_status` / `task_id` 必须被复制到 `PipelineTimeoutError` 上。
- **AC-4.5**: 下载阶段抛出的 `ResultDownloadTimeoutError` 必须被翻译为 `PipelineTimeoutError(stage="download")`，原始异常作为 `__cause__` 保留。
- **AC-4.6**: 提取阶段是纯 CPU / 内存操作，**不接受**时间预算参数；预算在提取**结束后**检查，若已超预算必须抛 `PipelineTimeoutError(stage="extract")` 并丢弃结果（提取不可中断）。
- **AC-4.7**: 除等待阶段外，管道**无法中断**正在进行的下载（`resolve()` 不接受每调用预算，见 SPEC-002 AC-2.1）。若下载阶段越过端到端预算，管道只能在阶段结束后检出并抛 `PipelineTimeoutError(stage="download")`；该限制必须在 README 与本 Spec 中显式说明。
- **AC-4.8**: 不提供 `timeout` / `deadline_epoch` 时，等待阶段**无上界**（继承 SPEC-001 的 `wait()` 语义）。该默认值必须在 README 中以风险提示的形式给出（长文档解析可能耗时数分钟），但不得由管道自行代入隐式默认值。
- **AC-4.9**: 预算检查必须使用可注入的单调时钟；测试必须能在不 sleep 的情况下确定性地触发预算耗尽（AC-8.2）。

---

### US-5: 任务恢复与崩溃安全

**As a** 服务集成方
**I want to** 任务提交后立刻拿到 `task_id`，并在进程重启后接着等
**So that** 崩溃不会留下无人认领的任务，也不会重复提交

#### 验收标准 (Acceptance Criteria)

- **AC-5.1**: `parse(uri)` 必须在 **submit 成功之后、进入 wait 之前**调用 `on_task_created(task_id)`；回调必须收到服务端返回的 `task_id`（与 `AsyncResult.task_id` 一致）。
- **AC-5.2**: `on_task_created` 抛出的任何异常必须被吞掉并记录 `mineru.pipeline.on_task_created.failed` 警告日志，**不得**中断流水线（对齐 SPEC-001 AC-7.2 的回调隔离约定）。
- **AC-5.3**: `parse(task_id=...)` 必须**跳过提交阶段**：不得产生任何 `POST /extract/task` 请求（继承 SPEC-001 AC-3.4），必须经由客户端的 `resume()` 句柄继续等待。
- **AC-5.4**: `uri` 与 `task_id` 必须**恰好提供一个**：都不给或都给必须抛出 `PipelineConfigurationError`，且不得发起任何网络请求、不得创建组件实例。
- **AC-5.5**: 恢复路径下 `data_id` 必须透传给恢复句柄用于对账（继承 SPEC-001 AC-3.2 的 `data_id` 校验）。
- **AC-5.6**: 管道**不得**声称提交是幂等的：相同 `uri` + `data_id` 的两次 `parse()` 会创建两个任务（`data_id` 按 SPEC-001 语义仅用于对账，不是幂等键）。该行为必须在 README 中提示。
- **AC-5.7**: 孤儿任务的清理、取消与对账由调用方负责；管道不得自动取消任务，也不得提供任何取消接口（服务端能力不在本库范围，见 Non-Goals）。
- **AC-5.8**: 恢复路径的阶段序列必须是 **wait → download → extract**；`PipelineStage` 中不得出现 `submit`（该路径未经历提交阶段），遥测的阶段耗时中同样不得出现 `submit` 条目。

---

### US-6: 阶段归因与可观测性

**As a** 运维 / 服务集成方
**I want to** 知道失败发生在哪个阶段
**So that** 我能快速判断是上游慢、下载被拦还是包坏了

#### 验收标准 (Acceptance Criteria)

- **AC-6.1**: 必须定义封闭枚举 `PipelineStage`，取值恰好为 `submit` / `wait` / `download` / `extract`（`StrEnum`）；不得新增其他取值，也不得用自由文本表示阶段。
- **AC-6.2**: 任一阶段失败时，管道必须在抛出前调用 `on_error(stage, exception)`，其中 `exception` 是**该阶段原始抛出的异常对象**（超时翻译前）。
- **AC-6.3**: **除超时外**，阶段异常必须**原样抛出**：管道不得包装、翻译、替换或吞掉；抛出的对象必须与阶段抛出的对象**同一**（`is`），其类型、属性与异常链保持不变。因此 `except MinerUQuotaError` / `except ResultDownloadSecurityError` / `except ResultExtractionLimitError` 等既有捕获方式在 `parse()` 下**继续有效**。
- **AC-6.4**: 管道自身产生的失败必须使用 `PipelineError` 家族：`PipelineConfigurationError`（配置或参数非法）与 `PipelineTimeoutError`（端到端预算耗尽）。二者均继承 `PipelineError`，而 `PipelineError` 继承库级根 `MinerUParserError`。
- **AC-6.5**: `on_error` 抛出的任何异常必须被吞掉并记录 `mineru.pipeline.on_error.failed` 警告日志，不得影响主流程。
- **AC-6.6**: `on_metric` 抛出的任何异常必须被吞掉并记录 `mineru.metric.failed` 警告日志（与 SPEC-001/002/003 的既有约定一致）。
- **AC-6.7**: 管道自身的指标必须在 `finally` 中**恰好上报一次**；失败时 `mineru.pipeline.pages` / `mineru.pipeline.images` / `mineru.pipeline.image_bytes` 必须为 0。
- **AC-6.8**: 提供的 `correlation_id` 必须透传到 client / downloader / extractor 的**全部**日志与指标（各自组件按其 SPEC 附加该字段），并附加到管道自身的日志。
- **AC-6.9**: 指标标签只允许封闭枚举（`outcome`、`stage`）；**不得**包含 URI、`task_id`、`data_id`、`zip_url`、路径、成员名、异常消息或 `correlation_id`。
- **AC-6.10**: 未知的非 `MinerUParserError` 异常必须原样抛出，并记录 `outcome="unexpected"`；`MemoryError`、`KeyboardInterrupt`、`SystemExit` 不得被包装或吞掉（对齐 SPEC-003 AC-6.8）。
- **AC-6.11**: 管道自身的日志名必须为：`mineru.pipeline`（成功）、`mineru.pipeline.error`（失败，含 `stage` 与 `error_type`）、`mineru.pipeline.stage`（阶段切换，含阶段耗时）。三组件的既有日志名保持不变。
- **AC-6.12**: 阶段耗时必须以毫秒为单位记录，且四个阶段（恢复路径为三个）的耗时都必须出现在成功与失败两种情形的日志中。

---

### US-7: 资源预算自洽

**As a** 服务集成方
**I want to** 知道一次 `parse()` 真实占多少内存
**So that** 我能据此决定并发度，而不是等 OOM

#### 验收标准 (Acceptance Criteria)

- **AC-7.1**: 管道必须把**压缩侧上限**（下载的 `max_bytes`，默认 50 MiB）与**解压侧上限**（提取限额，SPEC-003 默认值）作为两个**独立量纲**管理，两者都必须有默认值；两者不得互相替代或合并为单一上限。
- **AC-7.2**: 单次 `parse()` 的峰值内存必须按 §3.6 的公式估算，并在 **README 中写明默认档位的峰值上界**（≈ 290 MiB）。该数字必须与 SPEC-003 §3.2 的推导口径保持自洽。
- **AC-7.3**: 管道不得因"下载成功但解压超限"而重试、改换路径或降级；`ResultExtractionLimitError` 必须原样抛出（终态），并由调用方按"该结果包超出本环境预算"理解（继承 SPEC-003 §3.2 的量纲说明）。
- **AC-7.4**: `limits` 参数必须是 `ExtractionLimits | None`；非法值必须在**进入任何阶段之前**抛出 `PipelineConfigurationError`，不得静默回退到默认值。
- **AC-7.5**: 管道不得缓存、落盘、复制或二次压缩结果包字节；ZIP 字节在生命周期内只存在一份（下载器返回的那份）。
- **AC-7.6**: 管道不得因内存压力主动中止或跳过提取；内存不足由 Python 抛出 `MemoryError`，按 AC-6.10 原样透出。

---

### US-8: 可测试性

**As a** 维护者
**I want to** 在无网络环境下覆盖整条流水线
**So that** CI 不需要 MinerU 凭据、真实结果包或外网

#### 验收标准 (Acceptance Criteria)

- **AC-8.1**: 全部行为必须可在**无网络**环境下测试：client 与 downloader 必须可被替身注入（AC-1.3 的注入缝），时钟必须可注入（AC-4.9）。
- **AC-8.2**: 测试必须覆盖：四阶段成功路径（submit / wait / download / extract 各一次）、四个阶段的失败路径、预算耗尽（分别在四个阶段边界触发）、超时翻译、异常原样抛出、组件与流的关闭、回调隔离。
- **AC-8.3**: 必须包含"**异常同一性**"测试：对每个阶段的失败，断言 `parse()` 抛出的对象与替身阶段抛出的对象 `is` 相同（超时除外，超时必须断言 `__cause__` 指向原始超时异常）。
- **AC-8.4**: 必须包含"**顶层 API 面**"测试：断言 `mineru_parser.__all__` 中的可调用对象恰好只有 `parse`，且 AC-2.2 要求保留的名称均存在、AC-2.3 要求移除的名称均不存在。
- **AC-8.5**: 默认构造路径（不注入 client）必须被覆盖：使用**本地回环地址**的 mock HTTP 服务提供 `/extract/task` 与 `/extract/task/{id}`（客户端无 SSRF 限制，允许回环），并注入 downloader 替身覆盖下载阶段（下载器的 SSRF 防护会拒绝回环地址，这是刻意行为，不得为测试放宽）。
- **AC-8.6**: 测试不得依赖真实 MinerU 服务、真实 CDN、真实外网地址或真实 API 凭据；不得读取环境变量 `MINERU_API_KEY`（必须显式注入）。
- **AC-8.7**: 管道实现必须是无状态的纯编排：不得引入模块级可变状态、不得使用全局单例、不得在导入时发起网络请求。

---

## 3. 技术方案设计 (Technical Design)

### 3.1 架构与数据流 (Architecture &amp; Data Flow)

#### 端到端链路

见 §1.1 的链路图。管道在其中承担的是"把 ① ② ③ 串起来并对整条链负责"的角色：

- **① submit**：客户端提交任务，产出 `task_id`；管道在拿到 `task_id` 的第一时间交给 `on_task_created`（崩溃安全）。
- **② wait**：客户端轮询到终态，产出 `zip_url`；管道在此消耗端到端预算的绝大部分。
- **③ download**：下载器把结果包读入 `io.BytesIO`；管道拥有并在提取后关闭该流。
- **④ extract**：提取器把 ZIP 内存流解析为 `{"pages", "images"}`；管道关闭流并交付结果。

#### 组件职责与边界


| 组件                           | 职责                                | 明确不做                          |
| :---------------------------- | :--------------------------------- | :----------------------------- |
| `mineru_parser.parse`（门面）    | 参数校验、阶段编排、预算检查、生命周期与所有权、阶段归因、遥测汇总 | 不实现协议、不解析 ZIP、不改变组件语义         |
| `mineru_parser.pipeline`（内部） | 上述逻辑的实现包；持有阶段状态机与预算计算             | 不被顶层 `__all__` 暴露内部名称（AC-2.8） |
| `client`（SPEC-001）           | 提交、轮询、终态解释、结果交付                   | 不下载、不解析                       |
| `downloader`（SPEC-002）       | 流式下载、重试、SSRF 防护、内存上限              | 不解压、不解析                       |
| `extractor`（SPEC-003）        | manifest 定位、Schema 校验、图片收集、解压后限额  | 不下载、不重试、不落盘                   |


#### 门面视角的组件编排

```mermaid
flowchart TB
    subgraph FACADE["mineru_parser（顶层）"]
        PARSE["parse(uri, ...)<br/>唯一公共入口"]
    end

    subgraph LIB["mineru_parser.pipeline（内部实现）"]
        ORCH["编排器<br/>阶段推进 · 预算 · 所有权 · 归因"]
        BUDGET["端到端预算<br/>timeout / deadline_epoch"]
        STAGE["PipelineStage<br/>submit / wait / download / extract"]
    end

    subgraph COMPONENTS["三个既有组件（契约不变）"]
        CLI["client<br/>MinerUApiClient · AsyncResult"]
        DL["downloader<br/>ResultDownloader"]
        EX["extractor<br/>extract_result"]
    end

    OUT["ParseResult<br/>{pages, images, task_id, data_id, zip_url}"]

    PARSE --> ORCH
    ORCH --> BUDGET
    ORCH --> STAGE
    ORCH --> CLI
    ORCH --> DL
    ORCH --> EX
    ORCH --> OUT

    style FACADE fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c
    style LIB fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1
    style COMPONENTS fill:#fce4ec,stroke:#ad1457,stroke-width:2px,color:#880e4f
    style OUT fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20
```

#### 编排时序

```mermaid
sequenceDiagram
    autonumber
    actor Caller as 调用方
    participant P as parse
    participant B as 端到端预算
    participant C as client
    participant D as downloader
    participant E as extractor

    Caller->>P: parse(uri, timeout=...)
    P->>P: 校验参数（uri / task_id 互斥、回调、limits）
    P->>C: 自建或使用注入的 client
    P->>D: 自建或使用注入的 downloader

    alt 提交路径
        P->>C: submit(uri, model_version, data_id)
        C-->>P: AsyncResult(task_id)
        P->>P: on_task_created(task_id)
        P->>B: 检查剩余预算
    else 恢复路径
        P->>C: resume(task_id, data_id)
        P->>B: 检查剩余预算
    end

    P->>C: wait(timeout=剩余预算)
    C-->>P: MinerUTaskResult(zip_url)

    P->>B: 检查剩余预算
    P->>D: resolve(zip_url)
    D-->>P: io.BytesIO（ZIP）
    P->>B: 检查剩余预算

    P->>E: extract_result(stream, limits)
    E-->>P: {pages, images}
    P->>P: 关闭 ZIP 流
    P->>B: 检查剩余预算（extract 阶段）

    P->>P: 关闭 downloader → client
    P-->>Caller: ParseResult {pages, images, task_id, data_id, zip_url}
```

#### 包结构

```text
src/mineru_parser/
├── __init__.py          # 唯一公共函数 parse + 类型再导出（AC-2.1 / AC-2.2）
├── errors.py            # MinerUParserError（既有，不变）
├── pipeline/            # 内部实现层（AC-2.7 / AC-2.8）
│   ├── __init__.py      # 内部再导出（parse 实现入口）
│   ├── orchestrator.py  # 阶段推进、生命周期、所有权、异常翻译
│   ├── budget.py        # 端到端预算与阶段计时
│   ├── stages.py        # PipelineStage
│   └── errors.py        # PipelineError / PipelineConfigurationError / PipelineTimeoutError
├── client/              # 既有（SPEC-001）
├── downloader/          # 既有（SPEC-002）
└── extractor/           # 既有（SPEC-003）
```

> 管道层**不新增第三方运行时依赖**；`pipeline` 包只依赖标准库、三个既有组件与 `pydantic`（间接）。

### 3.2 数据模型 (Data Model)

#### 阶段枚举

`PipelineStage` 为 `StrEnum`，取值恰好四个：


| 取值         | 含义                           | 恢复路径是否出现 |
| :---------- | :---------------------------- | :--------: |
| `submit`   | 提交解析任务（`POST /extract/task`） | ❌        |
| `wait`     | 轮询等待任务终态                     | ✅        |
| `download` | 下载结果包                        | ✅        |
| `extract`  | 解析结果包                        | ✅        |


> 取值必须是**封闭枚举**：它是指标标签与 `on_error` 参数的取值来源，必须低基数、可安全用于监控维度。

#### 异常体系

```text
MinerUParserError                  # 库级公共根异常（既有）
├── MinerUError                    # SPEC-001（既有）
├── ResultDownloadError            # SPEC-002（既有）
├── ResultExtractionError          # SPEC-003（既有）
└── PipelineError                  # 本 Spec 新增
    ├── PipelineConfigurationError  # 参数 / 配置非法
    └── PipelineTimeoutError        # 端到端预算耗尽
```


| 异常                           | 附加字段                                                                                | 说明                                                                                                                                                                                        |
| :---------------------------- | :----------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `PipelineConfigurationError` | `field: str | None`                                                                 | 参数名（如 `uri` / `task_id` / `limits` / `client` / `downloader` / `timeout` / `deadline_epoch` / `on_error` / `on_task_created` / `on_update` / `on_metric` / `correlation_id`）；未指明时为 `None` |
| `PipelineTimeoutError`       | `stage: PipelineStage`、`task_id: str | None`、`last_status: MinerUTaskStatus | None` | `last_status` 仅在等待阶段超时时可得（继承 SPEC-001 AC-4.3）；`__cause__` 为被翻译的原始超时异常                                                                                                                     |


> **与既有异常家族的关系**：`PipelineError` 与 `MinerUError` / `ResultDownloadError` / `ResultExtractionError` **互不继承**，四者共享公共根 `MinerUParserError`。因此 `except MinerUParserError` 可一次性捕获全库失败，而 `except ResultExtractionError` **不会**捕获管道自身的配置错误。
>
> **超时是唯一的翻译点**：`parse()` 的超时**统一**表现为 `PipelineTimeoutError`（AC-4.4 / AC-4.5），因此 `except MinerUTimeoutError` **不会**捕获 `parse()` 抛出的等待超时——这是有意的语义收敛：调用 `parse()` 的代码只需要认识一个超时类型。组件被直接调用时，各自的超时异常类型不变。

#### `parse` 参数


| 参数                | 类型                                                      | 默认值     | 语义                                         |
| :----------------- | :------------------------------------------------------- | :------- | :------------------------------------------ |
| `uri`             | `str | None`                                            | `None`  | PDF 的绝对 http(s) URI；与 `task_id` 恰好提供一个     |
| `task_id`         | `str | None`                                            | `None`  | 已提交任务的 id；提供时跳过提交阶段                        |
| `model_version`   | `str`                                                   | `"vlm"` | 透传给 `client.submit`（继承 SPEC-001）           |
| `data_id`         | `str | None`                                            | `None`  | 对账标识；**不是幂等键**（继承 SPEC-001）                |
| `timeout`         | `float | None`                                          | `None`  | 端到端相对预算（秒）；与 `deadline_epoch` 互斥           |
| `deadline_epoch`  | `float | None`                                          | `None`  | 端到端绝对截止（Unix 时间戳）；与 `timeout` 互斥           |
| `limits`          | `ExtractionLimits | None`                               | `None`  | 提取限额；`None` 使用 `DEFAULT_EXTRACTION_LIMITS` |
| `client`          | `MinerUApiClient | None`                                | `None`  | **高级 / 测试缝**：注入客户端；提供时管道不拥有、不关闭            |
| `downloader`      | `ResultDownloader | None`                               | `None`  | **高级 / 测试缝**：注入下载器；提供时管道不拥有、不关闭            |
| `on_update`       | `Callable[[MinerUTaskStatus], None] | None`             | `None`  | 透传给 `AsyncResult.wait`（继承 SPEC-001 AC-7.1） |
| `on_task_created` | `Callable[[str], None] | None`                          | `None`  | 提交成功后收到 `task_id`                          |
| `on_error`        | `Callable[[PipelineStage, BaseException], None] | None` | `None`  | 阶段失败时收到 `(stage, 原始异常)`                    |
| `on_metric`       | `MetricHook | None`                                     | `None`  | 管道与三个组件共用的指标回调                             |
| `correlation_id`  | `str | None`                                            | `None`  | 透传到三个组件的全部日志与指标                            |


> **注入参数的地位**：`client` / `downloader` 是**唯一**允许出现在 `parse` 签名里的组件级参数，且被明确标注为"高级 / 测试缝"。它们**不是**顶层导出的公共 API（组件类仍不在顶层 `__all__` 中，AC-2.3），普通用户不需要知道它们的存在。
>
> **参数校验时机**：所有参数校验必须在**创建任何组件实例之前**完成（AC-4.1 / AC-4.4 / AC-7.4），确保"配置错误"不会产生任何网络副作用。

#### 输出

`parse()` 返回 `ParseResult`——在解析产物之外**携带任务元数据**的管道层类型。

```python
from typing import TypedDict

from ..extractor import ExtractedResult


class ParseResult(ExtractedResult):
    task_id: str
    data_id: str | None
    zip_url: str
```

运行时 `ParseResult` 是普通 `dict`；`TypedDict` 只提供静态类型与文档约束。`ParseResult` **结构化继承** `ExtractedResult`，因此 `pages` / `images` 的语义完全沿用 SPEC-003，且 `ParseResult` 可直接赋值给期望 `ExtractedResult` 的位置（结构化子类型）。


| 字段               | 类型                      | 说明                                                         |
| :---------------- | :----------------------- | :---------------------------------------------------------- |
| `pages`          | `DocumentContentSchema` | 按 manifest 顺序；每页是版面块模型列表（继承 SPEC-003）                      |
| `images[].path`  | `str`                   | canonical 归档相对路径，恒为 `images/...`（继承 SPEC-003）              |
| `images[].bytes` | `bytes`                 | ZIP 成员解压后的精确字节；不转码（继承 SPEC-003）                            |
| `task_id`        | `str`                   | 本次任务的服务端 id；等于 `MinerUTaskResult.provider_task_id`（AC-1.9） |
| `data_id`        | `str | None`            | 对账标识；服务端与提交参数都缺失时为 `None`（AC-1.9）                          |
| `zip_url`        | `str`                   | 结果包地址；**敏感值**，不得进入日志或指标标签（AC-1.10）                         |


> **不污染既有契约**：`ExtractedResult` 的"恰好两个键"约束（SPEC-003 AC-1.2）针对的是 `extract_result` 的返回值，**不受影响**。`ParseResult` 是管道层**新增**的类型，扩展而非修改 `ExtractedResult`。
>
> **元数据与回调的分工**：`ParseResult` 提供的是**调用结束后**的元数据快照；`on_task_created` 提供的是**提交成功后、等待开始前**的 `task_id`——二者在崩溃安全场景中不可互相替代（等待可能长达数分钟，进程可能在等待中崩溃）。
>
> **恢复路径**：恢复路径（`task_id=`）同样返回完整的 `ParseResult`，`task_id` 为被恢复任务的 id，`data_id` 取自恢复句柄（AC-5.5）。

### 3.3 接口契约 (API Contracts)

#### 公共 API

```python
def parse(
    uri: str | None = None,
    *,
    task_id: str | None = None,
    model_version: str = "vlm",
    data_id: str | None = None,
    timeout: float | None = None,
    deadline_epoch: float | None = None,
    limits: ExtractionLimits | None = None,
    client: MinerUApiClient | None = None,
    downloader: ResultDownloader | None = None,
    on_update: Callable[[MinerUTaskStatus], None] | None = None,
    on_task_created: Callable[[str], None] | None = None,
    on_error: Callable[[PipelineStage, BaseException], None] | None = None,
    on_metric: MetricHook | None = None,
    correlation_id: str | None = None,
) -> ParseResult: ...
```

> 这是本库**唯一**的顶层函数（AC-2.1 / AC-2.6）。它是同步阻塞调用；异步版本不在本期范围（Non-Goals）。

#### 公共 API 稳定性


| 层级                  | 名称                                                                                                                                                 | 承诺                      |
| :------------------- | :-------------------------------------------------------------------------------------------------------------------------------------------------- | :----------------------- |
| **稳定（唯一函数）**        | `parse`                                                                                                                                            | 遵循 SemVer；大版本才允许破坏性变更   |
| **稳定（类型）**          | `ParseResult`、`ExtractedResult`、`ExtractedImage`、`ExtractionLimits`、`PipelineStage`、`MinerUTaskStatus`、`MetricHook`、`MinerUParserError`            | 跟随 `parse` 的稳定性         |
| **高级 / 测试缝**        | `parse` 的 `client` / `downloader` 参数                                                                                                               | 签名稳定；注入对象的类型契约遵循各自 SPEC |
| **内部 / 不遵循 SemVer** | `mineru_parser.pipeline` 包内名称、三个组件的全部 API（`MinerUApiClient`、`AsyncResult`、`ResultDownloader`、`extract_result`、`canonicalize_member_path`、三族具体异常类等） | 可调整；行为契约由各自 SPEC 约束     |


#### 输入契约 (Input Contract)


| 项    | 约定                                                                                       |
| :---- | :---------------------------------------------------------------------------------------- |
| 目标   | `uri` 与 `task_id` **恰好提供一个**；`uri` 必须是非空白的绝对 http(s) URL（由 client 校验，继承 SPEC-001 AC-2.4） |
| 凭证   | 由 client 从 `MINERU_API_KEY` 读取（继承 SPEC-001 AC-1.2）；管道不接触凭据，也不记录它                         |
| 结果包  | 由服务端返回的 `zip_url` 指向；管道不校验其来源，只依赖 downloader 的 SSRF 防护                                   |
| 前置条件 | 不依赖磁盘、临时文件或除 `MINERU_API_KEY` 外的环境变量                                                     |
| 并发   | `parse()` 可被并发调用；每次调用自建组件（AC-1.6 / AC-3.6）                                               |


#### 返回契约

1. **完整性**：只有四个阶段全部成功才返回；任何失败都不返回部分结果（对齐 SPEC-003 AC-3.10 / AC-4.11）。
2. **形状**：`ParseResult`，恰好 `pages`、`images`、`task_id`、`data_id`、`zip_url` 五个键（AC-1.1）；`pages` / `images` 与 `extract_result` 的返回值逐字相同。
3. **独立性**：全新对象，不与内部流共享生命周期（AC-1.4 / AC-3.4）。
4. **无重试**：管道不重放整链；阶段内部的重试由各组件负责（Non-Goals）。
5. **失败语义**：除超时翻译外，阶段异常原样抛出（AC-6.3）。

#### 所有权契约


| 对象                      | 所有者 | 关闭时机                       |
| :----------------------- | :--- | :-------------------------- |
| 自建的 `MinerUApiClient`   | 管道  | 返回前，`finally` 中            |
| 自建的 `ResultDownloader`  | 管道  | 返回前，`finally` 中（先于 client） |
| 注入的 client / downloader | 调用方 | 管道**不得**关闭（AC-3.2）         |
| 中间 ZIP `io.BytesIO`     | 管道  | 提取结束后立即（成功与失败都关）           |
| 返回的 `ParseResult`       | 调用方 | 由调用方处置                     |


#### 集成示例

```python
from mineru_parser import parse

# 最简形态：一个 URI 进，一个 ParseResult 出
result = parse("https://example.com/paper.pdf")

for page in result["pages"]:
    for block in page:
        print(block.type, block.bbox)
for image in result["images"]:
    print(image["path"], len(image["bytes"]))

# 任务元数据随结果一并返回
print(result["task_id"], result["data_id"])
```

```python
from mineru_parser import parse

# 崩溃安全：先拿到 task_id 落库，再等待；进程重启后接着等
def remember(task_id: str) -> None:
    store_task_id(task_id)          # 必须在 wait 之前持久化

result = parse(
    "https://example.com/paper.pdf",
    data_id="doc-42",
    timeout=600,
    on_task_created=remember,
    on_update=lambda status: print(status.state),
)

# 另一进程里：凭 task_id 恢复等待，不重复提交
result = parse(task_id=load_task_id(), timeout=600)
```

```python
from mineru_parser import parse
from mineru_parser.client import MinerUAuthenticationError, MinerUQuotaError
from mineru_parser.extractor import ResultExtractionLimitError

try:
    result = parse("https://example.com/paper.pdf", timeout=600)
except MinerUQuotaError:
    ...                              # 额度耗尽：可退避后重试
except ResultExtractionLimitError:
    ...                              # 该结果包超出本环境预算：终态，调整 limits
except Exception:
    ...                              # 其余异常按各自类型处理
```

> 上例中具体的阶段异常类**从子模块导入**（顶层不再导出，AC-2.3）；`PipelineTimeoutError` 与 `PipelineConfigurationError` 则从顶层 `mineru_parser` 导入。

### 3.4 编排算法 (Orchestration)

本节描述**控制流契约**：每个阶段做什么、用什么判据、失败时抛出什么。实现方式（函数划分、异常捕获顺序、内部数据结构）由实现者决定。

#### 编排阶段


| #   | 阶段     | 动作                                                                                                 | 失败结果                                                                         | 依据                                         |
| :---: | :------ | :-------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------- | :------------------------------------------ |
| 1   | 参数校验   | 校验 `uri` / `task_id` 互斥与必填、`timeout` / `deadline_epoch` 互斥、回调可调用性、`limits` 类型、`correlation_id` 类型  | `PipelineConfigurationError(field=...)`                                      | AC-4.1 / AC-4.4 / AC-7.4                   |
| 2   | 预算建立   | 由 `timeout` 或 `deadline_epoch` 换算剩余预算；换算后剩余 $\le 0$ 立即失败                                           | `PipelineTimeoutError(stage="submit")`                                       | AC-4.2 / AC-4.3                            |
| 3   | 组件准备   | 自建或校验注入的 client / downloader                                                                       | `PipelineConfigurationError(field="client" / "downloader")`                  | AC-1.3 / AC-3.1 / AC-3.2                   |
| 4   | 提交（可选） | `client.submit(uri, model_version=..., data_id=...)`；成功后调用 `on_task_created(task_id)`              | `MinerUError` 子类原样抛出                                                         | AC-5.1 / AC-6.3                            |
| 5   | 等待     | `client.resume(task_id)` 或复用提交得到的句柄 → `wait(timeout=剩余预算, on_update=...)`                          | `MinerUTimeoutError` → `PipelineTimeoutError(stage="wait")`；其余原样             | AC-4.4 / AC-5.3                            |
| 6   | 下载     | `downloader.resolve(result.zip_url)`                                                               | `ResultDownloadTimeoutError` → `PipelineTimeoutError(stage="download")`；其余原样 | AC-4.5 / AC-6.3                            |
| 7   | 解析     | `extract_result(stream, limits=...)`                                                               | `ResultExtractionError` 子类原样抛出                                               | AC-6.3 / AC-7.3                            |
| 8   | 交付     | 组装 `ParseResult`（`pages` / `images` + `task_id` / `data_id` / `zip_url`）；关闭 ZIP 流；检查预算；关闭自建组件；上报遥测 | `PipelineTimeoutError(stage="extract")`（预算耗尽）                                | AC-1.1 / AC-1.9 / AC-3.3 / AC-4.6 / AC-3.8 |


> **阶段 1 早于阶段 3**：配置错误必须在创建任何组件（尤其是 Session）之前暴露，避免"配置错了却建立了连接池"的副作用。
>
> **阶段 2 早于阶段 4**：预算已耗尽时不得提交任务——否则会产生一个无人等待的孤儿任务。
>
> **阶段 7 之后的关闭在阶段 8**：ZIP 流必须在提取后立即关闭（不再需要），而 client / downloader 的关闭在 `finally` 中执行（覆盖所有失败路径）。

#### 预算检查点


| 检查点 | 位置             | 耗尽时的 `stage` |
| :--- | :-------------- | :------------ |
| 提交前 | 进入 submit 之前   | `submit`     |
| 等待前 | 进入 wait 之前     | `wait`       |
| 下载前 | 进入 download 之前 | `download`   |
| 解析前 | 进入 extract 之前  | `extract`    |
| 解析后 | 提取完成、关闭流之后     | `extract`    |


> 等待阶段**不另设**检查点：剩余预算已作为 `wait(timeout=remaining)` 传入，客户端会在每次查询前与每次 sleep 后自行检查（继承 SPEC-001 AC-4.4）。管道在该阶段只负责把 `MinerUTimeoutError` 翻译为 `PipelineTimeoutError(stage="wait")`。
>
> **检查点语义**：预算耗尽一律**终止**本次调用并抛出 `PipelineTimeoutError`，不得"跳过下载"或"返回部分结果"。

#### 异常处理规则


| 情形                                                 | 处理                                                                                      |
| :-------------------------------------------------- | :--------------------------------------------------------------------------------------- |
| 阶段抛出 `MinerUTimeoutError`                          | 翻译为 `PipelineTimeoutError(stage="wait")`，原异常作为 `__cause__`，复制 `task_id` / `last_status` |
| 阶段抛出 `ResultDownloadTimeoutError`                  | 翻译为 `PipelineTimeoutError(stage="download")`，原异常作为 `__cause__`                          |
| 阶段抛出其他 `MinerUParserError` 子类                      | **原样抛出**（同一对象，AC-6.3）                                                                   |
| 阶段抛出未知异常                                           | **原样抛出**，记录 `outcome="unexpected"`（AC-6.10）                                             |
| `on_task_created` / `on_error` / `on_update` 抛异常   | 吞掉并记录对应 `mineru.pipeline.*.failed` 日志（AC-5.2 / AC-6.5）                                  |
| `on_metric` 抛异常                                    | 吞掉并记录 `mineru.metric.failed`（AC-6.6）                                                    |
| `MemoryError` / `KeyboardInterrupt` / `SystemExit` | 原样抛出，不包装、不吞掉（AC-6.10）                                                                   |


> **翻译的实现约束**：翻译必须用 `raise PipelineTimeoutError(...) from original`，保证 `__cause__` 指向原始超时异常（AC-8.3）；不得用 `from None`（会丢失原始异常，违背 AC-4.4 / AC-4.5 的"保留 `__cause__`"要求）。
>
> **非超时的原样透出约束**：管道捕获阶段异常后，只做"记录归因 + 回调 + 重新抛出"，**不得**重新构造异常对象、不得修改其属性、不得改变其 `__cause__` / `__context__`（AC-6.3）。实现上必须使用裸 `raise`（而非 `raise exc`）以保留 traceback。

#### 遥测与日志


| 类型  | 名称                                       | 标签 / 字段                                                          |
| :--- | :---------------------------------------- | :---------------------------------------------------------------- |
| 日志  | `mineru.pipeline`                        | `duration_ms`、`outcome`、`task_id`、`data_id`、`stage_durations_ms` |
| 日志  | `mineru.pipeline.stage`                  | `stage`、`duration_ms`、`outcome`                                  |
| 日志  | `mineru.pipeline.error`                  | `stage`、`error_type`、`duration_ms`、`outcome`                     |
| 日志  | `mineru.pipeline.on_task_created.failed` | `error_type`                                                     |
| 日志  | `mineru.pipeline.on_error.failed`        | `stage`、`error_type`                                             |
| 指标  | `mineru.pipeline.total`                  | `outcome`、`stage`                                                |
| 指标  | `mineru.pipeline.duration_ms`            | `outcome`                                                        |
| 指标  | `mineru.pipeline.stage.duration_ms`      | `stage`、`outcome`                                                |
| 指标  | `mineru.pipeline.pages`                  | `outcome`                                                        |
| 指标  | `mineru.pipeline.images`                 | `outcome`                                                        |
| 指标  | `mineru.pipeline.image_bytes`            | `outcome`                                                        |


`outcome` 枚举（低基数，禁止自由文本）：


| outcome        | 触发                                   |
| :-------------- | :------------------------------------ |
| `success`      | 四阶段全部成功                              |
| `config_error` | 参数校验失败（`PipelineConfigurationError`） |
| `timeout`      | 端到端预算耗尽（`PipelineTimeoutError`）      |
| `stage_error`  | 阶段失败（非超时）                            |
| `unexpected`   | 未知非 `MinerUParserError` 异常           |


> `mineru.pipeline.total` 的 `stage` 标签在成功时为**最后一个阶段**（`extract`），失败时为**失败发生的阶段**。`stage` 取值封闭于 `PipelineStage`（AC-6.1 / AC-6.9）。
>
> `mineru.pipeline.pages` / `images` / `image_bytes` 在成功时取自提取结果，在失败时为 0（AC-6.7）。
>
> 日志字段中的 `task_id` / `data_id` 属于**日志**（不是指标标签），可用于人工排障；指标标签严禁包含它们（AC-6.9）。

### 3.5 端到端资源预算 (End-to-End Resource Budget)

三个组件的限额各自成立，但**只有编排层能看见它们的和**。一次 `parse()` 的峰值内存近似为：

$$
M_{\text{peak}} \approx \underbrace{\texttt{max\_bytes}}_{\text{压缩侧：ZIP 缓冲}} + \underbrace{\texttt{max\_total\_image\_bytes} + \texttt{max\_manifest\_bytes}\times(1+k_{\text{model}}) + M_{\text{zipinfo}} + M_{\text{result}}}_{\text{解压侧：SPEC-003 §3.2}}
$$

其中 $k_{\text{model}}$ 是 Pydantic 模型相对 JSON 文本的内存放大系数（由 SPEC-003 R-3 标定，当前取 1），$M_{\text{zipinfo}}$ 是中央目录 `ZipInfo` 的常驻开销，$M_{\text{result}}$ 是结果字典自身开销。

> **与 SPEC-003 的差异**：SPEC-003 的推导只覆盖解压侧，得 $M_{\text{peak}} \approx 240\,\text{MiB}$；管道**额外承担压缩侧的 ZIP 缓冲**（默认上限 50 MiB），因为该缓冲在整个提取过程中都驻留（提取器从中读取图片字节）。

代入默认值（压缩侧 50 MiB、解压侧 160 + 32 + 40 + 8 MiB）：

$$
M_{\text{peak}} \approx 50 + 160 + 32 \times 2 + 40 + 8 = 290\,\text{MiB}
$$

部署侧必须满足：

$$
W \times M_{\text{peak}} \le M_{\text{container}}
$$


| 形态                                             | 校验                                                                 |
| :---------------------------------------------- | :------------------------------------------------------------------ |
| $W = 3$、$M_{\text{container}} = 1\,\text{GiB}$ | $3 \times 290 = 870\,\text{MiB} \le 1024\,\text{MiB}$ ✓（默认档位可用）    |
| $W = 4$、$M_{\text{container}} = 1\,\text{GiB}$ | $4 \times 290 = 1160\,\text{MiB} > 1024\,\text{MiB}$ ✗（默认档位**超限**） |


并发 4 时需要的解压侧限额（记 $X = \texttt{max\_total\_image\_bytes}$）：

$$
4 \times (50 + X + 32 + 40 + 8) \le 1024 \quad\Longrightarrow\quad X \le 126\,\text{MiB}
$$

> **结论（必须写入 README）**：默认档位下 `parse()` 单次调用峰值约 **290 MiB**；在 1 GiB 容器中默认并发度**不超过 3**。需要并发 4 时，必须用 `ExtractionLimits(max_total_image_bytes=126 * 1024 * 1024)` 覆盖解压侧上限，或降低并发度。
>
> 本推导随 $k_{\text{model}}$ 变化，标定后必须同步回写本节与 README（承接 SPEC-003 R-3）。

**压缩侧与解压侧不是同一量纲**：下载器的 `max_bytes` 约束**压缩后**字节，提取限额约束**解压后**字节。因此"下载成功但提取被限额拒绝"是**正常可达状态**，不是错误（继承 SPEC-003 §3.2 的说明）。管道不得把这种情况当作失败重试（AC-7.3）。

### 3.6 与既有组件的契约衔接


| 衔接点              | 规则                                                                                       |
| :---------------- | :---------------------------------------------------------------------------------------- |
| `submit` 参数      | `model_version` / `data_id` 原样透传；`uri` 原样透传（校验由 client 负责，继承 SPEC-001 AC-2.4）            |
| `wait` 参数        | `timeout` 传**剩余预算**（不是调用方的原始 `timeout`）；`on_update` 原样透传；`policy` 不暴露（沿用客户端默认）           |
| `resume`         | 恢复路径必须经 `client.resume(task_id, data_id=...)`，产生**零次 POST**（继承 SPEC-001 AC-3.1 / AC-3.4） |
| `resolve`        | `zip_url` 原样传入；管道不预检、不改写、不缓存该 URL                                                        |
| `extract_result` | 流原样传入；`limits` 透传（`None` → 默认）；管道不改变流语义（不关闭、不 seek），关闭由管道在提取后执行                          |
| 异常               | 除超时翻译外，管道**只观察不介入**（AC-6.3）                                                              |
| 遥测               | 管道与三个组件共用同一个 `on_metric` 与 `correlation_id`；各组件按自身 SPEC 上报自身指标，管道只上报自身指标（指标名不冲突）         |


---

## 4. 边界条件与异常处理 (Edge Cases &amp; Error Handling)


| 场景描述                               | 触发条件                              | 预期处理逻辑                                                      | 返回异常 / 表现                                                                   |
| :---------------------------------- | :--------------------------------- | :----------------------------------------------------------- | :--------------------------------------------------------------------------- |
| `uri` 与 `task_id` 都没给              | 调用方遗漏                             | 参数校验阶段拒绝，不创建组件、不发请求                                         | `PipelineConfigurationError(field="uri")`                                   |
| `uri` 与 `task_id` 都给               | 调用方误用                             | 同上                                                          | `PipelineConfigurationError(field="task_id")`                               |
| `timeout` 与 `deadline_epoch` 都给    | 调用方误用                             | 同上                                                          | `PipelineConfigurationError(field="timeout")`                               |
| 预算在提交前已耗尽                          | `timeout=0` 或过期的 `deadline_epoch` | 不提交任务，直接失败（避免孤儿任务）                                          | `PipelineTimeoutError(stage="submit")`                                      |
| 等待阶段超时                             | 服务端长时间不就绪                         | 客户端抛 `MinerUTimeoutError`；翻译并保留 `__cause__` 与 `last_status` | `PipelineTimeoutError(stage="wait")`                                        |
| 下载阶段超时                             | 下载器总预算耗尽                          | 翻译并保留 `__cause__`                                           | `PipelineTimeoutError(stage="download")`                                    |
| 提取阶段超时（预算已耗尽但提取不可中断）               | 提取耗时超过剩余预算                        | 提取完成后检出，丢弃结果                                                | `PipelineTimeoutError(stage="extract")`                                     |
| 下载阶段越过端到端预算                        | 预算不足但 `resolve()` 不接受每调用预算        | 只能在阶段结束后检出（AC-4.7 已知限制）                                     | `PipelineTimeoutError(stage="download")`                                    |
| 提交失败（认证 / 额度 / 服务端错误）              | client 抛错                         | 原样透出，不重试（client 内部已按 SPEC-001 处理）                           | `MinerUAuthenticationError` / `MinerUQuotaError` / `MinerUExecutionError` 等 |
| 任务终态为失败 / 取消                       | 服务端返回 `failed` / `canceled`       | 原样透出                                                        | `MinerUExecutionError`                                                      |
| 下载被 SSRF 防护拒绝                      | `zip_url` 指向内网 / 非 HTTP(S)        | 原样透出，不降级、不重试到不安全路径                                          | `ResultDownloadSecurityError`                                               |
| 结果包超过下载上限                          | 压缩后字节超 `max_bytes`                | 原样透出（终态）                                                    | `ResultDownloadTooLargeError`                                               |
| 结果包解压后超限                           | 图片总量 / manifest 超提取限额             | 原样透出（终态，不重试、不降级）                                            | `ResultExtractionLimitError`                                                |
| 结果包结构异常                            | 无唯一顶层 manifest / Schema 不符        | 原样透出                                                        | `ResultExtractionManifestError` / `ResultExtractionValidationError`         |
| `on_task_created` 抛异常              | 调用方回调有 bug                        | 吞掉并告警，流水线继续                                                 | 记录 `mineru.pipeline.on_task_created.failed`                                 |
| `on_error` 抛异常                     | 调用方回调有 bug                        | 吞掉并告警，原始异常照常抛出                                              | 记录 `mineru.pipeline.on_error.failed`                                        |
| `on_metric` 抛异常                    | 指标后端不可用                           | 吞掉并告警                                                       | 记录 `mineru.metric.failed`                                                   |
| 注入的 client / downloader 类型不对       | 调用方传错对象                           | 参数校验阶段拒绝                                                    | `PipelineConfigurationError(field="client" / "downloader")`                 |
| 注入的 downloader 在下载阶段抛异常            | 替身行为                              | 原样透出；管道**不得**关闭注入的实例                                        | 原异常                                                                         |
| 进程在 submit 成功后崩溃                   | 崩溃                                | `on_task_created` 已把 `task_id` 交出（前提是调用方已持久化）；管道不负责清理孤儿任务   | —                                                                           |
| 同一 URI 重复调用 `parse()`              | 调用方重复请求                           | 创建两个任务（`data_id` 非幂等键）                                      | 两个独立结果或两个独立异常                                                               |
| 提取过程中 `MemoryError`                | 内存不足                              | 原样抛出，不包装                                                    | `MemoryError`                                                               |
| `KeyboardInterrupt` / `SystemExit` | 用户中断                              | 原样抛出；`finally` 仍须关闭已创建的组件与流                                 | 原异常                                                                         |


---

## 5. 任务拆解与实施步骤 (Task Breakdown)

### Phase 1: 契约与骨架

- [ ] 定义 `PipelineStage` 枚举、`PipelineError` / `PipelineConfigurationError` / `PipelineTimeoutError` 异常体系（`mineru_parser/pipeline/errors.py`、`stages.py`）
- [ ] 定义 `ParseResult` 类型（`pages` / `images` + `task_id` / `data_id` / `zip_url`，结构化继承 `ExtractedResult`）并从顶层导出
- [ ] 建立 `mineru_parser/pipeline` 包与 `orchestrator.py` 骨架（阶段状态机 + 生命周期骨架）
- [ ] 实现端到端预算模块（`budget.py`）：`timeout` / `deadline_epoch` 换算、剩余预算计算、检查点
- [ ] 顶层 `__init__.py` 收缩为"一个函数 + 必要类型"（AC-2.1 / AC-2.2 / AC-2.3），同步删除被移除的顶层导出

### Phase 2: 编排实现

- [ ] 实现四阶段编排与阶段归因（`on_error`、阶段日志、阶段耗时）
- [ ] 实现超时翻译（等待 / 下载 → `PipelineTimeoutError`，保留 `__cause__`）
- [ ] 实现所有权与关闭顺序（ZIP 流 → downloader → client），注入实例不关闭
- [ ] 实现 `on_task_created` 与恢复路径（`task_id=` 跳过提交）
- [ ] 实现管道遥测（§3.4 遥测表）与 `correlation_id` 透传

### Phase 3: 测试与验收

- [ ] 覆盖 AC-8.2 的全部路径：四阶段成功、四阶段失败、预算耗尽、超时翻译、回调隔离、生命周期关闭
- [ ] 异常同一性测试（AC-8.3）：断言抛出对象 `is` 阶段抛出对象
- [ ] 顶层 API 面测试（AC-8.4）：唯一可调用对象断言 + 保留 / 移除名单断言
- [ ] 默认构造路径测试（AC-8.5）：本地 mock HTTP 服务 + 注入 downloader
- [ ] 全量回归：`tests/test_client.py` / `test_downloader.py` / `test_extractor.py` / `test_extractor_property.py` 必须全部通过

### Phase 4: 文档与迁移

- [ ] README 重写：快速开始改为 `parse()` 单函数形态；删除三组件的手写编排样板
- [ ] README 补写：顶层 API 面（唯一函数）、迁移表（§1.2）、峰值内存 290 MiB 与并发度指引（§3.5）、超时语义（统一 `PipelineTimeoutError`，含"统一捕获超时"的三类写法）、任务恢复用法
- [ ] README 补写：`ParseResult` 的五个键与元数据来源；`zip_url` 作为敏感值的处理提示
- [ ] README 补写风险提示：`data_id` 非幂等键、默认无端到端超时、`on_task_created` 持久化建议
- [ ] 本 Spec 的 changelog 记录破坏性变更（已随初稿创建）；`docs/specs/CLAUDE.md` 若后续新增"组件清单"章节，须把 SPEC-004 补入
- [ ] 各组件 SPEC（001 / 002 / 003）的"由顶层导出"表述同步回写为"内部 / 高级"

### AC ↔ 测试映射（计划）


| AC                       | 计划测试名（`tests/test_pipeline.py`）                                     |
| :------------------------ | :------------------------------------------------------------------- |
| AC-1.1                   | `test_parse_returns_parse_result_shape`                             |
| AC-1.2                   | `test_stage_order_and_early_abort`                                  |
| AC-1.3 / AC-1.6          | `test_components_built_internally_and_isolated_per_call`            |
| AC-1.4                   | `test_results_are_fresh_objects`                                    |
| AC-1.5                   | `test_success_metrics_reported`                                     |
| AC-1.7                   | `test_component_contracts_unchanged`（委托给三组件既有测试）                    |
| AC-1.8                   | `test_no_retained_references`                                       |
| AC-1.9                   | `test_parse_result_metadata_provenance`                             |
| AC-1.10                  | `test_zip_url_never_logged_or_labelled`                             |
| AC-2.1 / AC-2.2 / AC-2.3 | `test_top_level_exports_exactly_one_callable`                       |
| AC-2.4                   | （文档项，由 README / changelog 评审核对）                                     |
| AC-2.5                   | `test_parse_signature_is_stable`（签名快照）                              |
| AC-2.6                   | `test_top_level_has_no_second_function`                             |
| AC-2.7 / AC-2.8          | `test_orchestration_lives_in_pipeline_package`                      |
| AC-3.1 / AC-3.8          | `test_owned_components_closed_in_order`                             |
| AC-3.2                   | `test_injected_components_not_closed`                               |
| AC-3.3 / AC-3.4          | `test_zip_stream_closed_and_result_independent`                     |
| AC-3.5                   | `test_no_retained_references`                                       |
| AC-3.6                   | `test_components_built_internally_and_isolated_per_call`            |
| AC-3.7                   | `test_caller_owned_objects_untouched`                               |
| AC-4.1                   | `test_mutually_exclusive_parameters_rejected_before_network`        |
| AC-4.2 / AC-4.3          | `test_budget_exhausted_at_each_boundary`                            |
| AC-4.4                   | `test_wait_timeout_translated_with_cause`                           |
| AC-4.5                   | `test_download_timeout_translated_with_cause`                       |
| AC-4.6                   | `test_extract_overrun_detected_after_extract`                       |
| AC-4.7                   | `test_download_overrun_documented_behaviour`                        |
| AC-4.8                   | `test_no_default_timeout_means_unbounded_wait`                      |
| AC-4.9                   | `test_budget_uses_injected_monotonic_clock`                         |
| AC-5.1 / AC-5.2          | `test_on_task_created_called_and_isolated`                          |
| AC-5.3                   | `test_resume_path_issues_no_post`                                   |
| AC-5.4                   | `test_uri_and_task_id_exclusivity`                                  |
| AC-5.5                   | `test_resume_passes_data_id`                                        |
| AC-5.6                   | `test_duplicate_calls_create_two_tasks`                             |
| AC-5.8                   | `test_resume_path_has_no_submit_stage`                              |
| AC-6.1                   | `test_pipeline_stage_enum_is_closed`                                |
| AC-6.2 / AC-6.3 / AC-8.3 | `test_stage_error_propagates_unchanged`                             |
| AC-6.4                   | `test_pipeline_error_hierarchy`                                     |
| AC-6.5                   | `test_on_error_isolated`                                            |
| AC-6.6                   | `test_on_metric_isolated`                                           |
| AC-6.7                   | `test_metrics_reported_exactly_once`                                |
| AC-6.8                   | `test_correlation_id_propagated_to_components`                      |
| AC-6.9                   | `test_metric_labels_are_closed_enums`                               |
| AC-6.10                  | `test_unknown_exception_propagates`                                 |
| AC-6.11 / AC-6.12        | `test_pipeline_logs_and_stage_durations`                            |
| AC-7.1 / AC-7.2          | `test_budget_formula_documented`（文档项）+ `test_peak_budget_constants` |
| AC-7.3                   | `test_extraction_limit_is_terminal`                                 |
| AC-7.4                   | `test_invalid_limits_rejected_before_stages`                        |
| AC-7.5                   | `test_no_caching_or_disk_writes`                                    |
| AC-7.6                   | `test_memory_error_propagates`                                      |
| AC-8.1 / AC-8.5          | `test_default_path_with_local_mock_server`                          |
| AC-8.6                   | `test_no_network_access`（断网断言）                                      |
| AC-8.7                   | `test_no_module_level_mutable_state`                                |


---

## 6. 风险与待决事项 (Risks &amp; Open Questions)

### 6.1 风险评估表 (Risk Register)


| 编号       | 风险 / 问题描述                              | 潜在影响                                                              | 缓解 / 规避方案                                                                                            | 状态 / 负责人       |
| :-------- | :-------------------------------------- | :----------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------- | :-------------- |
| `[R-1]`  | **顶层 API 收缩是破坏性变更**                    | 既有用户 `from mineru_parser import ResultDownloader` 直接报 ImportError | 顶层 `__all__` 只保留 `parse` + 类型；组件 API 保留在子模块且**行为不变**；README 迁移表 + changelog 登记；项目未到 1.0，一次性收敛优于分阶段弃用 | 待评审 / @jackafx |
| `[R-2]`  | **注入参数削弱"唯一入口"的简洁性**                   | 用户可能绕过 `parse` 直接用组件，门面价值下降                                       | 注入参数明确标注为"高级 / 测试缝"且组件类不在顶层导出；README 主线只讲 `parse`                                                    | 待评审 / @jackafx |
| `[R-3]`  | **重复调用即重复计费**                          | 同一 URI 重复 `parse()` 产生多个任务与费用                                     | `data_id` 非幂等键的事实必须在 README 显式提示；`on_task_created` 供调用方自行去重；本期不实现幂等（Non-Goals）                       | 待处理 / @jackafx |
| `[R-4]`  | **超时语义翻译造成捕获方式变化**                     | `except MinerUTimeoutError` 不再捕获 `parse()` 的等待超时                  | 统一为 `PipelineTimeoutError` 并在 README 明示；`__cause__` 保留原始异常，需要时可从 `__cause__` 细分                      | 待评审 / @jackafx |
| `[R-5]`  | **端到端预算无法中断下载**                        | 下载阶段可能越过预算，浪费一次下载                                                 | 文档化已知限制（AC-4.7）；下载器自带 `total_timeout` 作为内层上界；后续可评估给 `resolve` 增加每调用预算                                | 待评估 / @jackafx |
| `[R-6]`  | **峰值内存数字是推导值而非实测值**                    | 部署时按 290 MiB 配置仍可能 OOM                                            | §3.5 公式与假设全部公开；README 给出并发度指引；真实并发峰值需在目标环境用 `tracemalloc` 标定（承接 SPEC-003 R-3）                        | 待标定 / @jackafx |
| `[R-7]`  | **`on_task_created` 抛异常被吞掉**           | 调用方误以为 `task_id` 已持久化                                             | 吞掉并记录 `mineru.pipeline.on_task_created.failed` 告警日志；回调契约在 README 中写明"持久化失败必须自行处理"                    | 待处理 / @jackafx |
| `[R-8]`  | **阶段归因依赖调用方提供 `on_error`**             | 不提供回调时，失败阶段只能从日志 / 指标中读                                           | 阶段信息同时进入 `mineru.pipeline.error` 日志与 `mineru.pipeline.total{stage}` 指标，标签低基数可直接聚合                    | 已缓解 / @jackafx |
| `[R-9]`  | **管道层引入新的失败模式**（预算、翻译、回调）              | 故障面变多，排查成本上升                                                      | 管道自身失败只有两类（配置 / 超时），且均在**任何网络副作用之前**或**超时翻译**中产生；组件异常零改写（AC-6.3）                                     | 已缓解 / @jackafx |
| `[R-10]` | **组件 API 失去顶层导出后，组件的可发现性下降**           | 用户难以发现"还能直接用组件"                                                   | README 的"核心模块"章节保留三组件说明并标注"内部 / 高级"，指向子模块导入路径                                                        | 待处理 / @jackafx |
| `[R-11]` | **`parse()` 每次调用自建 Session，跨调用无连接池复用** | 高频小任务场景下 TLS 握手开销显著                                               | 记录为已知代价；高频场景可注入自持 Session 的 client / downloader；本期不引入全局会话缓存（Non-Goals）                               | 待评估 / @jackafx |
| `[R-12]` | **管道不改变组件契约，但组合效应未被契约测试覆盖**            | 三者组合后的边界（如"下载成功但提取超限"）可能在生产首次暴露                                   | 契约测试覆盖组合路径（§5 AC 映射）；边界表逐条列出组合场景（§4）                                                                 | 待处理 / @jackafx |


### 6.2 待决事项 (Open Questions)

> **已闭环（划线/归档）：**
>
> - [x] ~~`Q-0`：顶层 API 面如何收敛？~~ → **决策**：顶层只保留 `parse` 一个函数 + 签名/返回值所需的类型；组件 API 降级为子模块导入的"内部 / 高级"层，不遵循 SemVer（见 §1.2 与 AC-2.1 \~ AC-2.8）。
> - [x] ~~`Q-1`：端到端预算由谁负责？~~ → **决策**：由管道提供单一 `timeout` / `deadline_epoch`，覆盖四个阶段；等待阶段把剩余预算下传给 client（AC-4.2 / AC-4.4）。
> - [x] ~~`Q-2`：超时异常是否统一？~~ → **决策**：统一为 `PipelineTimeoutError(stage=...)`，其余阶段异常原样透传（AC-4.4 / AC-4.5 / AC-6.3）。
> - [x] ~~`Q-3`：`PipelineTimeoutError` 是否**同时**继承 `MinerUTimeoutError`？~~ → **决策**：**保持独立**——只继承 `PipelineError`，四个异常家族继续互不继承（AC-6.4）。代价是"统一捕获超时"需显式列出三个超时类型，README 必须给出该写法。
> - [x] ~~`Q-4`：是否提供 `on_stage`（阶段进入 / 退出）回调？~~ → **决策**：**不提供**。阶段信息只经 `on_error` 回调、日志与指标暴露（AC-6.1 / AC-6.2 / AC-6.11），保持回调面最小。
> - [x] ~~`Q-5`：结果元数据（`task_id` / `data_id` / `zip_url`）如何交付？~~ → **决策**：新增管道层类型 **`ParseResult`**（`pages` / `images` + `task_id` / `data_id` / `zip_url`），由 `parse()` 返回；`ExtractedResult` 的既有契约**不变**（AC-1.1 / AC-1.9 / AC-1.10）。
> - [x] ~~`Q-6`：是否提供"只提交不解析"的入口（`parse(submit_only=True)`）？~~ → **决策**：**不提供**，保持入口简洁；批量作业由调用方直接使用 `mineru_parser.client`（Non-Goals）。
> - [x] ~~`Q-7`：是否提供结果包的断点续传 / 本地缓存？~~ → **决策**：**不提供**——结果包体积有限，重新下载的成本可接受（Non-Goals）。
> - [x] ~~`Q-10`：`mineru_parser.pipeline` 是否作为**公开**子包（允许第三方扩展阶段）？~~ → **决策**：**不公开**，管道实现保持内部；第三方插入阶段不在本期范围（AC-2.8 / Non-Goals）。

#### 1. 核心架构与契约 (Architecture &amp; Contract)

#### 1. 核心架构与契约 (Architecture &amp; Contract)

- [ ] **`Q-12`**：`ParseResult` 是否应再携带运行期字段（如 `duration_ms` / `state` / `page_count`）？
  - **现状 / 影响**：当前 `ParseResult` 只含解析产物与三项任务元数据。耗时已进日志与指标；`state` 恒为 `succeeded`（失败时抛异常），`page_count` 可由 `len(result["pages"])` 导出。
  - **备选方案**：**方案 A**：维持现状（元数据够用，其余可导出）；**方案 B**：加 `duration_ms`，代价是结果类型开始承载运行期观测数据，与"结果 = 数据"的定位有张力。
  - **跟进人 / 期限**：@jackafx / 评审时

#### 2. 业务边界与扩展性 (Scope &amp; Extensibility)

- [ ] **`Q-8`**：`data_id` 的幂等语义是否需要在管道层补齐（例如同 `data_id` 复用已有任务）？
  - **结论**：暂不纳入；服务端未提供该能力，管道不得伪造幂等（R-3）。

#### 3. 性能与解耦 (Performance &amp; Modularization)

- [ ] **`Q-9`**：是否引入跨调用的 Session 复用缓存（`parse()` 默认复用进程内 Session）？
  - **现状 / 影响**：当前每次调用自建两个 Session，跨调用无连接池复用（R-11）；复用会引入全局可变状态，与 AC-8.7 的"无模块级可变状态"冲突。
  - **备选方案**：**方案 A**：维持现状；**方案 B**：提供显式的 `SessionPool` 对象由调用方持有并注入 client / downloader。
  - **跟进人 / 期限**：@jackafx / 评审时

- [ ] **`Q-11`**：峰值内存 290 MiB 是否需要在实现阶段用 `tracemalloc` 实测校正？
  - **结论**：需要——实现阶段补一条内存测量测试，把实测值回写 §3.5 与 README（与 SPEC-003 R-3 的标定合并进行）。