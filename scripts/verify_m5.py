"""Verify the current package, HTTP evidence and frozen historical M4 traces."""

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
from material_scheduler.interfaces.artifacts import package_identity, write_json
from run_m5_examples import ROOT, source_hashes


def main():
    from stage_guard import require_stage
    require_stage("0.5.0")
    python = ROOT / "var/m5-clean-venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = ROOT / "var/m5-wheel/material_scheduling_agent-0.5.0-py3-none-any.whl"
    with ZipFile(wheel) as archive:
        for path in (ROOT / "src/material_scheduler").rglob("*"):
            if path.suffix in {".py", ".html", ".css", ".js", ".svg"}:
                assert archive.read(path.relative_to(ROOT / "src").as_posix()).replace(b"\r\n", b"\n") == path.read_bytes().replace(b"\r\n", b"\n"), path
    commands = [
        ("development-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("clean-wheel-tests", [str(python), "-I", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("development-compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        ("development-pip-check", [sys.executable, "-m", "pip", "check"]),
        ("clean-wheel-pip-check", [str(python), "-m", "pip", "check"]),
        ("clean-wheel-package", [str(python), "-I", "-c", "import material_scheduler; print(material_scheduler.__version__); print(material_scheduler.__file__)"]),
        ("javascript-syntax", ["node", "--check", "src/material_scheduler/interfaces/web/app.js"]),
    ]
    records = []
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    for name, command in commands:
        process = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=180)
        output = (process.stdout + process.stderr).replace("\r\n", "\n").rstrip() + "\n"
        path = ROOT / f"examples/evaluation/M5-{name}.txt"
        path.write_text(output, encoding="utf-8", newline="\n")
        record = {"check": name, "command": command, "returncode": process.returncode,
                  "log": path.relative_to(ROOT).as_posix(), "log_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if name.endswith("tests"):
            matched = re.search(r"Ran (\d+) tests", output)
            assert matched and output.endswith("OK\n"), output[-4000:]
            record["tests_run"] = int(matched[1])
        if name == "clean-wheel-package":
            assert output.splitlines()[0] == "0.5.0"
            assert Path(output.splitlines()[1]).resolve().is_relative_to(python.parents[1].resolve())
        assert process.returncode == 0, output[-4000:]
        records.append(record)
        print(name + ": passed", flush=True)
    evidence = ROOT / "examples/workbench/http/manifest.json"
    current = json.loads(evidence.read_text(encoding="utf-8"))
    assert current["source_hashes_lf_sha256"] == source_hashes()
    assert current["all_passed"] and not current["real_decision_verified"]
    for path, expected in current["evidence_sha256"].items():
        assert hashlib.sha256((evidence.parent / path).read_bytes()).hexdigest() == expected, path
    for path in evidence.parent.rglob("trace.jsonl"):
        verify_trace(path)
    real_folder = ROOT / "examples/workbench/real-normal"
    real = json.loads((real_folder / "assessment.json").read_text(encoding="utf-8"))
    assert real["all_passed"] and real["code"] == package_identity()
    for path, expected in real["evidence_sha256"].items():
        assert hashlib.sha256((real_folder / path).read_bytes()).hexdigest() == expected
    verify_trace(real_folder / "trace.jsonl")
    historical = ROOT / "examples/evaluation/M4-real-cases.json"
    old = json.loads(historical.read_text(encoding="utf-8"))
    for path, expected in old["evidence_sha256"].items():
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
    for case in old["cases"]:
        verify_trace(ROOT / case["trace"])
    # Historical evidence is authenticated, never relabeled as a current-package run.
    assert old["all_passed"] and old["real_react_verified"]
    write_json(ROOT / "examples/evaluation/M5-summary.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(), "source_hashes_lf_sha256": source_hashes(),
        "checks": records, "http_cases": len(current["cases"]), "http_evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest(),
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(), "wheel_sources_and_assets_match": True,
        "current_web_real_runs": 1, "current_web_provider_calls": real["provider_calls"],
        "real_web_assessment_sha256": hashlib.sha256((real_folder / "assessment.json").read_bytes()).hexdigest(),
        "historical_M4": {"commit": "d48e50f", "runs": len(old["cases"]), "evidence_unmodified": True,
                          "manifest_sha256": hashlib.sha256(historical.read_bytes()).hexdigest()},
        "test_count_definition": "unittest methods; live provider calls and browser checks are counted separately",
        "full_submission_complete": False,
    })


if __name__ == "__main__":
    main()
