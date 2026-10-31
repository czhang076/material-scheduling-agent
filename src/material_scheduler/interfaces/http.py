"""Loopback-only workbench HTTP boundary; no shell, CORS or arbitrary files."""

from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
from pathlib import Path
import re
import secrets
from threading import Lock
import time
from urllib.parse import parse_qs, unquote, urlsplit

from material_scheduler.adapters.compatible_model import CompatibleChatModel
from material_scheduler.adapters.mock_model import ObservationMock
from material_scheduler.adapters.run_journal import RunJournal
from material_scheduler.application.workbench import Workbench
from material_scheduler.domain.drafts import ConfirmationCommand
from material_scheduler.domain.validation import DomainError, integer, object_fields, parse_json
from .artifacts import run_request


class Sessions:
    def __init__(self):
        self._values = {}
        self._lock = Lock()

    def get(self, cookie, *, create=False):
        try:
            parsed = SimpleCookie(cookie or "")
            session_id = parsed["workbench_session"].value if "workbench_session" in parsed else None
        except Exception:
            session_id = None
        with self._lock:
            stamp = time.monotonic()
            self._values = {key: value for key, value in self._values.items() if value[1] > stamp}
            if session_id in self._values:
                return session_id, self._values[session_id][0]
            if not create:
                raise DomainError("SESSION_EXPIRED", "Refresh the page to reconnect to this local session")
            if len(self._values) >= 128:
                self._values.pop(next(iter(self._values)))
            session_id, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            self._values[session_id] = (csrf, stamp + 8 * 3600)
            return session_id, csrf


def create_workbench(store, state_dir: Path, *, model_config=None):
    def factory(mode):
        if mode == "mock":
            return ObservationMock()
        if model_config is None:
            raise DomainError("MODEL_CONFIGURATION_ERROR", "Start the local server with a real provider configuration first")
        return CompatibleChatModel(model_config)
    journal = RunJournal(state_dir, store.path.with_name(store.path.name + ".web-lock.sqlite3"))
    return Workbench(store, journal, factory, run_request,
                     real_model_name=model_config.model_name if model_config else None)


