"""Protocol fixtures are explicit test providers, not real model evidence."""

from dataclasses import replace
import json
from pathlib import Path
from unittest.mock import patch

from material_scheduler.adapters.compatible_model import CompatibleChatModel, ProviderError, WIRE_INSTRUCTION
from material_scheduler.adapters.model_config import ModelConfig, load_model_config
from material_scheduler.agent.decisions import ModelContext
from material_scheduler.agent.prompt import SYSTEM_PROMPT
from material_scheduler.agent.runner import AgentRunner
from material_scheduler.application.tools import tool_definitions
from material_scheduler.domain.validation import DomainError
from tests.integration.m2_helpers import LedgerTest, request


SECRET = "test-secret-not-a-real-key"


def config(**changes):
    values = {"base_url": "https://provider.example/v1", "model_name": "test-model", "api_key": SECRET, **changes}
    return ModelConfig(**values)


def response(tool="read_material", arguments=None, call_id="native-call-1", **updates):
    data = {"id": "response-test", "model": "served-test", "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
        "role": "assistant", "content": None, "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": tool, "arguments": json.dumps(arguments or {"item_id": "I01", "rationale": "read actual facts"})}}],
    }}], "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20}, **updates}
    return data


class TransportStub:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def post(self, configuration, payload, *, timeout_seconds):
        self.requests.append((json.loads(payload), timeout_seconds))
        reply = next(self.responses)
        if isinstance(reply, Exception):
            raise reply
        return (json.dumps(reply).encode() if type(reply) is dict else reply), "header-request-1"


def context(history=(), *, run_id="RUN-test"):
    return ModelContext(SYSTEM_PROMPT, request().to_dict(), {}, tool_definitions(), tuple(history),
                        {"tools_remaining": 11, "per_item_remaining": {"I01": 10}}, run_id)


class ModelConfigTests(LedgerTest):
    def test_secret_not_in_repr_or_public_configuration(self):
        settings = config()
        self.assertNotIn(SECRET, repr(settings))
        self.assertNotIn(SECRET, json.dumps(settings.public_info()))

    def test_environment_file_is_explicit_and_environment_takes_precedence(self):
        path = self.directory / "model.env"
        path.write_text('MODEL_BASE_URL=https://provider.example/v1\nMODEL_NAME="file-model"\nMODEL_API_KEY=' + SECRET + '\n', encoding="utf-8")
        settings = load_model_config(path, environ={"MODEL_NAME": "process-model"})
        self.assertEqual(settings.model_name, "process-model")
        self.assertEqual(settings.api_key, SECRET)
        with self.assertRaises(DomainError):
            load_model_config(environ={})

    def test_invalid_or_duplicate_config_does_not_echo_values(self):
        for content in ["MODEL_API_KEY=" + SECRET + "\nMODEL_API_KEY=other\n", "UNKNOWN=" + SECRET,
                        "MODEL_NAME='unclosed\n", "not an assignment"]:
            path = self.directory / "invalid.env"
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(DomainError) as error:
                load_model_config(path, environ={})
            self.assertNotIn(SECRET, str(error.exception))

    def test_endpoint_rejects_credentials_queries_fragments_and_remote_http(self):
        for endpoint in ["http://provider.example/v1", "https://user:password@provider.example/v1", "https://provider.example/?key=" + SECRET,
                         "https://provider.example/#fragment", "file:///tmp/model", "https://provider.example:99999", "https://bad\\host/v1"]:
            with self.subTest(endpoint=endpoint):
                with self.assertRaises(DomainError):
                    config(base_url=endpoint)
        self.assertTrue(config(base_url="http://127.0.0.1:8000/v1").endpoint.endswith("/chat/completions"))
        self.assertTrue(config(base_url="http://[::1]:8000/v1").endpoint.endswith("/chat/completions"))

    def test_config_limits_and_unknown_parameter_names_are_rejected(self):
        for values in [{"max_output_tokens": True}, {"max_output_tokens": 4097}, {"token_parameter": "anything"},
                       {"strict_tools": "false"}, {"api_key": SECRET + "\n"}, {"model_name": SECRET}]:
            with self.assertRaises(DomainError):
                config(**values)

    def test_deepseek_profile_has_explicit_supported_defaults(self):
        settings = load_model_config(environ={"MODEL_BASE_URL": "https://api.deepseek.com", "MODEL_NAME": "deepseek-flash",
                                               "MODEL_API_KEY": SECRET, "MODEL_PROVIDER": "deepseek"})
        self.assertEqual(settings.token_parameter, "max_tokens")
        self.assertEqual(settings.public_info()["thinking"], "disabled")


