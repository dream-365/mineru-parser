# Changelog: SPEC-003 Result Extractor

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
- **说明**: 本期假设调用方已通过 `ResultDownloader` 或可信渠道获得 ZIP；ZIP 内容仍按不可信数据处理。已用一个最小真实样本核对「根目录 manifest + 根 `images/`」布局，并通过 `TypeAdapter(DocumentSchema)` 校验（1 页、6 个块、1 张图片）；默认限额仍需更多真实样本校准，布局与 Schema 漂移通过契约测试与遥测监控。
- **状态**: Draft。
