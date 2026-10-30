"""JSON CLI; confirmation is an explicit trusted-user command."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

from material_scheduler.adapters.fixture_loader import load_fixture_set
from material_scheduler.adapters.mock_model import ObservationMock
from material_scheduler.adapters.sqlite_store import SQLiteStore
from material_scheduler.domain.budgets import ExecutionLimits
from material_scheduler.domain.drafts import ConfirmationCommand
from material_scheduler.domain.requests import SchedulingRequest
from material_scheduler.domain.validation import DomainError, parse_json
from .artifacts import result_exit_code, run_request


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DomainError("INVALID_INPUT", message)


def _parser():
    parser = Parser(description="素材审核与排期草稿；仅本地草稿，不发布")
    commands = parser.add_subparsers(dest="command", required=True, parser_class=Parser)
    initialize = commands.add_parser("init", help="显式导入合成资料和规则")
    initialize.add_argument("--data-dir", type=Path, default=Path("data"))
    initialize.add_argument("--db", type=Path, required=True)
    run = commands.add_parser("run", help="运行有界离线 Agent；真实模式待 M4")
    run.add_argument("--input", type=Path, required=True)
    run.add_argument("--db", type=Path, required=True)
    run.add_argument("--out", type=Path, required=True)
    run.add_argument("--mode", choices=["mock", "real"], required=True)
    for field in ("max-tool-attempts", "max-model-rounds", "per-item-tool-limit", "run-timeout-seconds", "model-timeout-seconds"):
        run.add_argument("--" + field, type=int)
    inspect = commands.add_parser("inspect", help="重新核验草稿，可能标记过期")
    inspect.add_argument("--db", type=Path, required=True)
    inspect.add_argument("--request-id", required=True)
    confirm = commands.add_parser("confirm", help="用户明确同意当前草稿版本及全部事项")
    confirm.add_argument("--db", type=Path, required=True)
    confirm.add_argument("--draft-id", required=True)
    confirm.add_argument("--expected-version", type=int, required=True)
    confirm.add_argument("--confirmation-id", required=True)
    confirm.add_argument("--actor", required=True)
    confirm.add_argument("--accept", action="append", required=True)
    confirm.add_argument("--note")
    evaluate = commands.add_parser("evaluate", help="运行合成离线验收场景，明确标注 Mock")
    evaluate.add_argument("--data-dir", type=Path, default=Path("data"))
    evaluate.add_argument("--out", type=Path, required=True)
    return parser


def read_json(path):
    try:
        if path.stat().st_size > 1_048_576:
            raise DomainError("INVALID_INPUT", "Input file exceeds 1 MiB")
        return parse_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise DomainError("INVALID_INPUT", "Cannot read the input JSON file") from exc


def open_store(path):
    if not path.is_file():
        raise DomainError("STORE_UNAVAILABLE", "Initialize the local database before this command")
    return SQLiteStore(path)


def _limits(arguments, count):
    values = asdict(ExecutionLimits.for_items(count))
    for field in values:
        selected = getattr(arguments, field, None)
        if selected is not None:
            if selected > values[field]:
                raise DomainError("INVALID_INPUT", "Local options may only tighten execution limits")
            values[field] = selected
    values["model_timeout_seconds"] = min(values["model_timeout_seconds"], values["run_timeout_seconds"])
    return ExecutionLimits(**values)


def dispatch(arguments, invocation):
    if arguments.command == "init":
        dataset = load_fixture_set(arguments.data_dir)
        store = SQLiteStore(arguments.db)
        return {"import": store.import_dataset(dataset), "source_identity": store.source_identity(), "published": False}, 0
    if arguments.command == "evaluate":
        from .evaluation import evaluate
        result = evaluate(arguments.data_dir, arguments.out)
        return result, 0 if result["all_passed"] else 4
    if arguments.command == "run":
        if arguments.mode == "real":
            raise DomainError("REAL_MODEL_NOT_IMPLEMENTED", "Real provider setup is deferred to M4; explicitly select mock for offline use")
        request = SchedulingRequest.from_dict(read_json(arguments.input))
        limits = _limits(arguments, len(request.items))
        store = open_store(arguments.db)
        result = run_request(store, request, ObservationMock(), arguments.out, limits=limits, invocation=invocation)
        return result, result_exit_code(result)
    store = open_store(arguments.db)
    if arguments.command == "inspect":
        return store.snapshot(arguments.request_id), 0
    command = ConfirmationCommand.from_dict({
        "confirmation_id": arguments.confirmation_id, "draft_id": arguments.draft_id,
        "expected_version": arguments.expected_version, "accepted_item_ids": arguments.accept,
        "actor": arguments.actor, "note": arguments.note,
    })
    return store.confirm(command).to_dict(), 0


def main(argv=None):
    invocation = list(sys.argv[1:] if argv is None else argv)
    try:
        result, code = dispatch(_parser().parse_args(invocation), invocation)
    except DomainError as exc:
        result = {"task_status": "FAILED", "error": exc.to_dict(), "published": False}
        code = 3 if exc.code in {"INVALID_INPUT", "REQUEST_ID_CONFLICT", "OUTPUT_EXISTS"} else 4
    except (OSError, UnicodeError):
        result = {"task_status": "FAILED", "error": {"code": "LOCAL_IO_ERROR", "message": "Local file operation failed"}, "published": False}
        code = 4
    except KeyboardInterrupt:
        result = {"task_status": "INCOMPLETE", "stop_reason": "CANCELLED", "published": False}
        code = 5
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return code
