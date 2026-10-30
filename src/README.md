# 源码目录（M1 已实现）

未来包名：`material_scheduler`。目录职责见 [架构设计](../docs/design/architecture.md)。

`domain` 放确定性业务规则，`application` 放工具与用户确认用例，`agent` 放模型循环，`adapters` 放 SQLite/资料/模型实现，`interfaces` 放 CLI 与后续本地 HTTP，`interfaces/web` 预留网页静态资源目录。

已实现 domain 下的严格校验、时间区间、请求身份、预算派生、素材与规则、审核证据、候选与草稿状态，以及 adapters/fixture_loader.py 的合成资料加载。

application、agent、CLI/HTTP、网页与 SQLite 适配器尚未实现。创建 Python 草稿对象不等于数据库保存。
