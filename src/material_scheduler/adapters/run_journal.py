"""Durable local web runs; a process-held SQLite lease prevents two owners."""

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

from material_scheduler.domain.validation import DomainError


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class RunJournal:
    def __init__(self, directory: Path, lease_path: Path):
        self.directory = directory.resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "runs.sqlite3"
        self._leases = []
        try:
            for path in (lease_path, self.directory / ".owner.sqlite3"):
                lease = sqlite3.connect(path, timeout=0.1, isolation_level=None, check_same_thread=False)
                self._leases.append(lease)
                lease.execute("BEGIN EXCLUSIVE")
        except sqlite3.Error:
            self.close()
            raise DomainError("WORKBENCH_IN_USE", "Another workbench owns this ledger or state directory") from None
        try:
            with self._connection(write=True) as connection:
                connection.executescript("""
CREATE TABLE IF NOT EXISTS runs(
 run_id TEXT PRIMARY KEY, request_id TEXT NOT NULL, payload_hash TEXT NOT NULL,
 mode TEXT NOT NULL, request_json TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','FINISHED','FAILED','INTERRUPTED')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, result_json TEXT, error_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs((1)) WHERE status IN ('QUEUED','RUNNING');
CREATE TABLE IF NOT EXISTS submissions(submission_id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(run_id));
CREATE TABLE IF NOT EXISTS events(run_id TEXT NOT NULL REFERENCES runs(run_id), sequence INTEGER NOT NULL,
 payload_json TEXT NOT NULL, PRIMARY KEY(run_id,sequence));
CREATE TABLE IF NOT EXISTS owner(singleton INTEGER PRIMARY KEY CHECK(singleton=1), ledger_path TEXT NOT NULL);
""")
                connection.execute("BEGIN IMMEDIATE")
                owner = str(lease_path.resolve()).casefold()
                previous = connection.execute("SELECT ledger_path FROM owner WHERE singleton=1").fetchone()
                if previous and previous[0] != owner:
                    raise DomainError("STATE_DIRECTORY_CONFLICT", "Use a separate workbench state directory for this ledger")
                connection.execute("INSERT OR IGNORE INTO owner VALUES(1,?)", (owner,))
                connection.execute("UPDATE runs SET status='INTERRUPTED',updated_at=?,error_json=? WHERE status IN ('QUEUED','RUNNING')",
                                   (now(), json.dumps({"code": "SERVER_RESTARTED", "message": "Server restarted; inspect saved drafts before retrying"})))
        except BaseException:
            self.close()
            raise

    @contextmanager
    def _connection(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=3, isolation_level=None)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            if write:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
            yield connection
            if write and connection.in_transaction:
                connection.commit()
        except sqlite3.Error:
            raise DomainError("RUN_STORE_UNAVAILABLE", "Cannot access the run journal") from None
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    @staticmethod
    def _view(row, *, detail=True):
        value = {key: row[key] for key in ("run_id", "request_id", "payload_hash", "mode", "status", "created_at", "updated_at")}
        value["error"] = json.loads(row["error_json"]) if row["error_json"] else None
        if detail:
            value["request"] = json.loads(row["request_json"])
            value["result"] = json.loads(row["result_json"]) if row["result_json"] else None
        return value

    def active(self):
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE status IN ('QUEUED','RUNNING')").fetchone()
            return self._view(row) if row else None

    def for_submission(self, submission_id):
        with self._connection() as connection:
            row = connection.execute("SELECT runs.* FROM submissions JOIN runs USING(run_id) WHERE submission_id=?", (submission_id,)).fetchone()
            return self._view(row) if row else None

    def alias_submission(self, submission_id, run_id):
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO submissions VALUES(?,?)", (submission_id, run_id))

    def create(self, run_id, submission_id, request, mode):
        with self._connection(write=True) as connection:
            stamp = now()
            connection.execute("INSERT INTO runs VALUES(?,?,?,?,?,'QUEUED',?,?,NULL,NULL)",
                               (run_id, request.request_id, request.payload_hash, mode,
                                json.dumps(request.to_dict(), ensure_ascii=False), stamp, stamp))
            connection.execute("INSERT INTO submissions VALUES(?,?)", (submission_id, run_id))

    def update(self, run_id, status, *, result=None, error=None):
        with self._connection(write=True) as connection:
            connection.execute("UPDATE runs SET status=?,updated_at=?,result_json=?,error_json=? WHERE run_id=?",
                               (status, now(), json.dumps(result, ensure_ascii=False) if result is not None else None,
                                json.dumps(error, ensure_ascii=False) if error is not None else None, run_id))

    def append(self, event):
        with self._connection(write=True) as connection:
            connection.execute("INSERT INTO events VALUES(?,?,?)", (event["run_id"], event["sequence"], json.dumps(event, ensure_ascii=False)))

    def get(self, run_id):
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise DomainError("RUN_NOT_FOUND", "Run does not exist")
            return self._view(row)

    def list(self):
        with self._connection() as connection:
            return [self._view(row, detail=False) for row in connection.execute("SELECT * FROM runs ORDER BY rowid DESC LIMIT 50")]

    def events(self, run_id, after, limit):
        self.get(run_id)
        with self._connection() as connection:
            rows = connection.execute("SELECT payload_json FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                                      (run_id, after, limit + 1)).fetchall()
            events = [json.loads(row[0]) for row in rows[:limit]]
            return {"events": events, "next_after": events[-1]["sequence"] if events else after, "has_more": len(rows) > limit}

    def close(self):
        for lease in self._leases:
            lease.close()
        self._leases.clear()
