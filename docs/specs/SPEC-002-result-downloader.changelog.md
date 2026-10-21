# Changelog: SPEC-002 ResultDownloader

## [2026-10-21] - 随 SPEC-004 同步导出路径：组件转为私有实现

- **修改类型**: Changed
- **影响范围**: §3.3 公共 API 稳定性说明、§5 任务拆解中的导出条目
- **变更原因**: SPEC-004 将 client / downloader / extractor 三个组件包私有化（`mineru_parser._downloader`），公开路径 `mineru_parser.downloader` 与顶层 `mineru_parser.__all__` 不再提供组件 API（SPEC-004 AC-2.3）。本 Spec 中"必须从顶层导出"的表述若不同步，将形成无法满足的断言。
- **具体内容**: 把"通过 `mineru_parser.downloader.__all__` 与顶层 `mineru_parser.__all__` 导出"改为"通过私有实现包 `mineru_parser._downloader.__all__` 导出，不再由顶层导出"；任务拆解中的导出路径同步改名。下载器的行为契约、异常层次、限额与判定规则均未改动。
- **说明**: 纯文档对齐，无契约语义变化。
- **状态**: In Review。

## [2026-10-21] - 引入库级公共根异常 `MinerUParserError`，并指向 SPEC-003

- **修改类型**: Changed / Added
- **影响范围**: 1.4 非目标、US-8（新增 AC-8.10）、3.1 包结构、3.2 异常体系、3.3 公共 API 稳定性、6.2 待决事项 Q-0 / Q-10
- **变更原因**: SPEC-003（Result Extractor）落地后，库内出现第三条失败路径。三条路径需要能"一网打尽"地统一捕获，但必须保持互不继承——下载失败可重试，解析失败是终态，不能被同一个 `except` 混为一谈。本 Spec 此前已在 3.2 与 Q-10 中预告过该共享根的设计，本次正式落地。
- **具体内容**:
  - 新增库级公共根异常 `MinerUParserError`（定义于 `mineru_parser/errors.py`，由 `mineru_parser` 顶层导出），直接继承 `Exception`；`ResultDownloadError` 改为**同时**继承它，既有子类层次（`ResultDownloadConfigurationError` / `ResultDownloadSecurityError` / `ResultDownloadTooLargeError` / `ResultDownloadContentTypeError` / `ResultDownloadHTTPError` / `ResultDownloadTransientError` / `ResultDownloadTimeoutError`）完全不变。
  - 3.2 异常体系图更新为 `MinerUParserError → ResultDownloadError → ...`，并改写原"本期不引入库级共享错误根"的说明：共享根已引入，但 `ResultDownloadError` 与 `MinerUError`、`ResultExtractionError` **互不继承**。
  - 3.1 包结构新增 `errors.py`（库级根异常）；3.3 公共 API 稳定性表的"稳定"层加入 `MinerUParserError`。
  - 新增 AC-8.10：继承关系与互不继承约束必须由 `issubclass` 断言覆盖。
  - Q-10 结论更新为"已引入"，并补记引入时机与理由（成本随组件数量线性增长，趁组件最少时落地最优）。
  - Q-0 与 1.4 非目标补充落地指向：解压与内容解析由 **SPEC-003** 承担，下载器交付边界止于 `io.BytesIO`。
  - §5 新增 **Phase 5**（库级公共根异常的代码落地：`ResultDownloadError` 继承调整、顶层导出、模块说明更新、继承断言测试、全量回归）与 **Phase 6**（§3.4 / §3.6 实现伪码收敛为契约条款，落实 `docs/specs/CLAUDE.md` §1.6「除契约和示例外，SPEC 中不允许出现具体代码实现」）；AC-8.10 同步补入 AC 与测试映射表。
- **说明**: 属**纯加性**变更——既有 `except ResultDownloadError` 的捕获语义完全不变。下载器的重试、SSRF、超时等既有契约未发生其他变化。
- **代码落地**: 继承调整随 SPEC-003 的 Phase 0 一并实现。在此之前 `ResultDownloadError` 仍直接继承 `Exception`；两种状态的捕获行为无差异，仅 AC-8.10 的 `issubclass` 断言需等到 Phase 0 落地后才成立。
- **状态**: In Review。

## [2026-10-21] - 代码评审修复（超时 / 异常链 / 校验边界）

- **修改类型**: Fixed
- **影响范围**: AC-2.3、AC-3.7、AC-3.8、AC-4.11、5.1、6.1
- **变更原因**: 代码评审复现了慢速滴流响应绕过总预算、body 阶段读取超时被误分类、超时异常链泄漏签名 URL、IPv6 过渡网段判断失效等问题。`iter_content` 会缓冲到 `chunk_size` 才返回，无法在分块间执行 deadline 检查。
- **具体内容**:
  - AC-2.3：响应体读取改为优先 `raw.read1(chunk_size, decode_content=True)`，无 `raw.read1` 时回退 `iter_content`；AC-3.7 / 3.8 的缓冲与字节计数描述同步为读取层语义。
  - AC-4.11：明确 `raw.read1` 直接抛出的 urllib3 传输异常按瞬态错误处理。
  - 超时：阻塞的 `session.get` 返回后、空响应返回前、body 读取结束后均检查 deadline；body 阶段的 `ReadTimeoutError`（含 requests 包装为 `ConnectionError` 的情形）归类为 `ResultDownloadTimeoutError`；超时异常不再通过 `__context__` 链持有原始 requests 异常。
  - 安全：修复 IPv6 过渡网段（NAT64 / 6to4 / Teredo）的成员判断；拒绝注入 Session 的 bytes 形式敏感头；`redact_url` 剔除 C0/C1 控制字符。
  - 健壮性：`Retry-After` 极端日期、超大整数配置、退避指数与 `random_fn` 返回值不再以 `OverflowError` 逃逸；DNS resolver 自身抛出的 `TypeError` 按未知异常传播。
  - 依赖：`idna` 下限提升到 `>=3.7`（CVE-2024-3651）。
