"""The completion-manifest JSON schema and the runtime's strict required set must agree.

`bro_completion._check_manifest` enforces an EXACT field set: anything missing and
anything extra is `invalid completion manifest shape`. `schemas/completion-manifest.schema.json`
describes the same artifact with `additionalProperties: false` plus a `required` list.
Nothing validates a production manifest against that schema at runtime, so the two can
drift silently — and they did: the O-5 pass added `evidence_head_sha256` and
`head_sequence` to the runtime set while the schema, out of that pass's editing scope,
kept describing the older shape. A schema that under-describes the enforced shape reads
as documentation of a contract that no longer exists, and the only reason it did not
break anything is that nobody checks it.

These tests make the agreement a checked claim, in BOTH directions:

* every field the schema requires must be one the runtime accepts — a manifest carrying
  exactly the schema's fields must clear the shape check;
* every field the runtime requires must be one the schema requires — dropping any single
  schema field must make the runtime refuse, and a field the schema does not know about
  must be refused too.

The first bullet fails if the schema grows a field the runtime rejects as extra; the
second fails if the runtime grows a field the schema does not list. Neither can be
satisfied by editing only one file.
"""

from __future__ import annotations

import ast
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

from bro_completion import CompletionError, _check_manifest

SCHEMA_PATH = ROOT / "schemas" / "completion-manifest.schema.json"

#: The two fields the signature envelope supplies. `_check_manifest` subtracts them
#: before comparing against its required set (they are verified by `verify_artifact`,
#: not by the shape check), while the schema — which describes the signed payload as it
#: sits on disk — requires them. This is the one legitimate difference between the sets.
ENVELOPE = frozenset({"artifact_type", "key_id"})

TASK = {
    "task_id": "task-schema-agreement",
    "agent_id": "agt-p01-r01",
    "risk": "low",
    "done_criteria": ["schema and runtime agree"],
    "verification": {"required": False, "commands": []},
}


def schema_document() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def runtime_required_set() -> frozenset[str]:
    """The literal `required = {...}` set inside `bro_completion._check_manifest`.

    Read from the source rather than imported, because the set is a local of a private
    function; there is no module constant to compare against, and adding one would mean
    editing the runtime to make its own test pass. A parse failure is an assertion
    failure, never a silent pass.
    """
    tree = ast.parse((ROOT / "runtime" / "bro_completion.py").read_text(encoding="utf-8"))
    functions = [node for node in ast.walk(tree)
                 if isinstance(node, ast.FunctionDef) and node.name == "_check_manifest"]
    if len(functions) != 1:
        raise AssertionError(
            f"expected exactly one _check_manifest definition, found {len(functions)}")
    for node in ast.walk(functions[0]):
        if isinstance(node, ast.Assign) and any(
                isinstance(target, ast.Name) and target.id == "required"
                for target in node.targets):
            value = ast.literal_eval(node.value)
            if not isinstance(value, (set, frozenset)) or not value:
                raise AssertionError("_check_manifest `required` is not a non-empty set literal")
            return frozenset(value)
    raise AssertionError("no `required = {...}` assignment found in _check_manifest")


class DeclaredSetsAgreeTests(unittest.TestCase):
    """The two declarations, compared directly, with a readable diff either way."""

    def setUp(self) -> None:
        self.schema = schema_document()
        self.schema_required = frozenset(self.schema["required"])
        self.runtime_required = runtime_required_set()

    def test_the_schema_requires_exactly_what_the_runtime_requires(self) -> None:
        self.assertEqual(
            self.schema_required - ENVELOPE, self.runtime_required,
            "schemas/completion-manifest.schema.json and bro_completion._check_manifest "
            "no longer describe the same manifest: schema-only fields "
            f"{sorted(self.schema_required - ENVELOPE - self.runtime_required)}, "
            f"runtime-only fields {sorted(self.runtime_required - self.schema_required)}")

    def test_the_schema_requires_the_signature_envelope(self) -> None:
        # The runtime tolerates their absence because `verify_artifact` has already
        # checked them; the on-disk document must still carry both.
        self.assertTrue(ENVELOPE <= self.schema_required)

    def test_additional_properties_is_closed_and_covers_every_required_field(self) -> None:
        # `additionalProperties: false` is what makes the schema's field set exact, which
        # is the property the runtime's set-equality shape check has. A required field
        # with no `properties` entry would be required and simultaneously forbidden.
        self.assertIs(self.schema["additionalProperties"], False)
        self.assertEqual(set(self.schema["properties"]), self.schema_required)

    def test_the_o5_head_binding_is_in_both(self) -> None:
        for field in ("evidence_head_sha256", "head_sequence"):
            with self.subTest(field=field):
                self.assertIn(field, self.schema_required)
                self.assertIn(field, self.runtime_required)


