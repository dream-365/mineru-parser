# Changelog: SPEC-003 Result Extractor

## [2026-10-21] - 输入契约标准化，解除与上游下载组件的耦合

- **修改类型**: Changed
- **影响范围**: AC-1.1、§1.4 Non-Goals、§1.5 威胁模型、US-1、US-7、§3.1 依赖说明、§3.2 限额说明、§3.3 接口契约（新增「输入契约」小节并重写集成示例）、§4 边界表、R-2、Q-0、Q-5
- **变更原因**: 组件不应绑定特定的上游交付方式——只要调用方能提供符合约定的 ZIP 字节流即可使用。改用「标准契约」定义输入面，可让任意来源（上游交付、缓存命中、本地文件、测试夹具）复用同一入口，且契约条款与测试不依赖任何外部服务。
- **具体内容**:
  - §3.3 新增「输入契约 (Input Contract)」小节：介质（任意可读、可 seek 的二进制流，典型为 `io.BytesIO`）、内容（标准 ZIP 归档，合规性由调用方保证，不合规以 `invalid_zip` 失败关闭）、来源（不受限于任何特定上游）、所有权（调用方持有并负责关闭）、前置条件（不依赖网络、磁盘、环境变量或全局状态）。
  - AC-1.1 明确「输入字节的来源不受限，Extractor 不感知来源，也不参与下载或重试」。
  - 除 §1.1 背景外，全文移除对上游下载组件的指名引用：US-1 改为「任意来源的 ZIP 内存流」；集成示例改为 `io.BytesIO(zip_bytes)`；威胁模型输入来源改为「上游交付或调用方从其他途径获得的 ZIP」；§1.4 Non-Goals、§3.1 依赖说明、§3.2 限额说明、§4 空流场景、R-2、Q-0、Q-5 一并改为来源无关表述。
  - US-7 的 So that 改为「CI 不需要网络、磁盘或任何外部服务凭据」。
- **说明**: §1.1 背景保留上游链路描述，用于说明组件的来源动机；契约、需求与测试条款不再依赖该上下文。异常体系条款（AC-6.1）仍指名 `MinerUError` / `ResultDownloadError`，因其断言的是「与本库其他组件的异常基类互不继承」这一可验证约束，与输入来源无关。
- **状态**: Draft。

## [2026-10-21] - manifest 定位范围收敛到 ZIP 顶层目录

- **修改类型**: Changed
- **影响范围**: Goal 2、Goal 4、1.1 背景、1.3 Non-Goals、1.5 威胁模型、US-2（AC-2.1 / AC-2.3 / AC-2.8）、US-4（AC-4.1 / AC-4.3 / AC-4.6）、AC-5.5、3.1 时序图、3.2 输出结构、3.3 集成示例、3.5 Manifest 发现 / 图片根目录 / 图片收集、3.6 校验流水线、第 4 节边界表、第 5 节任务拆解与测试映射、R-5、Q-4、Q-16
- **变更原因**: 真实样本基线显示 MinerU 结果包恒为「顶层 manifest + 顶层 `images/`」布局；任意深度定位会把子目录残留（上游中间产物、其他文档的副本）纳入候选，既引入误命中风险，也让图片根目录推导出现分支。把搜索范围收敛到 ZIP 顶层后，定位规则唯一、可静态推理，且布局漂移表现为显式失败而非静默读到错误内容。
- **具体内容**:
  - Goal 2 改为「只在 ZIP 顶层目录定位唯一的 `*_content_list_v2.json`」；搜索范围由**原始成员名**判定（不含 `/` 的成员才算顶层成员），canonical 化之后不再存在层级分支。
  - 子目录 manifest（`result/foo_content_list_v2.json`）、带目录前缀的 manifest（`./foo_content_list_v2.json`）、macOS 资源分叉（`__MACOSX/._foo_content_list_v2.json`）与绝对路径成员一律不参与定位，也不计入 `ambiguous` 候选；顶层不存在同名 manifest 时报 `not_found` 失败关闭，不回退到子目录。
  - 顶层候选的名称安全校验保留：反斜杠、NUL/C0/C1 控制字符或非常规文件仍失败关闭 `unsafe_member`。
  - Goal 4 与图片根目录改为恒定的顶层 `images/`；「与 manifest 同级」在顶层限定下等价于「顶层」。子目录 `images/`（如 `result/images/`）一律忽略，不合并、不回退。`images[].path` 恒为 `images/...` 形式。
  - `_discover_manifest` 增加顶层范围短路；`_collect_images` 移除 `manifest_path` 参数与同级推导，`image_root` 固定为 `images/`；移除已不可达的「manifest 位于图片根下需排除」分支。
  - Q-16 关闭（该布局不再可达）；Q-4 决策改为「按顶层 `images/`」；R-5 缓解措施改为「监控 `outcome=manifest_error` 与 `outcome=success` 但 `images=0` 的比例」。
  - 边界表与测试映射同步更新：新增「manifest 位于子目录」「manifest 名称含目录前缀」「子目录 images 目录」等场景，`test_manifest_discovery_nested` 改为 `test_manifest_nested_not_found`，`test_images_adjacent_to_manifest` / `test_root_images_ignored_for_nested_manifest` 改为 `test_images_at_archive_root` / `test_nested_images_ignored`。
