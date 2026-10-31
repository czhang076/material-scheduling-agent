# 实际证据

M1为领域测试，M2为手动工具，M3为历史离线执行器。M4当前入口：[测试摘要](evaluation/M4-summary.json)、[真实路径](evaluation/M4-real-cases.json)、[Mock路径](evaluation/M4-mock-cases.json)。旧阶段按对应提交解释。

M4有14组Mock场景16次执行，及7次真实DeepSeek运行。Mock、回环协议fixture和实际网络模型证据分别标注，不能相互替代。M4-real-*-result.json是逐次原始结果；M4-real-*.json聚合结果含额外账本/审计/独立断言；运行清单的exported_files指向原始结果与Trace的精确字节。

原始真实result和manifest的验证字段为null，独立评测报告才给出true。服务回执含原生工具ID、响应ID、返回模型别名、用量和内容哈希，无密钥/原始思考。真实记录的运行包源码指纹必须匹配本阶段提交代码；本地数据库和.env均不提交。

离线刷新使用scripts/run_m4_offline.py，验证使用scripts/verify_m4.py；这两者不调用付费服务。显式运行scripts/run_m4_real.py --env-file .env会产生真实网络调用和用量。当前证据来自实际命令，未手写运行步骤冒充。

当前网络记录是有限合成场景，不是通用效果保证；完整说明见 [M4验收](../docs/M4-ACCEPTANCE.md)。
