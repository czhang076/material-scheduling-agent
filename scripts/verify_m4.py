"""Offline test/install/evidence verification. Never calls a real provider."""

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
from material_scheduler.interfaces.artifacts import package_identity
from run_m2_examples import ROOT, source_hashes, write_json


def main():
    clean = ROOT / "var/m4-clean-venv"
    clean_python = clean / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = ROOT / "var/m4-wheel/material_scheduling_agent-0.4.0-py3-none-any.whl"
    with ZipFile(wheel) as archive:
        for path in (ROOT / "src/material_scheduler").rglob("*.py"):
            assert archive.read(path.relative_to(ROOT / "src").as_posix()).replace(b"\r\n", b"\n") == path.read_bytes().replace(b"\r\n", b"\n"), path
    commands = [
        ("development-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("clean_wheel-tests", [str(clean_python), "-I", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("development-compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        ("development-pip_check", [sys.executable, "-m", "pip", "check"]),
        ("clean_wheel-pip_check", [str(clean_python), "-m", "pip", "check"]),
        ("clean_wheel-package", [str(clean_python), "-I", "-c", "import material_scheduler; print(material_scheduler.__version__); print(material_scheduler.__file__)"]),
    ]
    records = []
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for name, command in commands:
        process = subprocess.run(command, cwd=ROOT, env=environment, text=True, encoding="utf-8", capture_output=True, timeout=180)
        output = (process.stdout + process.stderr).replace("\r\n", "\n").rstrip()
        if output:
            output += "\n"
        log = ROOT / f"examples/evaluation/M4-{name}.txt"
        log.write_text(output, encoding="utf-8", newline="\n")
        record = {"check": name, "command": command, "returncode": process.returncode,
                  "log": log.relative_to(ROOT).as_posix(), "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        if name.endswith("tests"):
            matched = re.search(r"Ran (\d+) tests", output)
            record["tests_run"] = int(matched[1]) if matched else None
            assert matched and output.endswith("OK\n"), output[-4000:]
        if name == "clean_wheel-package":
            assert output.splitlines()[0] == "0.4.0" and Path(output.splitlines()[1]).resolve().is_relative_to(clean.resolve())
        records.append(record)
        print(f"{name}: returncode={process.returncode}", flush=True)
        if process.returncode:
            raise SystemExit(output[-4000:])
    mock_file = ROOT / "examples/evaluation/M4-mock-cases.json"
    network_file = ROOT / "examples/evaluation/M4-real-cases.json"
    mock = json.loads(mock_file.read_text(encoding="utf-8"))
    network = json.loads(network_file.read_text(encoding="utf-8"))
    assert mock["source_hashes_lf_sha256"] == source_hashes()
    assert network["code"] == package_identity(), "Network evidence must match the shipped package source"
    for report in (mock, network):
        for relative, expected in report["evidence_sha256"].items():
            content = (ROOT / relative).read_bytes()
            assert hashlib.sha256(content).hexdigest() == expected, relative
            assert not re.search(rb"sk-[0-9a-f]{25,}", content), "Do not export live credentials"
    for case in mock["cases"]:
        for run in case["runs"]:
            verify_trace(ROOT / run["trace"])
    for case in network["cases"]:
        verify_trace(ROOT / case["trace"])
        exported = json.loads((ROOT / case["manifest"]).read_text(encoding="utf-8"))
        for original, relative in exported["exported_files"].items():
            assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == exported["runtime_manifest"]["files"][original]
    assert mock["all_passed"] and network["all_passed"] and network["real_react_verified"]
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    write_json(ROOT / "examples/evaluation/M4-summary.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "base_commit": base,
        "source_state": "working_tree_source_hashes", "source_hashes_lf_sha256": source_hashes(), "checks": records,
        "wheel": {"path": wheel.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "package_source_matches_worktree": True},
        "mock_manifest_sha256": hashlib.sha256(mock_file.read_bytes()).hexdigest(),
        "real_manifest_sha256": hashlib.sha256(network_file.read_bytes()).hexdigest(),
        "test_count_definition": "unittest methods; subtests, environments and live runs are separate counts",
        "mock_cases_passed": len(mock["cases"]), "actual_real_runs": len(network["cases"]),
        "real_react_verified": network["real_react_verified"], "credentials_exported": False,
        "full_submission_complete": False,
    })


if __name__ == "__main__":
    main()
