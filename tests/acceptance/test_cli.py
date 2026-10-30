"""Subprocess-level CLI, manifests, real ledger and reproducible evaluation."""

import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from material_scheduler.adapters.mock_model import ObservationMock
from material_scheduler.agent.trace import verify_trace
from material_scheduler.domain.validation import DomainError
from material_scheduler.interfaces.artifacts import file_hash, run_request
from tests.integration.m2_helpers import LedgerTest, ROOT, occupied, request


class CLIAcceptanceTests(LedgerTest):
    def cli(self, *arguments):
        result = subprocess.run([sys.executable, "-I", "-m", "material_scheduler", *map(str, arguments)],
                                cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
                                encoding="utf-8", capture_output=True, timeout=60)
        self.assertEqual(result.stderr, "", result.stderr)
        return result.returncode, json.loads(result.stdout)

    def input_file(self, req=None):
        path = self.directory / "request.json"
        path.write_text(json.dumps((req or request()).to_dict()), encoding="utf-8")
        return path

    def run_cli(self, *options, out="run"):
        return self.cli("run", "--db", self.path, "--input", self.input_file(), "--mode", "mock",
                        "--out", self.directory / out, *options)

    def test_init_and_normal_run_create_linked_actual_artifacts(self):
        fresh_db = self.directory / "fresh.sqlite3"
        code, initialized = self.cli("init", "--db", fresh_db, "--data-dir", ROOT / "data")
        self.assertEqual(code, 0)
        self.assertTrue(initialized["import"]["changed"])
        code, result = self.run_cli()
        self.assertEqual(code, 0)
        self.assertEqual(result["task_status"], "READY_DRAFTS")
        out = self.directory / "run"
        manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["model"]["mode"], "mock")
        self.assertFalse(manifest["real_decision_verified"])
        for filename, expected in manifest["files"].items():
            self.assertEqual(file_hash(out / filename), expected)
        events = verify_trace(out / "trace.jsonl")
        actions = [event["event"]["action"]["tool"] for event in events if event["event"]["type"] == "action_selected"]
        self.assertEqual(actions, ["read_material", "check_rules", "query_slots", "save_draft", "finish"])

    def test_duplicate_run_uses_fresh_evidence_but_same_draft(self):
        _, first = self.run_cli(out="first")
        code, second = self.run_cli(out="second")
        self.assertEqual(code, 0)
        self.assertNotEqual(first["run_id"], second["run_id"])
        self.assertEqual(first["items"][0]["draft"]["draft_id"], second["items"][0]["draft"]["draft_id"])
        self.assertEqual(second["items"][0]["save_attempt"]["save_status"], "REUSED")

    def test_existing_output_is_not_overwritten(self):
        self.run_cli()
        old_trace = (self.directory / "run/trace.jsonl").read_bytes()
        code, result = self.run_cli()
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "OUTPUT_EXISTS")
        self.assertEqual((self.directory / "run/trace.jsonl").read_bytes(), old_trace)

    def test_cli_conflict_and_explicit_user_confirmation(self):
        self.store.import_dataset(occupied(self.dataset))
        code, proposed = self.run_cli()
        self.assertEqual(code, 2)
        draft = proposed["items"][0]["draft"]
        code, approved = self.cli("confirm", "--db", self.path, "--draft-id", draft["draft_id"],
                                  "--expected-version", draft["version"], "--confirmation-id", "C-CLI",
                                  "--actor", "local-reviewer", "--accept", "TIME_CHANGE")
        self.assertEqual(code, 0)
        self.assertEqual(approved["draft_state"], "READY")
        self.assertFalse(approved["published"])
        _, current = self.cli("inspect", "--db", self.path, "--request-id", proposed["request_id"])
        self.assertEqual(current["items"][0]["draft"]["version"], approved["version"])

    def test_cli_budget_restrictions_and_explicit_incomplete_exit(self):
        code, result = self.run_cli("--max-tool-attempts", 3)
        self.assertEqual(code, 5)
        self.assertEqual(result["stop_reason"], "LIMIT_REACHED")
        code, result = self.run_cli("--max-tool-attempts", 200, out="bad-limits")
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "INVALID_INPUT")
        self.assertFalse((self.directory / "bad-limits").exists())

    def test_real_mode_is_not_silently_replaced_by_mock(self):
        code, result = self.cli("run", "--db", self.path, "--input", self.input_file(), "--mode", "real",
                                "--out", self.directory / "real")
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "REAL_MODEL_NOT_IMPLEMENTED")
        self.assertFalse((self.directory / "real").exists())
        self.assertEqual(self.store.counts()["requests"], 0)

    def test_malformed_input_and_cli_arguments_are_json_errors(self):
        path = self.directory / "invalid.json"
        path.write_text('{"schema_version":"1.0","schema_version":"1.0"}', encoding="utf-8")
        code, result = self.cli("run", "--db", self.path, "--input", path, "--mode", "mock", "--out", self.directory / "bad")
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "INVALID_INPUT")
        path.write_text('{"request_id":' + '9' * 5000 + '}', encoding="utf-8")
        code, result = self.cli("run", "--db", self.path, "--input", path, "--mode", "mock", "--out", self.directory / "bad-numeric")
        self.assertEqual(code, 3)
        self.assertEqual(result["error"]["code"], "INVALID_INPUT")
        code, result = self.cli("run")
        self.assertEqual(code, 3)

    def test_missing_database_is_explicit_and_not_created(self):
        nonexistent = self.directory / "nonexistent.sqlite3"
        code, result = self.cli("inspect", "--db", nonexistent, "--request-id", "REQ")
        self.assertEqual(code, 4)
        self.assertEqual(result["error"]["code"], "STORE_UNAVAILABLE")
        self.assertFalse(nonexistent.exists())

    def test_full_offline_evaluation_covers_required_and_changed_occupancy_paths(self):
        out = self.directory / "evaluation"
        code, report = self.cli("evaluate", "--data-dir", ROOT / "data", "--out", out)
        self.assertEqual(code, 0)
        self.assertEqual(len(report["cases"]), 14)
        self.assertTrue(report["all_passed"])
        self.assertFalse(report["real_decision_verified"])
        for case in report["cases"]:
            self.assertTrue(case["passed"], case)
            for run in case["runs"]:
                events = verify_trace(out / run["trace"])
                self.assertEqual(events[-1]["event"]["type"], "run_stopped")

    def test_trace_modification_is_detected(self):
        self.run_cli()
        path = self.directory / "run/trace.jsonl"
        lines = path.read_text(encoding="utf-8").splitlines()
        path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
        with self.assertRaises(DomainError):
            verify_trace(path)
        first = json.loads(lines[0])
        first["event"]["request"]["request_id"] = "FORGED"
        lines[0] = json.dumps(first)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(DomainError):
            verify_trace(path)

    def test_final_artifact_failure_preserves_save_but_reports_failure(self):
        from material_scheduler.interfaces.artifacts import write_json as actual_write
        def failing(path, data):
            if Path(path).name == "result.json":
                raise DomainError("ARTIFACT_UNAVAILABLE", "test output disk failure")
            return actual_write(path, data)
        with patch("material_scheduler.interfaces.artifacts.write_json", side_effect=failing):
            result = run_request(self.store, request(), ObservationMock(), self.directory / "broken-output")
        self.assertEqual(result["stop_reason"], "ARTIFACT_UNAVAILABLE")
        self.assertEqual(result["items"][0]["draft"]["draft_state"], "READY")
        self.assertEqual(self.store.counts()["drafts"], 1)
