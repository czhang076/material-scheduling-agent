# M4 真实模型接入与动态路径验收

2026-10-31。用户提供 DeepSeek API Key 并明确授权试用；本轮完成配置、传输与协议测试，以及独立真实模型记录。仅操作合成资料和本地草稿，不接发布。

## 实际结果

**184 个 unittest 方法**在开发与独立 wheel 环境分别通过，M4 新增28个。另有14组Mock场景16次运行，和7次真实DeepSeek运行。三个分母分别统计，不将环境、subTest或模型调用轮次加成测试方法数。

|真实场景|模型调用数|实际业务结果|证据|
|---|---:|---|---|
|normal|5|READY_DRAFTS；一份可用草稿|[结果](../examples/outputs/M4-real-normal.json)、[Trace](../examples/traces/M4-real-normal.jsonl)|
|conflict|6|18点占用→19点待确认，零全局占用|[结果](../examples/outputs/M4-real-conflict.json)、[Trace](../examples/traces/M4-real-conflict.jsonl)|
|duplicate|5|REUSED，同ID/版本，仍一份草稿|[结果](../examples/outputs/M4-real-duplicate.json)|
|changed-occupancy|6|同请求新增19点占用后改建议20点，原草稿新版本|[结果](../examples/outputs/M4-real-changed-occupancy.json)、[Trace](../examples/traces/M4-real-changed-occupancy.jsonl)|
|missing|5|补查仍缺版权资料，NEEDS_INPUT，零草稿|[结果](../examples/outputs/M4-real-missing.json)|
|risk|3|版权争议BLOCKED，保留规则及证据，零草稿|[结果](../examples/outputs/M4-real-risk.json)|
|save-failure|6|写后故障两次，观察失败后重试一次再结束；FAILED/退出4|[结果](../examples/outputs/M4-real-save-failure.json)、[Trace](../examples/traces/M4-real-save-failure.jsonl)|

共36次实际模型调用，服务回报 total_tokens 合计90,864（含各轮输入历史，不是独立文本数量或费用估计）。请求与服务返回的模型标识均为 deepseek-flash；不推断或宣称已验证底层权重快照。7次结果符合各自预期，不能据此给出统计可靠成功率或通用遵循率。

真实完整索引：[M4-real-cases.json](../examples/evaluation/M4-real-cases.json)。测试摘要：[M4-summary](../examples/evaluation/M4-summary.json)；原始测试：[开发](../examples/evaluation/M4-development-tests.txt)、[独立wheel](../examples/evaluation/M4-clean_wheel-tests.txt)。Mock保存在 [M4-mock-cases](../examples/evaluation/M4-mock-cases.json)，不与真实记录混称。

## 如何观察动态决策

正常路径实际由服务选择 read_material → check_rules → query_slots(requested) → save_draft → finish。每个工具返回后，下一次网络请求回传真实观察。

冲突路径在目标查询返回无候选后，服务选择 query_slots(alternatives)，收到19点候选后保存待确认草稿。第二次为同请求新增19点占用后重新运行，服务选择20点候选，草稿ID保持不变、版本从1变为3（失效一次、重规划一次），原始18点和TIME_CHANGE要求保留。

资料不足路径实际执行补查并再次审核；风险路径审核后停止；保存故障由可信评测器注入本地SQLite写后失败，模型接收SAVE_FAILED再决定一次重试。故障参数没有放进模型工具参数。原始Trace是实际调用产生，不是预设决策日志。

## 协议与来源

