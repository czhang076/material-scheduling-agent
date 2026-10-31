# 测试目录

184个unittest方法：M3基线156个，M4新增28个；开发和独立wheel环境分别通过，subTest/场景/真实运行另计。

unit/ 为严格契约与领域；integration/ 为SQLite/并发/循环及模型配置、协议和回环HTTP；adversarial/ 为明确测试替身的越权/注入/预算检查；acceptance/ 为实际子进程CLI、确认、离线评估及配置入口。

M4覆盖原生调用ID回传、协议纠错、不伪造中途工具调用、重复ID、多调用/截断/拒绝/坏JSON、密钥回显、鉴权终态、429重试、禁止重定向、绝对正文读取截止时间、HTTP截断与字节上限。CLI测试清除继承的MODEL_变量且只用回环fixture，不自动使用本地.env或付费模型。

真实网络运行只由显式 scripts/run_m4_real.py 发起，不属于unittest或verify_m4。14组Mock与7组真实证据分别记录。临时账本仍使用公共LedgerTest的var/m2-tests/受控子目录并清理。见 [M4验收](../docs/M4-ACCEPTANCE.md)。
