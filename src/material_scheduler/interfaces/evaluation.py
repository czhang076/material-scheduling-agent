"""Trusted synthetic offline scenarios using the same runtime as CLI run."""

from dataclasses import replace
from pathlib import Path

from material_scheduler.adapters.faults import FaultInjector
from material_scheduler.adapters.fixture_loader import load_fixture_set
from material_scheduler.adapters.mock_model import ObservationMock
from material_scheduler.adapters.sqlite_store import SQLiteStore, fixture_to_dict
from material_scheduler.agent.trace import verify_trace
from material_scheduler.application.tools import ToolSession
from material_scheduler.domain.catalog import MetadataSupplement
from material_scheduler.domain.budgets import ExecutionLimits
from material_scheduler.domain.drafts import ConfirmationCommand
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.scheduling import Booking
from .artifacts import new_directory, result_exit_code, run_request, write_json


def _request(name, material):
    return {"schema_version": "1.0", "request_id": "REQ-M3-" + name,
            "items": [{"item_id": "I01", "material_id": material, "channel": "douyin",
                       "time_requirement": {"requested_start": "2030-06-01T18:00:00+08:00", "duration_minutes": 30,
                                            "mode": "hard", "alternative_window": {
                                                "start": "2030-06-01T18:00:00+08:00", "end": "2030-06-01T21:00:00+08:00"}}}]}


def scenarios(dataset):
    specifications = [
        ("normal", "M01", (), {}, "READY_DRAFTS", 1),
        ("missing", "M02", (), {}, "NEEDS_INPUT", 0),
        ("risk", "M03", (), {}, "BLOCKED", 0),
        ("conflict", "M01", (18,), {}, "NEEDS_CONFIRMATION", 1),
        ("duplicate", "M01", (), {}, "READY_DRAFTS", 1),
        ("save-failure", "M01", (), {"save.after_draft_write": 2}, "FAILED", 0),
        ("tool-recovery", "M01", (), {"query_slots": 1}, "READY_DRAFTS", 1),
        ("supplement", "M02", (), {}, "READY_DRAFTS", 1),
        ("changed-occupancy", "M01", (18,), {}, "NEEDS_CONFIRMATION", 1),
        ("confirmation", "M01", (18,), {}, "READY_DRAFTS", 1),
        ("manual-risk", "M04", (), {}, "NEEDS_CONFIRMATION", 1),
        ("no-slots", "M01", (18, 19, 20), {}, "INCOMPLETE", 0),
        ("limit", "M01", (), {}, "INCOMPLETE", 0),
        ("unknown-save", "M01", (), {"save.after_commit": 1, "receipt.read": 1}, "PARTIAL", 1),
    ]
    for name, material, hours, faults, expected, count in specifications:
        bookings = list(dataset.existing_bookings)
        for hour in hours:
            offer = next(offer for offer in dataset.slot_offers if offer.channel == "douyin" and offer.interval.start.hour == hour)
            bookings.append(Booking("EVAL-B" + str(hour), 1, offer.channel, offer.interval))
        current = replace(dataset, existing_bookings=tuple(bookings))
        if name == "supplement":
            current = replace(current, supplements=(MetadataSupplement(
                "EVAL-S02", "M02", 1, (("rights_status", "licensed"),), "synthetic local rights register"),))
        yield {"case": name, "request": _request(name, material), "dataset": current,
               "faults": faults, "expected_task_status": expected, "expected_drafts": count}


