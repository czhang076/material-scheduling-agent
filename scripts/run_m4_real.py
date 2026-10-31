"""Explicit, paid network verification. Never invoked by unittest/verify scripts.

Use --env-file with an ignored local key. Each CLI invocation is bounded. Export
only synthetic evidence; the external assessment does not rewrite runtime facts.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4
from types import SimpleNamespace

from material_scheduler.adapters.fixture_loader import load_fixture_set
from material_scheduler.adapters.model_config import load_model_config
from material_scheduler.adapters.compatible_model import CompatibleChatModel
from material_scheduler.adapters.faults import FaultInjector
from material_scheduler.adapters.sqlite_store import SQLiteStore, fixture_to_dict
from material_scheduler.agent.trace import verify_trace
from material_scheduler.domain.scheduling import Booking
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.interfaces.artifacts import package_identity, run_request, result_exit_code
from run_m2_examples import ROOT, write_json


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--out", type=Path)
    names = ("normal", "conflict", "duplicate", "changed-occupancy", "missing", "risk", "save-failure")
    parser.add_argument("--cases", nargs="+", choices=names)
    parser.add_argument("--append", action="store_true", help="Append independent missing/risk/failure cases to existing matching-code evidence")
    arguments = parser.parse_args()
    config = load_model_config(arguments.env_file)
    local = arguments.out or ROOT / "var/m4-real" / uuid4().hex
    local.mkdir(parents=True, exist_ok=False)
    initial_identity = package_identity()
    dataset = load_fixture_set(ROOT / "data")
    raw_base = json.loads((ROOT / "data/requests/normal.json").read_text(encoding="utf-8"))
    records, exported = [], []
    if arguments.append:
        prior = json.loads((ROOT / "examples/evaluation/M4-real-cases.json").read_text(encoding="utf-8"))
        assert prior["code"] == initial_identity and prior["provider"] == config.public_info()
        records = prior["cases"]
        exported = [ROOT / relative for relative in prior["evidence_sha256"]]
        assert arguments.cases and all(name in {"missing", "risk", "save-failure"} for name in arguments.cases)
    stores = {}
    for name in arguments.cases or names:
        assert name not in {record["case"] for record in records}, "Do not overwrite earlier paid-run evidence"
        group = "normal" if name in {"normal", "duplicate"} else "conflict" if name in {"conflict", "changed-occupancy"} else name
        if group not in stores:
            current = dataset
            if group == "conflict":
                offer = next(offer for offer in dataset.slot_offers if offer.interval.start.hour == 18)
                current = replace(dataset, existing_bookings=(Booking("REAL-B18", 1, offer.channel, offer.interval),))
            store = SQLiteStore(local / (group + ".sqlite3"), faults=FaultInjector({"save.after_draft_write": 2} if name == "save-failure" else {}))
            store.import_dataset(current)
            raw = json.loads(json.dumps(raw_base))
            raw["request_id"] = "REQ-REAL-" + group
            raw["items"][0]["material_id"] = {"missing": "M02", "risk": "M03"}.get(name, "M01")
            stores[group] = [store, current, raw]
        store, current, raw = stores[group]
        if name == "changed-occupancy":
            offer = next(offer for offer in current.slot_offers if offer.interval.start.hour == 19)
            current = replace(current, existing_bookings=current.existing_bookings + (Booking("REAL-B19", 1, offer.channel, offer.interval),))
            store.import_dataset(current)
        input_path = local / (name + "-request.json")
        write_json(input_path, raw)
        out = local / name
        command = [sys.executable, "-m", "material_scheduler", "run", "--mode", "real", "--env-file", str(arguments.env_file),
                   "--db", str(store.path), "--input", str(input_path), "--out", str(out),
                   "--max-tool-attempts", "10", "--max-model-rounds", "12", "--run-timeout-seconds", "120"]
        if name == "save-failure":
            from material_scheduler.domain.budgets import ExecutionLimits
            limits = replace(ExecutionLimits.for_items(1), max_tool_attempts=10, max_model_rounds=12, run_timeout_seconds=120)
            result = run_request(store, SchedulingRequest.from_dict(raw), CompatibleChatModel(config), out, limits=limits,
                                 invocation={"operation": "trusted_real_save_fault_evaluation", "faults": {"save.after_draft_write": 2}})
            process = SimpleNamespace(returncode=result_exit_code(result))
        else:
            process = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"), text=True, encoding="utf-8", capture_output=True, timeout=150)
            result = json.loads(process.stdout)
        events = verify_trace(out / "trace.jsonl") if (out / "trace.jsonl").exists() else []
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8")) if (out / "manifest.json").exists() else None
        receipts = [event["event"]["metadata"] for event in events if event["event"]["type"] == "provider_response_metadata"]
        actions = [event["event"]["action"] for event in events if event["event"]["type"] == "action_selected"]
        item = result.get("items", [{}])[0]
        draft = item.get("draft")
        expected = "READY_DRAFTS" if group == "normal" else "NEEDS_CONFIRMATION" if group == "conflict" else {
            "missing": "NEEDS_INPUT", "risk": "BLOCKED", "save-failure": "FAILED"}[name]
        checks = {"expected_state": result["task_status"] == expected, "real_mode": result.get("model", {}).get("mode") == "real",
                  "native_response_receipts": bool(receipts) and all(receipt.get("tool_call_id") and receipt.get("response_id") for receipt in receipts),
                  "trace_complete": result.get("trace_complete") is True, "not_published": result.get("published") is False,
                  "expected_draft_count": store.counts()["drafts"] == (1 if group in {"normal", "conflict"} else 0),
                  "original_request_retained": (bool(draft) and "18:00" in draft["requested_start"]) if group in {"normal", "conflict"} else True}
        if name == "save-failure":
            checks["failed_not_successful"] = item["save_attempt"]["save_status"] == "FAILED" and process.returncode == 4
        if group == "conflict":
            hour = "20:00" if name == "changed-occupancy" else "19:00"
            checks["alternative_requires_confirmation"] = bool(draft) and hour in draft["candidate"]["start"] and draft["pending_confirmations"] == ["TIME_CHANGE"]
            queries = [action["arguments"].get("mode") for action in actions if action["tool"] == "query_slots"]
            checks["observed_conflict_then_selected_alternative"] = "requested" in queries and "alternatives" in queries
        if name in {"duplicate", "changed-occupancy"}:
            prior = next(record for record in records if record["case"] == group)
            checks["same_draft_identity"] = bool(draft) and draft["draft_id"] == prior["draft_id"]
            if name == "duplicate":
                checks["save_reused"] = item["save_attempt"]["save_status"] == "REUSED"
            else:
                checks["new_version"] = bool(draft) and draft["version"] > prior["draft_version"]
        input_export = ROOT / f"examples/inputs/M4-real-{name}.json"
        output_export = ROOT / f"examples/outputs/M4-real-{name}.json"
        raw_result_export = ROOT / f"examples/outputs/M4-real-{name}-result.json"
        trace_export = ROOT / f"examples/traces/M4-real-{name}.jsonl"
        manifest_export = ROOT / f"examples/evaluation/M4-real-{name}-manifest.json"
        write_json(input_export, {"mode": "real", "request": raw, "trusted_dataset": fixture_to_dict(current),
                                  "trusted_faults": {"save.after_draft_write": 2} if name == "save-failure" else {}})
        write_json(output_export, {"result": result, "exit_code": process.returncode, "checks": checks,
                                   "ledger_counts": store.counts(), "audit_events": store.audit_events()})
        shutil.copyfile(out / "result.json", raw_result_export)
        if events:
            shutil.copyfile(out / "trace.jsonl", trace_export)
        write_json(manifest_export, {"runtime_manifest": manifest, "assessment_checks": checks,
                                    "exported_files": {"result.json": raw_result_export.relative_to(ROOT).as_posix(), "trace.jsonl": trace_export.relative_to(ROOT).as_posix()}})
        paths = [input_export, output_export, raw_result_export, manifest_export] + ([trace_export] if events else [])
        for path in paths:
            if config.api_key.encode() in path.read_bytes():
                raise RuntimeError("Credentials must not appear in reviewed artifacts")
        exported.extend(paths)
        records.append({"case": name, "passed": all(checks.values()), "expected_state": expected, "actual_state": result["task_status"],
                        "checks": checks, "input": input_export.relative_to(ROOT).as_posix(), "output": output_export.relative_to(ROOT).as_posix(),
                        "runtime_result": raw_result_export.relative_to(ROOT).as_posix(),
                        "trace": trace_export.relative_to(ROOT).as_posix() if events else None,
                        "manifest": manifest_export.relative_to(ROOT).as_posix(), "exit_code": process.returncode,
                        "draft_id": draft["draft_id"] if draft else None, "draft_version": draft["version"] if draft else None,
                        "provider_calls": len(receipts), "usage": [receipt.get("usage", {}) for receipt in receipts]})
        if result.get("stop_reason") in {"MODEL_AUTH_ERROR", "MODEL_HTTP_ERROR", "MODEL_UNAVAILABLE"}:
            break
    assert package_identity() == initial_identity, "Source changed while collecting network evidence"
    core = [record for record in records if record["case"] in {"normal", "conflict"}]
    report = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "code": initial_identity,
              "provider": config.public_info(), "real_model_called": True,
              "real_react_verified": len(core) == 2 and all(record["passed"] for record in core),
              "all_passed": {record["case"] for record in records} == set(names) and all(record["passed"] for record in records), "cases": records,
              "evidence_sha256": {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest() for path in exported}}
    write_json(ROOT / "examples/evaluation/M4-real-cases.json", report)
    print(json.dumps({"actual_real_runs": len(records), "all_passed": report["all_passed"],
                      "real_react_verified": report["real_react_verified"],
                      "states": {record["case"]: record["actual_state"] for record in records}}), flush=True)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(run())
