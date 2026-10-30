# 公开示例仓库对照记录

核对日期：2026-10-29（Asia/Shanghai）。本页保留 P0 阅读核对时的底座状态；当前实现进度另见 STATUS 和 M1-ACCEPTANCE。

## 1. 来源与阅读范围

参考仓库：[lwz1357/agent-campus-submission-example](https://github.com/lwz1357/agent-campus-submission-example)。本次记录的 main 提交：`38579ac1a59029e84647a99c496e34865da516c6`，由远程引用查询确认。

已阅读 README、核心流程、测试、方案、评估和 AI 使用说明。README 与评估文档另外按上述提交固定读取。关键入口：

- [固定版本 README](https://github.com/lwz1357/agent-campus-submission-example/blob/38579ac1a59029e84647a99c496e34865da516c6/README.md)
- [核心流程](https://github.com/lwz1357/agent-campus-submission-example/blob/38579ac1a59029e84647a99c496e34865da516c6/src/main.py)
- [测试](https://github.com/lwz1357/agent-campus-submission-example/blob/38579ac1a59029e84647a99c496e34865da516c6/tests/test_main.py)
- [评估说明](https://github.com/lwz1357/agent-campus-submission-example/blob/38579ac1a59029e84647a99c496e34865da516c6/docs/03-evaluation.md)
- [AI 使用说明](https://github.com/lwz1357/agent-campus-submission-example/blob/38579ac1a59029e84647a99c496e34865da516c6/docs/04-ai-usage.md)

本次只进行阅读和静态核对，没有复跑示例、引入示例代码或将其测试结果计入本项目。

最初创建本项目底座时依据的是用户粘贴的题面，尚未实际读取示例。本文件记录后续补做的参考核对，不把初始设计追溯描述为已经参考过示例。

## 2. 本项目采用的方式

保留现有独立仓库和针对排期题的设计；按示例核对交付组织与证据表达。无需重建仓库或替换成示例的脚本生成流程。

示例采用短视频脚本场景，且其 README 的题号标注与用户当前考卷不一致。本项目以用户提供的「素材审核与发布排期 Agent」题面为准。

## 3. 交付底座对照

|示例中的组织方式|本项目对应位置|当前真实状态|
|---|---|---|
|README 环境、运行命令、评审导航|根 README 与 RUNBOOK|导航已建；运行命令仅为规划，未实现|
|src 中的入口与流程|src/material_scheduler 下五个模块目录|只有目录占位，无业务代码|
|可执行测试|tests 下四类目录与 test-plan|用例计划已建，无测试代码或通过记录|
|合成素材与规则|data/catalog、rules、schedules|目录已建，数据集待实现阶段准备|
|输入与实际输出配对|examples/inputs、outputs|目录已建，尚无已执行案例|
|实际步骤和测试记录|examples/traces、evaluation|目录已建，尚无运行证据|
|01 需求与 02 方案|docs/01-requirements、02-solution|已写为设计稿|
|03 评估|docs/03-evaluation 与设计测试计划|明确标注未执行，未借用示例结果|
|04 AI 使用|docs/04-ai-usage|记录 AI 辅助范围，个人独立贡献待真实补充|
|05 复盘|docs/05-retrospective|只有已发生的设计反思，无虚构开发结果|
|依赖、环境示例与忽略规则|requirements.txt、.env.example、.gitignore|占位或准备配置，不代表可安装运行|
|GitHub URL 与最终 SHA|README、RUNBOOK、STATUS|只有本地 Git，无远程或最终提交|

目录允许按技术栈调整。我们把输入、输出、Trace 和评估分目录，仍需保持每个案例之间可追溯配对；不能只放一堆无法对应的 JSON。

## 4. 不能由示例替代的内容

示例明确使用离线确定性 Mock，不能证明真实模型生成或 ReAct 决策。本项目仍须独立完成：

- 模型观察工具结果后选择补查、替代、确认请求或停止。
- 四类排期工具及审核依据，含缺失信息、风险和冲突处理。
- 原始硬性要求、候选建议和用户授权分开，确认绑定草稿版本。
- 持久化、防重复、事务内冲突检查及保存失败/结果未知恢复。
- 六项必验的实际运行材料，以及至少两条真实模型动态路径。

这些属于未来实现与验证任务；设计齐全和目录齐全都不能代替达标证据。

## 5. 对现有设计的影响

交付类别与现有底座一致，未发现需要重建目录的组织差异。本次补充参考来源、版本与对应关系，未改变排期业务设计。

后续实现要特别延续示例的证据表达方式：每项记录输入变化、预期、实际、具体文件和未验证部分；所有结论归属本项目自己的实际运行。
