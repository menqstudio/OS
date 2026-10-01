#!/usr/bin/env python3
"""Offline structural tests for the renderer<->broker governed-turn JSON schema
contracts (rev-30 §4.10(g)).

These tests use ONLY the Python standard library (``json``). They do NOT depend
on ``jsonschema`` — they load each schema with ``json.load`` (proving it is valid
JSON) and make direct *structural* assertions about the constraints the design
locks: protocol consts, ``additionalProperties: false`` everywhere, the closed
committed/blocked oneOf, the committed message's required fields + ``role`` /
``trust_state`` consts, and the closed ``reason`` enum.

WHERE THE SCHEMA AND THE RUST TYPE DO NOT AGREE, stated because this paragraph used to
say the two are "kept in lock-step": they are, on shape and on every field but one. The
schema pins the committed message's ``trust_state`` to the const ``trusted_verified``.
The Rust ``CommittedMessage`` no longer does -- ``CommittedMessage::new`` carries the
label the committing transaction stored, and ``governed_message_store.rs`` allows two
(``trusted_verified`` and ``demonstration_custody``). So the broker can project a frame
this schema refuses, and the renderer (``governedTurn.ts``) refuses it too, on purpose
and fail-closed. Which side is the contract -- widen the schema to the labels the broker
can commit, or have the broker decline to project anything but ``trusted_verified`` --
is a decision about what the window may be shown as committed, and it is the Owner's.
These tests pin the schema as it is: the NARROWER of the two.

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
        # role and trust_state are LOCKED consts IN THE SCHEMA. The Rust type's trust_state
        # is not a constant any more (see the module docstring); this asserts the schema, which
        # is what the renderer accepts, not what the broker is able to send.
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
