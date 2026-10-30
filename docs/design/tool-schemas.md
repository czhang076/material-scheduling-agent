# 工具参数 Schema v1

状态：参数为设计基线，M2 ToolSession 已执行六类工具并严格校验；尚未接入模型协议。下列为六个原生函数工具的完整参数定义。适配器按实际服务映射协议，不因为这些定义可解析就宣称服务兼容。

## 1. 统一规则

- 所有参数对象拒绝额外字段；每个工具必带简短公开 `rationale`，无需内部思维过程。
- `item_id` 只能引用当前请求中的项；字符合法不代表有权访问。
- `candidate_start` 由业务校验器检查偏移、分钟精度、窗口与本次候选观察，不能只依赖 Schema 字符串类型。
- 不提供发布、确认、修改请求、任意 SQL 或任意 URL 工具。
- 下面六个对象不直接包含供应商特有的 strict 等参数；是否启用由适配器在协议测试后明确记录，参数和业务约束不因服务能力而放宽。

## 2. 完整定义

```json
[
  {
    "type": "function",
    "function": {
      "name": "read_material",
      "description": "读取当前请求项的素材、来源、缺失字段及可补查标记。",
      "parameters": {
        "type": "object",
        "properties": {
          "item_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"},
          "rationale": {"type": "string", "minLength": 1, "maxLength": 240}
        },
        "required": ["item_id", "rationale"],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "lookup_metadata",
      "description": "从当前账本内的有来源补充资料填补缺失字段，报告剩余缺口或资料冲突。",
      "parameters": {
        "type": "object",
        "properties": {
          "item_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"},
          "rationale": {"type": "string", "minLength": 1, "maxLength": 240}
        },
        "required": ["item_id", "rationale"],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "check_rules",
      "description": "检查当前素材元数据与文案，返回审核状态、所有发现及审核快照。",
      "parameters": {
        "type": "object",
        "properties": {
          "item_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"},
          "rationale": {"type": "string", "minLength": 1, "maxLength": 240}
        },
        "required": ["item_id", "rationale"],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "query_slots",
      "description": "查询原始目标或允许搜索范围内的替代候选，不预留时段。",
      "parameters": {
        "type": "object",
        "properties": {
          "item_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"},
          "mode": {"type": "string", "enum": ["requested", "alternatives"]},
          "limit": {"type": "integer", "minimum": 1, "maximum": 10},
          "rationale": {"type": "string", "minLength": 1, "maxLength": 240}
        },
        "required": ["item_id", "mode", "limit", "rationale"],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "save_draft",
      "description": "保存当前项已观察到的候选草稿，服务端重新审核、查冲突并决定确认状态。",
      "parameters": {
        "type": "object",
        "properties": {
          "item_id": {"type": "string", "minLength": 1, "maxLength": 64, "pattern": "^[A-Za-z0-9_-]+$"},
          "candidate_start": {"type": "string", "minLength": 20, "maxLength": 40},
          "rationale": {"type": "string", "minLength": 1, "maxLength": 240}
        },
        "required": ["item_id", "candidate_start", "rationale"],
        "additionalProperties": false
      }
    }
  },
  {
    "type": "function",
    "function": {
      "name": "finish",
      "description": "结束本轮决策；最终业务与保存结果由执行器根据实际事实组装。",
      "parameters": {
        "type": "object",
        "properties": {
          "rationale": {"type": "string", "minLength": 1, "maxLength": 240}
        },
        "required": ["rationale"],
        "additionalProperties": false
      }
    }
  }
]
```

## 3. 返回契约

每次工具观察至少有 `ok`、`tool`、`item_id`（finish 为 null）、`observed_at`，成功时含 `data`，失败时含 `error`。两者互斥。所有观察均由执行器产生。

|工具|data 必含内容|
|---|---|
|read_material|material 或 null、source_id、revision、missing_fields、supplement_available|
|lookup_metadata|applied_fields、source_ids、remaining_missing、source_conflicts、当前 revision|
|check_rules|review_status、findings、missing_fields、review_coverage、review_snapshot_id|
|query_slots|mode、requested_available、candidates、conflicts、schedule_revision、available_as_of|
|save_draft|save_status、draft_id、version、draft_state、candidate、pending_confirmations、persisted|
|finish|stop_reason；结果组装在工具之外完成|

失败结构为 `code / retryable / next_step / message`，含义见 [数据契约](contracts.md)。返回 UNKNOWN 时不能填 `persisted=true`；若复查确认已提交，再返回实际保存事实。

## 4. 非模型确认契约

可信用户入口字段：`confirmation_id`、`draft_id`、`expected_version`、`accepted_item_ids`、`actor`、可选 `note`。未知字段拒绝，accepted_item_ids 不得漏项或包含不存在事项。

本地 CLI 和后续网页适配同一用例，不把该接口加入模型工具目录。重复 confirmation_id 的内容校验、版本复核与事务见 [持久化设计](persistence.md)。
