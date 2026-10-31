# 源码目录

已实现 domain、application、agent、adapters 和 CLI。AgentRunner 控制单动作协议、预算、时间、观察历史和 Trace；ObservationMock 只依据传入观察选择动作，明确为确定性离线策略。ToolSession 控制权限和实际审核/候选证据；SQLiteStore 封装保存、确认、失效和原子事务。

application 不导入具体适配器，domain 不依赖数据库或模型。CLI 是组合入口，用户确认独立于模型工具。运行目录和清单由 interfaces/artifacts.py 管理，可信离线场景由 interfaces/evaluation.py 组装。

model_config 与 compatible_model 使用标准库 HTTP、原生工具调用、严格回传及错误处理，真实模式复用 AgentRunner。CLI 不接受密钥参数，只显式读本地环境文件或进程环境。M5已实现本地HTTP和原生网页；M6修复未知提交保护、异步记录隔离及运行终态写入失败恢复，见 [M6验收](../docs/M6-ACCEPTANCE.md)。

Workbench持有业务用例与运行journal；业务规则仍由原SQLiteStore执行。GET通过只读投影展示账本及未持久化终态的明确降级状态，显式POST才重试终态写入。网页按加载代次、run_id和序号隔离事件，不能把晚返回的旧记录追加到新任务。
