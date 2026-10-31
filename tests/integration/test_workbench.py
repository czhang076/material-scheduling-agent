"""Real loopback HTTP, durable jobs and the shared transactional ledger."""

from dataclasses import replace
import http.client
import json
from threading import Event, Thread
import time

from material_scheduler.adapters.run_journal import RunJournal
from material_scheduler.agent.trace import verify_trace
from material_scheduler.domain.validation import DomainError
from material_scheduler.interfaces.http import WorkbenchServer, create_workbench
from tests.integration.m2_helpers import LedgerTest, occupied, request


class WorkbenchTests(LedgerTest):
    def setUp(self):
        super().setUp()
        self.app = create_workbench(self.store, self.directory / "web")
        self.server = WorkbenchServer(("127.0.0.1", 0), self.app)
        self.thread = Thread(target=self.server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.cookie = self.csrf = None
        status, data, headers = self.http("GET", "/api/bootstrap")
        self.assertEqual(status, 200, data)
        self.cookie = headers["Set-Cookie"].split(";")[0]
        self.csrf = data["csrf_token"]

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.app.close()

    def http(self, method, path, body=None, *, headers=None, raw=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=5)
        supplied = {"Origin": self.server.local_url}
        if self.cookie:
            supplied["Cookie"] = self.cookie
        if body is not None or raw is not None:
            supplied.update({"Content-Type": "application/json", "X-CSRF-Token": self.csrf or ""})
        supplied.update(headers or {})
        encoded = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        connection.request(method, path, encoded, supplied)
        response = connection.getresponse()
        content = response.read()
        response_headers = dict(response.getheaders())
        connection.close()
        data = json.loads(content) if response_headers.get("Content-Type", "").startswith("application/json") else content
        return response.status, data, response_headers

    def submit(self, req=None, submission="SUB-1", mode="mock"):
        return self.http("POST", "/api/runs", {"request": (req or request()).to_dict(), "submission_id": submission, "mode": mode})

    def finished(self, run_id):
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            status, data, _ = self.http("GET", "/api/runs/" + run_id)
            self.assertEqual(status, 200, data)
            if data["status"] not in {"QUEUED", "RUNNING"}:
                return data
            time.sleep(.01)
        self.fail("Bounded Mock job did not finish")

    def run_case(self, req=None):
        status, data, _ = self.submit(req)
        self.assertEqual(status, 202, data)
        return self.finished(data["run"]["run_id"])

    def confirm_body(self, draft, **changes):
        return {"confirmation_id": "CONF-HTTP", "expected_version": draft["version"],
                "accepted_item_ids": draft["pending_confirmations"], "actor": "local-user", **changes}

    def test_bootstrap_is_mock_default_secret_free_and_readonly(self):
        before = self.store.counts()
        status, data, headers = self.http("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertFalse(data["real_model"]["available"])
        self.assertTrue(data["catalog"]["preview_only"])
        self.assertTrue(data["draft_only"])
        self.assertNotIn("api_key", json.dumps(data))
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(before, self.store.counts())

    def test_static_assets_and_csp_no_arbitrary_files(self):
        for path in ("/", "/app.js", "/styles.css", "/favicon.svg"):
            with self.subTest(path=path):
                status, data, headers = self.http("GET", path)
                self.assertEqual(status, 200)
                self.assertTrue(data)
                self.assertIn("script-src 'self'", headers["Content-Security-Policy"])
                self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/.env", "/../.env", "/%2e%2e/.env", "/api/publish"):
            self.assertEqual(self.http("GET", path)[0], 404)

    def test_normal_actual_run_trace_events_and_readonly_refresh(self):
        run = self.run_case()
        self.assertEqual(run["status"], "FINISHED")
        self.assertEqual(run["result"]["task_status"], "READY_DRAFTS")
        draft = run["current"]["items"][0]["draft"]
        self.assertEqual(draft["draft_state"], "READY")
        before = self.store.counts()
        for path in ("/api/runs", "/api/runs/" + run["run_id"], "/api/requests/REQ-TEST", "/api/drafts/" + draft["draft_id"]):
            self.assertEqual(self.http("GET", path)[0], 200)
        self.assertEqual(before, self.store.counts())
        events, cursor = [], 0
        while True:
            status, data, _ = self.http("GET", f'/api/runs/{run["run_id"]}/events?after={cursor}&limit=2')
            self.assertEqual(status, 200)
            events.extend(data["events"])
            cursor = data["next_after"]
            if not data["has_more"]:
                break
        self.assertEqual(events, verify_trace(self.app.trace_path(run["run_id"])))
        status, content, headers = self.http("GET", f'/api/runs/{run["run_id"]}/trace')
        self.assertEqual(status, 200)
        self.assertEqual(content, self.app.trace_path(run["run_id"]).read_bytes())
        self.assertIn("attachment;", headers["Content-Disposition"])

    def test_hard_conflict_confirmation_and_idempotent_repeat(self):
        self.store.import_dataset(occupied(self.dataset))
        run = self.run_case()
        draft = run["current"]["items"][0]["draft"]
        self.assertEqual(draft["pending_confirmations"], ["TIME_CHANGE"])
        self.assertIn("18:00", draft["requested_start"])
        self.assertIn("19:00", draft["candidate"]["start"])
        url = "/api/drafts/" + draft["draft_id"] + "/confirm"
        body = self.confirm_body(draft)
        first = self.http("POST", url, body)
        self.assertEqual(first[0], 200, first[1])
        self.assertEqual(first[1]["draft_state"], "READY")
        self.assertFalse(first[1]["published"])
        repeated = self.http("POST", url, body)[1]
        self.assertEqual(repeated["confirmation_status"], "REUSED")
        self.assertEqual(repeated["draft_id"], first[1]["draft_id"])
        self.assertEqual(repeated["version"], first[1]["version"])
        self.assertEqual(self.store.counts()["confirmations"], 1)
        current = self.http("GET", "/api/runs/" + run["run_id"])[1]
        self.assertEqual(current["result"]["task_status"], "NEEDS_CONFIRMATION")
        self.assertEqual(current["current"]["items"][0]["draft"]["draft_state"], "READY")

    def test_incomplete_confirmation_cannot_be_forged(self):
        _, draft = self.pending(material="M04")
        url = "/api/drafts/" + draft["draft_id"] + "/confirm"
        status, data, _ = self.http("POST", url, self.confirm_body(draft, accepted_item_ids=[]))
        self.assertEqual(data["error"]["code"], "CONFIRMATION_INCOMPLETE")
        self.assertEqual(status, 409)
        for field in ("approved", "published", "draft_state"):
            body = self.confirm_body(draft)
            body[field] = True
            self.assertEqual(self.http("POST", url, body)[0], 400)
        self.assertEqual(self.store.counts()["confirmations"], 0)

    def test_wrong_version_does_not_confirm(self):
        _, draft = self.pending()
        status, data, _ = self.http("POST", "/api/drafts/" + draft["draft_id"] + "/confirm", self.confirm_body(draft, expected_version=draft["version"] + 1))
        self.assertEqual(data["error"]["code"], "DRAFT_VERSION_CONFLICT")
        self.assertEqual(status, 409)
        self.assertEqual(self.store.counts()["confirmations"], 0)

    def test_changed_source_is_conflict_and_get_exposes_stale_without_writes(self):
        _, draft = self.pending(material="M04")
        changed = tuple(replace(m, revision=m.revision + 1) if m.material_id == "M04" else m for m in self.dataset.materials)
        self.store.import_dataset(replace(self.dataset, materials=changed))
        before = self.store.counts()
        status, data, _ = self.http("GET", "/api/drafts/" + draft["draft_id"])
        self.assertEqual((status, data["draft_state"]), (200, "STALE"))
        self.assertEqual(before, self.store.counts())
        status, data, _ = self.http("POST", "/api/drafts/" + draft["draft_id"] + "/confirm", self.confirm_body(draft))
        self.assertEqual((status, data["error"]["code"]), (409, "STALE_REVIEW"))
        self.assertEqual(self.store.counts()["confirmations"], 0)

    def test_changed_occupancy_at_confirmation_stays_unapproved(self):
        _, draft = self.pending()
        self.store.import_dataset(occupied(self.dataset, 19))
        status, data, _ = self.http("POST", "/api/drafts/" + draft["draft_id"] + "/confirm", self.confirm_body(draft))
        self.assertEqual(status, 409, data)
        self.assertEqual(self.store.counts()["confirmations"], 0)
        self.assertEqual(self.store.read_draft(draft["draft_id"])["draft_state"], "STALE")

    def test_missing_information_is_not_ready(self):
        run = self.run_case(request(material="M99"))
        self.assertIsNone(run["current"]["items"][0]["draft"])
        self.assertNotEqual(run["result"]["task_status"], "READY_DRAFTS")

    def test_blocked_risk_is_not_saved(self):
        run = self.run_case(request(material="M05"))
        self.assertEqual(run["current"]["items"][0]["review"]["review_status"], "BLOCKED")
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_save_failure_returns_actual_failure(self):
        self.fault(**{"save.before_write": 3})
        run = self.run_case()
        self.assertIn(run["result"]["items"][0]["save_attempt"]["save_status"], {"FAILED", "UNKNOWN"})
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_same_submission_after_finish_returns_original_run(self):
        run = self.run_case()
        status, repeated, _ = self.submit()
        self.assertEqual(status, 200)
        self.assertTrue(repeated["reused"])
        self.assertEqual(repeated["run"]["run_id"], run["run_id"])
        self.assertEqual(len(self.app.journal.list()), 1)

    def test_explicit_retry_reruns_but_reuses_one_draft(self):
        run = self.run_case()
        status, repeated, _ = self.submit(submission="SUB-2")
        self.assertEqual(status, 202)
        next_run = self.finished(repeated["run"]["run_id"])
        self.assertNotEqual(next_run["run_id"], run["run_id"])
        self.assertEqual(self.store.counts()["drafts"], 1)
        self.assertEqual(next_run["result"]["items"][0]["save_attempt"]["save_status"], "REUSED")

    def test_submission_identity_rejects_changed_request_or_mode(self):
        self.run_case()
        altered = request(material="M05")
        status, data, _ = self.submit(altered)
        self.assertEqual((status, data["error"]["code"]), (409, "REQUEST_ID_CONFLICT"))
        status, data, _ = self.submit(mode="real")
        self.assertEqual((status, data["error"]["code"]), (409, "RUN_MODE_CONFLICT"))

    def test_one_active_run_aliases_same_request_and_rejects_another(self):
        started, release = Event(), Event()
        original = self.app.run_use_case
        def slow(*args, **kwargs):
            started.set()
            if not release.wait(4):
                raise RuntimeError("test deadline")
            return original(*args, **kwargs)
        self.app.run_use_case = slow
        self.addCleanup(release.set)
        first = self.submit()[1]["run"]
        self.assertTrue(started.wait(1))
        try:
            status, aliased, _ = self.submit(submission="SUB-2")
            self.assertEqual(status, 200)
            self.assertEqual(aliased["run"]["run_id"], first["run_id"])
            self.assertEqual(self.submit(request("REQ-OTHER"), "SUB-3")[0], 409)
            self.assertEqual(self.submit(submission="SUB-4", mode="real")[0], 409)
        finally:
            release.set()
        self.finished(first["run_id"])
        self.assertEqual(len(self.app.journal.list()), 1)
        self.assertEqual(self.http("GET", "/api/submissions/SUB-2")[1]["run"]["run_id"], first["run_id"])

    def test_unknown_and_invalid_cursor_return_explicit_errors(self):
        self.assertEqual(self.http("GET", "/api/runs/UNKNOWN")[0], 404)
        run = self.run_case()
        for query in ("after=-1", "limit=0", "limit=101", "after=no", "after=1&after=2", "unknown=1"):
            self.assertEqual(self.http("GET", "/api/runs/" + run["run_id"] + "/events?" + query)[0], 400)

    def test_host_origin_session_and_csrf_rejected_before_any_write(self):
        body = {"request": request().to_dict(), "mode": "mock", "submission_id": "SUB-1"}
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"},
                        {"X-CSRF-Token": "wrong"}, {"Cookie": "workbench_session=made-up"},
                        {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.http("POST", "/api/runs", body, headers=headers)[0], 403)
        self.assertEqual(self.store.counts()["requests"], 0)

    def test_no_origin_is_rejected_even_with_valid_csrf(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.request("POST", "/api/runs", b"{}", {"Cookie": self.cookie, "X-CSRF-Token": self.csrf, "Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.close()

    def test_duplicate_host_and_untrusted_read_session_rejected(self):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port)
        connection.putrequest("GET", "/")
        connection.putheader("Host", "evil.example")
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.close()
        self.assertEqual(self.http("GET", "/api/runs", headers={"Cookie": ""})[0], 403)

    def test_strict_json_and_bounded_payload_cannot_forge_run_result(self):
        raw = b'{"mode":"mock","mode":"real"}'
        self.assertEqual(self.http("POST", "/api/runs", raw=raw)[0], 400)
        self.assertEqual(self.http("POST", "/api/runs", raw=b"{}", headers={"Content-Type": "text/plain"})[0], 400)
        self.assertEqual(self.http("POST", "/api/runs", raw=b"{}", headers={"Content-Length": "1048577"})[0], 413)
        payload = {"request": request().to_dict(), "mode": "mock", "submission_id": "SUB-1", "result": {"published": True}}
        self.assertEqual(self.http("POST", "/api/runs", payload)[0], 400)
        self.assertEqual(self.store.counts()["requests"], 0)

    def test_real_requires_explicit_server_configuration_no_mock_fallback(self):
        status, data, _ = self.submit(mode="real")
        self.assertEqual((status, data["error"]["code"]), (400, "MODEL_CONFIGURATION_ERROR"))
        self.assertEqual(self.store.counts()["requests"], 0)
        self.assertEqual(self.app.journal.list(), [])

    def test_revalidation_is_explicit_post_and_audited(self):
        run = self.run_case()
        before = self.store.counts()
        self.http("GET", "/api/requests/REQ-TEST")
        self.assertEqual(self.store.counts(), before)
        status, _, _ = self.http("POST", "/api/requests/REQ-TEST/revalidate", {})
        self.assertEqual(status, 200)
        self.assertGreater(self.store.counts()["audit_events"], before["audit_events"])
        self.assertEqual(len(self.app.journal.list()), 1)

    def test_server_refuses_public_bind(self):
        with self.assertRaises(DomainError) as caught:
            WorkbenchServer(("0.0.0.0", 0), self.app)
        self.assertEqual(caught.exception.code, "INVALID_INPUT")

    def test_only_one_owner_even_if_state_directory_differs(self):
        with self.assertRaises(DomainError) as caught:
            create_workbench(self.store, self.directory / "different-web")
        self.assertEqual(caught.exception.code, "WORKBENCH_IN_USE")

    def test_state_directory_cannot_be_shared_by_two_ledgers(self):
        with self.assertRaises(DomainError) as caught:
            RunJournal(self.directory / "web", self.directory / "another-ledger-lock.sqlite3")
        self.assertEqual(caught.exception.code, "WORKBENCH_IN_USE")

    def test_state_directory_cannot_be_rebound_after_restart(self):
        directory = self.directory / "bound-state"
        journal = RunJournal(directory, self.directory / "first-lock.sqlite3")
        journal.close()
        with self.assertRaises(DomainError) as caught:
            RunJournal(directory, self.directory / "second-lock.sqlite3")
        self.assertEqual(caught.exception.code, "STATE_DIRECTORY_CONFLICT")

    def test_trace_journal_failure_cannot_claim_complete_evidence(self):
        original = self.app.journal.append
        count = 0
        def broken(event):
            nonlocal count
            count += 1
            if count == 2:
                raise DomainError("RUN_STORE_UNAVAILABLE", "Injected event journal fault")
            original(event)
        self.app.journal.append = broken
        run = self.run_case()
        self.assertEqual(run["result"]["stop_reason"], "TRACE_UNAVAILABLE")
        self.assertFalse(run["result"]["trace_complete"])
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_journal_restart_marks_active_interrupted_and_keeps_drafts(self):
        _, draft = self.ready()
        path = self.directory / "independent-lock.sqlite3"
        journal = RunJournal(self.directory / "recovery", path)
        journal.create("RUN-RECOVERY", "SUB-RECOVERY", request(), "mock")
        journal.update("RUN-RECOVERY", "RUNNING")
        journal.close()
        recovered = RunJournal(self.directory / "recovery", path)
        try:
            old = recovered.for_submission("SUB-RECOVERY")
            self.assertEqual(old["status"], "INTERRUPTED")
            self.assertEqual(old["error"]["code"], "SERVER_RESTARTED")
            self.assertEqual(self.store.read_draft(draft["draft_id"])["draft_state"], "READY")
            self.assertIsNone(recovered.active())
        finally:
            recovered.close()

    def test_worker_exception_does_not_expose_internal_message(self):
        def broken(*args, **kwargs):
            raise RuntimeError("credential-sentinel-must-never-be-visible")
        self.app.run_use_case = broken
        run = self.run_case()
        self.assertEqual(run["status"], "FAILED")
        self.assertEqual(run["error"]["code"], "RUN_INTERRUPTED")
        self.assertNotIn("sentinel", json.dumps(run))
        self.assertEqual(self.store.counts()["drafts"], 0)

    def test_catalog_material_text_is_not_interpreted_and_evidence_uses_codepoints(self):
        material = self.dataset.materials[0]
        changed = replace(material, title='<img src=x onerror="alert(1)">', copy_text="😀全网第一<script>payload</script>")
        self.store.import_dataset(replace(self.dataset, materials=(changed, *self.dataset.materials[1:])))
        status, data, _ = self.http("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        entry = next(row for row in data["catalog"]["materials"] if row["material"]["material_id"] == material.material_id)
        self.assertEqual(entry["material"]["title"], changed.title)
        for finding in entry["review_preview"]["findings"]:
            if finding["start"] is not None:
                self.assertEqual(finding["value"][finding["start"]:finding["end"]], finding["quote"])
        # Browser execution is separately recorded; this only checks the shipped sink policy.
        from importlib.resources import files
        js = files("material_scheduler.interfaces.web").joinpath("app.js").read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", js)
        self.assertIn("Array.from(finding.value)", js)
