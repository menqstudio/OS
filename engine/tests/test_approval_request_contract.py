"""The approval-request contract, and the five invariants it is not allowed to break.

`docs/OWNER_ACTION_REQUIRED.md` fixed five contract invariants for this path BEFORE anything was built,
with its reason stated: *"Fixing them now means the contract test is not designed by whoever is trying
to pass it."* So these tests are written against that list rather than against the schema, and the
schema is what has to satisfy them:

  1. no key, lease, nonce or verdict crosses the wall in this direction
  2. the desktop requests and never decides
  3. the desktop's own T-010/T-011 approval authority stays a separately named thing
  4. `RECORDS_ARE_AUTHENTICATED` stays false -- `requested_by` is a NAME, never an identity
  5. the engine schema change is audited before it lands

Two kinds of assertion, deliberately:

  * STRUCTURAL ones read the schema document itself and need no dependency, so they run in every job --
    including `Negative matrix`, which installs nothing. A closed property set is what makes invariant 1
    true by construction rather than by a validator being present.
  * ACCEPTANCE ones drive `jsonschema` and are skipped where it is absent, because "I could not check"
    and "it is fine" are different answers.
"""
from __future__ import annotations

import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SCHEMA_PATH = ROOT / "schemas" / "approval-request.schema.json"
SOURCE_PATH = REPO / "contracts" / "approval-request.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

try:
    import jsonschema
except ImportError:                                     # pragma: no cover - dependency-free jobs
    jsonschema = None

#: The whole property set, written out so ADDING a field is a failing test rather than a silent
#: widening of what may cross. This is invariant 1 held structurally.
EXPECTED_PROPERTIES = {
    "schema", "protocol", "op", "request_id", "task_id", "requested_command",
    "expected_task_state", "reason", "evidence_refs", "requested_by_type", "requested_by",
    "requested_at_epoch",
}

#: Names that must not appear, in any casing. Not a heuristic over values -- a list of the words this
#: repository's own artifacts use for the things that may not cross.
FORBIDDEN_FIELD_WORDS = (
    "key", "signature", "sig", "nonce", "lease", "verdict", "secret", "token", "credential",
    "password", "private", "seed", "cert", "attest",
)


def request(**overrides):
    doc = {
        "schema": 1,
        "protocol": "brops.approval-request.v1",
        "op": "approval.request",
        "request_id": "req-7f2a91c4",
        "task_id": "task-0001",
        "requested_command": "approve",
        "expected_task_state": "awaiting-owner-approval",
        "reason": "the cockpit operator asks the owner to approve this task",
        "requested_by_type": "desktop-operator",
        "requested_by": "gev@cockpit",
        "requested_at_epoch": 1_758_240_000,
    }
    doc.update(overrides)
    return {k: v for k, v in doc.items() if v is not _ABSENT}


_ABSENT = object()


class TheSchemaIsClosed(unittest.TestCase):
    """Invariant 1, held by construction rather than by a validator being installed."""

    def test_additional_properties_are_refused(self):
        self.assertIs(SCHEMA["additionalProperties"], False,
                      "an open property set would let a key ride in a field nobody declared")

    def test_the_property_set_is_exactly_what_was_agreed(self):
        self.assertEqual(set(SCHEMA["properties"]), EXPECTED_PROPERTIES)

    def test_no_property_is_named_after_a_thing_that_may_not_cross(self):
        for name in SCHEMA["properties"]:
            for word in FORBIDDEN_FIELD_WORDS:
                with self.subTest(property=name, word=word):
                    self.assertNotIn(word, name.lower(),
                                     f"`{name}` reads as a carrier for something invariant 1 forbids")

    def test_required_is_a_subset_of_properties(self):
        self.assertTrue(set(SCHEMA["required"]) <= set(SCHEMA["properties"]))

    def test_evidence_refs_are_references_and_not_contents(self):
        """A ref the engine can resolve is not a new input to its trust boundary; a blob would be."""
        items = SCHEMA["properties"]["evidence_refs"]["items"]
        self.assertEqual(items["type"], "string")
        self.assertNotIn("object", json.dumps(items))


class TheDesktopAsksAndNeverDecides(unittest.TestCase):
    """Invariants 2 and 3."""

    def test_the_requested_command_is_one_of_three_asks(self):
        self.assertEqual(set(SCHEMA["properties"]["requested_command"]["enum"]),
                         {"approve", "deny", "request-verification"})

    def test_the_command_surface_is_not_reachable_through_this_document(self):
        """`cancel`, `retry` and `reassign` are commands and not approvals. A request shape wide enough
        to drive the whole control-room surface would be a command channel with a softer name."""
        enum = set(SCHEMA["properties"]["requested_command"]["enum"])
        for verb in ("cancel", "retry", "reassign"):
            with self.subTest(verb=verb):
                self.assertNotIn(verb, enum)

    def test_there_is_no_field_a_reply_could_be_read_out_of(self):
        """The document cannot carry a decision, a state transition or an outcome. What the engine does
        with it is the engine's, and the desktop has nowhere to write what it wishes had happened."""
        for banned in ("granted", "decision", "outcome", "state", "adjudicated", "result"):
            with self.subTest(field=banned):
                self.assertNotIn(banned, SCHEMA["properties"])

    def test_the_signed_command_and_this_document_are_different_artifacts(self):
        """Invariant 3, mechanically: the artifact that DECIDES carries `key_id` and `signature`, and
        this one has neither. If they ever converge, this fails rather than a reader noticing."""
        decider = json.loads((ROOT / "schemas" / "control-room-command.schema.json")
                             .read_text(encoding="utf-8"))
        self.assertIn("key_id", decider["properties"])
        self.assertIn("signature", decider["properties"])
        self.assertNotIn("key_id", SCHEMA["properties"])
        self.assertNotIn("signature", SCHEMA["properties"])


