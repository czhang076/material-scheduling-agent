# 数据与工具契约（设计稿）

本文 JSON 均为**设计示例**，不是实际运行记录。实现阶段须把契约落实为严格校验并添加契约测试。

## 1. 请求

```json
{
  "schema_version": "1.0",
  "request_id": "REQ-DEMO-001",
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

严格约束：

- 顶层及嵌套对象均拒绝未知字段，拒绝在输入中注入确认、审核通过或保存成功字段。
- 请求 ID 和项 ID 非空、长度受限；项 ID 在请求内唯一。素材 ID、渠道也有长度与字符约束。
- 请求 ID、项 ID、素材 ID、来源/占用/候选 ID 长度为 1–64，使用 ASCII 字母、数字、下划线与连字符；渠道长度 1–32，由规则集/资料渠道列表约束。版本为正整数或规则集规定的非空版本字符串，不混用。
- 首版最多 20 项；`duration_minutes` 指排期占用长度，与视频播放时长无关，为 1–180 的整数，布尔值不得作为整数通过。
- 所有时间带 UTC 偏移，拒绝无时区时间；秒为 0，不接受隐式舍入。
- 窗口开始早于结束，最大 7 天；原始要求的完整区间应落在显式窗口内。
- 未给窗口按 [生命周期约定](lifecycle.md) 处理，不把缺省当成变更授权。
- `mode` 仅 `hard / preferred`。日期采用固定偏移时刻；不自动推断地区时区或夏令时。
- 请求中的业务字段不可原地修改。更新原始要求需要新请求 ID；确认通过独立入口处理。

初始版本不处理自然语言时间解析。输入格式问题属于输入错误；缺少素材元数据属于业务上的资料不足，两者不能混为一类。

## 2. 素材与补充资料

素材字段：`material_id`、`revision`、`title`、`copy_text`、`description`、`rights_status`、`supported_channels`、`tags`、`source_id`。

首版审核必要字段：标题、待发布文案、版权状态、支持渠道。标题最多 200 个 Unicode 码点，文案最多 8000 个，超限明确拒绝，不静默截断。描述和标签可以为空，但必须按对应规则的适用条件处理。不存在的素材返回明确资料缺口。

资料导入允许审核字段缺失，供 Agent 发现并补查；素材身份、来源、版本、已存在字段类型与长度仍须合法。缺少审核字段与导入格式损坏分开处理。具体版权枚举及五类规则语义见 [合成规则基线](design-fixtures.md)。

补充资料字段：`source_id`、`material_id`、`revision`、`fields`、`provenance`。模型只选择补查，不能提交自己编造的字段作为补查结果。

合并原则：只填充缺失字段，保留来源。若新旧资料相互矛盾，记录冲突并要求人工核对；不静默覆盖，也不让模型任意选一份当成权威。

## 3. 规则

每份规则集带 `rule_set_id`、`version` 与内容指纹；每条规则带稳定 `rule_id`、适用字段、条件、严重程度、说明。

首版只支持白名单规则类型，例如必填字段、版权状态枚举、渠道适配、明确禁用词、人工审核标签。不执行规则文件中的 Python、SQL 或模板代码。

示例设计：

|规则 ID|条件|结论|
|---|---|---|
|R-META-001|标题或版权状态等必填资料缺失|NEEDS_INPUT|
|R-RIGHTS-001|版权明确争议或无权使用|BLOCKED|
|R-CHANNEL-001|素材不支持请求渠道|BLOCKED|
|R-CLAIM-001|命中示例禁用承诺用语|BLOCKED|
|R-MEDICAL-001|医疗标签需人工核对|NEEDS_REVIEW|

关键词规则能力有限。上述规则仅作为合成业务规则，不代表平台官方审核规则或真实合规结论。

## 4. 既有排期与候选

既有排期：`booking_id`、`channel`、`start`、`end`、`source_revision`。容量暂定每个渠道任一时刻 1 项。

候选定义允许的渠道、起止时间、候选来源 ID 和版本。一个候选只有在完整容纳请求时长、处于搜索窗口且不冲突时才可建议。

候选查询不会预留时段。`available_as_of` 只描述观察时刻，保存仍必须重新检查。

## 5. 统一动作

逻辑动作结构：`action`、`arguments`、`reason`。`reason` 是至多 240 字的可公开简短依据，例如“18:00 已占用，查询同日替代时段”，无须提供内部思维过程。

采用原生工具调用的适配器可把 `reason` 作为每个工具共同的 `rationale` 参数；执行器提取后按下列业务参数验证。未知工具或额外业务参数都拒绝。

完整参数 Schema 及工具返回契约见 [tool-schemas](tool-schemas.md)，不再仅依赖下表文字描述。

|动作|业务参数|主要返回|
|---|---|---|
|`read_material`|`item_id`|素材字段、版本、来源、缺失字段、可补查标记|
|`lookup_metadata`|`item_id`|补充来源、填充项、剩余缺口或资料冲突|
|`check_rules`|`item_id`|审核状态、完整 findings、审核快照 ID|
|`query_slots`|`item_id`, `mode: requested/alternatives`, `limit: 1..10`|目标占用情况、候选、冲突原因、查询版本|
|`save_draft`|`item_id`, `candidate_start`|真实保存状态、草稿 ID、版本、待确认事项、草稿状态|
|`finish`|无|结束本轮运行；实际结果由执行器组装|

执行器把 `item_id` 绑定到原始请求，工具不接受模型重新指定渠道、原始时间、审核状态、确认者或草稿保存结果。

`save_draft` 必须具备本次有效审核观察和本次查询返回的候选；随后在事务内重新检查。把候选字符串猜对也不能绕过查询。

## 6. 统一工具观察

```json
{
  "ok": false,
  "tool": "save_draft",
  "item_id": "I01",
  "error": {
    "code": "SLOT_CONFLICT",
    "retryable": false,
    "next_step": "query_slots",
    "message": "候选时段已被占用，需要重新查询"
  },
  "observed_at": "2030-06-01T09:00:00Z"
}
```

错误消息不包含密钥、SQL、绝对私有路径或未经筛选的响应正文。`retryable=false` 表示不应原样自动重试；模型仍可选择重新查询、补查或停止。

关键错误码：

|类别|错误码|期望处理|
|---|---|---|
|输入/身份|`INVALID_INPUT`, `REQUEST_ID_CONFLICT`|拒绝，不生成新草稿|
|动作/权限|`INVALID_ACTION`, `INVALID_ARGUMENTS`, `ACTION_NOT_ALLOWED`|返回观察，计入预算|
|资料|`MATERIAL_NOT_FOUND`, `METADATA_MISSING`, `SOURCE_CONFLICT`|补查或请求补充|
|审核|`REVIEW_BLOCKED`, `REVIEW_REQUIRED`, `STALE_REVIEW`|阻断、待确认或重新检查|
|时段|`SLOT_CONFLICT`, `NO_CANDIDATE`, `OUTSIDE_WINDOW`, `CANDIDATE_NOT_OBSERVED`|重新查询或停止|
|确认|`DRAFT_VERSION_CONFLICT`, `CONFIRMATION_INCOMPLETE`, `STALE_DRAFT`|重新读取/规划，不继承旧同意|
|执行|`TOOL_UNAVAILABLE`, `MODEL_UNAVAILABLE`, `MODEL_PROTOCOL_ERROR`, `LIMIT_REACHED`|有界恢复或明确未完成|
|存储|`SAVE_FAILED`, `SAVE_OUTCOME_UNKNOWN`, `STORE_UNAVAILABLE`|失败或待核验，禁止宣称成功|

## 7. 逐项结果

字段分组：

- 身份：请求 ID、运行 ID、项 ID、素材 ID、渠道。
- 审核：状态、风险规则 ID、证据字段、来源、原文片段或字段值；`review_coverage` 明确 metadata 与 copy_text，图片/视频未检查。
- 时间：原始要求、建议区间、查询观察时间、冲突说明。
- 确认：待确认事项、确认记录引用；未确认不得填写确认者。
- 草稿：ID、版本、状态、最近核验时间。
- 保存：本次尝试的保存状态、错误码、是否已读取到持久化结果。
- 业务完成：项状态、剩余缺口；固定 `published=false`。

每次保存失败应同时报告已有草稿事实。例如“本次更新 FAILED；旧版草稿仍存在”，不可把旧草稿的存在当成这次更新成功。

模型可提供说明，但身份、审核依据、时间、确认、版本和保存状态只能来自工具与持久化事实。

## 8. Trace 与运行清单

Trace 采用 JSONL。事件字段：`schema_version`、`run_id`、序号、事件类型、时间、耗时、模型模式、动作、脱敏参数、公开理由、观察摘要、错误码、预算余量、关联项与草稿版本。

事件至少覆盖：`run_started`、`decision`、`tool_result`、`guard_rejected`、`run_stopped`。前一工具结果和后一模型动作通过事件序号关联，不预写“后续动作”。

运行清单另记：输入指纹、数据与规则版本、代码 commit、模型服务/模型名（真实运行时）、执行上限、停止原因、Trace/输出路径和校验值。

设计阶段不得生成具有这些结构却假装实际执行的材料。

标准合成输入、六项必验的精确变体与预期投影见 [design-fixtures](design-fixtures.md)；完整提示见 [model-prompt](model-prompt.md)。