- **状态**: In Review。

## [2026-10-21] - 架构评审修订（P0 / P1）

- **修改类型**: Changed / Fixed
- **影响范围**: 1.1、1.2、1.4、1.5（新增）、AC-1.2 / 1.5 / 1.6 / 1.7 / 1.10 / 1.11、AC-2.6、AC-3.7 / 3.8 / 3.10、AC-4.9 / 4.11 / 4.12、AC-5.3 / 5.4、AC-6.1 ~ 6.13、AC-7.4、AC-8.4 / 8.8 / 8.9、AC-9.1 / 9.2 / 9.4 / 9.6、3.1、3.2、3.3、3.4、3.5、3.6、3.7、3.8、4、5、6
- **变更原因**: 架构评审发现 SSRF 判据不足、DNS 重试时序矛盾、内部异常逃逸、注入 Session 敏感头泄漏、异常链泄漏签名 URL、IDNA 规范化缺失等问题；同时存在超时语义自相矛盾、构造器 API 面积过大、指标收口不明确等设计问题。
- **具体内容**:
  - 新增 1.5 威胁模型，明确 URL 不可信、代理与注入 Session 的安全前提。
  - SSRF：用 3.6 的 `_is_public_ip` 取代单纯 `is_global`，拒绝多播、site-local、NAT64、6to4、Teredo 等；新增 IDNA UTS46 主机规范化，要求校验、DNS、请求 URL 使用同一 canonical host。
  - DNS：拆分 `validate_url_syntax` 与 `validate_target`；初始 URL 的 DNS 失败也进入重试；DNS 缓存限制在单次 attempt。
  - 异常：`_IncompleteBody` 必须继承 `_Retryable`；公共消息与 `last_error` 脱敏；禁止原始异常链泄漏签名 URL。
  - Session：新增 AC-8.8，禁止注入 Session 携带敏感全局头 / `session.auth`；AC-6.9 限定为下载器传入的头。
  - 超时：删除“截断 sleep”的矛盾表述；等待时间超过预算时立即抛 `TimeoutError` 并携带状态码 / `Retry-After`。
  - 遥测：`finally` 中恰好上报一次；新增 `outcome` 枚举与指标类型 / 单位。
  - API：补充公共 API 稳定性分层、callable / `bool` / header token 校验、版本号来源。
  - 待决事项：关闭 Q-1 / Q-2 / Q-8 / Q-9，新增 Q-10 / Q-11 / Q-12 并给出结论。
  - 测试：补充 IP 分类、IDNA、控制字符、Session 泄漏、异常脱敏、`finally` 指标、内存上界等映射。
- **状态**: Draft → In Review。

## [2026-10-21] - 初始设计

- **修改类型**: Added
- **影响范围**: 全文（1.1 ~ 6.2）
- **变更原因**: `SPEC-001` 将结果包下载列为 `MinerUApiClient` 的 Non-Goal，但下游仍需要一个可复用、内存安全、可测试的下载组件。本 Spec 以独立 `ResultDownloader` 承接「网络 URL → `io.BytesIO`」职责，不改变客户端契约。
- **具体内容**:
  - 新增 `docs/specs/SPEC-002-result-downloader.md`，状态标记为 `Draft`。
  - 定义公共 API：`resolve(url) -> io.BytesIO`、`close()`、上下文管理器，以及只读属性 `max_bytes` / `retry_policy`。
  - 定义构造参数：`max_bytes`、`chunk_size`、`request_timeout`、`total_timeout`、`DownloadRetryPolicy`、`allowed_content_types`、`allowed_hosts`、`allow_private_hosts`、`allow_https_downgrade`、`max_redirects`、`headers`、`Session` 与可注入的时钟 / DNS / 随机源 / 指标钩子。
  - 定义 9 组用户故事与 AC-1.1 ~ AC-9.6，覆盖配置、流式读取、内存上限、重试、超时、SSRF、重定向、Content-Type、生命周期与遥测。
  - 固化下载算法：先校验后请求、逐跳重定向复验、`Content-Length` 预检 + 流式累加、`BytesIO` 游标归零、失败不返回部分数据。
  - 固化重试与超时：指数退避 + 抖动、`Retry-After` 优先与截断、单调时钟总预算、sleep 截断与立即超时。
  - 定义异常体系：配置、安全、超限、内容类型、HTTP、瞬态与超时。
  - 明确 Non-Goals：解压、校验、落盘、Range、缓存、主动限流、中间件、异步 / 并发、DNS Pin 的完全消除。
  - 补充风险登记表（DNS Rebinding、签名 URL 过期、内存放大、压缩炸弹、代理解析差异等）与 9 项待决事项。
- **说明**: 本期假设调用方受信任、URL 可能来自外部输入、单次结果包默认不超过 50 MiB、并发度中低；高并发与大文件场景留待后续评估。
