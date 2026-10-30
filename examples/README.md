# 验证证据目录

- `inputs/`：实际执行所用输入。
- `outputs/`：实际结果，不手写预期冒充输出。
- `traces/`：实际动作与工具观察 JSONL。
- `evaluation/`：实际断言结果、运行清单、指标与失败分析。

未来每组证据记录用例 ID、模式（Mock/真实）、数据版本、代码 commit、命令及文件校验值。至少分别覆盖六个必验场景，详见 [测试计划](../docs/design/test-plan.md)。

evaluation/ 已有 M1 的实际基础测试、编译检查、依赖检查记录和机器摘要。它们不证明数据库保存或真实模型决策；Agent 的 inputs/outputs/traces 当前仍为空。

设计文档中的预期投影不得移动进本目录当作已执行结果。合成输入数据位于 data/，实际 M1 范围见 [验收记录](../docs/M1-ACCEPTANCE.md)。
