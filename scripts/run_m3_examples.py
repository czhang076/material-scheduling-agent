"""Execute the actual offline CLI and export reviewed evidence, without DBs."""

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import shutil
import subprocess
import sys
from uuid import uuid4

from material_scheduler.agent.trace import verify_trace
from run_m2_examples import ROOT, source_hashes, write_json


def run(prefix="M3"):
    local = ROOT / "var/m3-examples" / uuid4().hex
    command = [sys.executable, "-m", "material_scheduler", "evaluate", "--data-dir", "data", "--out", str(local)]
    process = subprocess.run(command, cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),
                             text=True, encoding="utf-8", capture_output=True, timeout=120)
    if process.returncode:
        raise SystemExit(process.stdout + process.stderr)
    report = json.loads(process.stdout)
    assert report["all_passed"]
    exported = []
    exported_cases = []
    for case in report["cases"]:
        name = case["case"]
        record = {**case, "runs": []}
        for key, directory in [("input", "inputs"), ("output", "outputs")]:
            path = ROOT / f"examples/{directory}/{prefix}-{name}.json"
            shutil.copyfile(local / case[key], path)
            record[key] = path.relative_to(ROOT).as_posix()
            exported.append(path)
        for index, original in enumerate(case["runs"], 1):
            run_prefix = f"{prefix}-{name}-run{index}"
            result_file = ROOT / f"examples/outputs/{run_prefix}.json"
            trace_file = ROOT / f"examples/traces/{run_prefix}.jsonl"
            shutil.copyfile(local / original["result"], result_file)
            shutil.copyfile(local / original["trace"], trace_file)
            events = verify_trace(trace_file)
            manifest = json.loads((local / original["manifest"]).read_text(encoding="utf-8"))
            assert manifest["files"]["result.json"] == sha256(result_file.read_bytes()).hexdigest()
            assert manifest["files"]["trace.jsonl"] == sha256(trace_file.read_bytes()).hexdigest()
            manifest_file = ROOT / f"examples/evaluation/{run_prefix}-manifest.json"
            # Preserve the actual runtime manifest, mapping original relative
            # artifact names to reviewed export paths without rewriting facts.
            write_json(manifest_file, {"runtime_manifest": manifest,
                                      "exported_files": {"result.json": result_file.relative_to(ROOT).as_posix(),
                                                         "trace.jsonl": trace_file.relative_to(ROOT).as_posix()}})
            record["runs"].append({"result": result_file.relative_to(ROOT).as_posix(),
                                   "trace": trace_file.relative_to(ROOT).as_posix(),
                                   "manifest": manifest_file.relative_to(ROOT).as_posix(),
                                   "exit_code": original["exit_code"], "trace_events": len(events)})
            exported.extend([result_file, trace_file, manifest_file])
        exported_cases.append(record)
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    write_json(ROOT / f"examples/evaluation/{prefix}-cases.json", {
        **report, "cases": exported_cases, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "actual_command": command, "base_commit": base, "source_state": "working_tree_source_hashes",
        "source_hashes_lf_sha256": source_hashes(), "real_model_called": False,
        "evidence_sha256": {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest() for path in exported},
    })
    print(json.dumps({"mock_cases_passed": len(report["cases"]), "actual_runs": sum(len(case["runs"]) for case in report["cases"]),
                      "real_model_called": False}))


if __name__ == "__main__":
    run()
