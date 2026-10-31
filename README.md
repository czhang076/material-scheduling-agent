# 素材审核与发布排期 Agent

帮助内容团队审核素材的元数据与文案，形成可确认、可追溯的排期草稿。**仅草稿，不接真实发布。**

> 当前0.6.0已完成独立技术验收，并发布至 [GitHub公开仓库](https://github.com/czhang076/material-scheduling-agent)。结果见 [严格验收报告](docs/FINAL-ACCEPTANCE.md)，评审访问见 [交付说明](docs/GITHUB-DELIVERY.md)。默认Mock，仅保存草稿；个人投入约4小时（估算，未连续计时），AI辅助与个人贡献见 [使用记录](docs/04-ai-usage.md)。

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

当前222个unittest方法、另7个Node网页状态用例分别计数，已从e89b238导出的干净源码重新构建、安装并全部复跑。Node仅用于开发验证，项目运行无需Node。提交前新增8次真实CLI路径、2次真实网页运行，共51次DeepSeek调用，以及14组离线场景16次运行、6组HTTP业务和1组终态恢复。原始证据见 [最终验收清单](examples/final-acceptance/manifest.json)。M4/M5/M6旧证据保持原样，不重新标记为新运行。

## 本地网页

复用上面初始化的账本：

```powershell
.\.venv\Scripts\python.exe -m material_scheduler serve --db var/scheduler.sqlite3 --state-dir var/workbench --port 8765
```

浏览器打开 [本地工作台](http://127.0.0.1:8765)，Ctrl+C 停止。界面默认离线 Mock；启动时追加 `--env-file .env` 后，可在页面明确选择真实模型。浏览页面不会自动调用模型。运行、同步、逐项确认、Trace 下载均读取或操作实际账本；关闭页面不取消后台任务。业务要求改变时新建任务，同一要求可复用任务重试。

未知提交保留原要求和模式；新输入不会自动替换或重发旧要求。先查询原提交，需要重发时明确点击“重试原提交”。运行状态日志暂时写失败会显示状态待保存，存储恢复后显式提交可对账；GET只读。

当前运行与独立安装包验证步骤见 [运行手册](docs/RUNBOOK.md)；修复验收见 [M6](docs/M6-ACCEPTANCE.md)。无需前端安装或构建，静态资源随 Python 包分发。只用于本地单用户工作。

## 真实模式

真实模式配置与复跑（会调用付费服务）：

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 在本地 .env 填写 MODEL_API_KEY；不要填写到 .env.example。
.\.venv\Scripts\python.exe -m material_scheduler run --input data/requests/normal.json --db var/scheduler.sqlite3 --mode real --env-file .env --out var/real-demo-001
```

配置项的服务差异、截止时间与错误边界见 [M4 验收](docs/M4-ACCEPTANCE.md)。本次 DeepSeek 请求使用 `deepseek-flash`、非思考模式、每轮最多一个工具。其他兼容服务须独立验证，不因协议相近就宣称已兼容。

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
  interfaces/    # CLI、本地 HTTP、静态网页、实际运行文件与评估
```

模型接口每轮只收到请求、预算和真实历史；下一动作从实际观察产生。真实适配器传回原生工具调用，再按原始调用 ID 回传实际观察。执行器只编排、计数和限时，业务保护由确定性工具与 SQLite 事务约束。Mock 的分支只验证流程，真实动态效果由独立网络记录验证。

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
|提交前独立严格验收|[FINAL-ACCEPTANCE](docs/FINAL-ACCEPTANCE.md)|
|GitHub地址、评审访问与提交信息|[GITHUB-DELIVERY](docs/GITHUB-DELIVERY.md)|
|M6审查修复与当前验收|[M6-ACCEPTANCE](docs/M6-ACCEPTANCE.md)|
|M4 配置、协议测试及真实路径|[M4-ACCEPTANCE](docs/M4-ACCEPTANCE.md)|
|M3 历史离线基线|[M3-ACCEPTANCE](docs/M3-ACCEPTANCE.md)|
|环境、命令及交接|[RUNBOOK](docs/RUNBOOK.md)|
|阶段进度|[STATUS](docs/STATUS.md) / [PLAN](docs/PLAN.md)|
|模块 / 存储 / 执行循环|[architecture](docs/design/architecture.md) / [persistence](docs/design/persistence.md) / [agent-loop](docs/design/agent-loop.md)|
|工具 Schema / 提示|[tool-schemas](docs/design/tool-schemas.md) / [model-prompt](docs/design/model-prompt.md)|
|公开示例参考及历史基线|[REFERENCE-REVIEW](docs/REFERENCE-REVIEW.md) / [P0](docs/P0-ACCEPTANCE.md) / [M1](docs/M1-ACCEPTANCE.md) / [M2](docs/M2-ACCEPTANCE.md)|
|M5网页历史记录 / 当前设计|[M5-ACCEPTANCE](docs/M5-ACCEPTANCE.md) / [workbench](docs/design/workbench.md)|
|图片与视频扩展设计|[media-extension](docs/design/media-extension.md)|

资料全部合成，运行数据库在忽略的 var/ 内；实际JSON/Trace在examples/，不提交密钥或数据库。真实模式显式配置，未配置则失败，不降级Mock。无视觉审核、多人认证、真实发布或线上部署。GitHub仓库公开且已匿名验证可读；提交时填写题号1、仓库URL及远程main最新SHA。个人投入约4小时（本人估算）；实际参与、AI辅助范围及关键修改统一见 [协作记录](docs/04-ai-usage.md)，设计取舍及改进见 [复盘](docs/05-retrospective.md)。
