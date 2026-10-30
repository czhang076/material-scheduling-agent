# 素材审核与发布排期 Agent

帮助内容团队审核待处理素材，并形成无冲突、可确认、可追溯的发布排期草稿。仅保存草稿，不接真实发布。

> 当前 **M2：工具与草稿闭环已完成**。已有真实 SQLite、审核与时段工具、版本确认、防重复、故障处理及并发保护；113 个测试和 7 组实际工具案例可复跑。Agent 循环、业务 CLI、真实模型和网页留待后续阶段。

## 当前可以运行什么

已在 Windows、Python 3.13.12 验证：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe scripts/run_m2_examples.py
.\.venv\Scripts\python.exe -m pip check
```

示例脚本实际调用工具、创建独立 SQLite 账本并生成输入、输出和逐步记录；调用顺序由脚本控制，明确不算 ReAct。M2 无需环境变量或密钥。实际记录见 [M2 验收](docs/M2-ACCEPTANCE.md)、[测试摘要](examples/evaluation/M2-summary.json)和[七组案例](examples/evaluation/M2-cases.json)。

## 从哪里开始看

|需要了解的内容|入口|
|---|---|
|需求与成功标准|[01-requirements](docs/01-requirements.md)|
|总体方案与技术取舍|[02-solution](docs/02-solution.md)|
|仓库与模块职责|[architecture](docs/design/architecture.md)|
|请求、工具、结果与错误契约|[contracts](docs/design/contracts.md)|
|模型决策与执行上限|[agent-loop](docs/design/agent-loop.md)|
|审核、草稿状态与用户确认|[lifecycle](docs/design/lifecycle.md)|
|防重复、并发与保存事务|[persistence](docs/design/persistence.md)|
|信任、故障与数据边界|[trust-and-failures](docs/design/trust-and-failures.md)|
|验收用例与证据规划|[test-plan](docs/design/test-plan.md)|
|评估状态与证据入口|[03-evaluation](docs/03-evaluation.md)|
|AI 使用记录与个人贡献边界|[04-ai-usage](docs/04-ai-usage.md)|
|设计阶段反思|[05-retrospective](docs/05-retrospective.md)|
|推进顺序与当前状态|[PLAN](docs/PLAN.md) / [STATUS](docs/STATUS.md)|
|环境、预期操作与交接|[RUNBOOK](docs/RUNBOOK.md)|
|设计准备检查|[P0-ACCEPTANCE](docs/P0-ACCEPTANCE.md)|
|公开示例的参考范围与底座对照|[REFERENCE-REVIEW](docs/REFERENCE-REVIEW.md)|
|需要用户选择的范围与当前默认方案|[DECISIONS](docs/DECISIONS.md)|
|正常、冲突、缺失及恢复的用户流程|[user-journeys](docs/design/user-journeys.md)|
|元数据与文案审核、证据定位|[content-review](docs/design/content-review.md)|
|CLI 后续的本地网页工作台|[workbench](docs/design/workbench.md)|
|图片与视频扩展边界|[media-extension](docs/design/media-extension.md)|
|完整工具参数 Schema|[tool-schemas](docs/design/tool-schemas.md)|
|系统提示与观察协议|[model-prompt](docs/design/model-prompt.md)|
|标准合成资料与预期样例|[design-fixtures](docs/design/design-fixtures.md)|
|设计基线是否准备完成|[DESIGN-READINESS](docs/DESIGN-READINESS.md)|
|M1 已实现内容与实际验证|[M1-ACCEPTANCE](docs/M1-ACCEPTANCE.md)|
|M2 工具、事务、确认与并发验证|[M2-ACCEPTANCE](docs/M2-ACCEPTANCE.md)|

## 仓库结构

```text
src/material_scheduler/
  domain/          # 审核、时间约束、草稿状态等业务规则
  application/     # 工具用例、用户确认、运行结果组装
  agent/           # 模型决策循环、工具目录、执行预算与 Trace
  adapters/        # 本地数据、SQLite、真实模型与离线 Mock
  interfaces/      # CLI 与输入输出
    web/           # 后续本地网页静态资源，当前仅占位
tests/
  unit/            # 确定性业务规则
  integration/     # 真实本地存储与接口协议
  acceptance/      # 六项必验及确认闭环
  adversarial/     # 越权、提示注入、伪造成功、循环
data/
  catalog/         # 合成素材及补充资料
  rules/           # 有版本的审核规则
  schedules/       # 已有排期与候选时段
examples/
  inputs/          # M2 实际请求、资料快照和可信故障配置
  outputs/         # 实际工具结果、账本计数与业务审计
  traces/          # 手动工具调用 JSONL；尚无模型 Trace
  evaluation/      # M1/M2 实际评估报告
scripts/           # M2 案例生成与验证；非 Agent CLI
docs/
  01-...05-...     # 题目要求的五份交付文档
  design/          # 详细设计与测试计划
```

尚未实现的目录保留 `.gitkeep`。已实现 domain、application 工具会话及序列化、资料加载与 SQLite 适配器。

设计基线 v1 已收口；M1/M2 已实现并验证，预算执行与模型决策留到 M3。

## 已确定的原则

- 模型根据工具结果选择下一步；保存权限、冲突、确认及幂等性由确定性代码约束。
- 原始硬性发布时间不被建议值覆盖；调整时间必须标记待确认。
- 用户确认绑定草稿版本；保存或确认时再次检查资料、规则和占用。
- 相同请求重复执行只保留一份对应草稿；相同 ID 换输入明确拒绝。
- 错误、达到执行上限和保存结果不确定时明确返回未完成或待核验。
- 真实模型稍后配置。离线 Mock 验证流程，不能证明真实模型决策效果。

## 运行与提交状态

已确认范围为元数据与文案审核，预留图片/视频扩展设计；先完成 CLI 核心，再补轻量本地网页工作台。

M2 使用 Python 3.13.x 和标准库 SQLite，构建后端固定在 pyproject.toml。业务 CLI/网页尚未实现，未来命令设计见 [RUNBOOK](docs/RUNBOOK.md)。`.env.example` 仍为后续配置占位，当前无需配置。

当前仅本地 Git，无 GitHub 远程仓库或最终考核交付 SHA。真实模型配置仍由用户稍后提供，完整考核尚未满足。
