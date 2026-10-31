"""Fresh M6 HTTP + Mock evidence; historical M4/M5 files are never overwritten."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

from material_scheduler.agent.trace import verify_trace
from material_scheduler.interfaces.artifacts import new_directory, write_json
from run_m5_examples import ROOT, main as shared_http_cases, source_hashes
from tests.integration.test_workbench import WorkbenchTests
from tests.integration.m2_helpers import request


def main():
    output = (Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples/workbench/M6").resolve()
    new_directory(output)
    original_argv = sys.argv
    try:
        sys.argv = [__file__, str(output / "http")]
        shared_http_cases()
    finally:
        sys.argv = original_argv
    case = WorkbenchTests()
    case.setUp()
    try:
        run_id, original_update, attempts = case.fail_terminal_writes()
        initial_worker_ended = not case.app._thread.is_alive()
        before_counts, before_writes = case.store.counts(), len(attempts)
        degraded = case.http("GET", "/api/runs/" + run_id)
        listing = case.http("GET", "/api/runs")
        alias = case.http("GET", "/api/submissions/SUB-1")
        get_counts, get_writes = case.store.counts(), len(attempts)
        rejected = case.submit(request("REQ-BLOCKED-WRITE"), submission="SUB-NEW")
        case.app.journal.update = original_update
        recovered = case.submit()
        accepted = case.submit(request("REQ-RECOVERED-NEXT"), submission="SUB-NEXT")
        next_run = case.finished(accepted[1]["run"]["run_id"])
        checks = {
            "worker_ended": initial_worker_ended,
            "degraded_not_running": degraded[1]["status"] == "INTERRUPTED" and degraded[1]["error"]["code"] == "RUN_STATE_UNPERSISTED",
            "actual_draft_preserved": degraded[1]["current"]["items"][0]["draft"]["draft_state"] == "READY",
            "all_read_views_consistent": listing[1]["runs"][0]["status"] == alias[1]["run"]["status"] == "INTERRUPTED",
            "get_does_not_retry_writes": (before_counts, before_writes) == (get_counts, get_writes),
            "persistent_fault_explicit_failure": rejected[0] == 503 and rejected[1]["error"]["code"] == "RUN_STORE_UNAVAILABLE",
            "same_submission_reconciles_same_run": recovered[0] == 200 and recovered[1]["run"]["run_id"] == run_id and recovered[1]["run"]["status"] == "FINISHED",
            "next_request_no_longer_busy": accepted[0] == 202 and next_run["status"] == "FINISHED",
        }
        assert all(checks.values()), checks
        folder = output / "terminal-recovery"
        folder.mkdir()
        write_json(folder / "input.json", {"request": request().to_dict(), "fault": "Terminal journal updates fail until restored; tools remain Mock"})
        write_json(folder / "observations.json", {"degraded": degraded[1], "listing": listing[1], "submission_lookup": alias[1],
                   "new_work_during_fault": {"status": rejected[0], "body": rejected[1]},
                   "recovered_original": recovered[1], "next_run": next_run, "checks": checks})
        for job in case.app.journal.list():
            shutil.copytree(case.app.journal.directory / "runs" / job["run_id"], folder / job["run_id"])
            verify_trace(folder / job["run_id"] / "trace.jsonl")
        write_json(folder / "ledger-counts.json", case.store.counts())
    finally:
        case.doCleanups()
    hashes = {p.relative_to(output).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(output.rglob("*")) if p.is_file()}
    write_json(output / "manifest.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": "mock",
               "real_model_called": False, "source_hashes_lf_sha256": source_hashes(), "http_cases": 6,
               "recovery_case": checks, "all_passed": all(checks.values()), "evidence_sha256": hashes})
    print("terminal-recovery: passed", flush=True)


if __name__ == "__main__":
    main()
