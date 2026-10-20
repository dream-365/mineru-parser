# Changelog: SPEC-001 MinerUApiClient

## [2026-10-20] - 1.1 增加链路流程图

- **修改类型**: Added
- **影响范围**: 1.1 背景 (Context)
- **变更原因**: 用 Mermaid 流程图直观说明上游、客户端公共边界与下游的调用关系，以及 `submit` / `resume` / `wait` 三条路径。
- **具体内容**:
  - 增加链路概览图：`submit(uri)` 提交、`resume(task_id)` 恢复、`AsyncResult.wait()` 轮询并交付 `zip_url`。
  - 图中标注持久化 `task_id` 的本地恢复路径，以及轮询阶段的退避 / 超时处理。

## [2026-10-20] - 重写 1.1 背景，聚焦业务痛点

- **修改类型**: Changed
- **影响范围**: 1.1 背景 (Context)
- **变更原因**: 按 `docs/specs/CLAUDE.md` 的写作要求，1.1 应简明回答“为什么要做（Why）”，突出业务痛点，避免混入 Transport / Task / Poller 等内部实现细节。
- **具体内容**:
  - 重写背景为三段：业务场景、核心痛点、客户端定位。
  - 明确痛点：异步链路重复实现、进程重启后的任务恢复、限流与偶发 5xx、退避抖动、等待超时、错误分类与可观测性缺失。
  - 保留上游（MinerU API）与下游（业务后端 / 批处理 / 离线处理管线）的边界说明。
  - 内部实现细节移至 3.1 架构与数据流。

## [2026-10-20] - task() 重命名为 resume()

- **修改类型**: Changed
- **影响范围**: 1.1 背景、1.2 Gap Analysis、1.3 Goals、2. US-3、3.1 组件职责、3.3 API 契约、4. 边界条件、5. 任务拆解、6. 风险
- **变更原因**: 原 `task()` 的本意是通过 `task_id` 重新取得 `AsyncResult` 句柄，而不是操作任务本身；`resume()` 更准确地表达“恢复等待”的语义。
- **具体内容**:
  - 公共方法 `task()` 重命名为 `resume()`，参数与行为不变。
  - 调用方式：`client.resume(task_id, data_id=None) -> AsyncResult`。
  - 同步更新背景、Goals、US-3、组件职责、API 签名与方法语义、边界条件、风险与任务拆解中的引用。

## [2026-10-20] - submit 返回 AsyncResult

- **修改类型**: Changed
- **影响范围**: 1.1 背景、1.3 Goals、2. 用户故事、3.1 组件职责、3.3 API 契约、4. 边界条件、5. 任务拆解、6. 风险
- **变更原因**: 将异步提交的结果统一建模为 `AsyncResult`；`submit()` 与 `task()` 均返回该句柄，调用方通过 `AsyncResult.wait()` 获取最终结果，避免把“任务句柄”作为另一个概念暴露。
- **具体内容**:
  - 将原 `MinerUTask` 公共句柄重命名为 `AsyncResult`（`MinerUTaskState` / `MinerUTaskStatus` / `MinerUTaskResult` 保持不变）。
  - 新增 `AsyncResult` 契约：`task_id`、`data_id`、`status`、`state`、`result`、`refresh()`、`wait()`。
  - 明确 `AsyncResult` 是同步阻塞式结果句柄，不实现 `asyncio.Future`，且非线程安全。
  - 同步更新背景、Goals、用户故事、时序图、组件职责、边界条件与风险表述。
  - 当前 Spec 仍为 10 组用户故事、AC-1.1 ~ AC-10.3。

## [2026-10-20] - 移除 trace() 公共暴露

- **修改类型**: Changed
- **影响范围**: 1.1 背景、1.2 Gap Analysis、1.3 Goals、1.4 Non-Goals、2. 用户故事、3.1 组件职责、3.3 API 契约、3.5 错误分类、4. 边界条件、5. 任务拆解与测试映射
- **变更原因**: `trace` 是客户端内部的状态查询机制，仅由 `MinerUTask.refresh()` 调用；它不应作为公共 API 暴露给调用方。
- **具体内容**:
  - 删除原 US-3「单次查询任务状态」及原 AC-3.1 ~ AC-3.4。
  - 后续用户故事与 AC 重新编号：原 US-4 ~ US-11 → US-3 ~ US-10；原 AC-4.x ~ AC-11.x → AC-3.x ~ AC-10.x。
  - 从公共 API 签名与方法语义中移除 `trace`，在 Non-Goals 中明确其内部机制定位。
  - 在任务恢复故事中新增 AC-3.5：内部状态查询必须对 `task_id` 做 URL 编码。
  - 当前 Spec 为 10 组用户故事、AC-1.1 ~ AC-10.3。

## [2026-10-20] - 移除 parse() 业务编排

- **修改类型**: Changed
- **影响范围**: 1.2 Gap Analysis、1.3 Goals、1.4 Non-Goals、2. 用户故事、3.1 组件职责、3.3 API 契约、4. 边界条件、5. 任务拆解与测试映射、6. 风险与待决事项
- **变更原因**: `parse()` 将 `submit()` 与 `wait()` 组合成一步式业务流程，属于调用方的业务编排职责；`MinerUApiClient` 应只提供提交、查询、恢复与等待原语。
- **具体内容**:
  - 删除 `parse()` 相关目标、用户故事、原 AC-5.1 ~ AC-5.4、API 签名与方法语义。
  - 后续用户故事与 AC 重新编号：原 US-6 ~ US-12 → US-5 ~ US-11；原 AC-6.x ~ AC-12.x → AC-5.x ~ AC-11.x。
  - 在 Non-Goals 中明确：一步式解析由调用方组合 `submit()` 与句柄 `wait()` 完成。
  - 移除与 `parse()` 绑定的原风险 R-10 与原待决事项 Q-3，并重新编号后续条目。
  - 当前 Spec 为 11 组用户故事、AC-1.1 ~ AC-11.3。

## [2026-10-20] - 初始补写 MinerUApiClient Spec

- **修改类型**: Added
- **影响范围**: 全文（1.1 ~ 6.2）
- **变更原因**: 项目已有 README 数据管道图与完整实现，但 `docs/specs/` 下缺少以公共入口 `MinerUApiClient` 为核心的技术规格。按 `docs/specs/CLAUDE.md` 的模板与维护规范补齐客户端契约、验收标准与测试映射。
- **具体内容**:
  - 新增 `SPEC-001-mineru-api-client.md`，状态标记为 `Implemented`。
  - 明确上游（MinerU API）与下游（业务后端 / 批处理 / 离线处理管线）的链路边界。
  - 以 `MinerUApiClient` 为唯一公共入口，定义构造参数、内部状态、公共方法与只读属性。
  - 将 Client / Transport / Task / Poller / Telemetry 的数据管道定位为客户端的内部实现机制。
  - 定义 12 组用户故事及 AC-1.1 ~ AC-12.3，并映射到现有 28 个行为测试。
  - 固化轮询算法（退避、抖动、`Retry-After`、deadline 截断）与错误分类矩阵。
  - 补充边界条件、风险登记表与 9 项待决事项。
- **说明**: 初稿曾以 `data-pipeline` 为主题整理；评审后按公共契约收敛为 `MinerUApiClient` 主题，文件同步重命名。
