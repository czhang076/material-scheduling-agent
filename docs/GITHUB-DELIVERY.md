# GitHub 交付与评审访问

- 题号：**1 — 素材审核与发布排期 Agent**。
- GitHub：[czhang076/material-scheduling-agent](https://github.com/czhang076/material-scheduling-agent)。
- 可见性：**公开**，由用户明确选择。
- 评审入口：[README](../README.md)、[最终技术验收](FINAL-ACCEPTANCE.md)、[实际运行证据](../examples/final-acceptance/manifest.json)。
- 提交SHA：以本次交付回执给出的40位SHA及远程main实际提交为准；本地可执行 `git rev-parse HEAD` 获取。说明文档更新也会形成新提交，不能沿用旧SHA。

## 评审可读验证

公开仓库无需添加评审账号为协作者。已在不使用GitHub登录凭据的情况下：

1. 关闭Git系统/全局认证配置及凭据助手，读取远程main，确认与本地提交一致，未发送Authorization头。
2. 完成匿名浅克隆。
3. 通过匿名HTTPS读取README、应用源码、最终验收清单和.env.example，逐字节与已提交内容核对。
4. 验证真实.env未出现在远程；扫描全部Git历史，未发现当前模型密钥。

首次验证固定于技术验收资料提交 `cb6fc590f29734c021cde9a6a9a7e77aaa05f5de`，完整记录见 [github-public-access.json](github-public-access.json)。交付说明推送后，再核对最终main与本地SHA及公开文件；最终SHA在交付回执中给出，避免把文档内部记录误当成最终提交。

GitHub匿名REST API当时共享配额耗尽，因此使用匿名Git与原始文件访问验证；API限流不是仓库权限不足。验证仅证明GitHub公开读取权限，不代表已代替候选人提交招聘系统。

## 提交前本人补充

技术验收、AI辅助范围及已确认的个人选择/授权均有记录。实际投入时间仍需本人如实填写；估算时明确注明估算。本轮上传不编造候选人独立编程或亲自验收经历。

GitHub推送与说明更新未修改业务代码，也未改写历史模型输出、Trace或已冻结的验收清单。原始清单中的GitHub待办字段保留其生成时事实；后续完成情况以本页及交付回执为准。
