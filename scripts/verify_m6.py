"""Current offline release checks; authenticate historical evidence without relabeling it."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile

from material_scheduler.agent.trace import verify_trace
from material_scheduler.interfaces.artifacts import write_json
from run_m5_examples import ROOT, source_hashes
from stage_guard import require_stage


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    require_stage("0.6.0")
    clean = ROOT / "var/m6-clean-venv"
    python = clean / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = ROOT / "var/m6-wheel/material_scheduling_agent-0.6.0-py3-none-any.whl"
    with ZipFile(wheel) as archive:
        for path in (ROOT / "src/material_scheduler").rglob("*"):
            if path.suffix in {".py", ".html", ".css", ".js", ".svg"}:
                assert archive.read(path.relative_to(ROOT / "src").as_posix()).replace(b"\r\n", b"\n") == path.read_bytes().replace(b"\r\n", b"\n"), path
    checks = [
        ("development-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("clean-wheel-tests", [str(python), "-I", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("web-state-tests", ["node", "--test", "tests/web/state.test.cjs"]),
        ("javascript-syntax", ["node", "--check", "src/material_scheduler/interfaces/web/app.js"]),
        ("compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        ("development-pip-check", [sys.executable, "-m", "pip", "check"]),
        ("clean-wheel-pip-check", [str(python), "-m", "pip", "check"]),
        ("clean-wheel-package", [str(python), "-I", "-c", "import material_scheduler; print(material_scheduler.__version__); print(material_scheduler.__file__)"]),
    ]
    records = []
    for name, command in checks:
        process = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8"),
                                 capture_output=True, text=True, encoding="utf-8", timeout=180)
        output = (process.stdout + process.stderr).replace("\r\n", "\n").rstrip() + "\n"
        log = ROOT / f"examples/evaluation/M6-{name}.txt"
        log.write_text(output, encoding="utf-8", newline="\n")
        record = {"check": name, "command": command, "returncode": process.returncode,
                  "log": log.relative_to(ROOT).as_posix(), "log_sha256": sha(log)}
        if name.endswith("tests") and name != "web-state-tests":
            matched = re.search(r"Ran (\d+) tests", output)
            assert matched and output.endswith("OK\n"), output[-4000:]
            record["unittest_methods"] = int(matched[1])
        if name == "web-state-tests":
            count, failed = re.search(r"# tests (\d+)", output), re.search(r"# fail (\d+)", output)
            assert count and failed and int(failed[1]) == 0, output[-4000:]
            record["node_cases"] = int(count[1])
        if name == "clean-wheel-package":
            assert output.splitlines()[0] == "0.6.0" and Path(output.splitlines()[1]).resolve().is_relative_to(clean.resolve())
        assert process.returncode == 0, output[-4000:]
        records.append(record)
        print(name + ": passed", flush=True)
    current_file = ROOT / "examples/workbench/M6/manifest.json"
    current = json.loads(current_file.read_text(encoding="utf-8"))
    assert current["source_hashes_lf_sha256"] == source_hashes() and current["all_passed"]
    current_traces = 0
    for relative, expected in current["evidence_sha256"].items():
        path = current_file.parent / relative
        assert sha(path) == expected, relative
        if path.name == "trace.jsonl":
            verify_trace(path)
            current_traces += 1
    historical = []
    for relative, commit, base in [
        ("examples/evaluation/M4-real-cases.json", "d48e50f", ROOT),
        ("examples/evaluation/M4-mock-cases.json", "d48e50f", ROOT),
        ("examples/workbench/http/manifest.json", "9af839e", ROOT / "examples/workbench/http"),
        ("examples/workbench/real-normal/assessment.json", "9af839e", ROOT / "examples/workbench/real-normal"),
    ]:
        path = ROOT / relative
        data = json.loads(path.read_text(encoding="utf-8"))
        for item, expected in data["evidence_sha256"].items():
            artifact = base / item
            assert sha(artifact) == expected, item
            if artifact.suffix == ".jsonl":
                verify_trace(artifact)
        historical.append({"manifest": relative, "commit": commit, "sha256": sha(path), "unmodified": True})
    write_json(ROOT / "examples/evaluation/M6-summary.json", {"generated_at": datetime.now(timezone.utc).isoformat(),
               "source_hashes_lf_sha256": source_hashes(), "checks": records, "wheel_sha256": sha(wheel),
               "wheel_sources_and_assets_match": True, "current_evidence_sha256": sha(current_file),
               "current_http_cases": 6, "current_terminal_recovery_cases": 1, "current_verified_traces": current_traces,
               "historical_evidence": historical, "paid_provider_calls_this_stage": 0,
               "test_count_definition": "unittest methods, Node cases, HTTP cases and historical real runs are separate counts",
               "full_submission_complete": False})


if __name__ == "__main__":
    main()