def evaluate(data_dir: Path, out: Path):
    dataset = load_fixture_set(data_dir)
    new_directory(out)
    reports = []
    for scenario in scenarios(dataset):
        name = scenario["case"]
        case_dir = out / name
        case_dir.mkdir()
        raw = scenario["request"]
        request = SchedulingRequest.from_dict(raw)
        store = SQLiteStore(case_dir / "ledger.sqlite3", faults=FaultInjector(scenario["faults"]))
        store.import_dataset(scenario["dataset"])
        input_data = {"model_mode": "mock", "request": raw, "trusted_dataset": fixture_to_dict(scenario["dataset"]),
                      "trusted_faults": scenario["faults"], "trusted_confirmation": name == "confirmation"}
        limits = replace(ExecutionLimits.for_items(1), max_tool_attempts=3) if name == "limit" else None
        if limits:
            input_data["limit_overrides"] = {"max_tool_attempts": 3}
        changed_dataset = None
        if name == "changed-occupancy":
            offer = next(offer for offer in dataset.slot_offers if offer.channel == "douyin" and offer.interval.start.hour == 19)
            changed_dataset = replace(scenario["dataset"], existing_bookings=scenario["dataset"].existing_bookings + (
                Booking("EVAL-B19", 1, offer.channel, offer.interval),))
            input_data["trusted_dataset_updates_between_runs"] = [fixture_to_dict(changed_dataset)]
        write_json(case_dir / "input.json", input_data)
        results, runs = [], []
        for index in range(2 if name in {"duplicate", "changed-occupancy"} else 1):
            if index and changed_dataset is not None:
                store.import_dataset(changed_dataset)
            run_dir = case_dir / f"run-{index + 1}"
            result = run_request(store, request, ObservationMock(), run_dir,
                                 limits=limits, invocation={"command": "evaluate", "case": name, "run_index": index + 1})
            results.append(result)
            verify_trace(run_dir / "trace.jsonl")
            runs.append({"result": (run_dir / "result.json").relative_to(out).as_posix(),
                         "trace": (run_dir / "trace.jsonl").relative_to(out).as_posix(),
                         "manifest": (run_dir / "manifest.json").relative_to(out).as_posix(),
                         "exit_code": result_exit_code(result)})
        final = results[-1]
        trusted_confirmation = None
        if name == "confirmation":
            draft = final["items"][0]["draft"]
            consent = {"confirmation_id": "C-M3-example", "draft_id": draft["draft_id"],
                       "expected_version": draft["version"], "accepted_item_ids": draft["pending_confirmations"],
                       "actor": "synthetic-local-reviewer", "note": "合成评测用户明确接受当前19点建议"}
            approved = store.confirm(ConfirmationCommand.from_dict(consent)).to_dict()
            trusted_confirmation = {"origin": "trusted_synthetic_user", "model_called": False,
                                    "command": consent, "actual_result": approved}
            final = ToolSession(store, request).result()
        counts = store.counts()
        checks = {"task_status": final["task_status"] == scenario["expected_task_status"],
                  "draft_count": counts["drafts"] == scenario["expected_drafts"],
                  "never_published": not final["published"],
                  "traces_complete": all(result["trace_complete"] for result in results),
                  "model_mode_explicit": all(result["model"]["mode"] == "mock" for result in results)}
        if name == "duplicate":
            before, after = [result["items"][0]["draft"] for result in results]
            checks["same_draft_and_version"] = (before["draft_id"], before["version"]) == (after["draft_id"], after["version"])
            checks["reused"] = final["items"][0]["save_attempt"]["save_status"] == "REUSED"
        if name in {"conflict", "changed-occupancy"}:
            draft = final["items"][0]["draft"]
            expected_hour = "20:00" if name == "changed-occupancy" else "19:00"
            checks["candidate_changes_with_occupancy"] = expected_hour in draft["candidate"]["start"]
            checks["original_retained_and_confirmation_required"] = "18:00" in draft["requested_start"] and draft["pending_confirmations"] == ["TIME_CHANGE"]
            checks["pending_not_reserved"] = counts["reservations"] == 0
        if name == "save-failure":
            checks["rollback"] = counts["reservations"] == counts["operation_receipts"] == 0
            checks["failed_attempt"] = final["items"][0]["save_attempt"]["save_status"] == "FAILED"
        if name == "confirmation":
            checks["one_user_consent_one_reservation"] = counts["confirmations"] == counts["reservations"] == 1
        if name == "changed-occupancy":
            before, after = [result["items"][0]["draft"] for result in results]
            checks["same_request_replanned_same_draft"] = before["draft_id"] == after["draft_id"] and after["version"] > before["version"]
        if name == "limit":
            checks["explicit_bounded_stop"] = final["stop_reason"] == "LIMIT_REACHED" and final["stats"]["tool_attempts"] == 3
        if name == "unknown-save":
            checks["unknown_not_false_success"] = final["items"][0]["save_attempt"]["save_status"] == "UNKNOWN" and counts["drafts"] == 1
        output = {"model_mode": "mock", "real_decision_verified": False, "checkpoints": results,
                  "trusted_confirmation": trusted_confirmation, "final_result": final,
                  "ledger_counts": counts, "audit_events": store.audit_events(), "checks": checks}
        write_json(case_dir / "actual.json", output)
        reports.append({"case": name, "passed": all(checks.values()), "checks": checks,
                        "expected_task_status": scenario["expected_task_status"], "actual_task_status": final["task_status"],
                        "input": (case_dir / "input.json").relative_to(out).as_posix(),
                        "output": (case_dir / "actual.json").relative_to(out).as_posix(), "runs": runs})
    report = {"evaluation_mode": "mock", "real_decision_verified": False,
              "all_passed": all(case["passed"] for case in reports), "cases": reports}
    write_json(out / "evaluation.json", report)
    return report
