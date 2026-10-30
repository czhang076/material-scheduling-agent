# M3 离线 Agent、CLI 与 Trace 验收

2026-10-30 收口。**全部决策轨迹为确定性 Mock；没有调用真实模型，不作为完整 ReAct 达标依据。**

## 实现范围

|模块|实际职责|
|---|---|
|agent/decisions.py|提供者接口、单动作 JSON、拒绝多动作/额外字段/重复键/非有限数/非法 Unicode|
|agent/runner.py|提供真实观察历史、执行预算、计数、协议纠错、限时、取消、权限拒绝反馈、可信最终状态|
|agent/trace.py|实际事件 JSONL，写前意图、flush/fsync、序号/哈希链、完整起止检查|
|agent/prompt.py|安装包内提示正文，每次运行记录实际指纹|
|adapters/mock_model.py|依据实际观察选择补查、替代、重试、保存或结束；明确规则 Mock|
|application/tools.py|六个工具及同源参数 Schema；沿用 M2 的观察权限和业务约束|
|interfaces/cli.py|init/run/inspect/confirm/evaluate，JSON 输出及退出码|
|interfaces/artifacts.py|新运行目录、原子结果文件、实际清单、来源/代码/提示/工具/输出哈希|
|interfaces/evaluation.py|可信合成资料/故障/用户同意场景；复用 CLI run 的运行用例|

执行器不按业务风险写固定调度流程。它把请求、工具目录、预算及已发生的观察交给提供者；下一动作来自提供者。Mock 的条件分支是明确的替身策略，真实模型适配器仍待 M4。

## 实际验证

开发环境与独立 wheel 环境各通过 **156 个 unittest 方法**：M2 基础 113 个，本阶段新增 43 个；subTest、场景和环境不重复计数。记录见 [机器报告](../examples/evaluation/M3-summary.json)、[开发日志](../examples/evaluation/M3-development-tests.txt)、[独立安装日志](../examples/evaluation/M3-clean_wheel-tests.txt)。编译、两环境依赖检查、独立包来源和 wheel 源码一致性均有实际记录。

重点验证：实际观察进入下一轮、冲突与保存竞争后重规划、临时错误最多一次重试、提前结束不冒充成功、未知工具/伪造同意/未观察候选拒绝、协议错误和提供者失败有界、单项/全局/模型轮数/总时间/取消保护、20 项预算、Trace 写前/写后故障、输出文件失败及最终账本不可读。

20 项正常测试使用 20 个合成独立渠道，真实执行 81 次工具尝试并形成 20 份草稿，低于 201 上限；不把该结果推广为任意素材/渠道组合必然成功。

## 实际离线路径

正常：read_material → check_rules(PASS) → query_slots(requested，可用) → save_draft(READY) → finish。

冲突：read_material → check_rules(PASS) → query_slots(requested，无候选) → query_slots(alternatives，19 点) → save_draft(PENDING_CONFIRMATION) → finish。

占用变化：同请求第一轮建议 19 点；可信环境新增 19 点占用后，第二轮重新读取/审核/查询并建议 20 点，同一草稿 ID 的新版本，原始 18 点和待确认事项保留。Trace 中每个动作都对应实际工具观察。

## 场景索引

[M3-cases.json](../examples/evaluation/M3-cases.json) 链接全部输入、聚合输出、逐次原始结果、Trace、实际运行清单和文件校验值。共 **14 组场景、16 次运行**；重复和占用变化各运行两次。

|场景|预期及实际|关键证据|
|---|---|---|
|normal|READY_DRAFTS，一份 READY 草稿|[输入](../examples/inputs/M3-normal.json)、[结果](../examples/outputs/M3-normal.json)、[Trace](../examples/traces/M3-normal-run1.jsonl)|
|missing|补查无来源，NEEDS_INPUT，零草稿|[结果](../examples/outputs/M3-missing.json)|
|risk|版权争议 BLOCKED，零草稿|[结果](../examples/outputs/M3-risk.json)|
|conflict|18 点占用→19 点待确认，不预留|[结果](../examples/outputs/M3-conflict.json)、[Trace](../examples/traces/M3-conflict-run1.jsonl)|
|duplicate|第二次 REUSED，同 ID/版本，一份草稿|[结果](../examples/outputs/M3-duplicate.json)|
|save-failure|写后故障两次，均回滚，FAILED/退出 4|[结果](../examples/outputs/M3-save-failure.json)|
|tool-recovery|查询失败一次，观察后重试并完成|[结果](../examples/outputs/M3-tool-recovery.json)|
|supplement|补齐版权、重新审核后保存|[结果](../examples/outputs/M3-supplement.json)|
|changed-occupancy|同请求从19改20，新版本仍待确认|[结果](../examples/outputs/M3-changed-occupancy.json)、[第二轮 Trace](../examples/traces/M3-changed-occupancy-run2.jsonl)|
|confirmation|Mock 先建议；可信合成用户另行确认当前版本|[结果](../examples/outputs/M3-confirmation.json)|
|manual-risk|人工审核风险保留，待逐项确认|[结果](../examples/outputs/M3-manual-risk.json)|
|no-slots|所有可选占用，INCOMPLETE，零草稿|[结果](../examples/outputs/M3-no-slots.json)|
|limit|3 次工具后 LIMIT_REACHED，INCOMPLETE/退出 5|[结果](../examples/outputs/M3-limit.json)|
|unknown-save|提交已发生但回执查证失败，保存 UNKNOWN，整体 PARTIAL/退出 4|[结果](../examples/outputs/M3-unknown-save.json)|

