# 源码目录

已实现：domain 的严格契约、规则与原文证据、时间/状态；application 的 ToolSession、SaveEvidence 和纯 JSON 序列化；adapters 的合成资料加载、SQLiteStore 与可信故障注入。

ToolSession 控制六个工具及本会话观察权限，SQLiteStore 封装原子保存/确认/失效。application 不导入具体 SQLite 实现。领域不依赖数据库或模型。

Agent、CLI、HTTP 和网页仍未实现；详见 [架构](../docs/design/architecture.md)及 [M2 验收](../docs/M2-ACCEPTANCE.md)。
