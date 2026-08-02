#!/usr/bin/env python3
"""Offline structural tests for the renderer<->broker governed-turn JSON schema
contracts (rev-30 §4.10(g)).

These tests use ONLY the Python standard library (``json``). They do NOT depend
on ``jsonschema`` — they load each schema with ``json.load`` (proving it is valid
JSON) and make direct *structural* assertions about the constraints the design
locks: protocol consts, ``additionalProperties: false`` everywhere, the closed
committed/blocked oneOf, the committed message's required fields + ``role`` /
``trust_state`` consts, and the closed ``reason`` enum. Kept in lock-step with
``apps/desktop/src-tauri/core/src/governed_turn_ipc.rs`` so the Rust wire types
and the schemas agree.

Run: ``python -m unittest tools.test_renderer_broker_schemas`` (or execute the
file directly).
"""

import json
import os
import unittest

_CONTRACTS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "bridge",
    "contracts",
)
REQUEST_SCHEMA = os.path.join(_CONTRACTS, "renderer-governed-turn.schema.json")
RESULT_SCHEMA = os.path.join(_CONTRACTS, "renderer-governed-turn-result.schema.json")

REQUEST_PROTOCOL = "brops.renderer-governed-turn.v1"
RESULT_PROTOCOL = "brops.renderer-governed-turn-result.v1"
CLOSED_REASONS = {
    "malformed",
    "peer_denied",
    "retry_conflict",
    "turn_in_progress",
    "commit_readback_mismatch",
    "upstream_blocked",
}
COMMITTED_MESSAGE_FIELDS = {
    "message_id",
    "role",
    "author",
    "body",
    "created_at_ms",
    "trust_state",
}


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


class RequestSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = _load(REQUEST_SCHEMA)

    def test_is_valid_json_object(self):
        self.assertIsInstance(self.schema, dict)
        self.assertEqual(self.schema["type"], "object")

    def test_additional_properties_false(self):
        self.assertIs(self.schema["additionalProperties"], False)

    def test_protocol_const(self):
        self.assertEqual(
            self.schema["properties"]["protocol"]["const"], REQUEST_PROTOCOL
        )

    def test_required_fields(self):
        self.assertEqual(
            set(self.schema["required"]),
            {"protocol", "conversation_id", "client_request_id"},
        )
        # ``agent`` is defined but optional (not in required).
        self.assertIn("agent", self.schema["properties"])
        self.assertNotIn("agent", self.schema["required"])

    def test_id_length_caps(self):
        for field in ("conversation_id", "agent"):
            self.assertEqual(self.schema["properties"][field]["maxLength"], 128)

    def test_client_request_id_uuidv4_pattern(self):
        pattern = self.schema["properties"]["client_request_id"]["pattern"]
        self.assertEqual(
            pattern,
            "^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
        )
        # Sanity: the pattern accepts a canonical lowercase v4 UUID and rejects
        # an uppercase / wrong-version one (mirrors the Rust is_canonical_uuidv4).
        import re

        rx = re.compile(pattern)
        self.assertTrue(rx.match("3f2504e0-4f89-41d3-9a0c-0305e82c3301"))
        self.assertFalse(rx.match("3F2504E0-4F89-41D3-9A0C-0305E82C3301"))
        self.assertFalse(rx.match("3f2504e0-4f89-11d3-9a0c-0305e82c3301"))


class ResultSchemaTests(unittest.TestCase):
    def setUp(self):
        self.schema = _load(RESULT_SCHEMA)
        self.branches = self.schema["oneOf"]
        self.by_status = {}
        for branch in self.branches:
            status = branch["properties"]["status"]["const"]
            self.by_status[status] = branch

    def test_is_valid_json_with_oneof(self):
        self.assertIsInstance(self.schema, dict)
        self.assertEqual(len(self.branches), 2)
        self.assertEqual(set(self.by_status), {"committed", "blocked"})

    def test_every_branch_additional_properties_false(self):
        for branch in self.branches:
            self.assertIs(branch["additionalProperties"], False)

    def test_every_branch_protocol_const(self):
        for branch in self.branches:
            self.assertEqual(
                branch["properties"]["protocol"]["const"], RESULT_PROTOCOL
            )

    def test_committed_required_and_no_reason(self):
        committed = self.by_status["committed"]
        self.assertEqual(
            set(committed["required"]),
            {
                "protocol",
                "status",
                "client_request_id",
                "broker_turn_id",
                "conversation_id",
                "message",
            },
        )
        # A committed frame must NOT define a reason property (closed shape).
        self.assertNotIn("reason", committed["properties"])

    def test_committed_message_shape(self):
        message = self.by_status["committed"]["properties"]["message"]
        self.assertEqual(message["type"], "object")
        self.assertIs(message["additionalProperties"], False)
        self.assertEqual(set(message["required"]), COMMITTED_MESSAGE_FIELDS)
        self.assertEqual(set(message["properties"]), COMMITTED_MESSAGE_FIELDS)
        # role and trust_state are LOCKED consts.
        self.assertEqual(message["properties"]["role"]["const"], "assistant")
        self.assertEqual(
            message["properties"]["trust_state"]["const"], "trusted_verified"
        )
        # created_at_ms is an integer (matches the Rust i64).
        self.assertEqual(message["properties"]["created_at_ms"]["type"], "integer")

    def test_blocked_required_and_no_message(self):
        blocked = self.by_status["blocked"]
        self.assertEqual(
            set(blocked["required"]),
            {
                "protocol",
                "status",
                "client_request_id",
                "broker_turn_id",
                "conversation_id",
                "reason",
            },
        )
        # A blocked frame must NOT define a message property (closed shape).
        self.assertNotIn("message", blocked["properties"])

    def test_blocked_reason_is_closed_enum(self):
        reason = self.by_status["blocked"]["properties"]["reason"]
        self.assertEqual(reason["type"], "string")
        self.assertEqual(set(reason["enum"]), CLOSED_REASONS)


if __name__ == "__main__":
    unittest.main()
