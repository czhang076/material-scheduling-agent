# 环境、命令与交接

当前版本 0.6.0（M6 审查修复）。Python 3.13.x，标准库 SQLite 与 HTTP，零第三方运行依赖；构建依赖 setuptools==82.0.1。Node 是开发验证工具，不是运行网页的依赖。

## 安装与 CLI

在仓库根目录执行：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m material_scheduler init --data-dir data --db var/scheduler.sqlite3
.\.venv\Scripts\python.exe -m material_scheduler run --input data/requests/normal.json --mode mock --db var/scheduler.sqlite3 --out var/run-001
```

输出目录必须不存在；重复执行换证据目录、保留 request_id。init 是显式导入，资料变化可能使草稿失效；日常启动不必再次 init。业务输入是原始请求；examples/inputs/M3-*.json 是带资料与故障的评测封装，不能直接传给 run。

## 本地网页

```powershell
.\.venv\Scripts\python.exe -m material_scheduler serve --db var/scheduler.sqlite3 --state-dir var/workbench --port 8765
```

打开 [本地工作台](http://127.0.0.1:8765)，Ctrl+C 停止服务。默认 Mock。启动命令追加 --env-file .env 后，可在页面显式选择真实模型；浏览和刷新不会调用模型，密钥只在服务端。每个账本使用独立 state-dir，不能混用已有状态目录。

未知提交会显示原请求、原时间与原模式。编辑新要求后点击主运行按钮不会重发旧要求；先“查询原提交”，需要重发时明确点击“重试原提交”。同一请求重试使用同一业务身份。原提交未查明时，不通过新建任务绕过未知结果。

正常写入终态期间仍显示执行中。终态日志写入失败后，工作线程已结束但当前进程保留真实结果，以 INTERRUPTED / RUN_STATE_UNPERSISTED / state_persisted=false 显示状态待保存；GET 只读。存储恢复后，显式重新提交原 submission_id 会先保存原终态并查回同一运行；新提交也会先完成这一步，不会永久 RUN_BUSY。写入仍失败时返回503，不注册新请求。进程重启会丢失未持久化结果缓存，原运行按已有启动恢复逻辑标中断，草稿事实仍在；不能把进程内兜底描述为断电恢复。

## 检查与确认

```powershell
.\.venv\Scripts\python.exe -m material_scheduler inspect --db var/scheduler.sqlite3 --request-id REQ-DESIGN-A01
```

inspect 会重新核验并可能使草稿过期。网页 GET 使用独立只读投影；显式“重新核验”才会复核并留审计。确认使用实际草稿 ID、当前版本及全部待确认事项，例如：

```powershell
.\.venv\Scripts\python.exe -m material_scheduler confirm --db var/scheduler.sqlite3 --draft-id <实际草稿ID> --expected-version <当前版本> --confirmation-id C-LOCAL-001 --actor local-user --accept TIME_CHANGE
```

每项同意分别传 --accept；确认仍复核资料与占用，只形成可用草稿，不发布。actor 是本地审计标签。

## 当前测试与证据复跑

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -t . -v
node --test tests/web/state.test.cjs
.\.venv\Scripts\python.exe -m material_scheduler evaluate --data-dir data --out var/eval-m6-001
.\.venv\Scripts\python.exe scripts/run_m6_examples.py var/http-m6-001
```

当前 222 个 unittest 方法，另有7个 Node 状态控制器用例，分别计数。没有 Node 时只跳过 Python 套件内的网页状态桥接方法；Python/网页运行仍不需要 Node。开发完整验收应另运行 Node 用例。全部自动化使用 Mock 或协议替身，不读取本地密钥调用付费服务。

复跑输出到新目录，不能覆盖历史例证。M4 记录固定于 d48e50f，M5 固定于 9af839e，不能按当前源码重新解释。M1–M5 专用导出/验证脚本只在对应提交使用；M4 导出与 M4/M5 验证入口已加版本保护，当前版本会在写文件前拒绝。

## 独立 wheel 验证

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir var/m6-wheel
.\.venv\Scripts\python.exe -m venv var/m6-clean-venv
.\var\m6-clean-venv\Scripts\python.exe -m pip install --no-index --no-deps var/m6-wheel/material_scheduling_agent-0.6.0-py3-none-any.whl
.\.venv\Scripts\python.exe scripts/verify_m6.py
```

verify_m6 需要上述安装包环境、Node，以及仓库内已提交的 M6 证据。它复核包中源码/资源、两环境测试和历史证据完整性，更新 M6 检查日志；不重发真实模型调用。历史材料不改写。

## 退出码与恢复

run：0 全部可用草稿；2 业务需补充/确认、阻断或其他未完成；3 输入/身份/输出目录错误；4 工具/模型/存储/证据故障或保存未知；5 预算耗尽或取消。evaluate 的0表示各场景符合预期，失败场景仍必须如实失败。serve 正常停止返回STOPPED。

逐项 save_attempt、draft、incomplete_reasons、stop_reason、execution_status 和 trace_complete 共同说明事实。已有 READY 不能覆盖本次运行故障。UNKNOWN 保留原身份，重新核验；不盲目更换请求再保存。

## 真实模式及交付

真实模式显式运行 run --mode real --env-file .env，或服务带该配置并在网页明确选真实模式；会产生API用量。配置与网络边界见 [M4验收](M4-ACCEPTANCE.md)。旧M4/M5路径保留原提交边界。随后提交前严格验收另跑了当前0.6.0的8次CLI和2次网页真实路径，共51次调用，详见 [最终验收报告](FINAL-ACCEPTANCE.md)。

当前最终证据可执行只读复核：`python examples/final-acceptance/verify_evidence.py`，不会调用付费模型。付费重新生成8条真实CLI路径使用同目录reproduce_real.py，参数和干净环境说明见最终验收报告；始终输出到新目录。

交接先读AGENTS → CONTEXT → STATUS → 需求/方案 → [最终技术验收](FINAL-ACCEPTANCE.md)。数据库及本地配置在忽略的var/与.env；仅保留合成证据。GitHub公开地址和匿名可读验证见 [GITHUB-DELIVERY](GITHUB-DELIVERY.md)。提交题号1、仓库URL及远程main最终SHA；个人投入约4小时（估算，未连续计时），协作分工见04-ai-usage；招聘系统提交由本人完成。