class TheRequesterIsNamedAndNotAuthenticated(unittest.TestCase):
    """Invariant 4."""

    def test_the_requester_type_cannot_claim_to_be_the_owner(self):
        self.assertEqual(SCHEMA["properties"]["requested_by_type"]["enum"], ["desktop-operator"])

    def test_the_signed_command_is_the_one_that_may_say_owner(self):
        decider = json.loads((ROOT / "schemas" / "control-room-command.schema.json")
                             .read_text(encoding="utf-8"))
        self.assertEqual(set(decider["properties"]["requested_by_type"]["enum"]), {"owner", "bro"})

    def test_the_schema_says_the_name_is_a_claim(self):
        text = SCHEMA["properties"]["requested_by"]["description"].lower()
        self.assertIn("never an authenticated identity", text)
        self.assertIn("records_are_authenticated", text)


class TheTwoCopiesAreOneContract(unittest.TestCase):
    """`contracts/` is the source; `engine/schemas/` is vendored. A gate holds them byte-identical and
    this names it, so a tree that loses the gate still fails on the fact."""

    def test_the_source_and_the_vendored_copy_are_byte_identical(self):
        self.assertEqual(SOURCE_PATH.read_bytes(), SCHEMA_PATH.read_bytes())

    def test_the_engine_registry_loads_it(self):
        registry = json.loads((ROOT / "schemas" / "registry.json").read_text(encoding="utf-8"))
        paths = {s["id"]: s["path"] for s in registry["schemas"]}
        self.assertEqual(paths.get("approval-request"), "schemas/approval-request.schema.json")


@unittest.skipIf(jsonschema is None, "jsonschema is not installed in this job")
class WhatTheSchemaAcceptsAndRefuses(unittest.TestCase):
    """The acceptance half. Skipped rather than silently passed where the dependency is absent."""

    def setUp(self):
        cls = jsonschema.validators.validator_for(SCHEMA)
        cls.check_schema(SCHEMA)
        self.validator = cls(SCHEMA)

    def refused(self, doc, because):
        errors = list(self.validator.iter_errors(doc))
        self.assertTrue(errors, f"the schema accepted a document it must refuse: {because}")
        return errors

    def test_a_well_formed_request_is_accepted(self):
        """The control. Without it every refusal below could be arriving from the fixture."""
        self.assertEqual(list(self.validator.iter_errors(request())), [])

    def test_a_request_carrying_a_key_is_refused(self):
        for field, value in (("key_id", "control-room-1"),
                             ("signature", "ab" * 64),
                             ("nonce", "7f2a91c4"),
                             ("lease", {"id": "lease-1"}),
                             ("verdict", "GREEN"),
                             ("token", "eyJhbGciOiJFZERTQSJ9.e30.x")):
            with self.subTest(field=field):
                self.refused(request(**{field: value}), f"it carries `{field}`")

    def test_a_request_claiming_to_be_the_owner_is_refused(self):
        for who in ("owner", "bro", "engine"):
            with self.subTest(requested_by_type=who):
                self.refused(request(requested_by_type=who), f"it claims to be `{who}`")

    def test_a_command_that_is_not_an_approval_is_refused(self):
        for verb in ("cancel", "retry", "reassign", "grant", "escalate"):
            with self.subTest(requested_command=verb):
                self.refused(request(requested_command=verb), f"`{verb}` is not one of the three asks")

    def test_every_required_field_is_really_required(self):
        for field in SCHEMA["required"]:
            with self.subTest(missing=field):
                self.refused(request(**{field: _ABSENT}), f"`{field}` is absent")

    def test_the_protocol_and_op_are_pinned(self):
        self.refused(request(protocol="brops.governance-read.v1"), "the protocol is another one")
        self.refused(request(op="governance.read"), "the op is another one")

    def test_an_empty_reason_is_refused(self):
        self.refused(request(reason=""), "a request with no reason is not a request")

    def test_evidence_refs_may_be_absent_and_may_be_empty(self):
        self.assertEqual(list(self.validator.iter_errors(request())), [])
        self.assertEqual(list(self.validator.iter_errors(request(evidence_refs=[]))), [])
        self.refused(request(evidence_refs=[{"blob": "..."}]), "a ref is a string, not a document")


if __name__ == "__main__":
    unittest.main()
