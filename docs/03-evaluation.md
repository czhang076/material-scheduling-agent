# 效果验证与限制

M5 已实现本地网页；当前测试与历史模型实证分别记录。

|验证对象|实际结果|证据边界|
|---|---|---|
|确定性、SQLite、循环、CLI与对抗、网页|214个方法，两环境分别通过|M5新增30个方法；不按环境重复计数|
|M4新增配置/传输/协议|28个新增方法，含真实回环HTTP|协议fixture不是实际模型效果|
|Mock评估|14组场景16次运行符合预期|验证流程及故障，不证明模型决策|
|真实DeepSeek|7次运行符合预期，含六项必验和占用变化|实际网络模型动作，有服务回执；是有限合成样本|
|网页HTTP与交互|6组HTTP + Mock案例、桌面/手机浏览器检查|真实本地服务；Mock不证明模型效果|
|生产级调度/真实发布|未实现或验证|无对应结论|

机器记录：[M4-summary](../examples/evaluation/M4-summary.json)、[开发测试](../examples/evaluation/M4-development-tests.txt)、[独立wheel测试](../examples/evaluation/M4-clean_wheel-tests.txt)。真实数据入口为 [M4-real-cases](../examples/evaluation/M4-real-cases.json)，Mock入口为 [M4-mock-cases](../examples/evaluation/M4-mock-cases.json)；两份清单分别关联输入、输出、Trace、运行清单和哈希。细节见 [M4 验收](M4-ACCEPTANCE.md)。

正常真实路径实际选择读取→审核→目标时段查询→保存→结束；冲突路径先收到18点不可用，再查询替代19点并保存待确认。相同请求重复时复用原草稿；新增19点占用后重跑改建议20点，原始18点和确认要求保留。另有资料不足、规则风险和本地保存故障下的真实模型行为。风险结论和写入保护仍由确定性工具执行。

真实记录中的 Provider metadata 包含请求/响应内容哈希、原始调用ID、服务响应ID和用量；不保存密钥或内部思考。raw result/manifest 中真实验证字段为 null，表示运行时不自证；独立评测检查动作/观察与实际账本后才给出 real_react_verified。API模式 real 或回环fixture本身不作为真实性证明。

本轮HTTP测试曾发现完整HTTP/1.0响应读完后底层socket自动关闭，继续设置读超时会被误报为连接失败；修正为识别响应正常结束，同时仍拒绝截断正文。原失败日志保留在 [M4-initial-http-failure](../examples/evaluation/M4-initial-http-failure.txt)，修复后复跑。M3历史输入修正及预期差异按其阶段报告保留。

限制：7次真实运行不是统计可靠的成功率或通用模型遵循率；模型返回别名不证明底层固定快照；HTTP fixture不证明所有第三方兼容服务；哈希链不提供来源签名；socket截止时间不能强杀系统DNS或任意阻塞I/O；故障注入不等于断电恢复；本地READY不表示平台锁时段；合成规则不证明视觉或完整安全审核；actor不是多人认证。

当前测试摘要见 [M5-summary](../examples/evaluation/M5-summary.json)，业务输入/实际输出/Trace 见 [M5-http](../examples/workbench/http/manifest.json)，实际交互见 [浏览器检查](../examples/workbench/M5-browser-checks.json)。M4 记录固定于 d48e50f，仅检查文件未变与 Trace 完整，不宣称它与当前源码指纹相同。M5 的网页真实运行按独立记录解释。

新增测试覆盖会话/同源、严格 JSON、只读查询、明确核验审计、重传/重跑差异、版本确认、资料变化、运行恢复和事件写入失败。浏览器实际发现 STALE_REVIEW 错误映射和当前状态同步问题；补冲突映射和回归后重测成功，见 [M5验收](M5-ACCEPTANCE.md)。

完整提交仍需 M6、候选人真实贡献记录及GitHub交付。原始模型行为如实保存，不通过修改Trace或预设决策日志制造模型效果。
