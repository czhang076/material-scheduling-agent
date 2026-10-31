# 效果验证与限制

0.6.0已完成最终独立严格验收，当前结果以 [FINAL-ACCEPTANCE](FINAL-ACCEPTANCE.md)为入口；M4/M5/M6阶段记录保留其原始时间和提交边界。

## 当前版本的题面验收入口

以下均来自最终独立验收的实际DeepSeek调用。输入为CLI请求；各目录的input.json另含完整合成资料及可信故障配置。输出和Trace为原始运行文件，未按预期改写。

|验收点|实际结果|输入 / 实际输出 / Trace|
|---|---|---|
|正常排期|18:00可用，READY_DRAFTS；一份草稿、一条预留|[输入](../examples/final-acceptance/real/normal/request.json) / [输出](../examples/final-acceptance/real/normal/run/result.json) / [Trace](../examples/final-acceptance/real/normal/run/trace.jsonl)|
|信息缺失|补查后仍不足，NEEDS_INPUT；无草稿|[输入](../examples/final-acceptance/real/missing/request.json) / [输出](../examples/final-acceptance/real/missing/run/result.json) / [Trace](../examples/final-acceptance/real/missing/run/trace.jsonl)|
|阻断风险|M03版权风险，BLOCKED；无草稿|[输入](../examples/final-acceptance/real/blocked-risk/request.json) / [输出](../examples/final-acceptance/real/blocked-risk/run/result.json) / [Trace](../examples/final-acceptance/real/blocked-risk/run/trace.jsonl)|
|人工确认风险|M04形成待确认草稿；模型未自行确认|[输入](../examples/final-acceptance/real/manual-risk/request.json) / [输出](../examples/final-acceptance/real/manual-risk/run/result.json) / [Trace](../examples/final-acceptance/real/manual-risk/run/trace.jsonl)|
|时段冲突|18:00被占用后再查19:00；保留硬性18:00要求，TIME_CHANGE待确认|[输入](../examples/final-acceptance/real/conflict/request.json) / [输出](../examples/final-acceptance/real/conflict/run/result.json) / [Trace](../examples/final-acceptance/real/conflict/run/trace.jsonl)|
|重复提交|重跑normal同一请求，REUSED；草稿ID/版本不变、仍只有一份|[输入](../examples/final-acceptance/real/duplicate/request.json) / [输出](../examples/final-acceptance/real/duplicate/run/result.json) / [Trace](../examples/final-acceptance/real/duplicate/run/trace.jsonl)|
|更换占用后重复|在conflict账本新增19:00占用后，模型建议20:00；沿用草稿ID、增加版本、仍待确认|[输入](../examples/final-acceptance/real/changed-occupancy/request.json) / [输出](../examples/final-acceptance/real/changed-occupancy/run/result.json) / [Trace](../examples/final-acceptance/real/changed-occupancy/run/trace.jsonl)|
|保存失败|可信工具注入持久写入故障；真实模型观察失败后重试并停止，FAILED；事务回滚、无草稿或预留|[输入](../examples/final-acceptance/real/save-failure/request.json) / [输出](../examples/final-acceptance/real/save-failure/run/result.json) / [Trace](../examples/final-acceptance/real/save-failure/run/trace.jsonl)|

各目录assessment.json记录独立账本核对结果，汇总见 [8条真实CLI路径](../examples/final-acceptance/real/manifest.json)。保存失败的 [合成资料及故障配置](../examples/final-acceptance/real/save-failure/input.json)由可信验收入口注入，不由模型设置。失败场景“验收通过”表示如实失败。

调用上限的实际负向案例见 [limit输入](../examples/final-acceptance/offline/limit/input.json)、[输出](../examples/final-acceptance/offline/limit/run-1/result.json)及 [Trace](../examples/final-acceptance/offline/limit/run-1/trace.jsonl)：第3次工具调用后明确返回INCOMPLETE / LIMIT_REACHED。该例为离线流程验证，不作为真实模型效果证明。

当前 [222项测试日志](../examples/final-acceptance/clean-unittest.txt)、[7项Node测试日志](../examples/final-acceptance/node-state.txt)、[独立安装检查](../examples/final-acceptance/installation.json)、[网页确认与交互检查](../examples/final-acceptance/web/browser-checks.json)均存放在examples。下文M4/M5/M6数字为各阶段原始记录，不能与最终验收重复累计为成功率。

证据中的GitHub、个人用时及完整交付未完成字段固定于技术验收时点，不改写历史快照；后续公开交付已另行验证，见 [交付记录](GITHUB-DELIVERY.md)。候选人随后自报累计投入约4小时（估算，未连续计时），见 [个人投入记录](04-ai-usage.md)。题面允许AI辅助，并不要求必须另写一段个人代码才能提交，但个人贡献与AI范围必须如实陈述。

