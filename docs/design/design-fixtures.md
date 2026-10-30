# 合成资料与标准场景 v1

本文是设计输入和预期规格，**不是实际输出或 Trace**。M1 已据此落下合成输入文件并执行基础测试，记录在 examples/evaluation；这里的完整 Agent 场景尚未运行。

## 1. 合成世界

以下给出基线资料。导入校验身份、字段类型、长度和规则结构；素材可以缺少审核必需字段，以便进入 NEEDS_INPUT，不能在导入时把所有资料不足素材丢弃。身份、版本、来源缺失及非法类型仍拒绝导入。

```json
{
  "schema_version": "1.0",
  "data_revision": 1,
  "materials": [
    {
      "material_id": "M01",
      "revision": 1,
      "title": "字幕功能介绍",
      "copy_text": "支持添加字幕。",
      "description": "合成产品介绍，仅验证元数据与文案。",
      "rights_status": "owned",
      "supported_channels": ["douyin"],
      "tags": [],
      "source_id": "SYN-M01"
    },
    {
      "material_id": "M02",
      "revision": 1,
      "title": "待补版权资料",
      "copy_text": "介绍字幕编辑功能。",
      "description": "故意缺少版权状态的合成素材。",
      "supported_channels": ["douyin"],
      "tags": [],
      "source_id": "SYN-M02"
    },
    {
      "material_id": "M03",
      "revision": 1,
      "title": "版权争议示例",
      "copy_text": "介绍剪辑操作。",
      "description": "仅用于阻断场景。",
      "rights_status": "disputed",
      "supported_channels": ["douyin"],
      "tags": [],
      "source_id": "SYN-M03"
    },
    {
      "material_id": "M04",
      "revision": 1,
      "title": "人工核对示例",
      "copy_text": "介绍健康知识短片的字幕制作。",
      "description": "医疗标签要求人工接受风险。",
      "rights_status": "owned",
      "supported_channels": ["douyin"],
      "tags": ["medical"],
      "source_id": "SYN-M04"
    },
    {
      "material_id": "M05",
      "revision": 1,
      "title": "禁用承诺示例",
      "copy_text": "100%保证有效",
      "description": "仅用于文案片段定位。",
      "rights_status": "owned",
      "supported_channels": ["douyin"],
      "tags": [],
      "source_id": "SYN-M05"
    }
  ],
  "supplements": [],
  "rule_set": {
    "rule_set_id": "SYN-BRAND-001",
    "version": "1.0",
    "rules": [
      {
        "rule_id": "R-META-001",
        "type": "required_fields",
        "fields": ["title", "copy_text", "rights_status", "supported_channels"],
        "severity": "NEEDS_INPUT",
        "message": "排期前须补齐必要资料"
      },
      {
        "rule_id": "R-RIGHTS-001",
        "type": "forbidden_values",
        "field": "rights_status",
        "values": ["disputed", "unlicensed"],
        "severity": "BLOCKED",
        "message": "版权存在争议或明确无权使用"
      },
      {
        "rule_id": "R-CHANNEL-001",
        "type": "channel_supported",
        "field": "supported_channels",
        "severity": "BLOCKED",
        "message": "素材不支持请求渠道"
      },
      {
        "rule_id": "R-CLAIM-001",
        "type": "forbidden_phrases",
        "fields": ["title", "copy_text"],
        "phrases": ["100%保证", "绝对治愈"],
        "severity": "BLOCKED",
        "message": "命中合成品牌规则的禁用承诺"
      },
      {
        "rule_id": "R-MEDICAL-001",
        "type": "manual_tags",
        "field": "tags",
        "values": ["medical"],
        "severity": "NEEDS_REVIEW",
        "message": "需人工核对并明确接受对应风险"
      }
    ]
  },
  "slot_offers": [
    {"offer_id": "O18", "revision": 1, "channel": "douyin", "start": "2030-06-01T18:00:00+08:00", "end": "2030-06-01T18:30:00+08:00"},
    {"offer_id": "O19", "revision": 1, "channel": "douyin", "start": "2030-06-01T19:00:00+08:00", "end": "2030-06-01T19:30:00+08:00"},
    {"offer_id": "O20", "revision": 1, "channel": "douyin", "start": "2030-06-01T20:00:00+08:00", "end": "2030-06-01T20:30:00+08:00"}
  ],
  "existing_bookings": []
}
```

## 2. 规则方言与缺失语义

只支持上述五种 type，每种只允许其展示的字段和固定 severity。规则 ID 唯一；禁止未知 type、额外表达式、空匹配短语和与类型不一致的 severity。

M1 明确基础保护不可因配置漏项而消失：required_fields 的集合须覆盖四个基础字段，forbidden_values 须阻断 disputed/unlicensed，并至少有一条渠道检查。缺少这些保护的规则集拒绝加载；文案和人工风险配置仍可版本化调整。

- required_fields：缺失、null、空字符串、空渠道列表视为缺口；不允许布尔/数值冒充文本。描述/标签可空。
- forbidden_values：仅检查存在且类型合法的字段，缺失交给 required_fields；版权允许 owned、licensed、disputed、unlicensed、unknown。unknown 作为版权未明确归入 NEEDS_INPUT。
- channel_supported：对存在的渠道列表检查请求渠道；缺少列表记录缺口，不重复虚构渠道不支持。
- forbidden_phrases：在原始 title/copy_text 中精确匹配并返回所有命中；否定或引用也可能命中，此行为公开，不宣称理解其语义。
- manual_tags：命中配置标签产生 NEEDS_REVIEW。用户接受后仍保留原风险。

