# 当前状态

项目启动：2026-10-29 11:38（Asia/Shanghai）。本轮 M5 收口：2026-10-31。

**M5 本地网页工作台已完成。** 实现素材/草稿/运行历史、单后台运行、持久化进度、严格 HTTP 边界及版本确认。默认 Mock，真实模型显式选择；密钥仍仅在忽略的服务端 .env。

当前 214 个 unittest 方法（M4 的184个 + M5新增30个），开发与独立 wheel 环境分别通过；新增6组HTTP + Mock实际记录和桌面/手机浏览器检查。M4的14组Mock、7次DeepSeek真实路径保留为d48e50f历史实证，不换算为当前版本重新运行。真实和模拟证据分别记录。

入口：[M5 验收](M5-ACCEPTANCE.md)、[当前测试摘要](../examples/evaluation/M5-summary.json)、[HTTP记录](../examples/workbench/http/manifest.json)、[浏览器检查](../examples/workbench/M5-browser-checks.json)。历史真实记录见[M4](../examples/evaluation/M4-real-cases.json)。模型标识只证明服务返回的别名，不推断底层权重快照。

已实现显式本地配置、标准库 HTTP、原生工具调用及原始 ID 回传、响应/请求上限、超时、拒绝重定向、HTTP分类、不重试终态鉴权错误、同一执行器与可信结果。真实模式不降级Mock。公开回执仅保留响应ID、模型别名、用量及内容哈希，不保存原始自由文本或内部思考。

M1基线3a23f01、M2基线2d08270、M3基线b68c0a4；旧阶段材料按对应提交解释。M4实证保存运行包指纹，测试报告保存源码指纹及生成时基线；阶段提交可用 git log -1 查看。

下一阶段为 M6：最终审查与交付。候选人亲自修改/理解记录、实际投入补录及GitHub URL/最终SHA仍未完成。当前无GitHub远程或推送，无真实发布、视觉审核或线上部署。

M5 浏览器另有 1 次当前版本真实 DeepSeek 正常链路（5 次模型调用），与历史七路径分开记录：[独立检查](../examples/workbench/real-normal/assessment.json)。