class CompatibleModelTests(LedgerTest):
    def provider(self, replies, **options):
        transport = TransportStub(replies)
        return CompatibleChatModel(config(**options), transport=transport, evidence_kind="protocol_stub"), transport

    def test_native_call_and_actual_id_are_replayed_with_matching_tool_observation(self):
        provider, transport = self.provider([response(), response("finish", {"rationale": "done"}, "native-call-2")])
        selected = json.loads(provider.choose(context(), timeout_seconds=7))
        observation = {"ok": True, "tool": "read_material", "item_id": "I01", "data": {"title": "actual synthetic result"}}
        history = [{"kind": "tool", "call_id": "CALL-1", "action": selected, "observation": observation, "dispatched": True}]
        provider.choose(context(history), timeout_seconds=6)
        messages = transport.requests[1][0]["messages"]
        self.assertEqual(messages[2]["tool_calls"][0]["id"], "native-call-1")
        self.assertEqual(messages[3]["tool_call_id"], "native-call-1")
        self.assertEqual(json.loads(messages[3]["content"]), observation)
        self.assertEqual(transport.requests[0][1], 7)
        self.assertIn(WIRE_INSTRUCTION, transport.requests[0][0]["messages"][0]["content"])
        self.assertFalse(transport.requests[0][0]["parallel_tool_calls"])

    def test_strict_and_token_options_are_explicit(self):
        provider, transport = self.provider([response()], strict_tools=True, max_output_tokens=512)
        provider.choose(context(), timeout_seconds=3)
        payload = transport.requests[0][0]
        self.assertEqual(payload["max_completion_tokens"], 512)
        self.assertTrue(all(tool["function"]["strict"] for tool in payload["tools"]))
        self.assertEqual(payload["tool_choice"], "required")

    def test_deepseek_payload_disables_thinking_and_omits_unverified_parallel_option(self):
        provider, transport = self.provider([response()], provider="deepseek", token_parameter="max_tokens")
        provider.choose(context(), timeout_seconds=3)
        payload = transport.requests[0][0]
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertNotIn("parallel_tool_calls", payload)
        self.assertIn("max_tokens", payload)

    def test_multi_call_free_text_refusal_and_truncation_are_not_executed(self):
        variants = []
        multiple = response()
        multiple["choices"][0]["message"]["tool_calls"] *= 2
        variants.append(multiple)
        for reason in ("stop", "length", "content_filter"):
            variant = response()
            variant["choices"][0]["finish_reason"] = reason
            variants.append(variant)
        refusal = response()
        refusal["choices"][0]["message"]["refusal"] = "refused"
        variants.append(refusal)
        for variant in variants:
            provider, _ = self.provider([variant])
            with self.assertRaises(DomainError) as error:
                provider.choose(context(), timeout_seconds=3)
            self.assertEqual(error.exception.code, "MODEL_PROTOCOL_ERROR")

    def test_invalid_json_arguments_duplicate_keys_and_private_reasoning_rejected(self):
        for arguments in ['{"item_id":"I01","item_id":"I02"}', '["not-object"]', '{bad', '{"rationale":1e999}']:
            variant = response()
            variant["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
            provider, _ = self.provider([variant])
            with self.assertRaises(DomainError):
                provider.choose(context(), timeout_seconds=3)
        variant = response()
        variant["choices"][0]["message"]["reasoning_content"] = "private internal content"
        provider, _ = self.provider([variant])
        with self.assertRaises(DomainError):
            provider.choose(context(), timeout_seconds=3)
        self.assertNotIn("private internal", json.dumps(provider.last_decision_metadata()))

    def test_secret_echo_is_not_accepted_or_recorded(self):
        provider, _ = self.provider([response(arguments={"item_id": "I01", "rationale": SECRET})])
        with self.assertRaises(DomainError):
            provider.choose(context(), timeout_seconds=3)
        self.assertNotIn(SECRET, json.dumps(provider.last_decision_metadata()))

    def test_observation_injection_or_reuse_across_run_is_rejected(self):
        provider, _ = self.provider([response()])
        provider.choose(context(), timeout_seconds=3)
        forged = [{"kind": "tool", "action": {"tool": "save_draft", "arguments": {}}, "observation": {}}]
        with self.assertRaises(ProviderError) as error:
            provider.choose(context(forged), timeout_seconds=3)
        self.assertEqual(error.exception.code, "MODEL_HISTORY_ERROR")
        with self.assertRaises(ProviderError):
            provider.choose(context(run_id="RUN-other"), timeout_seconds=3)

    def test_request_and_response_byte_limits_do_not_dispatch_tools(self):
        provider, transport = self.provider([response()], max_request_bytes=20)
        with self.assertRaises(ProviderError) as error:
            provider.choose(context(), timeout_seconds=3)
        self.assertEqual(error.exception.code, "MODEL_CONTEXT_LIMIT")
        self.assertEqual(transport.requests, [])
        provider, _ = self.provider([b"x" * 200], max_response_bytes=100)
        with self.assertRaises(ProviderError) as error:
            provider.choose(context(), timeout_seconds=3)
        self.assertEqual(error.exception.code, "MODEL_RESPONSE_LIMIT")

    def test_sanitized_receipt_contains_usage_and_native_identifiers(self):
        provider, _ = self.provider([response()])
        provider.choose(context(), timeout_seconds=3)
        metadata = provider.last_decision_metadata()
        self.assertEqual(metadata["tool_call_id"], "native-call-1")
        self.assertEqual(metadata["usage"]["total_tokens"], 20)
        self.assertEqual(metadata["served_model"], "served-test")
        self.assertNotIn(SECRET, json.dumps(metadata))

    def test_auth_failure_is_terminal_and_not_retried(self):
        provider, transport = self.provider([ProviderError("MODEL_AUTH_ERROR", "Provider rejected request", http_status=401)])
        runner = AgentRunner(self.session(), provider)
        result = runner.run()
        self.assertEqual(result["stop_reason"], "MODEL_AUTH_ERROR")
        self.assertEqual(result["execution_status"], "FAILED")
        self.assertEqual(len(transport.requests), 1)
        self.assertEqual(result["stats"]["tool_attempts"], 0)

    def test_protocol_correction_is_fed_back_without_fabricating_tool_calls(self):
        provider, transport = self.provider([b"not-json", response("finish", {"rationale": "stop"})])
        result = AgentRunner(self.session(), provider).run()
        self.assertEqual(result["stats"]["protocol_errors"], 1)
        messages = transport.requests[1][0]["messages"]
        self.assertFalse(any(message["role"] == "tool" for message in messages))
        self.assertTrue(any("runtime_feedback" in str(message["content"]) for message in messages))

    def test_reused_native_tool_call_identity_is_rejected(self):
        provider, _ = self.provider([response(), response("finish", {"rationale": "stop"})])
        selected = json.loads(provider.choose(context(), timeout_seconds=3))
        history = [{"kind": "tool", "action": selected, "observation": {"ok": True}}]
        with self.assertRaises(DomainError) as error:
            provider.choose(context(history), timeout_seconds=3)
        self.assertEqual(error.exception.code, "MODEL_PROTOCOL_ERROR")
