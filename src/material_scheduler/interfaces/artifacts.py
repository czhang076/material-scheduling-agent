"""Owned run directories, actual output and a content-linked run manifest."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

from material_scheduler import __version__
from material_scheduler.agent.runner import AgentRunner
from material_scheduler.agent.trace import FileTrace
from material_scheduler.application.tools import ToolSession
from material_scheduler.domain.validation import DomainError, fingerprint


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def package_identity():
    root = Path(__file__).resolve().parents[1]
    sources = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
               for path in sorted(root.rglob("*.py"))}
    return {"package_version": __version__, "package_source_sha256": fingerprint(sources)}


def write_json(path: Path, data):
    """Only replace an artifact in a directory owned by this invocation."""
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, UnicodeError, ValueError) as exc:
        raise DomainError("ARTIFACT_UNAVAILABLE", "Cannot save the run artifact") from exc


def new_directory(path: Path):
    try:
        path.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise DomainError("OUTPUT_EXISTS", "Choose a fresh output directory; existing evidence is preserved") from exc
    except OSError as exc:
        raise DomainError("ARTIFACT_UNAVAILABLE", "Cannot create the output directory") from exc


def run_request(store, request, model, out: Path, *, limits=None, invocation=None):
    new_directory(out)
    source = store.source_identity()
    session = ToolSession(store, request)
    manifest = {"schema_version": "1.0", "run_id": session.run_id, "request_id": request.request_id,
                "request_sha256": request.payload_hash, "source_identity": source,
                "code": package_identity(), "invocation": invocation,
                "model": {"mode": model.mode, "name": model.name, "version": model.version},
                "started_at": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "status": "RUNNING", "real_decision_verified": None if model.mode == "real" else False}
    write_json(out / "manifest.json", manifest)
    trace = FileTrace(out / "trace.jsonl", session.run_id)
    try:
        result = AgentRunner(session, model, trace=trace, limits=limits, source_identity=source).run()
    except BaseException:
        try:
            trace.close()
        except DomainError:
            pass
        raise
    try:
        trace.close()
    except DomainError:
        result.update(task_status="FAILED", execution_status="FAILED", stop_reason="TRACE_UNAVAILABLE", trace_complete=False)
    try:
        write_json(out / "result.json", result)
        manifest.update(status="FINISHED", finished_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                        model=result["model"],
                        task_status=result["task_status"], execution_status=result["execution_status"],
                        stop_reason=result["stop_reason"], trace_complete=result["trace_complete"],
                        limits=result["limits"], stats=result["stats"],
                        prompt_sha256=result["prompt_sha256"], tools_sha256=result["tools_sha256"],
                        files={"result.json": file_hash(out / "result.json"), "trace.jsonl": file_hash(out / "trace.jsonl")})
        write_json(out / "manifest.json", manifest)
    except DomainError as exc:
        result.update(task_status="FAILED", execution_status="FAILED", stop_reason="ARTIFACT_UNAVAILABLE",
                      artifact_error=exc.to_dict())
    return result


def result_exit_code(result):
    if result["stop_reason"] in {"LIMIT_REACHED", "CANCELLED"} or any(
        "ITEM_LIMIT_REACHED" in item.get("incomplete_reasons", []) for item in result.get("items", [])
    ):
        return 5
    if result["execution_status"] == "FAILED" or result["task_status"] == "FAILED" or any(
        item.get("save_attempt", {}).get("save_status") in {"FAILED", "UNKNOWN"}
        or any(reason in {"TOOL_UNAVAILABLE", "STORE_UNAVAILABLE", "SAVE_FAILED"} for reason in item.get("incomplete_reasons", []))
        for item in result.get("items", [])
    ):
        return 4
    return 0 if result["task_status"] == "READY_DRAFTS" else 2
