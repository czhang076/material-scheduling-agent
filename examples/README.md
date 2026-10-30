# 验证证据

M1 测试报告为历史基础验证。M2 新增 7 组实际工具案例：inputs/ 含请求及完整合成资料，outputs/ 含实际结果/账本计数/业务审计，traces/ 含真实工具参数和返回。重新运行 scripts/run_m2_examples.py 会生成新的实际 ID、时间和证据。

M2 全部为 driver_mode=manual_tools、model_called=false，不是 ReAct 或 Mock Agent 验收。确认案例明确记录可信本地合成用户操作，模型没有确认工具。

[evaluation/M2-cases.json](evaluation/M2-cases.json) 给出预期、实际结果和文件哈希；[M2-summary.json](evaluation/M2-summary.json) 给出两环境实际测试、编译、依赖、wheel 与源码校验值。生成时基线提交和源码指纹共同定位代码，不虚写尚不存在的最终提交号。

所有资料合成；数据库仅在忽略的 var/ 中，不提交。完整解释见 [M2 验收](../docs/M2-ACCEPTANCE.md)。
