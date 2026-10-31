# M5 本地网页工作台验收

2026-10-31；版本 0.5.0。CLI 仍为完整复现入口，网页为本地单用户操作入口。没有线上部署、多人登录或真实发布。

## 运行

在仓库根目录安装后：

```powershell
.\.venv\Scripts\python.exe -m material_scheduler init --data-dir data --db var/workbench.sqlite3
.\.venv\Scripts\python.exe -m material_scheduler serve --db var/workbench.sqlite3 --state-dir var/workbench --port 8765
```

浏览器打开 http://127.0.0.1:8765 。默认离线 Mock；需要真实模型时，服务启动命令追加 `--env-file .env`，页面再明确选择真实模式。仅启动或浏览页面不调用模型。Ctrl+C 停止服务。初始化是导入操作，已有资料变更可能使草稿过期；日常启动只执行 serve。

## 实现与验证

新增 30 个 unittest 方法，合计 214 个；包含真实回环 HTTP、并发提交、恢复和共享账本测试。开发与独立 wheel 两环境的实际结果见 [M5-summary](../examples/evaluation/M5-summary.json)。静态资源随 wheel 分发，前端无需 Node 或构建工具；Node 仅用于开发时的语法检查。

6 组 HTTP + Mock 业务用例实际生成输入、响应、账本计数和 Trace：[manifest](../examples/workbench/http/manifest.json)。覆盖正常、信息不足、阻断风险、冲突与用户确认、重复提交、保存失败。离线证据不证明模型决策效果。浏览器实际检查见 [记录](../examples/workbench/M5-browser-checks.json)；截图为 [桌面](../examples/workbench/M5-desktop.png) / [手机](../examples/workbench/M5-mobile.png)，截图不替代代码和 Trace。

|计划|检查及实际结果|证据|
|---|---|---|
|W01|素材、草稿、历史、实际工具动作；表单切换真实模式不改变旧 Mock 运行标识|浏览器记录；normal HTTP 用例|
|W02|确认项默认全不选；风险与时间变更须逐项接受；资料改变后旧面板保留旧版本，服务拒绝并展示 STALE|浏览器记录；changed_source / wrong_version / incomplete_confirmation 测试|
|W03|双击只一次提交；重复提交 ID 查回原运行；显式重跑复用草稿；重复确认只一条确认|浏览器记录；duplicate / conflict-confirm HTTP 用例|
|W04|断网显示结果待查询；重连与刷新查原任务，不自动提交；仅本地保存运行/提交编号|浏览器记录；submission / readonly 测试|
|W05|HTML 原样显示；无注入节点或执行；emoji 后风险片段准确高亮|浏览器 literal-html-codepoint-evidence；catalog 测试|
|W06|严格请求、无发布端点、Host/Origin/会话/防伪标记校验；伪造成功字段拒绝|HTTP 边界测试|
|W07|重开 journal 将活动记录标记 INTERRUPTED，保留草稿；同一账本或状态目录只一个服务所有者|journal_restart / owner 测试；浏览器完成任务的服务重启恢复|
|W08|GET 使用只读事务；显式 POST 复核留下审计；不启动模型|readonly / revalidation 测试|

W07 的活动任务恢复使用重新打开持久化 journal 的自动化测试，未把它称为操作系统断电实验。浏览器重启检查对象是已完成任务。

## 关键取舍

沿用 Python 标准库 HTTP + SQLite，以及原生 HTML/CSS/JavaScript，保持零第三方运行依赖。页面不另写业务审核、候选和确认规则；工作线程调用同一 run_request，用 FileTrace 的实际事件回调记录持久化进度。模型调用不会阻塞页面查询。

业务数据库和运行 journal 分开。request_id 约束业务身份；submission_id 约束一次 HTTP 提交，确认仍使用 confirmation_id。新操作可以明确重跑同一请求，已结束操作的重传则始终查回原运行。运行状态 FINISHED 只表示后台调用结束，业务失败、保存未知和证据缺口仍单独展示。

GET 只返回持久化草稿状态及当前资料预览；不替代新的事务校验。保存、确认、导入和显式核验承担状态变化。旧结果与当前账本分开，用户确认后不会改写历史的待确认输出。

## 实际失败与修正

首轮新测试中有素材编号、故障点名称和重复回执字段使用错误，按既有数据契约修正测试；没有放宽业务规则。显式复核未变化时原先无审计，现补 REQUEST_REVALIDATED。浏览器发现 STALE_REVIEW 未映射为冲突、确认失败后当前状态未同步，补 409 映射与回归；旧面板仍保持原版本。检查还修正了“已有 READY 草稿遮蔽运行/证据失败”的横幅判断。

最初使用不隔离构建时开发环境没有 setuptools，构建失败；按 pyproject 锁定的构建依赖正常隔离构建成功。未改变零运行依赖的约定。

## 限制与后续

本地单用户、默认回环监听，actor 是审计标签而非认证；不适合直接开放到公网。当前同一服务仅一个活动运行，历史列表最多 50、草稿列表最多 200；更早记录仍可按 ID 查询，无删除/归档 UI。没有 SSE、多人协作、跨设备恢复或持久化表单内容。网络未知提交刷新后仅查询编号，未登记时需要用户核对历史并重新提供原要求。

M4 的 7 次 DeepSeek 实证固定在 d48e50f，当前验证仅检查其文件未改及 Trace 完整，不冒充新版本的重新运行。

M5 另在浏览器明确选择真实 DeepSeek，实际跑通一次正常链路：读取 → 审核 → 查询 20:00 → 保存 → 结束，共 5 次模型调用，当前草稿 READY、硬性原始时间未变、未发布。当前版本的运行包指纹、原生服务回执、输出、Trace 与账本见 [独立评估](../examples/workbench/real-normal/assessment.json)。这是网页真实接入验证，不是一轮新的七场景模型评测；runtime result/manifest 的真实验证字段保持原值，由独立评估给出检查结论。

最终 M6、候选人亲自阅读/修改/复跑记录、实际工时补录和 GitHub URL/最终 SHA 尚未完成。
