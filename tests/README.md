# 测试目录（M1）

测试范围及验收矩阵见 [测试计划](../docs/design/test-plan.md)。

- `unit/`：业务规则及契约。
- `integration/`：临时 SQLite、事务、并发与模型协议模拟。
- `acceptance/`：输入到实际输出的完整链路。
- `adversarial/`：非法动作、权限越界、提示注入及循环。

M1 已实现 70 个 unittest 测试方法（含额外 subTest 边界），开发环境与独立 wheel 环境各通过一次最终验证。unit 覆盖领域约束，integration 当前仅覆盖真实合成资料加载与包集成。

SQLite、原生模型协议、完整 Agent 验收和网页测试尚未实现；不能把这 70 个方法换算为 42 组计划验收通过。实际结果见 [M1 机器报告](../examples/evaluation/M1-summary.json)。
