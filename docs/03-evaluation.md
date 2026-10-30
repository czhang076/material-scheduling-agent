# 效果验证与限制

**M3 离线 Agent/CLI 已完成验证；真实模型未接入。**

|对象|实际结果|证据含义|
|---|---|---|
|确定性领域与 SQLite|M1/M2 的 113 个方法继续通过|已测规则、事务、确认、来源和并发符合预期|
|M3 循环、CLI、Trace 与对抗|新增 43 个方法，合计 156 个在两环境通过|协议、观察反馈、预算、权限、证据错误和实际命令可复跑|
|离线场景|14 组、16 次实际运行通过各自预期|同一执行器有不同实际路径，全部明确 mock|
|20 项规模|20 个合成独立渠道场景，81 次工具尝试完成|默认预算支持已测正常批量，不承诺任意任务成功|
|真实模型|未实现/未运行|没有真实 ReAct 或模型准确率结论|
|网页、视觉与线上发布|尚未实现|没有相关效果或运行结论|

详细命令及验收矩阵见 [M3-ACCEPTANCE](M3-ACCEPTANCE.md)。实际记录：[机器摘要](../examples/evaluation/M3-summary.json)、[开发日志](../examples/evaluation/M3-development-tests.txt)、[独立 wheel 日志](../examples/evaluation/M3-clean_wheel-tests.txt)、[场景清单](../examples/evaluation/M3-cases.json)。清单逐一引用 examples/inputs、outputs、traces 和运行清单及校验值。

156 为 unittest 方法数量，subTest、14 个场景及两个环境不累加为独立测试数。场景预期包括 NEEDS_INPUT、BLOCKED、FAILED、PARTIAL 和 INCOMPLETE，不把这些状态统一包装成业务成功。

两条离线路径：正常 read→check→query requested→save→finish；冲突 read→check→query requested（无候选）→query alternatives→save 待确认→finish。changed-occupancy 在同一请求第二次执行前新增 19 点占用，从原建议 19 点变为 20 点，保持草稿身份并增加版本。上述决策来自规则 Mock，真实模型阶段须重跑。

覆盖的故障包括模型协议错误/提供者失败、工具短暂失败与有限重试、保存回滚/UNKNOWN、工具和模型预算、截止时间、取消、提前结束、伪造同意、上下文篡改、来源提示注入、Trace 写前/写后故障及最终输出文件失败。已保存事实与执行失败、已有草稿与本次保存尝试分别报告。

首轮未知保存案例的顶层预期曾写成 FAILED，实际是 PARTIAL：工具标记 UNKNOWN，但落库草稿客观存在。保持原投影语义，修正预期为 PARTIAL，并继续要求 UNKNOWN、退出码 4 和一份实际草稿。原报告保留在 [首次预期差异](../examples/evaluation/M3-initial-expectation-failure.json)，没有修改业务逻辑掩盖失败。

限制：Mock 通过不证明真实模型决策；超时使用单调时钟、调用前后检查并传递剩余时间，不能强杀任意阻塞 Python 函数或操作系统 I/O；哈希链提供内容完整性核对，不提供来源签名；故障注入不等于断电测试；双线程不是多进程压力测试；本地 READY 不是平台锁定；操作者标签不是多人认证；固定偏移不推断 DST；合成规则不证明视觉或通用安全审核。

M4 仍需真实服务协议和至少两条动态路径；M5/M6 仍需网页及最终加固/GitHub 交付。M1/M2 证据按其阶段提交解释，不要求旧哈希匹配当前版本。
