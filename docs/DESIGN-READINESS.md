# 设计基线 v1 收口

本文件记录 P0 设计基线收口时的范围与静态结果。用户之后要求下一步，已完成 M1；当前实现状态以 [STATUS](STATUS.md)和[M1 验收](M1-ACCEPTANCE.md)为准。本文件不是完整 Agent 验收或真实模型效果报告。

## 1. 完整性清单

|设计内容|入口|本阶段结论|
|---|---|---|
|题面与成功标准|[requirements](01-requirements.md)|六项必验、动态决策、交付材料均有对应|
|用户范围决定|[decisions](DECISIONS.md)|D01/D02 已选择，无待定核心范围|
|模块与依赖|[architecture](design/architecture.md)|职责、接口、依赖与代码目录已规划|
|请求/结果/错误/Trace|[contracts](design/contracts.md)|关键字段、来源、状态与边界已明确|
|完整工具参数|[tool-schemas](design/tool-schemas.md)|六个工具给出完整 JSON 参数定义|
|模型提示正文|[model-prompt](design/model-prompt.md)|约束、观察、动作、错误和结束协议明确|
|执行预算|[agent-loop](design/agent-loop.md)|按 N 计算，兼顾单项、总调用、轮数与时间上限|
|合成规则与样例|[design-fixtures](design/design-fixtures.md)|资料、五类规则、请求模板、六项必验差异和预期投影齐全|
|审核与证据|[content-review](design/content-review.md)|元数据/文案覆盖、原文定位、长度与缺失语义明确|
|确认与状态|[lifecycle](design/lifecycle.md)|原要求不覆盖、版本确认、过期及聚合规则明确|
|防重复与一致性|[persistence](design/persistence.md)|唯一性、事务、重查、UNKNOWN 恢复与审计明确|
|信任与故障|[trust-and-failures](design/trust-and-failures.md)|模型、素材、用户与存储的权限来源明确|
|网页与扩展|[workbench](design/workbench.md)、[media-extension](design/media-extension.md)|CLI 后本地网页、视觉只预留设计|
|验证与交付|[test-plan](design/test-plan.md)、[evaluation](03-evaluation.md)|42 组计划，当前全部未执行|

## 2. 本轮解决的问题

1. 固定 20 次工具限额不足以覆盖 20 项普通流程：改为每项 10 次、总计 `10*N+1`、硬上限 201，另设轮数与时间硬上限。20 项正常基础路径 81 次在预算内；不承诺真实模型必然完成。
2. 工具只有文字表格：补六个完整参数 Schema、统一返回及独立用户确认契约。
3. 提示只有职责说明：补完整系统提示与观察协议。
4. 规则/标准样例未收口：补完整合成世界、规则方言、请求模板、精确案例差异及明确标为设计预期的结果投影。
5. 审核必填与资料导入混淆：资料不足允许入库，审核时返回 NEEDS_INPUT；身份、类型及长度损坏仍拒绝。

## 3. 静态检查范围

设计 JSON 可解析、工具名与参数对应、标准场景身份/区间合法、规则证据片段可映射、预算基础算式一致、文档链接可达、无实现文件或伪造运行材料。

以上是设计材料检查，不是功能测试、Schema 执行器或真实模型调用验证。实际检查结果同时记录在 [P0-ACCEPTANCE](P0-ACCEPTANCE.md)。

2026-10-29 19:21（Asia/Shanghai）静态核对结果：55 个文件、33 份 Markdown、17 个空目录占位；7 段设计 JSON 可解析；6 个工具名和必需参数对应；5 份合成素材与 5 条规则结构可核对；1 项预算 11 次、20 项预算 201 次，均容纳基础正常路径；链接无缺失。未发现实现文件或实际运行证据。

## 4. 留到实现阶段的事项

- Python 包、精确依赖版本与配置加载方式。
- 数据库建表/迁移、工具实现、测试和真实合成数据文件。
- 用户本地选择并配置模型服务，协议兼容和提示有效性实测。
- CLI 核心完成后实现网页，做实际浏览器交互验证。
- 生成本项目自己的输入/实际输出/Trace、失败记录、GitHub URL 与最终 SHA。

这些属于实现与验证，不再是尚未选择的产品范围。实现发现矛盾或新事实时同步契约与测试，不借“设计完成”阻止必要修正。

## 5. 下一阶段入口

原设计确定从 M1 领域和数据契约开始；现已按用户后续指令完成该阶段。后续沿 PLAN 推进，不为目录数量继续添加无关功能。
