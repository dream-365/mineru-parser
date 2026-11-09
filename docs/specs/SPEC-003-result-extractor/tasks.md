---
type: tasks
status: Done
owner: jackafx
depends_on: []
spec: ./spec.md
spec_sha256: "a5a4fc8152a2861af1971d5194d3d33adb5c1353a50cc8821dbfc80c6a14f0fa"
updated_at: 2026-11-09
---

# 结果包提取器 结果包解析与图片提取 执行拆解

| ID | 任务 | 覆盖 | 依赖 | 写入 | 完成标准 | 验证 |
|---|---|---|---|---|---|---|
| T1 | 入口参数校验、流生命周期与结果契约 | G1 | — | src/mineru_parser/_extractor/extractor.py, src/mineru_parser/_extractor/models.py | 非 seekable / 非法 limits / 非法 hooks 在读取 ZIP 前被拒绝；成功与已处理失败后恢复游标且不关闭流 | `python -m pytest tests/test_extractor.py -q -k "basic or stream or invalid_streams or limits_argument or hooks"` |
| T2 | 顶层 manifest 唯一发现与错误上下文 | G2 | T1 | src/mineru_parser/_extractor/_manifest.py | 顶层唯一匹配；子目录 / 多份 / 非法成员名分别得到 `not_found` / `ambiguous` / `unsafe_member`，并携带顶层成员清单 | `python -m pytest tests/test_extractor.py -q -k "manifest"` |
| T3 | JSON / Schema 校验、错误清洗与脱敏 | G2 | T2 | src/mineru_parser/_extractor/_manifest.py | UTF-8 / BOM / JSON / Pydantic 错误分类正确；`category` 归一；`msg` 不泄漏输入值 | `python -m pytest tests/test_extractor.py -q -k "validation or invalid_json or invalid_utf8 or leak"` |
| T4 | 图片收集、canonical path 与确定性排序 | G3 | T2 | src/mineru_parser/_extractor/_members.py | 只收集顶层 `images/` 常规文件；路径 canonical 化、重复检测、字典序排序；与 `canonicalize_member_path` 规则一致 | `python -m pytest tests/test_extractor.py -q -k "images or canonicalize or symlink"` |
| T5 | 资源限额、有界读取与错误分类 | G4 | T3, T4 | src/mineru_parser/_extractor/limits.py, src/mineru_parser/_extractor/errors.py | manifest / 单图 / 总图片 / 数量 / 成员数超限均失败关闭；读取长度与声明一致；错误 `resource` / `limit` / `actual` 齐全 | `python -m pytest tests/test_extractor.py -q -k "limit or member_count or corrupt or encrypted or compression"` |
| T6 | 遥测、性质测试与真实样本回归 | G5 | T1, T5 | tests/test_extractor.py, tests/test_extractor_property.py | 成功 / 失败指标与日志齐全；Hypothesis 不变式通过；真实样本契约测试通过 | `python -m pytest tests/test_extractor.py tests/test_extractor_property.py -q` |
| T7 | 共享根异常与 canonicalize 公开路径 | G6 | T1 | src/mineru_parser/errors.py, src/mineru_parser/_extractor/__init__.py | `ResultExtractionError` 继承 `MinerUParserError` 且与其它家族互不继承；`canonicalize_member_path` 可从私有包导入 | `python -m pytest tests/test_extractor.py -q -k "hierarchy or private_package_exports"` |
