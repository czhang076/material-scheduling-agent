# 当前状态

最终验收后按补强要求新增 [变化场景评估](../examples/robustness/README.md)：42次真实运行、215次DeepSeek调用，另42次Mock运行，均符合预设预期；四类安全/保存指标均为0。已在原独立安装环境复跑222个应用方法、另8项评估器测试及7项Node用例。业务代码和提示词未变，旧证据保持原样。个人业务判断、导读实验及评估器实际修正见 [学习复盘](06-learning-review.md)。

项目启动：2026-10-29 11:38（Asia/Shanghai）。本轮M6审查修复：2026-10-31；版本0.6.0。

用户随后要求独立严格复核，已从e89b238导出干净源码、重建wheel并在全新环境实际验收：222个方法无跳过、7个Node用例、14组离线场景16次运行、6组HTTP/Mock业务及1组恢复；新增当前代码8次真实CLI、2次真实网页，共51次DeepSeek调用，全部符合各自预期。报告见 [FINAL-ACCEPTANCE](FINAL-ACCEPTANCE.md)，证据见 [总清单](../examples/final-acceptance/manifest.json)。业务代码没有因本轮验收而修改。

用户明确要求修复最终审查的4项问题，现已处理：未知提交不覆盖新要求/模式；终态日志故障可只读展示降级并在显式提交时对账；异步加载隔离旧Trace；运行/测试手册更新，旧阶段导出及验证入口受版本保护。

当前222个unittest方法，开发与独立wheel分别通过；另7个Node网页控制器用例，分别计数。新增当前6组HTTP + Mock业务记录及1组终态恢复场景、实际浏览器复查。详见 [M6验收](M6-ACCEPTANCE.md)、[检查摘要](../examples/evaluation/M6-summary.json)、[当前HTTP记录](../examples/workbench/M6/manifest.json)。运行命令统一见 [RUNBOOK](RUNBOOK.md)。

M4真实模型7次运行固定于d48e50f，M5网页正常链路1次/5次调用固定于9af839e；M6修复阶段未新增付费调用。这些旧JSON/Trace保留原样。随后独立严格验收的10次真实运行单独保存，均对应e89b238应用代码指纹，不把旧实证冒充当前结果。

密钥仅留忽略的服务端.env，不进仓库、网页或证据。默认网页Mock；真实模式需服务端配置及页面明确选择。只保存草稿，无真实发布、视觉审核、多人认证或线上部署。

M1基线3a23f01、M2基线2d08270、M3基线b68c0a4、M4基线d48e50f、M5基线9af839e。当前阶段提交可用git log -1查看。各阶段证据按对应提交及记录的包指纹解释，不静默复用为新版本结果。

GitHub已发布为 [czhang076/material-scheduling-agent](https://github.com/czhang076/material-scheduling-agent)，公开且已验证匿名Git读取、克隆和代表文件访问。交付说明及验证记录见 [GITHUB-DELIVERY](GITHUB-DELIVERY.md)。最终提交SHA以本轮交付回执和远程main为准。个人投入约4小时（估算，未连续计时），已补入AI使用记录；个人与AI贡献边界保持原样。题面交付材料已备齐，尚未代交招聘系统。