采用 Chat Completions 原生工具调用，保留 DecisionModel.choose 接口。官方格式依据为 [OpenAI 创建 Chat Completion](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)及 [Function calling](https://developers.openai.com/api/docs/guides/function-calling)；本次服务参数依据 [DeepSeek 首次调用](https://api-docs.deepseek.com/en/)、[Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)和 [Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)。来源核对日期2026-10-31；不由此宣称其他兼容服务已实测。

DeepSeek配置显式指定非思考模式、tool_choice=required、max_tokens=1024、非流式；未开启Beta strict。未将文档中未列出的parallel_tool_calls参数当成服务保证，每轮最多一个调用由本地严格校验；收到多个调用整体拒绝。通用compatible配置可显式使用max_completion_tokens、parallel_tool_calls=false及strict开关，第三方具体支持仍需独立验证。

适配器缓存服务原始工具调用ID，在后续 assistant/tool 消息中原样关联，不自行编造中途工具调用。协议错误只回传安全运行反馈；不重放无效响应或自由文本。固定提示后追加原生工具协议说明，实际wire_prompt与wire_tools指纹写入回执。

公开回执包括请求/响应SHA-256、字节数、服务响应ID、调用ID、返回模型别名与白名单用量字段；密钥、原始自由文本和内部思考不写入Trace。原始result和manifest中的真实验证字段为null，表示运行时不自证；外部评测核对实际动作/观察/账本后才在 M4-real-cases 中标记 real_react_verified=true。CLI模式real或回环fixture本身不证明真实模型。

## 配置与运行

离线不需要密钥且不读取.env。真实模式只显式加载 --env-file 指定文件及进程环境；同名进程环境优先。只支持示例列出的MODEL_字段，拒绝重复/未知配置；不执行shell、变量展开或任意代码。

```powershell
if (!(Test-Path .env)) { Copy-Item .env.example .env }
# 本地填入 MODEL_API_KEY，保留 .env.example 为空。
.\.venv\Scripts\python.exe -m material_scheduler init --data-dir data --db var/scheduler.sqlite3
.\.venv\Scripts\python.exe -m material_scheduler run --input data/requests/normal.json --db var/scheduler.sqlite3 --mode real --env-file .env --out var/real-demo-001
```

真实Key只保留在已忽略的.env；无CLI密钥参数。配置报错不回显值，repr不显示Key，URL禁止用户凭据/查询/片段，远程端点要求HTTPS（回环HTTP仅供本地服务和协议测试）。本次鉴权探测返回200，可用列表含deepseek-flash和deepseek-v4-pro；未把鉴权通过等同模型决策通过。

## 传输、失败及边界

标准库HTTP，无SDK隐藏重试或自动重定向。401/403、无效请求/TLS验证和上下文上限等终态错误不反复请求；429或服务器暂时错误受Runner最多一次恢复及全局预算约束，不静默改为Mock。请求默认2MiB、响应默认1MiB，输出token上限显式配置；没有静默裁掉观察历史。

连接/发送/读操作传递剩余时间，正文使用分段读取并逐次检查总截止时间；迟到动作不执行。系统DNS及某些底层阻塞操作不能强制终止，未宣称精确硬实时。关闭重定向防止凭据被转发到其他地址。HTTP截断、超大正文、坏JSON、多动作、重复原生ID、拒绝或截断完成、密钥回显均安全失败。

M4新增配置、协议、实际回环HTTP和子进程CLI测试共28个。回环fixture只验证协议，不计入真实7次运行。CLI测试主动移除继承的MODEL_变量，只使用显式测试配置，unittest和verify脚本不调用付费服务。

首次HTTP测试有两项失败：完整HTTP/1.0响应读完会自动关闭socket，下一轮设置超时被误判为连接失败。已区分正常响应结束和截断正文，并保留 [原始失败日志](../examples/evaluation/M4-initial-http-failure.txt)；修正后回环与真实调用均通过。

## 离线验证及有意的真实复跑

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir var/m4-wheel
py -3.13 -m venv var/m4-clean-venv
.\var\m4-clean-venv\Scripts\python.exe -m pip install --no-deps var/m4-wheel/material_scheduling_agent-0.4.0-py3-none-any.whl
.\.venv\Scripts\python.exe scripts/run_m4_offline.py
.\.venv\Scripts\python.exe scripts/verify_m4.py
```

同版本重建后安装加 --force-reinstall。以上验证只使用已存网络证据，不重发真实调用。真实复跑单独显式执行（会产生API用量）：

```powershell
.\.venv\Scripts\python.exe scripts/run_m4_real.py --env-file .env
```

原始结果、Trace、清单按精确字节导出，汇总结果另带审计/断言。网络记录保存运行包指纹，最终验证要求它与交付源码一致；生成时Git基线为M3 b68c0a4，源码完整指纹由最终报告记录。实际投入未连续计时，候选人亲自阅读/修改/复跑需如实补记。

M5本地网页及M6最终加固/GitHub交付仍未完成。模型决定动作，规则工具决定风险和保存权限；本地READY不代表真实平台发布或锁位，没有视觉审核、生产级高可用或多人认证。
