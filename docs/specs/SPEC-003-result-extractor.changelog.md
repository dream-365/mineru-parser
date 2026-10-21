# Changelog: SPEC-003 Result Extractor

## [2026-10-21] - 随 SPEC-004 同步导出路径：组件转为私有实现

- **修改类型**: Changed
- **影响范围**: AC-1.8、§3.3 公共名称导出说明、§5 任务拆解中的导出条目
- **变更原因**: SPEC-004 将提取器包私有化为 `mineru_parser._extractor`，公开路径 `mineru_parser.extractor` 与顶层 `mineru_parser.__all__` 不再提供组件 API（SPEC-004 AC-2.3）。AC-1.8 原文要求"可从 `mineru_parser.extractor` 与顶层 `mineru_parser` 导入"，在 SPEC-004 落地后不可满足。
- **具体内容**: AC-1.8 改为"必须可从私有实现包 `mineru_parser._extractor` 导入"；顶层只保留 `parse` 签名 / 返回值所需的 `ExtractedResult` / `ExtractedImage` / `ExtractionLimits`（SPEC-004 AC-2.2）。导出说明与任务拆解路径同步改名。提取器的行为契约、异常体系、限额与判定规则均未改动。
- **说明**: 纯文档对齐，无契约语义变化。
- **状态**: Approved。

## [2026-10-21] - 实现完成：任务拆解勾选、AC↔测试映射回填、状态推进为 Approved

- **修改类型**: Changed
- **影响范围**: Header（状态）、§1.3 目标（Goal 1 ~ 12）、§5 任务拆解（Phase 0 ~ 6 全部复选框、AC↔测试映射表）
- **变更原因**: 实现已随 `feat(extractor)` 提交落地（提交 `d03184f`），`tests/test_extractor.py` + `tests/test_extractor_property.py` 共 123 个测试全部通过，但 §5 的任务复选框与 AC↔测试映射表仍停留在计划态（"当前 Spec 为 Draft，以下为计划测试名"），Header 状态也未随实现推进。
- **具体内容**:
  - **Goal 与 Phase 勾选**：§1.3 的 Goal 1 ~ 12 全部勾选；§5 Phase 0（库级根异常）、Phase 1（公共契约）、Phase 2（ZIP 与 Manifest 发现）、Phase 3（JSON 与 Schema 校验）、Phase 4（图片提取）、Phase 5（生命周期/遥测/测试）、Phase 6（Spec 形态收敛，已于前序提交完成）全部勾选并标注完成依据。Phase 5 的 $k_{\text{model}}$ 条目保留 R-3 待标定说明——`tracemalloc` 测试已就位，但标定值尚未回写 §3.2。
  - **AC↔测试映射回填**：映射表由"计划测试名"替换为 `tests/test_extractor.py` / `tests/test_extractor_property.py` 中的**实际测试名**；计划名与实际名不一致处（如 `test_stream_position_restored` → `test_stream_position_restored_on_success_and_failure`、`test_non_seekable_stream_rejected` 并入 `test_invalid_streams_rejected_before_zip_read`）以实际名为准。
  - **状态推进**：`Draft` → `Approved`。代码与测试已在 `feature/result-extrator` 分支完成，待 PR 合并后按生命周期推进为 `Implemented`。
- **说明**: 本轮**未改变任何契约语义**——AC 清单、异常体系、限额默认值与判定规则保持不变；改动仅是进度事实的落盘。真实样本契约测试为 `test_real_sample_contract`（样本 `tests/data/result_001.zip`），与 §1.2 样本基线逐字节吻合。
- **状态**: Approved。

## [2026-10-21] - 评审修订：异常链契约、成员数预检闸门、错误分类与资源预算

