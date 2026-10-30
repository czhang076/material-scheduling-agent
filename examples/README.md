# 实际证据目录

inputs/ 为实际输入封装，outputs/ 为实际结果，traces/ 为逐次 JSONL，evaluation/ 为预期/实际核对、测试日志、运行清单和文件校验值。全部合成，无密钥或数据库。

M1 是历史基础测试。M2 是 7 组 manual_tools 记录。M3 是 14 组场景、16 次真正经过有界执行器的离线运行，明确 model.mode=mock，没有真实模型。

[场景索引](evaluation/M3-cases.json) 逐一关联输入、聚合结果、各次原始 result、Trace 和清单。每份导出清单保留 runtime_manifest，并用 exported_files 将原运行目录内的 result.json/trace.jsonl 映射到仓库文件；不改写实际工具返回。重复及占用变化场景各有两次独立运行。

确认由可信合成用户操作完成，单独记在聚合结果中；没有向模型增加确认工具，也没有把确认补写进已结束的决策 Trace。

[M3-summary](evaluation/M3-summary.json) 记录两环境测试、编译、依赖和安装来源、wheel 与 LF 源码校验值。首次未知保存预期差异报告也保留；解释见 [M3 验收](../docs/M3-ACCEPTANCE.md)。

重新运行 scripts/run_m3_examples.py 生成新的真实 ID、时间和证据，不要求字节相同。M1/M2 按历史阶段提交解释；不能用新源码核对旧阶段哈希。Mock 路径不作为真实 ReAct 验收依据。