class RuntimeEnforcesExactlyTheSchemaShapeTests(unittest.TestCase):
    """Behavioural half: the runtime is run for real against schema-derived manifests.

    Nothing is mocked. `_check_manifest` checks the shape first and the task binding
    second, so a manifest whose field set is right but whose values are placeholders is
    refused for the BINDING, never for the shape — which is exactly the discrimination
    these tests need, and it never reaches the key registry or the evidence store.
    """

    SHAPE = "invalid completion manifest shape"

    def setUp(self) -> None:
        self.schema_required = frozenset(schema_document()["required"])

    def refusal(self, manifest: dict) -> str:
        with self.assertRaises(CompletionError) as caught:
            _check_manifest(TASK, TASK["agent_id"], manifest,
                            root=pathlib.Path(self.id()), now=0, keys={},
                            evidence_store=None, receipt_store=None, require_live=False)
        return str(caught.exception)

    def schema_shaped_manifest(self) -> dict:
        """Exactly the schema's required fields, with values that cannot bind."""
        manifest = {field: "unbound-placeholder" for field in self.schema_required}
        manifest["schema"] = 1
        return manifest

    def test_a_manifest_carrying_exactly_the_schema_fields_clears_the_shape_check(self) -> None:
        # If the schema listed a field the runtime does not know, this manifest would be
        # rejected as extra; the refusal below proves the shape check was satisfied and
        # the run continued into the binding comparison.
        message = self.refusal(self.schema_shaped_manifest())
        self.assertNotIn(self.SHAPE, message)
        self.assertIn("completion manifest binding mismatch", message)

    def test_dropping_any_single_schema_field_is_refused_by_the_runtime(self) -> None:
        # If the runtime stopped requiring a field the schema lists, dropping it would
        # sail through to the binding error instead.
        for field in sorted(self.schema_required - ENVELOPE):
            with self.subTest(field=field):
                manifest = self.schema_shaped_manifest()
                del manifest[field]
                self.assertIn(self.SHAPE, self.refusal(manifest))

    def test_a_field_the_schema_does_not_describe_is_refused_by_the_runtime(self) -> None:
        # The mirror of `additionalProperties: false`.
        manifest = self.schema_shaped_manifest()
        manifest["evidence_head_floor_override"] = "x"
        self.assertIn(self.SHAPE, self.refusal(manifest))


class SchemaConstrainsTheHeadBindingTests(unittest.TestCase):
    """Listing the two O-5 fields is not enough — they must be constrained as the
    runtime constrains them, or the schema still under-describes the enforced shape.
    `_check_manifest` rejects a non-sha256 `evidence_head_sha256` and a `head_sequence`
    that is not a positive integer (see test_completion_head_binding.py); the schema
    must reject the same documents."""

    def setUp(self) -> None:
        import jsonschema

        self.jsonschema = jsonschema
        self.schema = schema_document()

    def manifest(self, **overrides) -> dict:
        payload = {
            "schema": 1,
            "artifact_type": "completion-manifest",
            "key_id": "dev-builder",
            "task_id": "task-x",
            "agent_id": "agt-p01-r02",
            "task_contract_sha256": "a" * 64,
            "candidate_head": "b" * 40,
            "candidate_tree": "c" * 64,
            "done_criteria": [{"criterion": "done", "status": "satisfied",
                               "evidence_event_ids": ["e1"]}],
            "tests": [{"command": ["pytest"], "status": "passed",
                       "evidence_event_id": "e2",
                       "execution_receipt_id": "rcpt-00000000000000e2"}],
            "evidence_event_ids": ["e1", "e2"],
            "evidence_head_sha256": "d" * 64,
            "head_sequence": 1,
            "open_risks": [],
            "rollback_ready": True,
            "nonce": "nonce-schema-agreement-1",
            "issued_at_epoch": 1_700_000_000,
            "expires_at_epoch": 1_700_003_600,
        }
        payload.update(overrides)
        return payload

    def test_a_well_formed_manifest_validates(self) -> None:
        self.jsonschema.validate(self.manifest(), self.schema)

    def test_a_manifest_without_the_head_binding_is_rejected(self) -> None:
        for field in ("evidence_head_sha256", "head_sequence"):
            with self.subTest(field=field):
                payload = self.manifest()
                del payload[field]
                with self.assertRaises(self.jsonschema.ValidationError):
                    self.jsonschema.validate(payload, self.schema)

    def test_evidence_head_sha256_must_be_lowercase_hex_of_the_right_length(self) -> None:
        for bad in ("not-a-digest", "D" * 64, "d" * 63, "d" * 65, 12, None):
            with self.subTest(bad=bad):
                with self.assertRaises(self.jsonschema.ValidationError):
                    self.jsonschema.validate(self.manifest(evidence_head_sha256=bad),
                                             self.schema)

    def test_head_sequence_must_be_a_positive_integer(self) -> None:
        for bad in (0, -1, "1", 1.5, True, None):
            with self.subTest(bad=bad):
                with self.assertRaises(self.jsonschema.ValidationError):
                    self.jsonschema.validate(self.manifest(head_sequence=bad), self.schema)


if __name__ == "__main__":
    unittest.main()