- **修改类型**: Changed / Fixed
- **影响范围**: AC-2.2、AC-3.2、AC-3.5、AC-4.4、AC-4.12、AC-5.1、AC-5.2、AC-5.9、AC-6.4、AC-7.7、§3.2（提取限额 / 端到端资源预算 / 输出结构 / 内部常量）、§3.4（编排阶段 / 编排与收尾契约）、§3.5（EOCD 预检 / 常规文件判定 / 错误上下文路径 / 图片收集 / 有界成员读取）、§3.6（校验流水线 / `category` 归一 / 限额检查点 / 错误分类 / 错误清洗）、§4 边界表、§5 任务拆解与 AC↔测试映射、§6.1（R-2 / R-17 / R-18）、§6.2（闭环 Q-22 / Q-23）
- **变更原因**: 对本 Spec 做了一轮对照**真实运行时**（CPython 3.13 `zipfile` / Pydantic v2 / 仓库真实样本 `tests/data/result_001.zip`）的契约核验，暴露出三类问题：(a) **AC-7.7 用 `from None` 无法满足**——Python 的隐式异常链取"当前正在处理的异常"，`from None` 只清 `__cause__`，原始 `ValidationError` 仍会挂在 `__context__` 上并携带 manifest 正文；(b) **EOCD 前置预检在默认限额下永远不可能触发**——条目数字段只有 16 位，≥65535 即写 ZIP64 标记，而超大成员数归档必然走 ZIP64；(c) **`category` 归一漏判**——`union_tag_not_found` 与"根层级少一层"两种情况都落到 `other`。另有若干"已验证的行为"陈述与事实不符，以及一处资源预算推导与默认值算不平。
- **具体内容**:
  - **异常链契约（P0）**：AC-6.4 明确原始 Pydantic 异常必须**同时**不出现在 `__cause__` 与 `__context__` 中，并写明唯一可靠形态——**在 `except` 块内只做信息提取，待 handler 退出后再抛出公共异常对象**；实测 `raise ... from None`（无论在 handler 内还是 handler 外）与显式赋 `__context__ = None` 均无法清除 `__context__`（`raise` 语句会用当前异常覆写它）。AC-3.5、AC-7.7、§3.6 错误清洗、§5 Phase 3/5 与测试映射同步补上 `__context__ is None` 的显式断言。
  - **成员数预检改用中央目录大小（P0）**：AC-5.9 与 §3.5 改写为**条目数上界公式** $\max(\texttt{count\_exact}, \lceil \texttt{cd\_size}/46\rceil)$。理由：EOCD 条目数字段上限 65534，≥65535 写 `0xFFFF`（ZIP64），在默认 `max_members = 100_000` 下只数该字段的预检是死代码；改用中央目录大小后，200,000 成员归档的上界为 247,827，可在构造 `ZipFile` 之前拒绝。同时明确**前置预检不是安全边界**（EOCD 字段可被谎报），权威判定仍是构造后的 `len(infolist()) > max_members`；并写明上界保守导致的**误拒取舍**（50,000 个成员、平均名约 100 字节时上界 ≈ 160,870 会被拒）。新增常量 `_CD_RECORD_MIN_BYTES` / `_ENTRY_COUNT_OVERFLOW` / `_CD_SIZE_OVERFLOW`。
  - **`category` 归一修正（P0）**：规则 1 扩展为 `union_tag_invalid` ∪ `union_tag_not_found`（块 `type` 缺失时 Pydantic 报的是后者，原先落入 `other`）；规则 3 扩展为"`loc` 为空 **或** 错误类型集合含 `list_type`"——根写成 `[block]`（少一层）时 `loc = (0,)` 非空，原先同样落入 `other`。补充说明规则 2 早于规则 4 使缺失 `bbox` 归 `invalid_bbox`（有意为之）。
  - **"已验证的行为"订正（P1）**：§3.5 关于"归档注释含 EOCD 签名"的原陈述（自洽性校验失败并跳过预检、`zipfile` 自身会报 `BadZipFile`）**两处都与事实不符**——伪记录位于窗口尾部且注释长度为 0，自洽性校验**通过**，预检读到 `cd_size = 0` 并放行；`zipfile` 同样命中伪记录，把归档**静默解析成 0 个成员**且不报错。已改为如实描述，并在 §4 补对应边界行。
  - **资源预算自洽（P1）**：`max_total_image_bytes` 由 256 MiB 下调为 **160 MiB**。按 $W=4$、$M=1$ GiB、$k_{\text{model}}=1$、$M_{\text{zipinfo}}=40$ MiB、$M_{\text{result}}=8$ MiB 推导，单次调用峰值约 240 MiB、$W=4$ 时约 960 MiB，满足 $W \times M_{\text{peak}} \le M_{\text{container}}$（原 256 MiB 在同一形态下约 1,272 MiB，超出 1 GiB）。§3.2 补齐推导假设表与 $X \le 192 - 16k$ MiB 的下调公式；AC-5.2、§5 Phase 5 的 README 峰值数字同步更新。
  - **解除对上游组件的耦合（P1）**：§3.2 端到端预算表中的"上游下载 `max_bytes = 50 MiB`"改为"调用方侧（示例）"，明确 Extractor 不依赖该下载组件，与输入契约的来源无关原则一致（该数值本身对 `ResultDownloader` 仍然正确）。
  - **常规文件判定补 `create_system`（P1）**：`external_attr` 的解释依赖 `create_system`（0 = MS-DOS，3 = Unix）。Unix mode 规则仅在 `create_system == 3` 时生效，MS-DOS 属性位规则仅在 `create_system == 0` 时生效，其他取值只按名称判定——避免 MS-DOS 归档高位残留位被误读为符号链接。同时说明 `zipfile` 对 Unix 目录项也会置 MS-DOS 标志 `0x10`，故目录判定以"名称以 `/` 结尾"为准。
  - **清单条目可辨性（P1）**：AC-2.2 明确 `top_level_members` / `candidates` 按 canonical path 字典序升序取前 20 条，并附完整数量；无法 canonical 化的条目以 `!` 前缀标记，与 canonical path 机器可辨。AC-4.4 明确"含 `images` 段"指**段相等**而非子串匹配。
  - **`LargeZipFile` 订正（P1）**：`zipfile.LargeZipFile` 的文档串为 "Raised when writing a zipfile"，三个抛出点全在写路径，**读取路径不会出现**。AC-3.2 / AC-4.12 / AC-5.1 与 §3.5 有界成员读取同步订正。
  - **`__annotations__` 断言移除（P1）**：仓库统一使用 `from __future__ import annotations`，此时 `ExtractedImage.__annotations__` 是字符串而非类型对象；§3.2 改为不断言其具体形态。
  - **边界表与 §4 同步（P1）**：三处"实际字节超限"行标注为**不可达**（与 §3.6 限额检查点表一致）；新增"成员名很长导致上界偏大"、"EOCD 字段被谎报"、"伪 EOCD 藏在归档注释"、"MS-DOS 归档"、"块 type 字段缺失"、"根层级少一层"六行。
  - **遥测口径对齐（P2）**：§3.4 编排说明补上"`on_metric` / `correlation_id` 非法时 `Telemetry` 尚未构造、无法上报指标"的例外，与 AC-6.6 / §3.7 一致。
  - **常量清单完备性说明（P2）**：§3.2 记录 `_UNSAFE_MSG_ERROR_TYPES` 的抽样验证结论（`json_invalid` / `list_type` / `dict_type` / `missing` / `literal_error` 的 `msg` 均不含输入值；`union_tag_invalid` 是当前唯一内嵌输入值的类型），并要求 Schema 变更后重新验证。
