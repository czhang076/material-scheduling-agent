"""Capture real development and isolated-wheel verification in reviewed logs.

Build/install the 0.2.0 wheel and its independent venv first, as documented in
M2-ACCEPTANCE. This script does not install dependencies or call a model.
"""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from zipfile import ZipFile

from run_m2_examples import ROOT, source_hashes, write_json


def main():
    clean = ROOT / "var/m2-clean-venv"
    clean_python = clean / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not clean_python.is_file():
        raise SystemExit("Create var/m2-clean-venv and install the M2 wheel first")
    wheel = ROOT / "var/m2-wheel/material_scheduling_agent-0.2.0-py3-none-any.whl"
    with ZipFile(wheel) as archive:
        for path in (ROOT / "src/material_scheduler").rglob("*.py"):
            relative = path.relative_to(ROOT / "src").as_posix()
            assert archive.read(relative).replace(b"\r\n", b"\n") == path.read_bytes().replace(b"\r\n", b"\n"), relative
    environment = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    commands = [
        ("development-tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("clean_wheel-tests", [str(clean_python), "-I", "-m", "unittest", "discover", "-s", "tests", "-t", ".", "-v"]),
        ("development-compileall", [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"]),
        ("development-pip_check", [sys.executable, "-m", "pip", "check"]),
        ("clean_wheel-pip_check", [str(clean_python), "-m", "pip", "check"]),
        ("clean_wheel-package", [str(clean_python), "-I", "-c", "import material_scheduler; print(material_scheduler.__version__); print(material_scheduler.__file__)"]),
    ]
    records = []
    for name, command in commands:
        result = subprocess.run(command, cwd=ROOT, env=environment, text=True, encoding="utf-8", capture_output=True, timeout=120)
        output = (result.stdout + result.stderr).replace("\r\n", "\n").rstrip()
        if output:
            output += "\n"
        log = ROOT / f"examples/evaluation/M2-{name}.txt"
        log.write_text(output, encoding="utf-8", newline="\n")
        record = {"check": name, "command": command, "returncode": result.returncode,
                  "log": log.relative_to(ROOT).as_posix(),
                  "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest()}
        if name.endswith("tests"):
            matched = re.search(r"Ran (\d+) tests", output)
            record["tests_run"] = int(matched[1]) if matched else None
            assert matched and output.endswith("OK\n"), output[-2000:]
        if name == "clean_wheel-package":
            package_file = Path(output.splitlines()[1]).resolve()
            assert package_file.is_relative_to(clean.resolve()), output
            assert output.splitlines()[0] == "0.2.0", output
        records.append(record)
        print(f"{name}: returncode={result.returncode}", flush=True)
        if result.returncode:
            raise SystemExit(output[-4000:])
    cases_file = ROOT / "examples/evaluation/M2-cases.json"
    cases = json.loads(cases_file.read_text(encoding="utf-8"))
    assert cases["source_hashes_lf_sha256"] == source_hashes(), "Regenerate examples after source changes"
    for relative, expected in cases["evidence_sha256"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected, relative
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    write_json(ROOT / "examples/evaluation/M2-summary.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "base_commit": base, "source_state": "working_tree_source_hashes",
        "source_hashes_lf_sha256": source_hashes(), "checks": records,
        "wheel": {"path": wheel.relative_to(ROOT).as_posix(), "sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                  "package_source_matches_worktree": True},
        "cases_manifest_sha256": hashlib.sha256(cases_file.read_bytes()).hexdigest(),
        "test_count_definition": "unittest methods; subtests and duplicate environments are not added",
        "manual_tool_cases_passed": len(cases["cases"]), "model_called": False,
        "real_sqlite_verified": True, "react_verified": False, "agent_acceptance_completed": False,
    })


if __name__ == "__main__":
    main()
