"""Read-only independent verification of this acceptance bundle. No paid calls."""

import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

from material_scheduler.agent.trace import verify_trace
from material_scheduler.interfaces.artifacts import package_identity


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    root = args.root.resolve()
    real = read(root / "real/manifest.json")
    endpoint = urlsplit(real["provider"]["endpoint"])
    assert endpoint.scheme == "https" and endpoint.hostname == "api.deepseek.com"
    assert real["all_passed"] and real["real_react_verified"] and len(real["cases"]) == 8
    assert real["code"] == package_identity(), "Evidence targets another application source fingerprint"
    for relative, expected in real["evidence_sha256"].items():
        assert hashlib.sha256((root / "real" / relative).read_bytes()).hexdigest() == expected, relative
    case_paths = list((root / "real").glob("*/run")) + list((root / "web").glob("RUN-*"))
    provider_calls = 0
    for folder in case_paths:
        manifest, result = read(folder / "manifest.json"), read(folder / "result.json")
        assert manifest["code"] == real["code"] and result["model"]["mode"] == "real"
        assert result["published"] is False
        for relative, expected in manifest["files"].items():
            assert hashlib.sha256((folder / relative).read_bytes()).hexdigest() == expected
        events = [event["event"] for event in verify_trace(folder / "trace.jsonl")]
        receipts = [event["metadata"] for event in events if event["type"] == "provider_response_metadata"]
        actions = [event["action"] for event in events if event["type"] == "action_selected"]
        assert receipts and len(receipts) == len(actions)
        assert all(receipt.get("response_id") and receipt.get("tool_call_id") for receipt in receipts)
        assert len({receipt["tool_call_id"] for receipt in receipts}) == len(receipts)
        assert [receipt["selected_tool"] for receipt in receipts] == [action["tool"] for action in actions]
        provider_calls += len(receipts)
    assert len(case_paths) == 10
    before, after = read(root / "web/ledger-before-confirm.json"), read(root / "web/ledger-after-confirm.json")
    assert before["drafts"] == 2 and before["reservations"] == 1 and before["confirmations"] == 0
    assert len(after["drafts"]) == len(after["reservations"]) == 2 and len(after["confirmations"]) == 1
    assert all(draft["state"] == "READY" for draft in after["drafts"])
    for index, first in enumerate(after["reservations"]):
        for second in after["reservations"][index + 1:]:
            assert first["channel"] != second["channel"] or first["start_utc"] >= second["end_utc"] or second["start_utc"] >= first["end_utc"]
    browser = {item["check"]: item for item in read(root / "web/browser-checks.json")["checks"]}
    normal = browser["real-web-normal"]
    assert normal["mode"] == "real" and normal["status"] == "READY_DRAFTS" and normal["published"] is False
    conflict = browser["real-web-hard-conflict-and-rejections"]
    assert conflict["mode"] == "real" and conflict["pending"] == ["TIME_CHANGE"]
    assert "18:00" in conflict["original"] and "19:00" in conflict["candidate"]
    assert conflict["incomplete"] == {"status": 409, "code": "CONFIRMATION_INCOMPLETE"}
    assert conflict["wrongVersion"] == {"status": 409, "code": "DRAFT_VERSION_CONFLICT"}
    consent = browser["real-web-consent-not-preselected"]
    assert consent["all_unchecked"] and consent["submit_disabled"]
    confirmation = browser["explicit-consent-and-idempotent-confirmation"]
    assert confirmation["confirmation_status"] == "REUSED" and confirmation["current"] == "READY" and confirmation["historical_run"] == "NEEDS_CONFIRMATION"
    isolation = browser["actual-real-history-isolation"]
    assert isolation["all_events_belong_to_selected"] and isolation["no_duplicates"]
    refresh = browser["refresh-does-not-rerun-model"]
    assert refresh["runs"] == 2 and refresh["drafts"] == 2 and refresh["run_mode"] == "real"
    assert browser["mobile"]["horizontal_page_overflow"] is False
    intent = browser["unknown-real-submission-cannot-override-new-mock-input"]
    assert intent["http_posts"] == 1 and intent["actual_server_runs"] == 2 and intent["original_identity_preserved"]
    assert intent["original_mode"] == "real" and intent["visible_mode"] == "mock"
    offline = read(root / "offline/evaluation.json")
    assert offline["all_passed"] and len(offline["cases"]) == 14
    offline_traces = list((root / "offline").rglob("trace.jsonl"))
    assert len(offline_traces) == 16
    for path in offline_traces:
        verify_trace(path)
    http = read(root / "http-mock/manifest.json")
    assert http["all_passed"] and all(http["recovery_case"].values())
    for relative, expected in http["evidence_sha256"].items():
        assert hashlib.sha256((root / "http-mock" / relative).read_bytes()).hexdigest() == expected
    http_traces = list((root / "http-mock").rglob("trace.jsonl"))
    for path in http_traces:
        verify_trace(path)
    tests = (root / "clean-unittest.txt").read_text(encoding="utf-8")
    assert "Ran 222 tests" in tests and tests.rstrip().endswith("OK") and not re.search(r"skipped=\d", tests)
    node = (root / "node-state.txt").read_text(encoding="utf-8")
    assert "# tests 7" in node and "# pass 7" in node and "# fail 0" in node
    assert all(record["returncode"] == 0 for record in read(root / "clean-checks.json")["records"])
    installation = read(root / "installation.json")
    assert installation["all_package_files_match"] and installation["package_files_checked"] == 39
    if (root / "manifest.json").is_file():
        bundle = read(root / "manifest.json")
        for relative, expected in bundle["evidence_sha256"].items():
            assert hashlib.sha256((root / relative).read_bytes()).hexdigest() == expected, relative
    print(json.dumps({"technical_checks_passed": True, "real_runs": len(case_paths), "real_provider_calls": provider_calls,
                      "offline_cases": len(offline["cases"]), "offline_runs": len(offline_traces),
                      "http_mock_traces": len(http_traces), "unittest_methods": 222, "node_cases": 7,
                      "github_delivery_verified": False, "candidate_work_hours_verified": False}))


if __name__ == "__main__":
    main()
