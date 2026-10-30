# M2 工具与草稿闭环验收

2026-10-30 收口。范围是实际本地工具和 SQLite，用手动工具驱动验证。**未实现 Agent 决策循环，不宣称满足完整 ReAct 考核。**

## 已实现

|能力|实现与验证|
|---|---|
|资料事实源|严格校验合成 JSON 后原子导入 SQLite；素材/规则/时段/既有排期同一快照|
|工具边界|read_material、lookup_metadata、check_rules、query_slots、save_draft、finish；严格字段和请求项范围|
|观察证据|保存只能使用本会话实际审核及查询所得候选；事务再次比较审核快照、候选身份、当前占用|
|补查|仅填缺失字段，保留来源；矛盾来源在导入时即标记，跳过补查也不能绕过|
|持久化幂等|请求内容不可变；同请求项唯一草稿；重复保存不增版本；确认身份重复不新增同意|
|用户确认|独立 ConfirmationCommand，不在模型工具目录；绑定版本和全部待确认事项|
|一致性|BEGIN IMMEDIATE、唯一约束、READY 占用、区间防重叠触发器；陈旧草稿释放占用|
|失败事实|事务内故障整体回滚；提交回执丢失按本次 operation_id 查证，不能证明则 UNKNOWN|
|结果与审计|最后保存尝试和已有草稿分开；最新资料快照与会话实际观察分开；业务审计同事务提交|

## 实际验证

开发环境与独立 wheel 环境各通过 **113 个 unittest 方法**，其中 M2 新增 43 个；subTest 的额外输入不另计，同组跨环境复跑不计成 226 个独立测试。

机器记录：[M2-summary.json](../examples/evaluation/M2-summary.json)。原始日志：[开发环境](../examples/evaluation/M2-development-tests.txt)、[独立 wheel](../examples/evaluation/M2-clean_wheel-tests.txt)。报告还记录编译、两环境依赖检查、独立安装来源、wheel SHA-256 和按 LF 归一化的源码指纹。

并发测试使用真实 SQLite 文件和两个线程，在两者均获得旧查询结果后才竞争写入。已验证不同请求只有一方获得 READY；同请求产生 CREATED/REUSED 且只有一份草稿；跨请求的相同待确认候选允许共存，确认时仅一方成功。此结果不等于多进程负载或断电恢复验证。

## 七组实际案例

统一重跑 `scripts/run_m2_examples.py`，每次新建本地账本。全部输入含明确的合成资料快照和可信驱动故障配置，未把故障参数交给工具。完整清单及文件哈希见 [M2-cases.json](../examples/evaluation/M2-cases.json)。

|场景|实际结果|输入 / 输出 / 逐步记录|
|---|---|---|
|正常|READY_DRAFTS；一份草稿、一项占用|[输入](../examples/inputs/M2-normal.json) / [输出](../examples/outputs/M2-normal.json) / [Trace](../examples/traces/M2-normal.jsonl)|
|信息缺失|M02 补查无来源，保持 NEEDS_INPUT，零草稿|[输入](../examples/inputs/M2-missing.json) / [输出](../examples/outputs/M2-missing.json) / [Trace](../examples/traces/M2-missing.jsonl)|
|规则风险|M03 版权争议 BLOCKED，零草稿|[输入](../examples/inputs/M2-risk.json) / [输出](../examples/outputs/M2-risk.json) / [Trace](../examples/traces/M2-risk.jsonl)|
|时段冲突|18 点占用，建议 19 点，待 TIME_CHANGE 确认，零占用|[输入](../examples/inputs/M2-conflict.json) / [输出](../examples/outputs/M2-conflict.json) / [Trace](../examples/traces/M2-conflict.jsonl)|
|重复提交|两个工具会话，第二次 REUSED，同一草稿 ID/版本|[输入](../examples/inputs/M2-duplicate.json) / [输出](../examples/outputs/M2-duplicate.json) / [Trace](../examples/traces/M2-duplicate.jsonl)|
|保存失败|写入草稿后注入故障，整体回滚；FAILED，零草稿/占用/回执|[输入](../examples/inputs/M2-save_failure.json) / [输出](../examples/outputs/M2-save_failure.json) / [Trace](../examples/traces/M2-save_failure.jsonl)|
|确认闭环|先待确认，再由可信合成用户命令同意当前版本，READY；仍未发布|[输入](../examples/inputs/M2-confirmation.json) / [输出](../examples/outputs/M2-confirmation.json) / [Trace](../examples/traces/M2-confirmation.jsonl)|