未知版权枚举、非法字段类型或规则结构属于资料导入错误。规则集内容指纹由规范化数据计算，不能把手写常量当作真实计算结果。

## 3. 完整请求模板

```json
{
  "schema_version": "1.0",
  "request_id": "REQ-DESIGN-A01",
  "items": [
    {
      "item_id": "I01",
      "material_id": "M01",
      "channel": "douyin",
      "time_requirement": {
        "requested_start": "2030-06-01T18:00:00+08:00",
        "duration_minutes": 30,
        "mode": "hard",
        "alternative_window": {
          "start": "2030-06-01T18:00:00+08:00",
          "end": "2030-06-01T21:00:00+08:00"
        }
      }
    }
  ]
}
```

每个独立案例从全新基线数据库开始；只有重复提交或变化重跑案例复用账本。下表精确指定模板差异，未列字段保持不变。

## 4. 六项必验的输入与预期

|用例|输入与环境变化|标准预期|
|---|---|---|
|A01 正常|完全使用模板和基线|PASS，18:00 READY，首次保存 CREATED，published=false|
|A02 缺资料|request_id=REQ-DESIGN-A02，material_id=M02|NEEDS_INPUT，列出 rights_status，草稿 ABSENT，保存 NOT_ATTEMPTED|
|A04 规则风险|request_id=REQ-DESIGN-A04，material_id=M03|BLOCKED，R-RIGHTS-001 与 disputed 证据，无草稿|
|A06 时段冲突|request_id=REQ-DESIGN-A06，增加下面的 B18 占用|原始 18:00 保留；标准候选排序首项 19:00，待确认 TIME_CHANGE；模型选择其他合法候选也按业务约束评估|
|A08 重复|A01 同一完整请求在同一账本执行两次|同一 draft_id；第二次若调用保存则 REUSED，若直接结束则保存 NOT_ATTEMPTED 并报告原草稿；不新增占用|
|A10 保存失败|request_id=REQ-DESIGN-A10，测试环境注入 save_draft 写入前失败|真实返回 SAVE_FAILED，草稿 ABSENT、本次保存 FAILED，不能宣称成功|

```json
{
  "booking_id": "B18",
  "source_revision": 1,
  "channel": "douyin",
  "start": "2030-06-01T18:00:00+08:00",
  "end": "2030-06-01T18:30:00+08:00"
}
```

query_slots 替代候选按“距离原时间的绝对差、候选 UTC 开始、offer_id”稳定排序，limit 截断排序结果。稳定排序不是强制模型必须选第一项；需要核对模型所选是否合法且理由符合观察。

故障注入属于测试环境控制，不进入业务请求或真实模型可编辑参数。独立用例结束后清除故障，不污染其他用例。

## 5. 冲突结果的设计投影

下例外层 `example_kind` 明确它是设计预期，内层只是实际结果应包含的关键字段，省略尚未生成的运行 ID、草稿 ID、观测时间与真实消耗。

```json
{
  "example_kind": "design_expectation_not_execution",
  "expected_projection": {
    "request_id": "REQ-DESIGN-A06",
    "task_status": "NEEDS_CONFIRMATION",
    "stop_reason": "MODEL_FINISHED",
    "items": [
      {
        "item_id": "I01",
        "material_id": "M01",
        "review_status": "PASS",
        "review_coverage": ["metadata", "copy_text"],
        "requested_start": "2030-06-01T18:00:00+08:00",
        "candidate_start": "2030-06-01T19:00:00+08:00",
        "pending_confirmations": ["TIME_CHANGE"],
        "draft_state": "PENDING_CONFIRMATION",
        "save_status": "CREATED",
        "persisted": true,
        "published": false
      }
    ]
  }
}
```

该投影只是选择 19:00 时的合法预期。真实模型也可能未能完成；实际运行必须保存真实失败，不得复制此投影覆盖结果。

## 6. 扩展用例的精确变体

- A03 补查：给 M02 增加 revision=1 的合成补充来源，fields 只含 rights_status=licensed；工具合并后递增素材 revision，再审核。
- A05 人工风险：material_id=M04；确认事项为 RISK:R-MEDICAL-001，接受后仍 NEEDS_REVIEW。
- A20 更换占用：A06 保存建议后，将 B18 显式替换为 19:00–19:30 占用；重跑同一 A06 请求应重新发现 18:00 可用，不能坚持旧的 19:00；同一草稿 ID 可形成新版本。
- A30 定位：material_id=M05，命中 copy_text 的 `100%保证`，码点区间 `[0, 6)`。emoji 变体在该片段前加一个 emoji，预期区间 `[1, 7)`；另加换行变体验证原文映射。
- 20 项预算核对使用 20 个独立素材、渠道或互不重叠且明确授权的时段，不能把 20 项都塞到同一占用区间而称正常批量。

实际 fixture 文件、实际输出与 Trace 在实现阶段生成，并按 [测试计划](test-plan.md) 留证。
