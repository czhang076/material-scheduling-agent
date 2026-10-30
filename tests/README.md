# 测试目录

M1 的 70 个方法加 M2 新增 43 个，共 113 个 unittest 方法，在开发与独立 wheel 环境通过；subTest 和复跑不重复计数。

unit/ 覆盖严格契约及领域规则。integration/ 覆盖真实合成文件、SQLite 事务与重启、来源补查与矛盾、确认版本、防重复、故障回滚/UNKNOWN、真实线程争用和数据库防重叠触发器。临时账本限制在 var/m2-tests/ 内，验证路径后清理。

acceptance/、adversarial/ 保留后续 Agent 验收位置；没有把 113 个方法等同于全部 Agent 场景通过。模型协议、预算、完整 Agent 和网页留到后续。命令及证据见 [M2 验收](../docs/M2-ACCEPTANCE.md)。