- **说明**: 本轮**未改变**组件的职责边界、公共 API 签名（`extract_result` / `canonicalize_member_path`）、异常体系层次、限额字段集合、canonical path 规则与 manifest 定位范围。变更集中在三处：**异常链契约**（新增"handler 外抛出"的实现约束）、**成员数预检的判定量**（条目数字段 → 中央目录大小上界）、**`max_total_image_bytes` 默认值**（256 MiB → 160 MiB）。其余为事实订正与表述收敛。
- **已核实为正确、本轮未改动的关键论断**: `len(data) ≤ file_size` 恒成立（`zipfile/__init__.py:1117` `data = data[:self._left]`；STORED 与 DEFLATED 均实测被钳制）；谎报 `file_size` + CRC 自洽确实导致静默截断（R-12）；`ZipFile.close()` 不关闭调用方传入的流（`_fpclose` 仅在 `not self._filePassed` 时关闭）；深层嵌套归 `json_invalid`（jiter "recursion limit exceeded"）；`union_tag_invalid` 是唯一内嵌输入值的 Pydantic 错误类型；重复成员在 `infolist()` 中保留两条而 `NameToInfo` 只留一条；§1.2 的样本基线与 `tests/data/result_001.zip` **逐字节吻合**（7 成员、manifest 4,803 B、1 页 6 块、图 13,936 B）。
- **状态**: Draft。

