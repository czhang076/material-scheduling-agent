"""Export one existing real web run for review. Does not call a provider."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3

from material_scheduler.adapters.sqlite_store import SQLiteStore, fixture_to_dict
from material_scheduler.agent.trace import verify_trace
from material_scheduler.interfaces.artifacts import new_directory, package_identity, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    with sqlite3.connect(f"file:{(args.state_dir / 'runs.sqlite3').resolve().as_posix()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM runs WHERE run_id=?", (args.run_id,)).fetchone()
        assert row is not None and row["mode"] == "real" and row["status"] == "FINISHED"
    folder = args.state_dir / "runs" / row["run_id"]
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["code"] == package_identity(), "Do not relabel an old run as current source"
    events = verify_trace(folder / "trace.jsonl")
    receipts = [event["event"]["metadata"] for event in events if event["event"]["type"] == "provider_response_metadata"]
    observations = [event["event"] for event in events if event["event"]["type"] == "tool_observation"]
    store = SQLiteStore(args.db)
    request = json.loads(row["request_json"])
    current = store.read_request(row["request_id"])
    draft = current["items"][0]["draft"]
    checks = {
        "local_workbench_entrypoint": manifest["invocation"]["entrypoint"] == "local_workbench",
        "ready_result": result["task_status"] == "READY_DRAFTS",
        "real_deepseek": result["model"]["mode"] == "real" and result["model"]["transport"]["provider"] == "deepseek",
        "native_service_receipts": bool(receipts) and all(r.get("response_id") and r.get("tool_call_id") for r in receipts),
        "actual_observation_loop": len(observations) >= 4 and observations[0]["action"]["tool"] == "read_material" and observations[-1]["action"]["tool"] == "finish",
        "persisted_current_ready": draft["draft_state"] == "READY",
        "hard_time_unchanged": draft["candidate"]["start"] == request["items"][0]["time_requirement"]["requested_start"],
        "trace_complete": result["trace_complete"] is True,
        "not_published": not result["published"] and not draft["published"],
    }
    assert all(checks.values()), checks
    new_directory(args.out)
    for name in ("trace.jsonl", "result.json", "manifest.json"):
        shutil.copyfile(folder / name, args.out / name)
    with store._readonly() as connection:
        dataset, _, _, _ = store._catalog(connection)
    write_json(args.out / "input.json", {"request": request, "trusted_dataset": fixture_to_dict(dataset),
               "note": "Synthetic QA catalog. Additional local drafts, including the earlier confirmed 19:00 draft, are in ledger.json."})
    write_json(args.out / "ledger.json", {"current": current, "drafts": store.list_drafts(), "counts": store.counts(),
                                          "audit": store.audit_events()})
    exported = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in args.out.iterdir() if p.is_file()}
    write_json(args.out / "assessment.json", {"generated_at": datetime.now(timezone.utc).isoformat(),
               "run_id": row["run_id"], "code": manifest["code"], "checks": checks, "all_passed": True,
               "provider_calls": len(receipts), "scope": "One real web normal-path integration; not a new seven-case model benchmark",
               "runtime_facts_preserved": True, "evidence_sha256": exported})
    print(json.dumps({"checks": checks, "provider_calls": len(receipts)}))


if __name__ == "__main__":
    main()
