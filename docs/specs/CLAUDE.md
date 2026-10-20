# 技术规格说明书 (Spec) 编写与维护指南

本指南旨在规范 AI agent 在本项目中撰写、修订和维护技术规格说明书（Technical Specification Document，简称 Spec）的标准流程与质量要求。

## 1. 核心编写原则与流程

在撰写任何 Spec 之前，Agent 必须遵循以下核心原则：

1. **叙事剥离与层次分明 (Clear Narrative Structure)**：

   * **1.1 背景 (Context)**：核心要回答“为什么要做（Why）”。
      - 先阅读 `README.md` 了解系统架构。
      - 想清楚几个问题： 整个业务的链路是怎么样的？上游是谁？下游又是谁？搞不清的地方必须跟用户确认。

   * **1.2 现状与差距分析 (Gap Analysis)**：摆事实、做对比，客观呈现当前系统能力与目标状态的差距。

   * **1.3 目标 (Goals)**：明确定义“要做什么（What）”。

2. **严禁混杂琐碎数据到背景**：

   * 严禁将具体的单元测试日志（如 `pytest` 执行结果、通过数量）、底层偶发报错堆砌在 **1.1 背景** 中。

   * 基线数据、性能指标或测试现状应提炼后放入 **1.2 现状与差距分析**，或在 **5. 任务拆解与实施步骤** 的验收阶段引用。

3. **严格划定需求边界**：

   * 必须明确区分 **Goals（目标）** 与 **Non-Goals（非目标）**，防止需求范围膨胀（Scope Creep）。

4. **可落地与可测试 (Actionable & Testable)**：

   * 每个功能点必须有明确的验收标准（Acceptance Criteria, $AC$），且必须能够直接映射到未来的单元测试或集成测试用例。

5. **保持 authentic 语调与规范**：

   * 遵循 LaTeX 数学公式规范（如 inline 使用 `$O(N)$`，display 使用 `$$ ... $$`）。

## 2. 模板结构与各章节写作规范

当创建新的 Spec 文件（如 `docs/specs/SPEC-001-document-store.md`）时，必须严格遵守模板结构 `docs/specs/template.md`。

### 写作细则指南：

1. **Context & Gap Analysis**：

   * 先用 2-3 段话写明驱动因素（如“需要多实例在线读写”、“SQLite 无法跨机器共享”）。

   * 使用矩阵表格，将不同的实现（如 Memory Store、SQLite Store、Mongo Store）在持久化、并发、CRUD、快照语义等维度进行横向对比。

2. **User Stories & Acceptance Criteria**：

   * 采用标准的 **As a... I want to... So that...** 格式。

   * $AC$ 必须清晰无歧义，带有明确的断言条件（例：“当插入重复 `element_id` 时，系统必须抛出 `DuplicateElementError` 异常”）。

3. **Technical Design**：

   * 代码与 Schema 必须完整可读，避免使用模糊的伪代码。

   * 多后端开发时，需说明各后端如何收敛行为一致性。

4. **Edge Cases & Error Handling**：

   * 汇总所有潜在的并发冲突、网络超时、格式非法、约束校验失败等场景，明确响应规则。

5. **Task Breakdown**：

   * 按照 Phase 拆分任务，并使用 `- [ ]` 复选框，便于后续追踪进度。

## 3. Spec 维护与 Changelog 规范

1. **文件命名规范与文件对 (Spec & Changelog File Pair)**：

   * **Spec 主文档**：`SPEC-<三位数字>-<kebab-case-名称>.md`
     * 示例：`SPEC-001-document-store.md`
   * **Spec 变更日志 (Changelog)**：`SPEC-<三位数字>-<kebab-case-名称>.changelog.md`
     * 示例：`SPEC-002-document-operator.changelog.md`
   * **存储位置**：统一存放在项目根目录的 `docs/specs/` 目录下。

2. **Changelog 维护要求**：

   * 每个 Spec 必须配备对应的 `.changelog.md` 文件。
   * 当对已经进入 `In Review` / `Approved` / `Implemented` 状态的 Spec 进行架构调整、AC 变更、增删 Goal 或边界规则修订时，**必须同步在对应的 `.changelog.md` 文件中记录**。
   * Changelog 格式要求：
     ```markdown
     # Changelog: SPEC-001 Document Store

     ## [YYYY-MM-DD] - <变更摘要>
     - **修改类型**: [Added / Changed / Fixed / Deprecated]
     - **影响范围**: [例如: AC-1.2, 3.2 Data Model]
     - **变更原因**: <为什么进行此修改>
     - **具体内容**: <修改的具体细节>
     ```

3. **状态流转 (Status Lifecycle)**：

   * **Draft**：草稿阶段，AI 或人工初稿，正在收集意见。

   * **In Review**：评审阶段，架构与方案讨论中。

   * **Approved**：已通过评审，等待或正在开发中。

   * **Implemented**：已开发完成并通过验收，代码已合并。

4. **版本控制与更新记录**：

   * 每次对 Spec 进行实质性修订时，除了在 `.changelog.md` 中添加日志外，必须同时更新 Spec 主文档 Header 中的 **更新时间 (Updated At)**。