## [2026-10-21] - 移除具体代码实现，规范收敛为契约表述

- **修改类型**: Changed
- **影响范围**: 头部评审指引、§3.2 提取限额、§3.4 提取算法（整节重写）、§3.5 成员发现与路径规则（整节重写）、§3.6 Manifest 校验、§3.6 错误清洗、§3.7 遥测、§5 任务拆解、AC-1.11 / AC-2.5 / AC-2.6 / AC-4.1 的表述
- **变更原因**: 项目写作规范新增「除了契约和示例外，SPEC 中不允许出现具体的代码实现」。本 Spec 此前把参考实现草案（`extract_result` 全量函数体、成员发现、路径归一、Schema 校验、错误清洗等）直接贴在 §3.4 ~ §3.6，读者难以分辨「哪些是必须满足的契约」与「哪些只是某个实现的选择」，实现一旦偏离就产生"Spec 与代码不一致"的伪冲突。
- **具体内容**:
  - §3.4 整节重写为**控制流契约**：新增「编排阶段」表（13 个阶段 × 动作 × 失败结果 × 依据）、参数校验契约表、流校验契约表、编排与收尾契约、异常 → `outcome` 映射表、指标标签装配规则。删除原「伪代码描述控制流」引导语与 `extract_result` 全量函数体、全部辅助函数实现。
  - §3.5 整节重写为**判定规则**：EOCD 前置预检（读取窗口 / 定位 / 取值字段 / 自洽性校验 / ZIP64 标记 / 判定结果表）、canonical path（6 条顺序判定 + 不变式）、常规文件判定表、错误上下文路径表、Manifest 发现（9 步表）、图片根目录、图片收集（10 步表）、有界成员读取（9 步表）。删除 `_eocd_entry_count` / `_precheck_member_count` / `canonicalize_member_path` / `is_regular_file` / `_looks_like_symlink` / `log_context_path` / `safe_member_context` / `_context_name` / `_discover_manifest` / `_collect_images` / `_read_member` 的实现体。
  - §3.6「Manifest 校验」重写为步骤表 + 错误明细清洗表 + `msg` 二次脱敏表 + `category` 归一判定顺序表；删除 `_sanitize_msg` / `_validation_category` / `_validate_manifest` 实现体。
  - §3.2 `ExtractionLimits` 保留字段级契约（公开类型形状），删除 `__post_init__` 校验实现，改为「构造契约」文字条款。
  - 全文清理对内部私有函数名的引用（`safe_member_context` / `log_context_path` / `_sanitize_msg` / `_validation_category` / `_precheck_member_count` / `_eocd_entry_count`），改为对应的规则表述；§5 任务拆解中的实现项同步改写为规则描述。
  - 头部评审指引改写：§3 给出的是契约，**不包含具体代码实现**；实现方式由实现者决定；实现与 §3 契约不一致时以 AC 为准。
  - **保留**（属契约或示例）：§3.2 `ExtractionLimits` 字段声明与 `ExtractedResult` / `ExtractedImage` / `ExtractionIssue` 类型定义、§3.3 公共 API 签名、§3.3 集成示例、AC-6.1 与 §3.2 异常体系树、§3.1 包结构与时序图、§3.6 校验流水线。
