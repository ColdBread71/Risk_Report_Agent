# 总体架构说明

## 范围

本项目当前第一阶段只覆盖 `Context / TOE` 抽取。

## 数据流

`客户原始资料` → `顺序读取` → `Context 状态累积` → `Context Draft 输出`

## 当前技术路线

- 使用 LangGraph 组织顺序抽取流程
- 不使用 RAG、chunk、embedding、索引检索作为主链路
- 输入材料按文件 / 页 / 章节顺序读取
- 每轮读取都更新全局 Context 状态

## 文档职责

- `01_input_spec.md`
  - 定义第一阶段抽取器的输入边界和资料包规则。
- `01_context_spec.md`
  - 定义 Context 字段字典、状态结构和输出约定。
- `02_tara_spec.md`
  - 仍保留为后续 TARA 预留说明，当前不进入实现。
- `03_evidence_policy.md`
  - 定义证据引用和溯源规则。

## 设计原则

- 不在 Python 代码里硬编码模板、Prompt 或规则。
- 所有抽取都围绕稳定的 State 和 Schema 进行。
- 缺失信息必须保留为空、空数组或待确认项。
- 允许保留 `others` / 候选信息，避免第一轮丢失潜在有用内容。
- 所有结论尽量都能回溯到证据。