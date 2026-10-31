"""Explicit paid acceptance against an installed package. Never runs on import.

Uses the normal CLI except for the explicitly disclosed persistent local-save
fault case. SQLite queries independently check output against committed facts.
Existing evidence is never replaced. Run with an isolated wheel interpreter.
"""

import argparse
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from urllib.parse import urlsplit

from material_scheduler.adapters.compatible_model import CompatibleChatModel
from material_scheduler.adapters.faults import FaultInjector
from material_scheduler.adapters.fixture_loader import load_fixture_set
from material_scheduler.adapters.model_config import load_model_config
from material_scheduler.adapters.sqlite_store import SQLiteStore, fixture_to_dict
from material_scheduler.agent.trace import verify_trace
from material_scheduler.domain.budgets import ExecutionLimits
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.scheduling import Booking
from material_scheduler.interfaces.artifacts import package_identity, result_exit_code, run_request


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def ledger(path):
    with sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        counts = {table: connection.execute("SELECT count(*) FROM " + table).fetchone()[0]
                  for table in ("requests", "drafts", "reservations", "confirmations", "operation_receipts")}
        overlaps = connection.execute("""SELECT count(*) FROM reservations a JOIN reservations b
          ON a.draft_id < b.draft_id AND a.channel=b.channel
          AND a.start_utc < b.end_utc AND b.start_utc < a.end_utc""").fetchone()[0]
        return {"counts": counts, "overlapping_reservations": overlaps,
                "requests": [json.loads(row[0]) for row in connection.execute("SELECT payload_json FROM requests")],
                "drafts": [dict(row) for row in connection.execute("SELECT draft_id,version,state,channel,start_utc,end_utc FROM drafts")],
                "reservations": [dict(row) for row in connection.execute("SELECT * FROM reservations")]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline-commit", required=True)
    args = parser.parse_args()
    config = load_model_config(args.env_file, environ={})
    assert config.provider == "deepseek", "This assessment only attests the configured DeepSeek provider"
    endpoint = urlsplit(config.endpoint)
    assert endpoint.scheme == "https" and endpoint.hostname == "api.deepseek.com", "Real acceptance requires the official HTTPS endpoint"
    args.out.mkdir(parents=True, exist_ok=False)
    args.work_dir.mkdir(parents=True, exist_ok=False)
    source = args.source_dir.resolve()
    base = load_fixture_set(source / "data")
    raw_base = json.loads((source / "data/requests/normal.json").read_text(encoding="utf-8"))
    environment = {key: value for key, value in os.environ.items() if not key.startswith("MODEL_") and key != "PYTHONPATH"}
    environment.update(PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    code, started = package_identity(), datetime.now(timezone.utc).isoformat()
    groups, records = {}, []
    for name in ("normal", "conflict", "duplicate", "changed-occupancy", "missing", "blocked-risk", "manual-risk", "save-failure"):
        group = {"duplicate": "normal", "changed-occupancy": "conflict"}.get(name, name)
        if group not in groups:
            dataset = base
            if group == "conflict":
                offer = next(o for o in base.slot_offers if o.channel == "douyin" and o.interval.start.hour == 18)
                dataset = replace(base, existing_bookings=(*base.existing_bookings, Booking("ACCEPT-B18", 1, offer.channel, offer.interval)))
            raw = json.loads(json.dumps(raw_base))
            raw["request_id"] = "REQ-ACCEPT-REAL-" + group
            raw["items"][0]["material_id"] = {"missing": "M02", "blocked-risk": "M03", "manual-risk": "M04"}.get(name, "M01")
            store = SQLiteStore(args.work_dir / (group + ".sqlite3"))
            store.import_dataset(dataset)
            groups[group] = (store, dataset, raw)
        store, dataset, raw = groups[group]
        if name == "changed-occupancy":
            offer = next(o for o in base.slot_offers if o.channel == "douyin" and o.interval.start.hour == 19)
            dataset = replace(dataset, existing_bookings=(*dataset.existing_bookings, Booking("ACCEPT-B19", 1, offer.channel, offer.interval)))
            store.import_dataset(dataset)
        case = args.out / name
        case.mkdir()
        write(case / "request.json", raw)
        write(case / "input.json", {"request": raw, "trusted_dataset": fixture_to_dict(dataset),
              "trusted_faults": {"save.after_draft_write": 100} if name == "save-failure" else {}})
        if name == "save-failure":
            store.faults = FaultInjector({"save.after_draft_write": 100})
            limits = replace(ExecutionLimits.for_items(1), max_tool_attempts=10, max_model_rounds=12, run_timeout_seconds=120)
            result = run_request(store, SchedulingRequest.from_dict(raw), CompatibleChatModel(config), case / "run", limits=limits,
                                 invocation={"entrypoint": "trusted_acceptance_fault_harness", "faults": {"save.after_draft_write": 100}})
            exit_code = result_exit_code(result)
            invocation = {"kind": "installed application use case", "fault_injected": True}
        else:
            command = [sys.executable, "-I", "-m", "material_scheduler", "run", "--mode", "real", "--env-file", str(args.env_file.resolve()),
                       "--db", str(store.path.resolve()), "--input", str((case / "request.json").resolve()), "--out", str((case / "run").resolve()),
                       "--max-tool-attempts", "10", "--max-model-rounds", "12", "--run-timeout-seconds", "120"]
            process = subprocess.run(command, cwd=source, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=150)
            result, exit_code = json.loads(process.stdout), process.returncode
            invocation = {"kind": "actual CLI subprocess", "command": command, "exit_code": exit_code}
            (case / "stderr.txt").write_text(process.stderr, encoding="utf-8", newline="\n")
        events = verify_trace(case / "run/trace.jsonl")
        manifest = json.loads((case / "run/manifest.json").read_text(encoding="utf-8"))
        facts = ledger(store.path)
        item = result.get("items", [{}])[0]
        draft = item.get("draft")
        actions = [(index, e["event"]["action"]) for index, e in enumerate(events) if e["event"]["type"] == "action_selected"]
        observations = [(index, e["event"]) for index, e in enumerate(events) if e["event"]["type"] == "tool_observation"]
        receipts = [e["event"]["metadata"] for e in events if e["event"]["type"] == "provider_response_metadata"]
        checks = {"real_provider": result["model"]["mode"] == "real" and result["model"]["transport"]["provider"] == "deepseek",
                  "installed_code_matches": manifest["code"] == code,
                  "trace_complete": result["trace_complete"] is True,
                  "native_response_receipts": bool(receipts) and any(r.get("response_id") and r.get("tool_call_id") for r in receipts),
                  "observations_change_next_actions": any(a > o for a, _ in actions for o, _ in observations),
                  "original_requirement_immutable": facts["requests"][0] == SchedulingRequest.from_dict(raw).to_dict(),
                  "not_published": result["published"] is False and (not draft or draft["published"] is False),
                  "tool_budget_respected": result["stats"]["tool_attempts"] <= 10,
                  "no_reservation_overlap": facts["overlapping_reservations"] == 0}
        if name in {"normal", "duplicate"}:
            checks.update(expected_state=result["task_status"] == "READY_DRAFTS", actual_one_ready=facts["counts"]["drafts"] == facts["counts"]["reservations"] == 1,
                          target_kept=bool(draft) and draft["candidate"]["start"] == raw["items"][0]["time_requirement"]["requested_start"])
        elif group == "conflict":
            hour = "20:00" if name == "changed-occupancy" else "19:00"
            checks.update(expected_state=result["task_status"] == "NEEDS_CONFIRMATION",
                          changed_hard_time_pending=bool(draft) and hour in draft["candidate"]["start"] and draft["pending_confirmations"] == ["TIME_CHANGE"],
                          pending_not_reserved=facts["counts"]["drafts"] == 1 and facts["counts"]["reservations"] == facts["counts"]["confirmations"] == 0,
                          conflict_then_alternative=any(a > o and action["tool"] == "query_slots" and action["arguments"].get("mode") == "alternatives"
                              for o, obs in observations if obs["action"]["tool"] == "query_slots" and obs["observation"].get("data", {}).get("requested_available") is False for a, action in actions))
        elif name in {"missing", "blocked-risk"}:
            checks.update(expected_state=result["task_status"] == ("NEEDS_INPUT" if name == "missing" else "BLOCKED"), no_draft=facts["counts"]["drafts"] == 0)
        elif name == "manual-risk":
            checks.update(expected_state=result["task_status"] == "NEEDS_CONFIRMATION",
                          risk_not_self_approved=bool(draft) and draft["review_status"] == "NEEDS_REVIEW" and any(p.startswith("RISK:") for p in draft["pending_confirmations"]),
                          no_model_confirmation=facts["counts"]["confirmations"] == facts["counts"]["reservations"] == 0)
        else:
            checks.update(failed_save_explicit=item.get("save_attempt", {}).get("save_status") == "FAILED" and result["task_status"] != "READY_DRAFTS" and exit_code in {4, 5},
                          rollback=facts["counts"]["drafts"] == facts["counts"]["reservations"] == facts["counts"]["operation_receipts"] == 0,
                          actual_failed_tool=any(obs["action"]["tool"] == "save_draft" and not obs["observation"]["ok"] for _, obs in observations))
        if name in {"duplicate", "changed-occupancy"}:
            previous = next(r for r in records if r["case"] == group)
            checks["same_draft_identity"] = bool(draft) and draft["draft_id"] == previous["draft_id"]
            checks["correct_version_behavior"] = bool(draft) and (draft["version"] == previous["draft_version"] if name == "duplicate" else draft["version"] > previous["draft_version"])
            if name == "duplicate":
                checks["save_reused"] = item["save_attempt"]["save_status"] == "REUSED"
        write(case / "assessment.json", {"checks": checks, "all_passed": all(checks.values()), "ledger": facts, "invocation": invocation,
                                          "actual_state": result["task_status"], "exit_code": exit_code})
        for path in case.rglob("*"):
            if path.is_file() and config.api_key.encode() in path.read_bytes():
                raise RuntimeError("Refusing to export a credential")
        records.append({"case": name, "passed": all(checks.values()), "checks": checks, "state": result["task_status"], "provider_calls": len(receipts),
                        "draft_id": draft["draft_id"] if draft else None, "draft_version": draft["version"] if draft else None})
        print(json.dumps({"case": name, "state": result["task_status"], "passed": all(checks.values()), "provider_calls": len(receipts)}), flush=True)
        if result["stop_reason"] in {"MODEL_AUTH_ERROR", "MODEL_HTTP_ERROR"}:
            break
    assert code == package_identity()
    report = {"started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(), "baseline_commit": args.baseline_commit,
              "code": code, "provider": config.public_info(), "interpreter": sys.executable, "cases": records,
              "all_passed": len(records) == 8 and all(r["passed"] for r in records),
              "real_react_verified": all(any(r["case"] == name and r["passed"] for r in records) for name in ("normal", "conflict")),
              "evidence_sha256": {p.relative_to(args.out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(args.out.rglob("*")) if p.is_file()}}
    write(args.out / "manifest.json", report)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
