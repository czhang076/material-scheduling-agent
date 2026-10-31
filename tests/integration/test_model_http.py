"""Real loopback HTTP I/O, deadlines and redirects; no real model calls."""

from dataclasses import replace
import time

from material_scheduler.adapters.compatible_model import CompatibleChatModel, HTTPTransport, ProviderError
from material_scheduler.agent.runner import AgentRunner
from tests.integration.http_fixture import FixtureServer
from tests.integration.m2_helpers import LedgerTest
from tests.integration.test_compatible_model import SECRET, config, context, response


class ModelHTTPTests(LedgerTest):
    def test_http_request_and_native_history_end_to_end(self):
        def responder(index, received):
            return {"body": response() if index == 1 else response("finish", {"rationale": "stop"}, "native-call-2"),
                    "headers": {"x-request-id": "loopback-request"}}
        with FixtureServer(responder) as server:
            provider = CompatibleChatModel(config(base_url=server.base_url), evidence_kind="protocol_stub")
            result = AgentRunner(self.session(), provider).run()
            self.assertEqual(result["stats"]["model_rounds"], 2)
            self.assertEqual(result["model"]["mode"], "test")
            self.assertEqual(server.requests[0]["path"], "/v1/chat/completions")
            self.assertEqual(server.requests[0]["headers"]["Authorization"], "Bearer " + SECRET)
            messages = server.requests[1]["body"]["messages"]
            self.assertEqual(messages[3]["role"], "tool")
            self.assertEqual(messages[3]["tool_call_id"], "native-call-1")

    def test_redirect_is_not_followed_or_given_credentials(self):
        with FixtureServer(lambda index, request: {"body": response()}) as destination:
            with FixtureServer(lambda index, request: {"status": 307, "headers": {"Location": destination.base_url + "/chat/completions"}}) as origin:
                provider = CompatibleChatModel(config(base_url=origin.base_url), evidence_kind="protocol_stub")
                with self.assertRaises(ProviderError) as error:
                    provider.choose(context(), timeout_seconds=2)
                self.assertEqual(error.exception.http_status, 307)
                self.assertEqual(destination.requests, [])

    def test_http_401_error_is_sanitized_and_terminal(self):
        with FixtureServer(lambda index, request: {"status": 401, "body": {"error": SECRET}}) as server:
            provider = CompatibleChatModel(config(base_url=server.base_url), evidence_kind="protocol_stub")
            result = AgentRunner(self.session(), provider).run()
            self.assertEqual(result["stop_reason"], "MODEL_AUTH_ERROR")
            self.assertEqual(len(server.requests), 1)
            self.assertNotIn(SECRET, str(result))

    def test_rate_limit_retry_is_owned_by_runner_not_transport(self):
        def responder(index, request):
            return {"status": 429} if index == 1 else {"body": response("finish", {"rationale": "stop"})}
        with FixtureServer(responder) as server:
            provider = CompatibleChatModel(config(base_url=server.base_url), evidence_kind="protocol_stub")
            result = AgentRunner(self.session(), provider).run()
            self.assertEqual(result["stats"]["model_rounds"], 2)
            self.assertEqual(len(server.requests), 2)
            self.assertEqual(result["stop_reason"], "MODEL_FINISHED")

    def test_response_byte_limit_is_enforced_during_http_read(self):
        with FixtureServer(lambda index, request: {"body": b"x" * 2000}) as server:
            settings = config(base_url=server.base_url, max_response_bytes=100)
            with self.assertRaises(ProviderError) as error:
                HTTPTransport().post(settings, b"{}", timeout_seconds=2)
            self.assertEqual(error.exception.code, "MODEL_RESPONSE_LIMIT")

    def test_truncated_http_body_does_not_become_a_valid_model_reply(self):
        with FixtureServer(lambda index, request: {"body": b"{}", "content_length": 100}) as server:
            with self.assertRaises(ProviderError) as error:
                HTTPTransport().post(config(base_url=server.base_url), b"{}", timeout_seconds=2)
            self.assertEqual(error.exception.code, "MODEL_UNAVAILABLE")

    def test_slow_body_checks_total_deadline_instead_of_resetting_idle_timeout(self):
        with FixtureServer(lambda index, request: {"body": b"x" * 100, "drip": 0.02}) as server:
            started = time.monotonic()
            with self.assertRaises(ProviderError) as error:
                HTTPTransport().post(config(base_url=server.base_url), b"{}", timeout_seconds=0.07)
            self.assertEqual(error.exception.code, "MODEL_TIMEOUT")
            self.assertLess(time.monotonic() - started, 1)
