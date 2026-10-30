# 素材审核与发布排期 Agent

帮助内容团队审核素材的元数据与文案，形成可确认、可追溯的排期草稿。**仅草稿，不接真实发布。**

> M3 离线链路已完成：有界决策循环、实际工具观察、SQLite 保存、CLI、用户确认和 Trace。离线提供者是明确的规则 Mock，验证流程与保护；真实模型接入和真实 ReAct 效果留到 M4，不用 Mock 结果替代。

## 安装与运行

Python 3.13.x；无第三方运行依赖，离线无需密钥或环境变量。以下在仓库根目录执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m material_scheduler init --data-dir data --db var/scheduler.sqlite3
.\.venv\Scripts\python.exe -m material_scheduler run --input data/requests/normal.json --db var/scheduler.sqlite3 --mode mock --out var/demo-001
```

`var/demo-001/` 生成实际 `result.json`、逐步 `trace.jsonl` 和 `manifest.json`。再次执行请换新的输出目录；业务请求 ID 保持不变即可验证防重复。已有证据目录会被拒绝覆盖。业务输入是严格请求 JSON，`examples/inputs/M3-*.json` 则是含资料/故障的完整评测封装，不直接作为 run 的输入。

运行全部离线场景及测试：

```powershell
.\.venv\Scripts\python.exe -m material_scheduler evaluate --data-dir data --out var/evaluation-001
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe -m pip check
```

当前 156 个 unittest 方法，开发环境及独立 wheel 环境分别通过；14 组离线场景实际运行 16 次，涵盖六项必验、补查成功、临时错误恢复、人工风险、无可用时段、上限、保存未知及占用变化后同请求重规划。详见 [M3 验收](docs/M3-ACCEPTANCE.md)、[测试摘要](examples/evaluation/M3-summary.json)、[案例索引](examples/evaluation/M3-cases.json)。这些是 Mock 验证，没有真实模型调用。

## 检查和确认

```powershell
.\.venv\Scripts\python.exe -m material_scheduler inspect --db var/scheduler.sqlite3 --request-id REQ-DESIGN-A01
```

inspect 会重新核验，可能将旧草稿标记为 STALE。硬性时间改变或需人工审核时，草稿保持 PENDING_CONFIRMATION，不占全局容量。

例如运行上述 evaluate 后，conflict 场景已有待确认的 19 点草稿；用户明确接受当前版本时执行：

```powershell
$proposal = Get-Content var/evaluation-001/conflict/run-1/result.json -Raw | ConvertFrom-Json
$draft = $proposal.items[0].draft
.\.venv\Scripts\python.exe -m material_scheduler confirm --db var/evaluation-001/conflict/ledger.sqlite3 --draft-id $draft.draft_id --expected-version $draft.version --confirmation-id C-LOCAL-001 --actor local-user --accept TIME_CHANGE
```

多项待确认事项需重复传 `--accept`，必须逐项同意。确认仍会复核资料和冲突，只形成 READY 草稿，仍未发布。模型工具目录中没有确认或发布动作。

运行退出码：0 全部可用草稿；2 待补充/待确认/阻断/其他业务未完成；3 输入或身份错误；4 工具/提供者/证据故障或保存未知；5 限额或取消。evaluate 的 0 表示所有场景符合各自预期，预期失败场景也必须如实失败。

## 架构和保护

```text
src/material_scheduler/
  domain/        # 不可变请求、审核证据、时间区间、草稿及确认规则
  application/   # 严格工具目录、实际观察权限、结果与序列化
  agent/         # 单动作协议、有界循环、提示、持久 Trace
  adapters/      # 合成资料、SQLite、可信故障、离线观察策略
  interfaces/    # CLI、运行文件和离线评估；web/ 仍占位
```

模型接口每轮只收到请求、预算和真实历史；下一动作从实际观察产生。执行器只编排、计数和限时，保存/确认规则由确定性工具与 SQLite 事务约束。Mock 的业务分支属于演示策略，不能证明真实模型决策效果。

- 相同请求项唯一草稿；同 ID 更换业务内容拒绝。
- 保存只能使用本会话审核与查询结果；事务再次查证据和占用。
- 待确认方案不预留全局容量；READY 占用本地账本。
- 硬性时间保留原值，用户同意绑定具体草稿版本与全部事项。
- 资料/规则/时段变化使旧证据失效；重规划沿用 ID、增加版本并清除旧授权。
- 写入中途故障整体回滚；提交结果无法查证时保留 UNKNOWN。
- 每项、全局、模型轮数及总时长均有上限；保留已成功结果并明确返回未完成。
- 写工具派发前持久化意图；提交后 Trace 失败如实保留保存事实并标记证据不完整。

## 评审导航

|内容|入口|
|---|---|
|需求、范围和成功标准|[01-requirements](docs/01-requirements.md)|
|总体设计与取舍|[02-solution](docs/02-solution.md)|
|实际验证、失败和限制|[03-evaluation](docs/03-evaluation.md)|
|AI 使用及个人贡献边界|[04-ai-usage](docs/04-ai-usage.md)|
|设计与开发复盘|[05-retrospective](docs/05-retrospective.md)|
|M3 实现、复跑、动态路径|[M3-ACCEPTANCE](docs/M3-ACCEPTANCE.md)|
|环境、命令及交接|[RUNBOOK](docs/RUNBOOK.md)|
|阶段进度|[STATUS](docs/STATUS.md) / [PLAN](docs/PLAN.md)|
|模块 / 存储 / 执行循环|[architecture](docs/design/architecture.md) / [persistence](docs/design/persistence.md) / [agent-loop](docs/design/agent-loop.md)|
|工具 Schema / 提示|[tool-schemas](docs/design/tool-schemas.md) / [model-prompt](docs/design/model-prompt.md)|
|公开示例参考及历史基线|[REFERENCE-REVIEW](docs/REFERENCE-REVIEW.md) / [P0](docs/P0-ACCEPTANCE.md) / [M1](docs/M1-ACCEPTANCE.md) / [M2](docs/M2-ACCEPTANCE.md)|
|后续本地网页 / 媒体扩展|[workbench](docs/design/workbench.md) / [media-extension](docs/design/media-extension.md)|

资料全部合成，运行数据库在忽略的 var/ 内；实际选取的 JSON/Trace 在 examples/，不提交密钥或数据库。真实模型由用户稍后配置，`--mode real` 当前明确报错。尚无网页、视觉审核、多人认证、真实发布平台或线上部署。GitHub 远程及最终考核 SHA 尚未交付；当前阶段提交可用 `git log -1` 查看。
