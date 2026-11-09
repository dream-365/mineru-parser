---
type: tasks
status: Done
owner: jackafx
depends_on: []
spec: ./spec.md
spec_sha256: "2efdc7584afb40ac92da7fb3df47aa7693f712929d9ce869b7572dbae8692429"
updated_at: 2026-11-09
---

# MinerU 客户端 异步任务提交与稳健轮询 执行拆解

| ID | 任务 | 覆盖 | 依赖 | 写入 | 完成标准 | 验证 |
|---|---|---|---|---|---|---|
| T1 | 客户端构造、配置校验与只读属性 | G1 | — | src/mineru_parser/_client/api.py, src/mineru_parser/_client/_validation.py | 非法 `api_key` / `base_url` / `request_timeout` / `poll_policy` 在构造期抛出 `MinerUConfigurationError`；只读 `base_url` / `poll_policy` 可用 | `python -m pytest tests/test_client.py -q -k "invalid_configuration or api_key or inject"` |
| T2 | `submit` / `resume` 与 `AsyncResult` 身份契约 | G2 | T1 | src/mineru_parser/_client/async_result.py | `submit` 返回身份正确的 `AsyncResult`；`resume` 不发网络；`data_id=None` 从请求体省略 | `python -m pytest tests/test_client.py -q -k "submit or resume or url_encoded"` |
| T3 | 轮询、退避、`Retry-After` 与等待预算 | G3 | T2 | src/mineru_parser/_client/polling.py | 默认策略值、抖动区间、状态重置、deadline 截断与连续错误上限均按 4.5 契约成立 | `python -m pytest tests/test_client.py -q -k "poll or timeout or retry_after or transient"` |
| T4 | 异常层级、错误映射与统一根 | G4 | T2 | src/mineru_parser/_client/errors.py, src/mineru_parser/errors.py | 提交 / 查询阶段错误映射符合 4.6；四个异常家族共享 `MinerUParserError` 且互不继承 | `python -m pytest tests/test_client.py tests/test_extractor.py -q -k "error or hierarchy or quota"` |
| T5 | Session 生命周期、回调隔离与遥测出口 | G5 | T1 | src/mineru_parser/_client/_telemetry.py | 自建 Session 被关闭、注入 Session 不被关闭；`on_update` 异常被吞掉并记录 `mineru.on_update.failed`；`correlation_id` 进入日志 | `python -m pytest tests/test_client.py -q -k "session or callback"` |
| T6 | 无网络回归与真实样本冒烟 | G3, G4, G5 | T3, T4, T5 | tests/test_client.py, docs/specs/SPEC-001-mineru-api-client/ | 29 个客户端测试函数全部通过；13 页样本 `status=success` 且等待阶段耗时记录在 README 基线内 | `python -m pytest tests/test_client.py tests/test_pipeline.py -q` |