补查成功、文案阻断、人工风险确认、旧版本失效、来源冲突、候选撤回和保存未知等更细边界在集成测试中验证。

## 复跑命令

在仓库根目录，Python 3.13.x；M2 运行无需密钥或 .env。

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe scripts/run_m2_examples.py
```

独立安装复核与生成完整报告：

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir var/m2-wheel
py -3.13 -m venv var/m2-clean-venv
.\var\m2-clean-venv\Scripts\python.exe -m pip install --no-deps var/m2-wheel/material_scheduling_agent-0.2.0-py3-none-any.whl
.\.venv\Scripts\python.exe scripts/run_m2_examples.py
.\.venv\Scripts\python.exe scripts/verify_m2.py
```

已经装过该版本 wheel 而源码发生变化时，安装命令加 `--force-reinstall`。测试临时目录限制在 `var/m2-tests/` 并自动清理；案例账本留在忽略的 `var/m2-examples/` 以供检查，不提交数据库。案例重新运行会更新真实 ID、时间和证据文件；不要求字节完全相同。

## 设计落实与调整

小型合成资料被合并为 `catalog` 中单个经过完整验证的快照，代替为素材/规则/时段分别建表；草稿、占用、确认、审计与操作回执仍独立建表。理由是首版资料量小、以整体导入为主，整份快照保证事务读到同一资料版本，避免无必要的数据拆分。未承诺大规模检索性能。

ToolSession 负责权限、实际观察缓存与结果；SQLiteStore 的小接口封装事务并复用领域规则。确认用例目前为 `SQLiteStore.confirm`，后续 CLI/网页共同调用，不额外建空的 confirmation.py。`schedule_revision` 是包含资料代次和可见占用的 SHA-256 指纹，不是仅反映资料导入的整数。

`snapshot()` 会重新核验并可能将旧草稿标记为 STALE；未来 HTTP GET 不直接调用它，应通过明确的重新核验操作或独立只读投影。M2 只有内存实际工具记录和导出脚本，运行时 Trace 文件写失败防护留到 M3。

## 限制及发现

本轮检查修正了两处投影问题：时段版本原先只含资料导入代次，现纳入本地占用指纹；当前审核是否实际在本会话观察过，现比较快照身份，不能只检查曾调用过审核。均已有回归断言。

首次报告脚本使用 `unittest -t .` 时发现 tests/ 缺少包入口，测试发现报 ImportError；补充 tests/__init__.py 后按相同命令复跑。原失败保留在 [首次发现日志](../examples/evaluation/M2-initial-discovery-failure.txt)，不是业务测试失败。

提交后响应丢失由可信故障注入模拟，不是实际断电或磁盘损坏测试。来源矛盾采用保守阻断；不自动决定权威优先级。不具备视觉审核、真实平台同步、多人认证、高可用或分布式锁。当前全部 published=false。

M3 仍需落实模型选择动作、观察后继续决策、工具/模型/总时长预算、严格模型协议、CLI 和可靠 Trace。M4 配置真实模型后提交至少两条实际动态路径，不能用本阶段 7 组手动记录代替。

M1 历史证据在其基线 `3a23f01` 对应；M2 报告使用生成时基线提交及实际源码哈希，避免写入尚不存在的自引用提交号。项目实际投入未连续计时，不虚填三小时。
