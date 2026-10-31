# 环境、命令与交接

## 已验证环境

Python 3.13.x（本机 3.13.12）、标准库 SQLite，无第三方运行依赖；setuptools==82.0.1 构建。M4 开发与独立 wheel 环境均可运行，具体记录见 [M4 验收](M4-ACCEPTANCE.md)。

离线不需要 .env 且不读取模型配置。真实模式显式传 --env-file .env 或使用进程MODEL_变量，缺配置明确失败，不降级为Mock。用户已授权DeepSeek试用，当前有真实路径。

## 当前实际命令

在仓库根目录执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m material_scheduler init --data-dir data --db var/scheduler.sqlite3
.\.venv\Scripts\python.exe -m material_scheduler run --input data/requests/normal.json --mode mock --db var/scheduler.sqlite3 --out var/run-001
.\.venv\Scripts\python.exe -m material_scheduler inspect --db var/scheduler.sqlite3 --request-id REQ-DESIGN-A01
.\.venv\Scripts\python.exe -m material_scheduler evaluate --data-dir data --out var/eval-001
```

输出目录必须不存在，重复运行需新目录；请求 ID 继续复用。init 是显式导入，会根据最新资料使旧草稿过期。inspect 是重新核验，会改变陈旧草稿状态；不能将它直接用于未来网页的只读 GET。

confirm 的实际形状：`python -m material_scheduler confirm --db <账本> --draft-id <实际ID> --expected-version <当前版本> --confirmation-id <本次同意ID> --actor local-user --accept TIME_CHANGE`。每项待确认事项分别传 --accept，不能遗漏或多接受。可用 --note 附用户说明。确认不发布。

run 支持收紧 --max-tool-attempts、--max-model-rounds、--per-item-tool-limit、--run-timeout-seconds、--model-timeout-seconds，不允许提高默认值。各项仍须满足 ExecutionLimits 的关联约束。

`examples/inputs/M3-*.json` 是评测封装，含 request、可信资料和可信故障；CLI run 只接受 request 原始结构。示例索引给出每次实际结果、Trace 与清单。

## 退出码和恢复

|退出码|含义|
|---|---|
|0|run 全部可用草稿；或 init/inspect/confirm 操作成功；evaluate 全部满足各自预期|
|2|业务需补充/确认、规则阻断、没有可用候选或其他业务未完成|
|3|请求/CLI 参数/身份冲突或已有输出目录|
|4|工具、提供者、存储、证据故障，或保存 UNKNOWN|
|5|执行限额、总截止时间或取消|

JSON 中的逐项审核、save_attempt、draft、incomplete_reasons、stop_reason 和 trace_complete 是具体依据。business_task_status 保留最新业务投影；task_status 还受运行失败或限额约束。stop_reason=MODEL_FINISHED 仅表示选择了 finish，不等于业务全部完成。

重复执行保持 request_id；UNKNOWN 不盲目新建请求，使用原身份重新核验。STALE 先重新审核/查询，旧确认不用于新版本。输出文件或 Trace 失败可能发生在提交后，须保留已存草稿并重跑到新证据目录。

## 测试和重建

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
.\.venv\Scripts\python.exe scripts/run_m4_offline.py
```

独立 wheel 验证步骤见 [M4-ACCEPTANCE](M4-ACCEPTANCE.md)。M1/M2/M3 脚本在对应阶段提交上重现旧报告；当前用M4脚本。verify_m4不重发付费调用，真实复跑另用run_m4_real.py。

实际数据库在 var/ 内，已忽略。离线评估的注入参数由可信评测器提供，不出现在模型工具参数中。examples/ 仅提交已选取的合成 JSON/JSONL、日志和校验记录。

## 后续和交接

先读 AGENTS → CONTEXT → STATUS → 需求/总体方案 → 相关设计。M4真实接入已完成，密钥只留本地；M5 本地网页仍待实现，无 serve 命令或线上部署。

本地已有阶段提交；无 GitHub 远程或推送。最终仓库 URL、评审访问权限及最终 SHA 留到完整交付阶段。实际投入未连续计时，候选人需如实补记。

## 真实模式

先按 .env.example 配置本地 .env，再运行 `python -m material_scheduler run --input data/requests/normal.json --db var/scheduler.sqlite3 --mode real --env-file .env --out var/real-001`。服务、模型、token字段及上限在配置中显式记录；同名进程环境优先，不自动展开变量。DeepSeek用非思考模式；其他服务须另行验证。

真实run依然使用同一事务和预算保护。终态鉴权/无效请求错误不会反复请求，临时限流或服务失败最多一次恢复。原始真实验证字段null由独立评测补足，不因mode=real就自称达标。详情和官方协议来源见M4验收。