确认不是模型动作，不补写到已结束的模型 Trace。实际用户命令和返回单独保留在 confirmation 聚合结果及业务审计；确认后仍 published=false。

## 预算和错误语义

每项默认 10 次工具尝试；全局 min(10×N+1,201)，含 finish；模型轮数全局工具上限+4，最高205；总秒数 min(180×N,1200)，单次提供者最多30秒。最多4次协议错误；提供者故障最多一次恢复机会。可信本地配置只能收紧。

未知项/未知工具/非法参数消耗全局额度；合法项的非法尝试也消耗该项额度。单项超过预算后仍可处理其他项；finish 不强制把业务标为完成。Trace 区分工具尝试、派发和通过参数检查的执行；最终状态重新核验计为一次 final_revalidations，不伪装成模型调用工具。

同动作及相同业务参数出现两次临时失败后，拒绝进一步重试；rationale 变化不重置身份。执行器不自动选择业务恢复工具，下一步仍由提供者选择。

task_status 受执行失败/上限约束，business_task_status 保留当前业务投影；items 中保留审核/资料缺口、原始要求、候选、待确认、已有草稿及本次 save_attempt。模型理由中的“已成功/已发布”不成为事实。最后状态不可读时返回 RESULT_UNAVAILABLE，保留最后已知保存回执，不能编造当前状态。

单调时钟在调用前后检查并将剩余秒数传给提供者。迟到的模型动作不会执行；工具已提交后才超时则保留提交事实并报告未完成。不能强杀任意阻塞 Python 代码或操作系统 I/O；真实网络超时由 M4 适配器落实并单独验证。

## Trace 与复现

每次运行在新目录生成 result.json、trace.jsonl、manifest.json。Trace 记录真实请求、提供者请求摘要、动作/参数/公开理由、工具意图、返回及停止状态；call_id 对应观察，model_requested 的上下文哈希对应实际输入。只记录公开动作，不输出内部思维过程或原始自由文本错误回复。

写工具意图持久化失败时阻止派发；写后观察丢失时停止运行，trace_complete=false，仍如实保留保存事实。输出文件失败也不撤销已确认提交。哈希链和清单用于内容一致性核对，不提供密码学来源认证或断电保证。

导出清单保留原 runtime_manifest，exported_files 映射原相对文件到仓库路径，不修改实际结果。报告记录生成时基线 `2d08270` 及 LF 源码指纹；不能自引用尚未创建的最终提交号。

## 可复制命令

基础运行见 [README](../README.md)和 [RUNBOOK](RUNBOOK.md)。独立安装及报告重建：

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir var/m3-wheel
py -3.13 -m venv var/m3-clean-venv
.\var\m3-clean-venv\Scripts\python.exe -m pip install --no-deps var/m3-wheel/material_scheduling_agent-0.3.0-py3-none-any.whl
.\.venv\Scripts\python.exe scripts/run_m3_examples.py
.\.venv\Scripts\python.exe scripts/verify_m3.py
```

源码变更后重建 wheel；安装过相同版本则加 --force-reinstall。脚本会真实调用 CLI，生成新 ID/时间，保留数据库于忽略的 var/，只导出选取的合成证据。

## 实际差异、失败及未完成

M3 提示位于安装包并保留设计语义，补充原生单动作 JSON 信封；实际提示/Schema 指纹写入每次清单。CLI 暂不读取 .env，所有离线参数显式传入。没有实现真实模式和 serve。

首轮未知保存评测将顶层预期写成 FAILED，而工具 UNKNOWN 且已存草稿存在时原投影为 PARTIAL。保留业务逻辑，修正预期并强制检查 UNKNOWN、退出4及实际一份草稿；原始差异见 [首次报告](../examples/evaluation/M3-initial-expectation-failure.json)。

最终输入检查发现超长整数触发 Python 数字解析限制，原 CLI 未将该 ValueError 包装为输入错误。现由共享 JSON 解析器统一转换，并拒绝指数溢出的非有限浮点数；CLI 和模型协议均增加回归边界。原始异常保留在 [输入失败日志](../examples/evaluation/M3-initial-numeric-input-failure.txt)，修正后重新构建 wheel 并复跑。

M4 尚需服务/模型配置、真实兼容协议和至少两条真实动态路径；M5 网页、M6 最终加固和 GitHub 交付仍未完成。合成规则不证明通用内容安全或视觉审核；本地占用不代表真实平台锁定，actor 不是多人认证。实际投入未连续计时，个人贡献仍须候选人如实补录。
