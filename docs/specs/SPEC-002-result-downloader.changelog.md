# Changelog: SPEC-002 ResultDownloader

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
