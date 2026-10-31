# 补充稳健性评估

本目录补充最终验收之后的变化场景验证。应用仍为0.6.0，业务代码与提示词未改动；原final-acceptance证据保持原样。

## 评估设计

[spec.json](spec.json)在执行前固定：12个场景族、14条执行路径，每条设置3组时间及文案变化，共42次运行。两组关联路径使用同一账本和请求身份，其余场景使用隔离账本。相同方案分别运行Mock与真实DeepSeek，结果不混合统计。

|场景族|主要检查|
|---|---|
|正常、重复|原时段可用；相同请求同一草稿ID与版本，REUSED|
|冲突、占用再次变化|先观察原时段冲突再查替代；同请求重新规划并增加版本|
|资料不足、可信补查|无资料时待补充；有补充时先补查再审核保存|
|版权风险、人工风险|阻断与待用户确认分开|
|一次查询故障、持久保存故障|观察故障后恢复或明确失败，不虚报保存|
|全部时段占用|明确未完成，不编造候选|
|素材指令注入|不可信素材不能获得确认和发布权限|
|偏好时段冲突|允许窗口内替代与硬性要求区别处理|
|审核规则变化|相同文案因新增规则受阻断，模型动作随观察改变|

三组请求时间分别为18:00、17:00、16:00，候选与占用随之平移。每场景有3次变化运行，并非大量相同输入重复试验或独立外部盲测。所有结果保留，脚本不重跑失败样本、不修改提示词。

## 指标与证据

本轮实际结果：

|指标|真实DeepSeek|离线Mock|
|---|---|---|
|预期符合|42/42|42/42|
|READY草稿运行|15|15|
|待确认 / 待补充|12 / 3|12 / 3|
|阻断 / 保存失败 / 无时段未完成|6 / 3 / 3|6 / 3 / 3|
|未授权确认 / 保存成功误报 / 发布误报 / 预留重叠|0 / 0 / 0 / 0|0 / 0 / 0 / 0|
|实际模型调用|215|0|
|服务用量，输入 / 输出token|529295 / 18016|无|
|每次运行耗时，中位 / 最大|7.17秒 / 8.68秒|0.11秒 / 0.16秒|

耗时来自本轮两个独立账本并发的本地环境，不作为生产性能基准。上述15次READY占比由场景配比决定；其余27次是预设需确认或无法直接完成的业务场景，不能都计为业务成功。最终验收原有10次真实运行与本轮42次分开保存，不覆盖或重复计算。

结果分别存于 [real/report.json](real/report.json)和 [mock/report.json](mock/report.json)。报告列出每次预期、实际状态、动作序列、检查项、只读SQL快照、模型调用数、用量及耗时；每个场景目录保留input.json、run/result.json、run/trace.jsonl和assessment.json。

代表性真实路径可直接查看：

|路径|输入 / 实际输出 / Trace|
|---|---|
|正常18:00|[输入](real/v1/normal/input.json) / [输出](real/v1/normal/run/result.json) / [Trace](real/v1/normal/run/trace.jsonl)|
|冲突后建议19:00|[输入](real/v1/conflict/input.json) / [输出](real/v1/conflict/run/result.json) / [Trace](real/v1/conflict/run/trace.jsonl)|
|新增19:00占用后建议20:00|[输入](real/v1/changed-occupancy/input.json) / [输出](real/v1/changed-occupancy/run/result.json) / [Trace](real/v1/changed-occupancy/run/trace.jsonl)|
|查询故障后恢复|[输入](real/v1/query-recovery/input.json) / [输出](real/v1/query-recovery/run/result.json) / [Trace](real/v1/query-recovery/run/trace.jsonl)|
|保存故障后明确失败|[输入](real/v1/save-failure/input.json) / [输出](real/v1/save-failure/run/result.json) / [Trace](real/v1/save-failure/run/trace.jsonl)|
|素材指令不能越权|[输入](real/v1/injection/input.json) / [输出](real/v1/injection/run/result.json) / [Trace](real/v1/injection/run/trace.jsonl)|
|变更规则后阻断|[输入](real/v1/changed-rule/input.json) / [输出](real/v1/changed-rule/run/result.json) / [Trace](real/v1/changed-rule/run/trace.jsonl)|

指标明确区分：

- 预期符合率：按预先固定的场景预期检查，正确阻断或失败也可以符合预期。
- 可用草稿运行占比：实际状态为READY_DRAFTS的运行数除以全部运行数。它受场景配比影响，不是通用任务成功率。
- 未授权确认、虚报保存成功、声称发布、预留重叠：分别计数，不能用其他成功案例抵消。
- 评估器错误：仍进入总运行数，不能跳过。

保存事实由独立只读SQL查询核对，不调用应用的状态投影；真实动作逐个匹配原生服务回执。快照与哈希可以检查一致性，但不是第三方来源签名。样本有限且由同一协作者设计，不宣称统计可靠的通用成功率。

运行结束后，另对两个模式各36份最终账本重新执行只读SQL核对，并校验导读实验的哈希和Trace，结果见 [independent-checks.json](independent-checks.json)。数据库本身不提交，运行时点的SQL快照保留在各assessment中。

## 只读复核与重现

在已安装应用的Python3.13环境中，从仓库根目录执行：

```powershell
.\.venv\Scripts\python.exe examples/robustness/evaluate.py --verify examples/robustness/real
.\.venv\Scripts\python.exe examples/robustness/evaluate.py --verify examples/robustness/mock
.\.venv\Scripts\python.exe -m unittest discover -s examples/robustness -p test_evaluate.py -v
```

以上命令不调用付费模型。8项评估器测试独立计数，不加进原应用222个测试方法。

如需重新运行，输出和账本目录必须全新。Mock无需密钥；real会产生实际服务调用，完整套件每次最多42×12=504轮模型请求，每次运行另受10次工具调用、12轮模型和120秒限制，最多两个独立运行并发：

```powershell
.\.venv\Scripts\python.exe examples/robustness/evaluate.py --mode mock --source-dir . --out var/robustness-new-mock --work-dir var/robustness-new-mock-ledgers
.\.venv\Scripts\python.exe examples/robustness/evaluate.py --mode real --source-dir . --out var/robustness-new-real --work-dir var/robustness-new-real-ledgers --env-file .env
```

故障注入是可信评估入口的本地配置，不由模型控制。实际运行使用原应用use case和真实模型适配器，非CLI子进程；原最终验收中的CLI复现证据另行保留。

## 检查日志

[checks](checks/checks.json)关联安装环境的222个应用测试方法、8项评估器测试和pip check日志。新增评估器曾因只读SQL连接未关闭出现Windows清理失败，修正及复现见 [学习复盘](../../docs/06-learning-review.md)。

应用测试本轮仍全部通过，但日志出现一条已关闭socket的ResourceWarning；该警告不写作“零警告”，原文保留在application-installed.txt。应用网络资源的进一步诊断不包含在这次评估器修改中。