- **说明**: 布局漂移（manifest 或 `images/` 下移）现在表现为 `not_found` 硬失败或 `images=[]`，不会读到错误内容；真实样本统计与限额校准仍见 R-1。
- **状态**: Draft。

## [2026-10-21] - 初始设计

- **修改类型**: Added
- **影响范围**: 全文（1.1 ~ 6.2）
- **变更原因**: `SPEC-002` 将结果包交付到 `io.BytesIO` 为止，下游仍需各自实现 manifest 定位、`content_v2` Schema 校验、图片收集与解压后限额。本 Spec 以无状态函数 `extract_result(stream)` 承接「ZIP 内存流 → `{pages, images}`」职责，不改变下载器与客户端的契约。
- **具体内容**:
  - 新增 `docs/specs/SPEC-003-result-extractor.md`，状态标记为 `Draft`。
  - 定义公共 API：`extract_result(stream, *, limits=None, on_metric=None, correlation_id=None) -> ExtractedResult`；输出为普通 `dict`，包含 `pages`（`DocumentSchema`）与 `images`（`path` + `bytes` 列表）。
  - 定义 `ExtractionLimits` 与 `DEFAULT_EXTRACTION_LIMITS`：manifest 16 MiB、单图 32 MiB、图片总量 256 MiB、图片数量 10,000、ZIP 成员数量 100,000；全部为正整数，不允许无上限模式。
  - 定义 manifest 发现规则：任意深度的唯一 `*_content_list_v2.json`；零份 `not_found`、多份 `ambiguous`；候选必须为常规文件且路径安全。
  - 定义 Schema 校验：模块级 `TypeAdapter(DocumentSchema)`、UTF-8 + 可选 BOM、`json_invalid` / `RecursionError` 分类、Pydantic 错误清洗（仅 `loc` / `type` / `msg`，最多 20 条）。
  - 定义图片提取：manifest 同级 `images/`、递归收集常规文件、canonical path、去重、字典序排序、零字节文件保留、缺失目录返回 `[]`。
  - 定义资源安全：所有成员有界读取（`open(info)` + `read(limit + 1)`）、声明大小与实际字节双检、不落盘、不读取无关成员。
  - 定义异常体系：配置、归档、manifest、Schema、限额五类，均继承 `ResultExtractionError`，独立于 `MinerUError` / `ResultDownloadError`。
  - 定义生命周期：调用方流不关闭、成功/失败恢复游标、恢复失败仅告警。
  - 定义遥测：`mineru.extract` / `mineru.extract.error` 日志与五个指标，`outcome` 枚举，指标回调异常隔离。
  - 明确 Non-Goals：下载/重试、落盘解压、v1/middle/model 格式、图片解码、引用交叉校验、流式解析、批量、类门面。
  - 补充风险登记表（限额校准、压缩炸弹、Pydantic 内存放大、Schema 漂移、目录布局、成员名编码等）与 Q-0 ~ Q-18 待决事项。
- **说明**: 本期假设调用方已通过上游组件或可信渠道获得 ZIP；ZIP 内容仍按不可信数据处理。已用一个最小真实样本核对「根目录 manifest + 根 `images/`」布局，并通过 `TypeAdapter(DocumentSchema)` 校验（1 页、6 个块、1 张图片）；默认限额仍需更多真实样本校准，布局与 Schema 漂移通过契约测试与遥测监控。
- **状态**: Draft。