- **说明**: **本轮未改变任何契约语义**——AC 清单、异常体系、限额默认值、判定规则、错误映射与 §4 边界表逐条保持不变；改动只涉及"契约如何被表述"。所有被删除的实现细节（函数划分、异常捕获顺序、辅助结构）均已由等价的行为条款覆盖，AC 与 §3 不再存在"实现与 Spec 打架"的表述冲突。SPEC-001 / SPEC-002 仍含实现代码块（SPEC-002 §3.4 的 `resolve()` 全量实现、SPEC-001 §3.4 的 poller 实现），待按同一规则收敛。
- **状态**: Draft。

## [2026-10-21] - 架构评审修订：大小判据、错误分类、可运营性与库级异常根

- **修改类型**: Changed / Added
- **影响范围**: Goal 10 ~ 12、§1.2 差距表、§1.4 Non-Goals、§1.5 威胁模型、US-1（AC-1.8 / AC-1.11）、US-2（AC-2.2）、US-3（AC-3.1 / AC-3.4 / AC-3.5）、US-4（AC-4.9 / AC-4.10 / AC-4.12 / AC-4.13 / AC-4.14）、US-5（AC-5.2 / AC-5.8 / 新增 AC-5.9 / 原 AC-5.9 顺延为 AC-5.10）、US-6（AC-6.1 / AC-6.2 / AC-6.3 / AC-6.5 / AC-6.7）、US-7（新增 AC-7.6 / AC-7.7）、§3.1 ~ §3.7、§4 边界表、§5 任务拆解与测试映射、§6.1 风险表（R-2 / R-5 / R-12 / 新增 R-17 / R-18）、§6.2 待决事项（新增 Q-19 / Q-20 / 闭环 Q-21）
- **变更原因**: 架构评审发现三类问题：(a) 规范陈述的**大小判据与 `zipfile` 实际行为相反**——`ZipExtFile` 把读取钳制在中央目录声明的 `file_size` 内，"实际字节是最终判据"不成立，且会掩盖一个未被记录的静默截断路径；(b) **公共异常会携带 manifest 正文**——Pydantic 的 `union_tag_invalid` 消息原样内嵌用户控制的 `type` 值；(c) **失败不可分诊**——`not_found` 无任何上下文，校验错误没有可供分支的粗粒度分类，指标缺少分类维度。此外有三处结构性改进：引入库级公共根异常、公开路径归一 API、把成员数量检查前置到构造 `ZipFile` 之前。
- **具体内容**:
  - **大小判据修正（P0）**：AC-3.1 / AC-4.9 / AC-4.10 与 §3.6 限额检查点表改写为"**中央目录声明的 `file_size` 是唯一事实来源，既是预检也是实际上界**"；三项"实际字节超限"检查标注为**不可达的冗余断言**（保留仅为防御 `zipfile` 行为变化）。新增可触发的完整性检查：读取后校验 `len(data) == info.file_size`，不等 → `ArchiveError(reason="corrupt_member")`。R-12 改写为"谎报偏大导致误拒 / 谎报偏小且 CRC 自洽导致**静默截断**"；静默截断无法在 Extractor 内消除，已写入输出契约与 AC-4.14（下游必须自行校验图片内容）。
  - **正文泄漏修复（P0）**：AC-3.5 要求 `msg` **二次脱敏**——`_UNSAFE_MSG_ERROR_TYPES = {"union_tag_invalid"}` 的错误类型其 `msg` 会内嵌用户输入，一律替换为固定文案；§3.6 清洗清单补入该条；AC-6.3 的禁止清单补入"`msg` 中内嵌的输入值"。新增 **AC-7.7 正文泄漏哨兵测试**（向 manifest 各字符串字段注入哨兵串，断言异常、`issues`、`__cause__`、`__context__` 均不含哨兵）。
  - **错误分类收敛（P0）**：删除 `too_deep` 原因——Pydantic v2 的 jiter 解析器在递归上限处报 `json_invalid` 而非 `RecursionError`，深度耗尽与语法错误同归 `invalid_json`；异常体系表、错误分类表、边界表、任务拆解同步更新。
  - **结构化字段保真（P1）**：`member` / `manifest_path` / `candidates` / `top_level_members` 中的 canonical path **完整未截断**（供调用方程序化定位）；512 字符截断只发生在**日志渲染**（`safe_context_path` 更名 `log_context_path`）。修正了 AC-4.12 与 AC-3.5 同 §3.6 之间的自相矛盾。
  - **引用解析约定（P1）**：明确 `image_source.path` 是上游原始字符串、**不保证与 `images[].path` 逐字相等**；新增**公共 API `canonicalize_member_path`**（Goal 12 / AC-1.11），下游须先归一再匹配；返回契约与集成示例同步给出可执行用法。
  - **失败可分诊（P1）**：`not_found` 携带 `top_level_members`（≤ 20）与 `top_level_member_count`；`ResultExtractionValidationError` 新增 `category`（`unknown_block_type` / `missing_field` / `invalid_bbox` / `root_shape` / `other`），回答"该升级 Schema 还是该拒收文档"。
  - **库级公共根异常（P2）**：新增 `MinerUParserError`（Goal 11 / AC-6.1），`MinerUError`、`ResultDownloadError`、`ResultExtractionError` 均继承之且**彼此互不继承**；纯加性变更，既有捕获语义不变。SPEC-001 / SPEC-002 的 Spec 侧回写已完成（见各自的 changelog）。
  - **成员数量前置预检（P2）**：新增 AC-5.9——从流尾部 64 KiB 窗口解析 EOCD 条目总数，在构造 `ZipFile` **之前**拒绝超限归档；自洽性校验不通过或 ZIP64 标记时跳过预检，中央目录解析后的后置检查始终保留。R-2 相应更新。
  - **端到端资源预算（P2）**：§3.2 新增"端到端资源预算"小节，给出峰值内存公式与并发约束 $W \times M_{\text{peak}} \le M_{\text{container}}$，并说明"压缩侧 50 MiB ≠ 解压侧 256 MiB"，因此"下载成功但提取被限额拒绝"是正常可达状态。新增 R-17。
  - **指标分类维度（P2）**：指标标签由仅 `outcome` 扩展为 `outcome` + `reason` / `resource` / `category`（均为封闭枚举，基数有界），使"上游返回错误页"与"可疑归档"可在同一监控图上区分；路径、成员名、文档内容、`correlation_id` 仍禁止进入标签。
  - **方法论（P2）**：新增 **AC-7.6 性质测试**（Hypothesis，对任意字节串断言结果不变式与"无部分结果、无落盘"）；文档头部增加**评审指引**，声明 §2 的 AC 为唯一契约源、§3 的代码块为参考实现草案；§5 新增 Phase 0（公共根异常）与性质测试任务。
  - **形态收敛**：§5 新增 Phase 6——把 §3.4 / §3.5 / §3.6 的实现伪码改写为契约条款，落实 `docs/specs/CLAUDE.md` §1.6「除契约和示例外，SPEC 中不允许出现具体代码实现」。SPEC-001 / SPEC-002 同步登记 Phase 6。
- **说明**: 本轮修订未改变组件的职责边界与输入契约；`extract_result` 的签名与返回结构保持不变，新增的公共面只有 `canonicalize_member_path` 与 `MinerUParserError` 两项。限额默认值未变，仅补齐了推导口径。SPEC-001 / SPEC-002 的 Spec 侧回写（异常体系、AC、非目标、待决事项、changelog）**已完成**；代码侧的继承调整随 §5 Phase 0 落地。
- **状态**: Draft。

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