## 阶段验证与已知限制

|验证对象|实际结果|证据边界|
|---|---|---|
|确定性、SQLite、循环、CLI与对抗、网页|222个方法，两环境分别通过|M6新增8个方法；不按环境重复计数|
|M4新增配置/传输/协议|28个新增方法，含真实回环HTTP|协议fixture不是实际模型效果|
|Mock评估|14组场景16次运行符合预期|验证流程及故障，不证明模型决策|
|真实DeepSeek|7次运行符合预期，含六项必验和占用变化|实际网络模型动作，有服务回执；是有限合成样本|
|网页HTTP与交互|6组HTTP + Mock案例、桌面/手机浏览器检查|真实本地服务；Mock不证明模型效果|
|M6审查回归|另7个Node状态用例、1组终态故障/恢复、实际浏览器复查|外壳测试与真实浏览器分开；本轮未重发付费模型|
|最终独立真实验收|当前版本8次CLI、2次网页，共51次DeepSeek调用，均符合预期|来自干净安装；有限合成样本；CLI保存失败为明确的可信工具故障注入|
|生产级调度/真实发布|未实现或验证|无对应结论|

机器记录：[M4-summary](../examples/evaluation/M4-summary.json)、[开发测试](../examples/evaluation/M4-development-tests.txt)、[独立wheel测试](../examples/evaluation/M4-clean_wheel-tests.txt)。真实数据入口为 [M4-real-cases](../examples/evaluation/M4-real-cases.json)，Mock入口为 [M4-mock-cases](../examples/evaluation/M4-mock-cases.json)；两份清单分别关联输入、输出、Trace、运行清单和哈希。细节见 [M4 验收](M4-ACCEPTANCE.md)。

正常真实路径实际选择读取→审核→目标时段查询→保存→结束；冲突路径先收到18点不可用，再查询替代19点并保存待确认。相同请求重复时复用原草稿；新增19点占用后重跑改建议20点，原始18点和确认要求保留。另有资料不足、规则风险和本地保存故障下的真实模型行为。风险结论和写入保护仍由确定性工具执行。

真实记录中的 Provider metadata 包含请求/响应内容哈希、原始调用ID、服务响应ID和用量；不保存密钥或内部思考。raw result/manifest 中真实验证字段为 null，表示运行时不自证；独立评测检查动作/观察与实际账本后才给出 real_react_verified。API模式 real 或回环fixture本身不作为真实性证明。

本轮HTTP测试曾发现完整HTTP/1.0响应读完后底层socket自动关闭，继续设置读超时会被误报为连接失败；修正为识别响应正常结束，同时仍拒绝截断正文。原失败日志保留在 [M4-initial-http-failure](../examples/evaluation/M4-initial-http-failure.txt)，修复后复跑。M3历史输入修正及预期差异按其阶段报告保留。

限制：7次真实运行不是统计可靠的成功率或通用模型遵循率；模型返回别名不证明底层固定快照；HTTP fixture不证明所有第三方兼容服务；哈希链不提供来源签名；socket截止时间不能强杀系统DNS或任意阻塞I/O；故障注入不等于断电恢复；本地READY不表示平台锁时段；合成规则不证明视觉或完整安全审核；actor不是多人认证。

M5阶段测试摘要见 [M5-summary](../examples/evaluation/M5-summary.json)，阶段输入/实际输出/Trace见 [M5-http](../examples/workbench/http/manifest.json)，阶段交互见 [浏览器检查](../examples/workbench/M5-browser-checks.json)。M4记录固定于d48e50f，M5固定于9af839e；不宣称旧运行与当前源码指纹相同。

新增测试覆盖会话/同源、严格 JSON、只读查询、明确核验审计、重传/重跑差异、版本确认、资料变化、运行恢复和事件写入失败。浏览器实际发现 STALE_REVIEW 错误映射和当前状态同步问题；补冲突映射和回归后重测成功，见 [M5验收](M5-ACCEPTANCE.md)。

M6审查修复已有独立记录；AI辅助范围和用户实际选择已如实记录，GitHub随后已公开交付。个人投入已按本人自报约4小时估算补录，不能将Codex操作记为本人亲自操作。原始模型行为如实保存，不通过修改Trace或预设决策日志制造模型效果。

上述M4/M5链接是历史阶段材料，分别固定d48e50f/9af839e。M6摘要为 [M6-summary](../examples/evaluation/M6-summary.json)，恢复记录为 [M6 manifest](../examples/workbench/M6/manifest.json)，修复关系见 [M6验收](M6-ACCEPTANCE.md)。旧模型运行不重新标记为新代码。GitHub后续已公开并验证匿名读取，见 [交付记录](GITHUB-DELIVERY.md)；个人投入估算已在AI使用记录中补录。
