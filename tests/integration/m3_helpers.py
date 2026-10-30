"""Explicit test providers; never represented as real model trajectories."""

import json

from material_scheduler.agent.trace import MemoryTrace


def action(tool, item_id="I01", **arguments):
    if tool != "finish":
        arguments["item_id"] = item_id
    return {"tool": tool, "arguments": {"rationale": "test-only public reason", **arguments}}


class ScriptedModel:
    mode, name, version = "test", "scripted-adversary", "1.0"

    def __init__(self, responses):
        self.responses = iter(responses)
        self.contexts = []
        self.timeouts = []

    def choose(self, context, *, timeout_seconds):
        self.contexts.append(context)
        self.timeouts.append(timeout_seconds)
        response = next(self.responses)
        if callable(response):
            response = response(context)
        if isinstance(response, Exception):
            raise response
        return json.dumps(response, ensure_ascii=False) if type(response) is dict else response


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FaultTrace(MemoryTrace):
    def __init__(self, run_id, event_type, tool=None):
        super().__init__(run_id)
        self.event_type, self.tool = event_type, tool

    def _write(self, envelope):
        event = envelope["event"]
        if event["type"] == self.event_type and (self.tool is None or event.get("action", {}).get("tool") == self.tool):
            raise OSError("test trace failure")
        super()._write(envelope)