class WorkbenchServer(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def __init__(self, address, workbench):
        if address[0] not in {"127.0.0.1", "localhost"}:
            raise DomainError("INVALID_INPUT", "Workbench only listens on the local loopback address")
        self.app = workbench
        self.sessions = Sessions()
        super().__init__(address, Handler)
        port = self.server_port
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        self.local_url = f"http://127.0.0.1:{port}"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.0"

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *arguments):
        pass

    def _send(self, status, body, *, content_type="application/json; charset=utf-8", cookie=None, filename=None):
        content = json.dumps(body, ensure_ascii=False, allow_nan=False).encode() if type(body) is not bytes else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
        if cookie:
            self.send_header("Set-Cookie", f"workbench_session={cookie}; HttpOnly; SameSite=Strict; Path=/; Max-Age=28800")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(content)
        except OSError:
            pass  # The browser disconnecting does not cancel a persisted run.

    def _boundary(self, *, write=False):
        hosts = self.headers.get_all("Host", [])
        if len(hosts) != 1 or hosts[0] not in self.server.allowed_hosts:
            raise DomainError("ORIGIN_REJECTED", "Only this local workbench origin is allowed")
        origin = self.headers.get("Origin")
        if (origin is not None and origin != "http://" + hosts[0]) or (write and origin is None):
            raise DomainError("ORIGIN_REJECTED", "Only this local workbench origin is allowed")
        if self.headers.get("Sec-Fetch-Site") == "cross-site":
            raise DomainError("ORIGIN_REJECTED", "Cross-site requests are not accepted")
        if write:
            _, token = self.server.sessions.get(self.headers.get("Cookie"))
            supplied = self.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(token, supplied):
                raise DomainError("CSRF_REJECTED", "Refresh the page before submitting an operation")

    def _body(self):
        if self.headers.get("Transfer-Encoding") or len(self.headers.get_all("Content-Length", [])) != 1:
            raise DomainError("INVALID_INPUT", "Send one bounded JSON body with Content-Length")
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            raise DomainError("INVALID_INPUT", "Expected application/json")
        try:
            size = int(self.headers["Content-Length"])
        except ValueError:
            raise DomainError("INVALID_INPUT", "Invalid body size") from None
        if not 1 <= size <= 1_048_576:
            raise DomainError("BODY_TOO_LARGE", "Request body must be between 1 byte and 1 MiB")
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise DomainError("INVALID_INPUT", "Incomplete request body")
        try:
            return parse_json(raw.decode("utf-8"))
        except UnicodeError:
            raise DomainError("INVALID_INPUT", "Expected UTF-8 JSON") from None

    def _route(self, write):
        self._boundary(write=write)
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        query = parse_qs(parsed.query, keep_blank_values=True)
        app = self.server.app
        static = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                  "/styles.css": ("styles.css", "text/css; charset=utf-8"), "/favicon.svg": ("favicon.svg", "image/svg+xml")}
        if not write and path in static and not query:
            name, mime = static[path]
            return self._send(200, files("material_scheduler.interfaces.web").joinpath(name).read_bytes(), content_type=mime)
        if not write and path == "/api/bootstrap":
            if set(query) - {"channel"} or any(len(values) != 1 for values in query.values()):
                raise DomainError("INVALID_INPUT", "Invalid bootstrap query")
            session_id, csrf = self.server.sessions.get(self.headers.get("Cookie"), create=True)
            return self._send(200, {"csrf_token": csrf, "catalog": app.store.catalog_preview(query.get("channel", ["douyin"])[0]),
                                    "drafts": app.store.list_drafts(), "runs": app.journal.list(),
                                    "real_model": {"available": app.real_model_name is not None, "name": app.real_model_name},
                                    "draft_only": True, "review_coverage": ["metadata", "copy_text"]}, cookie=session_id)
        self.server.sessions.get(self.headers.get("Cookie"))
        identifier_pattern = r"([A-Za-z0-9_-]{1,64})"
        if not write and path == "/api/runs" and not query:
            return self._send(200, {"runs": app.journal.list()})
        if write and path == "/api/runs" and not query:
            result = app.submit(self._body())
            return self._send(200 if result["reused"] else 202, result)
        match = re.fullmatch(r"/api/submissions/" + identifier_pattern, path)
        if not write and match and not query:
            value = app.journal.for_submission(match[1])
            if value is None:
                raise DomainError("RUN_NOT_FOUND", "Submission has not been registered")
            return self._send(200, {"run": value})
        match = re.fullmatch(r"/api/runs/" + identifier_pattern + r"(/events|/trace)?", path)
        if not write and match:
            run_id, suffix = match[1], match[2]
            if suffix == "/events":
                if set(query) - {"after", "limit"} or any(len(values) != 1 for values in query.values()):
                    raise DomainError("INVALID_INPUT", "Invalid events query")
                try:
                    after, limit = int(query.get("after", ["0"])[0]), int(query.get("limit", ["50"])[0])
                except ValueError:
                    raise DomainError("INVALID_INPUT", "Invalid event cursor") from None
                integer(after, "after", 0, 100000)
                integer(limit, "limit", 1, 100)
                return self._send(200, app.journal.events(run_id, after, limit))
            if query:
                raise DomainError("INVALID_INPUT", "Unexpected query parameters")
            if suffix == "/trace":
                trace = app.trace_path(run_id)
                if trace.stat().st_size > 32 * 1024 * 1024:
                    raise DomainError("TRACE_TOO_LARGE", "Inspect this trace from the local run directory")
                return self._send(200, trace.read_bytes(), content_type="application/x-ndjson", filename=run_id + ".jsonl")
            return self._send(200, app.get(run_id))
        match = re.fullmatch(r"/api/drafts/" + identifier_pattern + r"(/confirm)?", path)
        if match and not query:
            draft_id, suffix = match[1], match[2]
            if not write and suffix is None:
                return self._send(200, app.store.read_draft(draft_id))
            if write and suffix == "/confirm":
                data = self._body()
                command = ConfirmationCommand.from_dict({**object_fields(data,
                    {"confirmation_id", "expected_version", "accepted_item_ids", "actor"}, {"note"}, "confirmation"), "draft_id": draft_id})
                return self._send(200, app.store.confirm(command).to_dict())
        match = re.fullmatch(r"/api/requests/" + identifier_pattern + r"(/revalidate)?", path)
        if match and not query:
            if not write and match[2] is None:
                return self._send(200, app.store.read_request(match[1]))
            if write and match[2] == "/revalidate":
                object_fields(self._body(), set(), set(), "revalidation")
                return self._send(200, app.store.snapshot(match[1], audit_revalidation=True))
        raise DomainError("NOT_FOUND", "Endpoint does not exist")

    def _dispatch(self, write):
        try:
            self._route(write)
        except DomainError as exc:
            code = exc.code
            if code in {"ORIGIN_REJECTED", "SESSION_EXPIRED", "CSRF_REJECTED"}:
                status = 403
            elif code in {"NOT_FOUND", "RUN_NOT_FOUND", "DRAFT_NOT_FOUND", "TRACE_NOT_FOUND"}:
                status = 404
            elif code in {"RUN_BUSY", "RUN_MODE_CONFLICT", "REQUEST_ID_CONFLICT", "DRAFT_VERSION_CONFLICT", "STALE_DRAFT", "STALE_REVIEW", "SLOT_CONFLICT", "CONFIRMATION_INCOMPLETE"}:
                status = 409
            elif code == "BODY_TOO_LARGE":
                status = 413
            elif code in {"INVALID_INPUT", "MODEL_CONFIGURATION_ERROR", "METADATA_MISSING", "REVIEW_BLOCKED", "SOURCE_CONFLICT"}:
                status = 400
            else:
                status = 503
            self._send(status, {"error": exc.to_dict(), "published": False})
        except Exception:
            self._send(500, {"error": {"code": "INTERNAL_ERROR", "message": "Local operation failed; inspect the current run before retrying"}, "published": False})

    def do_GET(self):
        self._dispatch(False)

    def do_POST(self):
        self._dispatch(True)
