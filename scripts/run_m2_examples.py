"""Run actual tools manually; this is neither an Agent nor a model evaluation.

Execute from the repository root after installing the package. Each invocation
uses fresh local databases; reviewed JSON/JSONL evidence is written to examples/.
"""

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
from uuid import uuid4

from material_scheduler.adapters.faults import FaultInjector
from material_scheduler.adapters.fixture_loader import load_fixture_set
from material_scheduler.adapters.sqlite_store import SQLiteStore, fixture_to_dict
from material_scheduler.application.tools import ToolSession
from material_scheduler.domain.drafts import ConfirmationCommand
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.scheduling import Booking


ROOT = Path(__file__).resolve().parents[1]


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def source_hashes():
    paths = [ROOT / "pyproject.toml"]
    for directory in ("src", "tests", "scripts", "data"):
        paths.extend(path for path in (ROOT / directory).rglob("*") if path.suffix in {".py", ".json"})
    return {
        path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        for path in sorted(paths)
    }


def run():
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    local_root = ROOT / "var/m2-examples" / uuid4().hex
    local_root.mkdir(parents=True)
    dataset = load_fixture_set(ROOT / "data")
    raw_base = json.loads((ROOT / "data/requests/normal.json").read_text(encoding="utf-8"))
    cases = []
    for name in ("normal", "missing", "risk", "conflict", "duplicate", "save_failure", "confirmation"):
        raw = json.loads(json.dumps(raw_base))
        raw["request_id"] = "REQ-M2-" + name.replace("_", "-")
        raw["items"][0]["material_id"] = {"missing": "M02", "risk": "M03"}.get(name, "M01")
        current = dataset
        if name in {"conflict", "confirmation"}:
            offer = next(offer for offer in current.slot_offers if offer.interval.start.hour == 18)
            current = replace(current, existing_bookings=(Booking("B18", 1, offer.channel, offer.interval),))
        fault_config = {"save.after_draft_write": 1} if name == "save_failure" else {}
        store = SQLiteStore(local_root / (name + ".sqlite3"), faults=FaultInjector(fault_config))
        store.import_dataset(current)
        request = SchedulingRequest.from_dict(raw)
        traces = []
        checkpoints = []

        def execute_tools():
            session = ToolSession(store, request)

            def tool(action, rationale, **arguments):
                if action != "finish":
                    arguments["item_id"] = "I01"
                return session.execute(action, {**arguments, "rationale": rationale})

            tool("read_material", "读取待排期素材及资料缺口")
            review = tool("check_rules", "按当前素材和规则检查风险")
            status = review["data"]["review_status"]
            if status == "NEEDS_INPUT":
                tool("lookup_metadata", "版权资料缺失，补查可用来源")
                tool("check_rules", "补查后重新检查，未补齐则请求用户补充")
                tool("finish", "资料仍不足，结束并保留待补充状态")
            elif status == "BLOCKED":
                tool("finish", "版权规则阻断，停止排期")
            else:
                slots = tool("query_slots", "核对用户原始要求时段", mode="requested", limit=10)
                if not slots["data"]["candidates"]:
                    slots = tool("query_slots", "原时段已占用，查询替代建议并保留待确认边界", mode="alternatives", limit=10)
                candidate = slots["data"]["candidates"][0]
                tool("save_draft", "保存工具已返回的候选，硬性时间变化须待确认", candidate_start=candidate["start"])
                tool("finish", "依据实际保存结果结束本次工具演示")
            traces.extend({"driver_mode": "manual_tools", "model_called": False, **record} for record in session.records)
            return session.result()

        first = execute_tools()
        checkpoints.append(first)
        final = first
        if name == "duplicate":
            final = execute_tools()
            checkpoints.append(final)
            assert first["items"][0]["draft"]["draft_id"] == final["items"][0]["draft"]["draft_id"]
            assert final["items"][0]["save_attempt"]["save_status"] == "REUSED"
        if name == "confirmation":
            pending = first["items"][0]["draft"]
            consent = ConfirmationCommand.from_dict({
                "confirmation_id": "C-M2-example", "draft_id": pending["draft_id"],
                "expected_version": pending["version"], "accepted_item_ids": pending["pending_confirmations"],
                "actor": "local-example-reviewer", "note": "合成用户明确同意将18点调整为19点",
            })
            approved = store.confirm(consent).to_dict()
            traces.append({"driver_mode": "manual_tools", "model_called": False,
                           "entrypoint": "trusted_local_confirmation", "command": {
                               "draft_id": consent.draft_id, "expected_version": consent.expected_version,
                               "accepted_item_ids": list(consent.accepted_item_ids), "actor": consent.actor,
                               "confirmation_id": consent.confirmation_id, "note": consent.note,
                           }, "observation": approved})
            final = ToolSession(store, request).result()
            checkpoints.append(final)
        expected = {"normal": "READY_DRAFTS", "missing": "NEEDS_INPUT", "risk": "BLOCKED",
                    "conflict": "NEEDS_CONFIRMATION", "duplicate": "READY_DRAFTS",
                    "save_failure": "FAILED", "confirmation": "READY_DRAFTS"}[name]
        assert final["task_status"] == expected, (name, final)
        counts = store.counts()
        assert counts["drafts"] == (0 if name in {"missing", "risk", "save_failure"} else 1)
        assert counts["reservations"] == (1 if name in {"normal", "duplicate", "confirmation"} else 0)
        input_path = ROOT / f"examples/inputs/M2-{name}.json"
        output_path = ROOT / f"examples/outputs/M2-{name}.json"
        trace_path = ROOT / f"examples/traces/M2-{name}.jsonl"
        write_json(input_path, {"driver_mode": "manual_tools", "request": raw,
                               "trusted_dataset": fixture_to_dict(current), "trusted_faults": fault_config})
        write_json(output_path, {"driver_mode": "manual_tools", "model_called": False,
                                "checkpoints": checkpoints, "result": final, "ledger_counts": counts,
                                "audit_events": store.audit_events()})
        trace_path.write_text("".join(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n" for record in traces), encoding="utf-8", newline="\n")
        cases.append({"case": name, "expected": expected, "actual": final["task_status"],
                      "passed": True, "tool_calls": sum("tool" in record for record in traces),
                      "input": input_path.relative_to(ROOT).as_posix(),
                      "output": output_path.relative_to(ROOT).as_posix(),
                      "trace": trace_path.relative_to(ROOT).as_posix()})
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=True).stdout.strip()
    evidence_files = [ROOT / case[kind] for case in cases for kind in ("input", "output", "trace")]
    write_json(ROOT / "examples/evaluation/M2-cases.json", {
        "generated_at": stamp, "base_commit": base, "source_state": "working_tree_source_hashes",
        "source_hashes_lf_sha256": source_hashes(), "driver_mode": "manual_tools",
        "model_called": False, "react_verified": False, "cases": cases,
        "evidence_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in evidence_files},
    })
    print(json.dumps({"cases_passed": len(cases), "model_called": False, "driver_mode": "manual_tools"}))


if __name__ == "__main__":
    run()
