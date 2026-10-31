"""Exercise actual local HTTP + Mock jobs; export receipts and linked traces."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from material_scheduler.agent.trace import verify_trace
from material_scheduler.interfaces.artifacts import new_directory, write_json
from tests.integration.m2_helpers import occupied, request
from tests.integration.test_workbench import WorkbenchTests


def source_hashes():
    paths = [ROOT / "pyproject.toml"]
    for directory in ("src", "tests", "scripts", "data"):
        paths.extend(path for path in (ROOT / directory).rglob("*")
                     if path.suffix in {".py", ".json", ".html", ".css", ".js", ".cjs", ".svg"})
    return {path.relative_to(ROOT).as_posix(): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            for path in sorted(paths)}


def main():
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "examples/workbench/http"
    output = output.resolve()
    new_directory(output)
    reports = []
    for name in ("normal", "missing", "risk", "conflict-confirm", "duplicate", "save-failure"):
        case = WorkbenchTests()
        case.setUp()
        calls = []
        original = case.http
        def recorded(method, path, body=None, **kwargs):
            response = original(method, path, body, **kwargs)
            calls.append({"method": method, "path": path, "input": body, "status": response[0], "output": response[1]})
            return response
        case.http = recorded
        try:
            req = request("REQ-WEB-" + name, "M99" if name == "missing" else "M05" if name == "risk" else "M01")
            if name == "conflict-confirm":
                case.store.import_dataset(occupied(case.dataset))
            if name == "save-failure":
                case.fault(**{"save.before_write": 3})
            run = case.run_case(req)
            checks = {"mock_only": run["mode"] == "mock", "finished_registry": run["status"] == "FINISHED"}
            draft = run["current"]["items"][0]["draft"]
            if name == "normal":
                checks["ready"] = draft["draft_state"] == "READY"
            elif name in {"missing", "risk"}:
                checks["no_saved_draft"] = draft is None
                checks["not_ready"] = run["result"]["task_status"] != "READY_DRAFTS"
            elif name == "conflict-confirm":
                checks["hard_change_pending"] = draft["pending_confirmations"] == ["TIME_CHANGE"] and "18:00" in draft["requested_start"] and "19:00" in draft["candidate"]["start"]
                url = "/api/drafts/" + draft["draft_id"] + "/confirm"
                denied = case.http("POST", url, case.confirm_body(draft, accepted_item_ids=[]))
                accepted = case.http("POST", url, case.confirm_body(draft))
                repeated = case.http("POST", url, case.confirm_body(draft))
                checks["partial_consent_rejected"] = denied[0] == 409
                checks["explicit_version_ready_unpublished"] = accepted[0] == 200 and accepted[1]["draft_state"] == "READY" and not accepted[1]["published"]
                checks["same_confirmation_reused"] = repeated[1]["confirmation_status"] == "REUSED" and case.store.counts()["confirmations"] == 1
            elif name == "duplicate":
                reused = case.submit(req)
                again = case.submit(req, submission="SUB-2")
                next_run = case.finished(again[1]["run"]["run_id"])
                checks["same_submission_same_run"] = reused[0] == 200 and reused[1]["run"]["run_id"] == run["run_id"]
                checks["new_run_same_draft"] = next_run["result"]["items"][0]["save_attempt"]["save_status"] == "REUSED" and case.store.counts()["drafts"] == 1
            else:
                checks["actual_save_failed_no_draft"] = run["result"]["items"][0]["save_attempt"]["save_status"] == "FAILED" and draft is None
            before = case.store.counts()
            case.http("GET", "/api/runs/" + run["run_id"])
            checks["get_does_not_write"] = before == case.store.counts()
            folder = output / name
            folder.mkdir()
            write_json(folder / "input.json", req.to_dict())
            write_json(folder / "http.json", calls)
            write_json(folder / "ledger-counts.json", case.store.counts())
            for job in case.app.journal.list():
                source = case.app.journal.directory / "runs" / job["run_id"]
                shutil.copytree(source, folder / job["run_id"])
                verify_trace(folder / job["run_id"] / "trace.jsonl")
            reports.append({"case": name, "checks": checks, "passed": all(checks.values()), "run_id": run["run_id"],
                            "evidence_directory": folder.relative_to(output).as_posix()})
            assert all(checks.values()), (name, checks)
            print(name + ": passed", flush=True)
        finally:
            case.doCleanups()
    files = {path.relative_to(output).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
             for path in sorted(output.rglob("*")) if path.is_file()}
    write_json(output / "manifest.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "mode": "mock",
               "real_decision_verified": False, "source_hashes_lf_sha256": source_hashes(), "cases": reports,
               "all_passed": all(case["passed"] for case in reports), "evidence_sha256": files})


if __name__ == "__main__":
    main()
