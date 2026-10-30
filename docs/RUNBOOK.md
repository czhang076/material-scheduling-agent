# 环境、预期操作与交接

## 1. 当前可用内容

M2 Python 包、真实 SQLite 工具、113 个测试和 7 组手动工具案例可复跑，命令及结果见 [M2-ACCEPTANCE](M2-ACCEPTANCE.md)。运行 scripts/run_m2_examples.py 无需 .env 或密钥。下方的 Agent CLI/网页命令仍是规划，不是现有功能。

已验证 Python 3.13.12 下的 M2 editable 与独立 wheel 安装，以及 SQLite 事务、重启和双线程争用；未做性能、断电或多进程压力验证。

## 2. 后续环境策略

- 目标 Python 3.13.x，在项目独立虚拟环境内安装。
- M2 无第三方运行依赖，pyproject.toml 固定构建后端；后续模型/网页依赖另记录。
- requirements.txt 说明实际依赖；.env.example 仍是后续配置占位，尚无读取实现。
- 已完成独立 wheel 环境复跑，不使用全局站点包；命令见 M1 验收。
- 离线模式不需要密钥；真实模式未配置时应明确报错，不静默改为 Mock。

## 3. 预期 CLI（尚未实现）

|操作|拟定命令形状|预期效果|
|---|---|---|
|导入合成资料|`python -m material_scheduler init --data-dir data --db var/scheduler.sqlite3`|校验后导入资料、规则和排期|
|离线运行|`python -m material_scheduler run --input examples/inputs/A01.json --mode mock --out var/A01`|实际输出、Trace、运行清单|
|真实运行|同上，将模式设为 `real`|使用本地模型配置，明确记录服务及模型|
|检查草稿|`python -m material_scheduler inspect --request-id REQ-DEMO-001`|重新核验并输出当前草稿|
|用户确认|`python -m material_scheduler confirm --draft-id D001 --expected-version 1 --accept TIME_CHANGE --actor local-user --confirmation-id C001`|逐项同意并原子复核；仍仅草稿|
|评估|`python -m material_scheduler evaluate --mode mock`|运行验收集，保存真实结果|
|本地工作台|`python -m material_scheduler serve --host 127.0.0.1`|CLI 核心完成后提供本地页面；命令、端口和框架尚未实现|

这些命令参数尚未成为稳定接口，具体实现后统一更新 README 和文档。

## 4. 退出码计划

0：请求已全部形成可用草稿；2：需要用户补充或确认、风险阻断、部分完成；3：输入/身份错误；4：工具、存储或模型运行失败；5：达到预算/超时。JSON 里的逐项状态和停止原因比单个退出码更具体。

## 5. 复跑与恢复原则

重试复用 request_id；先检查草稿再执行恢复，不更换请求 ID 规避防重复。UNKNOWN 保存结果先核验，STALE 草稿先重新规划，旧版本确认不能复用到新版本。

运行数据库放在 `var/`，不要提交。选择脱敏的合成实际输出存入 `examples/`；保留模式、数据版本、代码 commit 和命令。

## 6. Git 与 GitHub

当前已有本地 M1 基线及 M2 收口记录；不配置远程、不推送，不把阶段 SHA 当成最终交付 SHA。后续实际提交时再确认目标 GitHub 仓库及评审访问权限。

## 7. 交接顺序

先读 AGENTS → CONTEXT → STATUS → 需求/总体方案 → 本次涉及的详细设计。当前已完成 M1/M2；下一阶段 M3。注意 snapshot() 是重新核验操作，可使草稿过期，未来 HTTP GET 应使用只读投影。
