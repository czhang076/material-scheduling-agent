# 测试目录

当前222个unittest方法：M5基线214个，M6新增8个；开发和独立wheel环境分别通过。另有7个Node状态控制器用例；subTest/场景/真实运行另计。

unit/ 为严格契约与领域；integration/ 为SQLite/并发/循环及模型配置、协议和回环HTTP；adversarial/ 为明确测试替身的越权/注入/预算检查；acceptance/ 为实际子进程CLI、确认、离线评估及配置入口。

M4覆盖原生调用ID回传、协议纠错、不伪造中途工具调用、重复ID、多调用/截断/拒绝/坏JSON、密钥回显、鉴权终态、429重试、禁止重定向、绝对正文读取截止时间、HTTP截断与字节上限。CLI测试清除继承的MODEL_变量且只用回环fixture，不自动使用本地.env或付费模型。

真实网络运行只由显式 scripts/run_m4_real.py 发起，不属于unittest或verify_m4。14组Mock与7组真实证据分别记录。临时账本仍使用公共LedgerTest的var/m2-tests/受控子目录并清理。见 [M4验收](../docs/M4-ACCEPTANCE.md)。

上段为M4历史验证方式，固定于d48e50f；M5记录固定于9af839e。当前M6用 scripts/run_m6_examples.py 向新目录生成实际HTTP/Mock记录，scripts/verify_m6.py 验证当前包及历史文件完整性，不重发付费调用。旧M4导出与M4/M5验证入口有版本保护，不能在新版下重写旧报告。

M6新增终态写入失败、只读降级、持久错误拒绝新任务、恢复后对账、线程启动失败、连接打开失败、正常终态写入中不误报中断，以及旧脚本安全退出。web/state.test.cjs 在小型DOM外壳中执行实际app.js状态控制器，覆盖未知提交的时间/模式变更、显式原提交重试、迟到元数据/事件和重叠刷新。Python桥接方法使用实际安装包的网页资源，独立wheel验证同样执行；无Node时仅跳过该桥接，完整开发验收仍须运行Node用例。真实浏览器交互另存证，不将DOM外壳称为浏览器。
