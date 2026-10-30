# M1 领域与数据契约验收

状态：已完成。最终验证时间：2026-10-29 19:47（Asia/Shanghai）。

本阶段交付可安装的 Python 包、确定性领域逻辑、合成输入和基础测试。不包括数据库保存、工具执行器、Agent 决策或网页。

## 1. 已实现内容

|模块|实际能力|边界|
|---|---|---|
|domain/validation.py|严格类型、额外字段、重复 JSON key、非有限数、非法 Unicode 校验|无模型或工具协议调用|
|domain/requests.py|不可变请求、时区/窗口校验、业务指纹、原始要求保留|不登记持久化请求身份|
|domain/time.py|固定偏移、分钟精度、UTC 比较、半开区间、跨午夜|不处理自然语言日期或 DST|
|domain/catalog.py|素材与补充资料契约，缺失事实保留|补查合并/审计留到 M2|
|domain/review.py|五类规则、完整 findings、原文码点证据、快照|合成规则，不是完整语义或视觉审核|
|domain/scheduling.py|目标/替代候选、全区间容量、渠道冲突、稳定排序|基于传入快照，不证明并发持久化正确|
|domain/drafts.py|待确认/READY/过期、版本、风险接受、重新规划|纯对象转换，不是已保存/已认证操作|
|domain/budgets.py|按 N 派生有限预算|运行时计数和超时执行留到 M3|
|adapters/fixture_loader.py|严格加载真实本地合成文件、身份与引用检查|不向 SQLite 导入|

## 2. 实际验证结果

机器摘要：[M1-summary.json](../examples/evaluation/M1-summary.json)。每条记录包含实际命令、返回码、日志、源文件校验值；当前无 commit，报告如实使用 git_commit=null。

源文件指纹按 UTF-8/LF 文本计算，与暂存 Git 内容逐文件核对；Windows 换行归一化不影响业务内容。安装包另记录原始 wheel SHA-256。

|环境/检查|实际结果|记录|
|---|---|---|
|项目虚拟环境、editable 安装|70 个测试方法通过|[development tests](../examples/evaluation/M1-development-tests.txt)|
|独立虚拟环境、wheel 安装、Python -I|相同 70 个测试方法通过；包来源确为独立 site-packages|[clean tests](../examples/evaluation/M1-clean_wheel-tests.txt)|
|Python 编译检查|返回码 0|[compileall](../examples/evaluation/M1-development-compileall.txt)|
|开发环境依赖检查|No broken requirements found|[development pip check](../examples/evaluation/M1-development-pip_check.txt)|
|独立环境依赖检查|No broken requirements found|[clean pip check](../examples/evaluation/M1-clean_wheel-pip_check.txt)|

计数为 70 个 unittest 方法；subTest 的多组边界没有另加计数。同一组在两个环境通过，不写成 140 个独立用例。

## 3. 可复制验证命令

在仓库根目录，Windows + Python 3.13.x：

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q src tests
.\.venv\Scripts\python.exe -m pip check
```

安装包复跑方式：

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir var/m1-wheel
py -3.13 -m venv var/m1-clean-venv
.\var\m1-clean-venv\Scripts\python.exe -m pip install --no-deps var/m1-wheel/material_scheduling_agent-0.1.0-py3-none-any.whl
.\var\m1-clean-venv\Scripts\python.exe -I -m unittest discover -s tests -v
```

var/ 和虚拟环境被忽略，不提交运行环境。M1 无第三方运行依赖；构建后端 setuptools==82.0.1 由 pyproject.toml 固定。后续依赖另记录，不复制全局环境。

## 4. 重点已验证行为

- 未知字段、布尔时长、无时区时间、重复键与非法日期不会被宽松接受。
- 显式窗口相同的等价时区表示不改变业务指纹；缺省窗口的日历日变化必须改变身份。
- 缺版权或正文保持 NEEDS_INPUT；风险和缺口并存时全部保留，BLOCKED 优先。
- 中文、emoji、换行和重叠短语的原文片段对应实际码点位置；浏览器高亮尚未验证。
- 硬性时间替代形成待确认对象；伪造 READY、少接受风险、旧版本或新冲突被拒绝。
- 接受可人工确认风险后仍保留 NEEDS_REVIEW，不改成无风险。
- 相同方案可复用纯领域对象；过期重规划沿用 ID 并清除旧授权。数据库幂等尚未验证。

## 5. 实现时明确的边界

1. 未给显式窗口时，“同日替代”限制候选开始日期；原始 23:45 开始、持续 30 分钟可以跨午夜。显式窗口仍要求全区间落入窗口。
2. 规则集必须覆盖基础必填、争议/无权版权阻断和渠道检查，不能因配置漏项而默认放行。文案与人工风险规则可版本化调整。
3. 字符串拒绝未配对代理码点，时间的本地表示与 UTC 表示都须可表示，避免后续指纹计算出现原始异常。

## 6. 失败与修正记录

首轮 67 个基础测试通过。添加边界测试时，一次测试方法拆分位置错误导致 NameError（测试局部变量 raw 不在新方法作用域）；修正后复跑。之后补充默认日历日变更不可绕过重新规划的回归，最终两环境均为 70/70。

不将该修正包装成模型效果改进，也不把基础测试通过写成六项 Agent 验收全部通过。

## 7. 下一阶段

M2：SQLite 请求/草稿/确认/占用账本、补查合并、四类工具用例、事务内复核、防重复及保存失败注入。必须在该阶段证明真实存储行为，不能只断言一个领域对象的状态。
