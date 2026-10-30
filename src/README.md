# 源码目录

已实现 domain、application、agent、adapters 和 CLI。AgentRunner 控制单动作协议、预算、时间、观察历史和 Trace；ObservationMock 只依据传入观察选择动作，明确为确定性离线策略。ToolSession 控制权限和实际审核/候选证据；SQLiteStore 封装保存、确认、失效和原子事务。

application 不导入具体适配器，domain 不依赖数据库或模型。CLI 是组合入口，用户确认独立于模型工具。运行目录和清单由 interfaces/artifacts.py 管理，可信离线场景由 interfaces/evaluation.py 组装。

真实模型适配器、HTTP 和网页仍未实现。详见 [M3 验收](../docs/M3-ACCEPTANCE.md)。
