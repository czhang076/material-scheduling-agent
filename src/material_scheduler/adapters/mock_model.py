"""Explicit deterministic offline policy; it is NOT evidence of LLM reasoning."""

import json

from material_scheduler.agent.decisions import Action, ModelContext


def _action(tool, item_id=None, rationale="根据实际观察继续", **arguments):
    if item_id is not None:
        arguments["item_id"] = item_id
    return Action(tool, {**arguments, "rationale": rationale})


class ObservationMock:
    mode = "mock"
    name = "observation-policy"
    version = "1.0"

    def choose(self, context: ModelContext, *, timeout_seconds: float) -> str:
        for item in context.request["items"]:
            item_id = item["item_id"]
            if context.budget["per_item_remaining"][item_id] <= 0 or item_id in context.budget["blocked_items"]:
                continue
            events = [entry for entry in context.history if entry["kind"] == "tool" and entry["observation"].get("item_id") == item_id]
            action = self._next(item_id, events)
            if action is not None:
                return json.dumps(action.to_dict(), ensure_ascii=False)
        return json.dumps(_action("finish", rationale="所有可继续项已处理；保留缺口、风险、待确认事项和实际保存状态").to_dict(), ensure_ascii=False)

    def _next(self, item_id, events):
        if not events:
            return _action("read_material", item_id, "先读取该项实际素材和缺失信息")
        last = events[-1]
        action, observation = last["action"], last["observation"]
        tool = action["tool"]
        looked_up = any(event["action"]["tool"] == "lookup_metadata" for event in events)
        if not observation["ok"]:
            code = observation["error"]["code"]
            if observation["error"].get("retryable"):
                signature = {key: value for key, value in action["arguments"].items() if key != "rationale"}
                failed = sum(not event["observation"]["ok"] and event["action"]["tool"] == tool and {
                    key: value for key, value in event["action"]["arguments"].items() if key != "rationale"
                } == signature for event in events)
                if failed <= 1:
                    return _action(tool, rationale="该工具暂时失败，在预算内按相同业务参数重试一次", **signature)
                return None
            if code == "STALE_REVIEW":
                return _action("check_rules", item_id, "审核证据已失效，重新审核")
            if code in {"SLOT_CONFLICT", "CANDIDATE_NOT_OBSERVED", "OUTSIDE_WINDOW"}:
                return _action("query_slots", item_id, "候选已变化或出现新冲突，重新查询替代", mode="alternatives", limit=10)
            if code == "METADATA_MISSING" and not looked_up:
                return _action("lookup_metadata", item_id, "保存指出缺口，尝试有来源的补查")
            return None
        data = observation["data"]
        if tool == "read_material":
            if data["material"] is None:
                return None
            return _action("check_rules", item_id, "素材已读，检查当前规则并取得证据")
        if tool == "lookup_metadata":
            return _action("check_rules", item_id, "补查已返回，依据实际资料重新审核")
        if tool == "check_rules":
            if data["review_status"] in {"PASS", "NEEDS_REVIEW"}:
                return _action("query_slots", item_id, "审核允许形成草稿，先检查原始要求时段", mode="requested", limit=10)
            if data["review_status"] == "NEEDS_INPUT" and not looked_up:
                return _action("lookup_metadata", item_id, "审核返回资料缺失，补查后再判断")
            return None
        if tool == "query_slots":
            if data["candidates"]:
                return _action("save_draft", item_id, "使用实际返回候选保存草稿，保留硬性调整与风险的确认边界", candidate_start=data["candidates"][0]["start"])
            if data["mode"] == "requested":
                return _action("query_slots", item_id, "原始时段无可用候选，查询允许范围内替代", mode="alternatives", limit=10)
        return None
