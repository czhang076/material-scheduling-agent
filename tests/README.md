# 测试目录

合计 156 个 unittest 方法：M1/M2 的 113 个，加 M3 的 43 个。开发及独立 wheel 环境分别通过；subTest、重复环境和评估场景不另计测试方法数量。

unit/ 覆盖契约及领域规则；integration/ 覆盖合成资料、真实 SQLite、并发、循环与预算；adversarial/ 使用明确的测试模型替身验证越权、伪造成功、来源注入和预算篡改；acceptance/ 通过真实子进程运行 CLI、用户确认、14 组离线评估及 Trace/文件校验。

M3 还验证 20 项正常批量、截止时间后的提交事实、提交 UNKNOWN、Trace 写前/写后故障及最终输出文件失败。临时文件仅在校验后的 var/m2-tests/ 子目录清理（公共 LedgerTest helper 保留阶段名称）。没有真实模型、网页或多进程压力测试。

命令和原始证据见 [M3 验收](../docs/M3-ACCEPTANCE.md)。
