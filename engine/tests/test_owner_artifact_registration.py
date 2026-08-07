"""O-4 / O-5 — the two owner artifact types are REGISTERED, and registering them
provisions nothing.

Both residual items dead-ended on the same wall. `bro_signature._parse_key` refuses any
trusted-key registry entry naming an artifact type absent from `ARTIFACT_AUTHORITY`, so
until the type exists the owner cannot be given a key for it *from configuration at all*:
the registry the operator signs would not load. That made two closures impossible rather
than merely unprovisioned —

* **O-4** `control-room-command` — the per-command artifact that would let an owner-issued
  control-room command be proven instead of claimed;
* **O-5** `evidence-floor-anchor` — the operator's statement of an evidence high-water mark,
  presented at `BRO_EVIDENCE_FLOOR_ANCHOR`, which distinguishes a wiped-and-re-provisioned
  floor from a first sighting.

Registering a type is emphatically NOT provisioning a key, and this file's job is to prove
that the distinction holds in the code and not only in a comment:

* the committed `config/trusted-keys.json` grants neither type to any key, so nothing in
  the shipped tree can sign either;
* with the type registered but **no key pinned for it**, both consuming paths still refuse,
  by name — a registry whose operator key is not granted the type does not verify an anchor
  signed by that very key;
* only a genuine Ed25519 signature by a key the operator-signed registry actually grants the
  type to establishes anything, and every corruption of that document refuses;
* the control-room owner actor is still refused by name even when a perfectly valid
  `control-room-command` artifact is presented — registering the type opened no path,
  because nothing consumes it yet. Its closure still needs the schema signature field and
  the verification call, both outside this change.

No key material is invented anywhere here: every key is an ephemeral development key the
test generates for itself, exactly as the rest of the suite does.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_signature import (ARTIFACT_AUTHORITY, AUTHORITY_TYPES, OPERATOR, SignatureError,
                           _parse_key, load_trusted_keys, verify_artifact)
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

# The two types this change registers.
CONTROL_ROOM_COMMAND = "control-room-command"
EVIDENCE_FLOOR_ANCHOR = "evidence-floor-anchor"
NEW_TYPES = (CONTROL_ROOM_COMMAND, EVIDENCE_FLOOR_ANCHOR)

ENV_FLOOR_ANCHOR = "BRO_EVIDENCE_FLOOR_ANCHOR"


class RegistryMayNameTheOwnerTypesTests(unittest.TestCase):
    """The registry-loading half: a signed registry may now carry these grants, and only
    under the operator authority."""

    NOW = 1_700_000_000

    def entry(self, authority: str, artifacts: list[str]) -> dict:
        return {
            "key_id": f"dev-{authority}",
            "public_key": "ab" * 32,
            "authority_type": authority,
            "allowed_artifact_types": artifacts,
            "not_before_epoch": self.NOW,
            "not_after_epoch": self.NOW + 86_400,
            "status": "active",
            "issued_by": "dev-operator-root",
        }

    def test_each_type_is_bound_to_the_operator_root_authority(self) -> None:
        for artifact in NEW_TYPES:
            with self.subTest(artifact=artifact):
                self.assertEqual(ARTIFACT_AUTHORITY.get(artifact), OPERATOR)

    def test_an_operator_registry_entry_may_name_each_type(self) -> None:
        """This is the wall that made both closures impossible: before the registration,
        `_parse_key` raised `unknown artifact type` and the whole registry failed to load,
        so the owner could not be given a key even offline."""
        for artifact in NEW_TYPES:
            with self.subTest(artifact=artifact):
                key = _parse_key(self.entry(OPERATOR, [artifact]))
                self.assertIn(artifact, key.allowed_artifact_types)

    def test_no_other_authority_may_be_granted_either_type(self) -> None:
        for artifact in NEW_TYPES:
            for authority in sorted(AUTHORITY_TYPES - {OPERATOR}):
                with self.subTest(artifact=artifact, authority=authority):
                    with self.assertRaises(SignatureError) as caught:
                        _parse_key(self.entry(authority, [artifact]))
                    self.assertIn("may not", str(caught.exception))

    def test_a_still_unregistered_type_is_refused_exactly_as_before(self) -> None:
        # The wall is intact for everything the change did not deliberately register.
        for artifact in ("owner-command", "control_room_command", "audit-head"):
            with self.subTest(artifact=artifact):
                with self.assertRaises(SignatureError) as caught:
                    _parse_key(self.entry(OPERATOR, [artifact]))
                self.assertIn("unknown artifact type", str(caught.exception))

    def test_the_committed_registry_grants_neither_type_to_any_key(self) -> None:
        """Registration provisioned nothing: the shipped trust root can sign neither."""
        document = json.loads(
            (ROOT / "config" / "trusted-keys.json").read_text(encoding="utf-8"))
        keys = load_trusted_keys(
            ROOT, operator_public_key=document["payload"]["operator_public_key"])
        self.assertTrue(keys)
        for key in keys.values():
            for artifact in NEW_TYPES:
                with self.subTest(key_id=key.key_id, artifact=artifact):
                    self.assertNotIn(artifact, key.allowed_artifact_types)

    def test_verify_artifact_refuses_a_type_the_presenting_key_was_not_granted(self) -> None:
        """The per-key grant, not the type registry, is what authorises a signature."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = pathlib.Path(temp.name)
        operator = generate_key(OPERATOR, "dev-operator-root", False)
        use_operator_pin(self, operator["public_key"])
        registry = build_registry([operator], int(time.time()) - 60, 86_400)
        # Strip the two grants back out: a deployment that has registered the types but
        # has not yet minted or pinned a key for them.
        for entry in registry["payload"]["keys"]:
            entry["allowed_artifact_types"] = [
                a for a in entry["allowed_artifact_types"] if a not in NEW_TYPES]
        resigned = sign_payload(operator["private_key"], registry["payload"])
        (base / "config").mkdir(parents=True)
        (base / "config" / "trusted-keys.json").write_text(json.dumps(resigned),
                                                           encoding="utf-8")
        keys = load_trusted_keys(base)
        for artifact in NEW_TYPES:
            with self.subTest(artifact=artifact):
                document = sign_payload(operator["private_key"], {
                    "artifact_type": artifact, "key_id": operator["key_id"],
                    "task_id": "task-1", "head_sequence": 5})
                with self.assertRaises(SignatureError) as caught:
                    verify_artifact(document, artifact, keys)
                self.assertIn("may not sign", str(caught.exception))


# `HeadBindingFixture` carries no test methods, so importing it does not re-run
# test_completion_head_binding's suite under this module's name.
from test_completion_head_binding import HeadBindingFixture  # noqa: E402


class EvidenceFloorAnchorTests(HeadBindingFixture):
    """O-5 end to end: the closure is now POSSIBLE, and everything short of a real
    operator signature still refuses.

    Every case starts from the residual defect itself — the floor is walked up to
    sequence 5, then deleted and re-provisioned, which reads exactly like a task being
    seen for the first time. `_require_establishable_mark` refuses that unless the
    deployment can present a signed anchor.
    """

    def wipe_floor(self) -> None:
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()

    def advance_to(self, head_sequence: int) -> None:
        self.check(self.manifest())
        self.reseal_head(head_sequence)
        self.check(self.manifest())

    def anchor(self, *, authority: str = "operator-root", tamper: bool = False,
               **overrides) -> pathlib.Path:
        payload = {
            "artifact_type": EVIDENCE_FLOOR_ANCHOR,
            "key_id": self.keys[authority]["key_id"],
            "task_id": "task-1",
            "head_sequence": 5,
            "issued_at_epoch": int(time.time()) - 10,
        }
        payload.update(overrides)
        document = sign_payload(self.keys[authority]["private_key"], payload)
        if tamper:
            document["payload"]["head_sequence"] = 99
        path = self.tmp / "floor-anchor.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return path

    def present(self, path: pathlib.Path):
        with unittest.mock.patch.dict(os.environ, {ENV_FLOOR_ANCHOR: str(path)}):
            return self.check(self.manifest())

    def refuse(self, path: pathlib.Path) -> str:
        from bro_completion import CompletionError
        with self.assertRaises(CompletionError) as caught:
            self.present(path)
        return str(caught.exception)

    def restrict_registry(self) -> None:
        """Re-sign the fixture registry with the two new grants removed.

        This is the state the hard rule is about: the artifact TYPE is registered, no key
        is pinned for it. The operator key here is the deployment's real, external,
        registry-signing root — and it still cannot sign a floor anchor.
        """
        path = self.repo / "config" / "trusted-keys.json"
        payload = json.loads(path.read_text(encoding="utf-8"))["payload"]
        for entry in payload["keys"]:
            entry["allowed_artifact_types"] = [
                a for a in entry["allowed_artifact_types"] if a not in NEW_TYPES]
        path.write_text(
            json.dumps(sign_payload(self.keys["operator-root"]["private_key"], payload)),
            encoding="utf-8")
        from bro_signature import load_trusted_keys as _load
        self.live_keys = _load(self.repo)

    # ---- the refusals -----------------------------------------------------------------

    def test_a_wiped_floor_with_no_anchor_presented_still_refuses(self) -> None:
        # Unchanged by the registration: presenting nothing is still a named refusal.
        from bro_completion import CompletionError
        self.wipe_floor()
        with self.assertRaises(CompletionError) as caught:
            self.check(self.manifest())
        message = str(caught.exception)
        self.assertIn("cannot establish the evidence high-water mark", message)
        self.assertIn(ENV_FLOOR_ANCHOR, message)
        self.assertIn("none is compiled in", message)

    def test_registered_but_unpinned_the_anchor_is_still_refused(self) -> None:
        """THE hard-rule case: type registered, no key granted it. Must still fail closed.

        The document is genuinely signed, by the deployment's own operator-root key, and
        that key anchors the registry itself. It is refused anyway, because authority to
        sign an artifact comes from the per-key grant in the operator-signed registry —
        which no one has issued.
        """
        self.wipe_floor()
        self.restrict_registry()
        message = self.refuse(self.anchor())
        self.assertIn("does not verify as an operator-signed evidence-floor-anchor", message)
        self.assertIn("may not sign", message)
        self.assertIn("none is compiled in", message)

    def test_an_anchor_from_a_non_operator_authority_is_refused(self) -> None:
        for authority in ("builder", "evidence-recorder", "issuer", "verifier", "release"):
            with self.subTest(authority=authority):
                self.setUp()
                self.wipe_floor()
                message = self.refuse(self.anchor(authority=authority))
                self.assertIn("does not verify as an operator-signed", message)

    def test_a_tampered_anchor_is_refused(self) -> None:
        self.wipe_floor()
        message = self.refuse(self.anchor(tamper=True))
        self.assertIn("does not verify as an operator-signed", message)

    def test_an_anchor_for_another_task_is_refused(self) -> None:
        self.wipe_floor()
        message = self.refuse(self.anchor(task_id="task-2"))
        self.assertIn("names task 'task-2'", message)

    def test_an_anchor_below_the_declared_mark_is_refused(self) -> None:
        # An anchor is a high-water statement, not a waiver: one naming a lower sequence
        # than the manifest binds cannot establish the manifest's claim.
        self.wipe_floor()
        message = self.refuse(self.anchor(head_sequence=4))
        self.assertIn("cannot establish the evidence high-water mark", message)

    def test_an_anchor_with_no_positive_head_sequence_is_refused(self) -> None:
        for bad in (0, -1, "5", True, None):
            with self.subTest(bad=bad):
                self.setUp()
                self.wipe_floor()
                message = self.refuse(self.anchor(head_sequence=bad))
                self.assertIn("carries no positive head_sequence", message)

    def test_an_artifact_of_another_type_may_not_stand_in(self) -> None:
        self.wipe_floor()
        message = self.refuse(self.anchor(artifact_type="workspace-binding"))
        self.assertIn("does not verify as an operator-signed", message)

    # ---- the closure the registration makes possible -----------------------------------

    def test_a_genuinely_operator_signed_anchor_establishes_the_mark(self) -> None:
        """The point of the registration: with a real key granted the type and a real
        signature over the payload, the owner can now close the wiped-floor case. Before
        the type existed this was unreachable — the registry naming it would not load."""
        self.wipe_floor()
        manifest, _hash, _receipts = self.present(self.anchor())
        self.assertEqual(manifest["head_sequence"], 5)

    def test_the_anchor_does_not_soften_any_other_gate(self) -> None:
        """An anchor answers one question — "was this floor wiped or is this new?" — and
        must not become a master key for the rest of the completion gate."""
        self.wipe_floor()
        # A genuine anchor present, but the store's own signed events reach past the
        # chain the manifest presents: still the truncation refusal.
        self.write_head("task-1", self.event_digest(2), 2, 2, head_sequence=5)
        path = self.anchor()
        from bro_completion import CompletionError
        with self.assertRaises(CompletionError) as caught:
            with unittest.mock.patch.dict(os.environ, {ENV_FLOOR_ANCHOR: str(path)}):
                self.check(self.manifest(event_ids=self.chain[:2]))
        self.assertIn("the evidence store holds signed events for task-1",
                      str(caught.exception))

    def event_digest(self, position: int, task_id: str = "task-1") -> str:
        from bro_evidence import event_hash
        document = json.loads(
            (self.store / f"{task_id}-e{position}.json").read_text(encoding="utf-8"))
        return event_hash(document["payload"])


# Imported after the signature assertions so a failure there is not masked by an
# unrelated import error in the control-room stack.
from bro_control_room_api import ControlRoomAPIError, ControlRoomAPIV1  # noqa: E402
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1  # noqa: E402
from bro_policy import CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE  # noqa: E402
from test_control_room_api import cancel_command, task_contract  # noqa: E402


class ControlRoomCommandTypeOpensNoPathTests(unittest.TestCase):
    """O-4: the type now exists, and `validate_command_intent` is exactly as strict.

    Registering `control-room-command` is a prerequisite for the owner half, not the
    closure. Nothing verifies a `control-room-command` document yet — the schema carries
    no `artifact_type` / `key_id` / signature field and `_prove_command_actor` does not
    consume one — so an owner-issued command must still be refused BY NAME, even when the
    caller can produce a flawless one.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = pathlib.Path(self.temp.name)
        self.now = int(time.time())
        self.keys = {authority: generate_key(authority, f"dev-{authority}", False)
                     for authority in (OPERATOR, "builder")}
        use_operator_pin(self, self.keys[OPERATOR]["public_key"])
        (base / "registry" / "config").mkdir(parents=True)
        (base / "registry" / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), self.now - 3600, 86_400)),
            encoding="utf-8")
        self.trusted = load_trusted_keys(base / "registry")
        self.runtime = DurableOrchestrationRuntimeV1(base / "state", ROOT,
                                                     evidence_keys=self.trusted)
        self.runtime.create_task(task_contract("task-actor-1"), now_epoch=self.now)
        self.api = ControlRoomAPIV1(self.runtime)

    def owner_command(self) -> dict:
        body = cancel_command("task-actor-1")
        body.update({
            "requested_by_type": "owner",
            "requested_by": "owner-gev",
            "requested_at_epoch": self.now,
            "expires_at_epoch": self.now + 3600,
            "scope": ["task:task-actor-1"],
        })
        return body

    def signed_command_artifact(self, command: dict) -> dict:
        """A flawless `control-room-command`: real Ed25519, operator-root key, granted
        the type by the operator-signed registry, bound to this exact command."""
        payload = {
            "artifact_type": CONTROL_ROOM_COMMAND,
            "key_id": self.keys[OPERATOR]["key_id"],
            "role": "owner",
            "agent_id": "owner-gev",
            "session_id": "s-owner",
            "command_id": command["command_id"],
            "issued_at_epoch": self.now - 10,
            "expires_at_epoch": self.now + 3600,
        }
        return sign_payload(self.keys[OPERATOR]["private_key"], payload)

    def test_the_registry_can_now_grant_the_type(self) -> None:
        # Precondition for the test below: the artifact really is verifiable here, so the
        # refusal that follows is about the consuming path, not about a broken fixture.
        command = self.owner_command()
        payload = verify_artifact(self.signed_command_artifact(command),
                                  CONTROL_ROOM_COMMAND, self.trusted, now=self.now)
        self.assertEqual(payload["command_id"], command["command_id"])

    def test_an_owner_command_is_still_refused_by_name(self) -> None:
        command = self.owner_command()
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(
                command, now_epoch=self.now + 1,
                actor_attestation=self.signed_command_artifact(command))
        message = str(caught.exception)
        self.assertIn("cannot be validated", message)
        for named in ("ARTIFACT_AUTHORITY", "config/trusted-keys.json",
                      "control-room-command.schema.json"):
            self.assertIn(named, message)

    def test_an_owner_command_with_no_attestation_at_all_is_refused(self) -> None:
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(self.owner_command(), now_epoch=self.now + 1)
        self.assertIn("self-asserted", str(caught.exception))

    def test_a_control_room_command_may_not_stand_in_for_a_conductor_session(self) -> None:
        """Artifact-type confusion: the conductor path takes a `conductor-session`, and a
        `control-room-command` signed by the same operator key is not one."""
        conductor = cancel_command("task-actor-1")
        conductor.update({
            "requested_by_type": CONDUCTOR_ROLE,
            "requested_by": CANONICAL_CONDUCTOR_ID,
            "requested_at_epoch": self.now,
            "expires_at_epoch": self.now + 3600,
            "scope": ["task:task-actor-1"],
        })
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(
                conductor, now_epoch=self.now + 1,
                actor_attestation=self.signed_command_artifact(conductor))
        self.assertIn("RED", str(caught.exception))

    def test_the_control_room_command_schema_still_carries_no_signature_field(self) -> None:
        """The remaining half of O-4, pinned so nobody reads the registration as closure:
        the command schema has no `artifact_type`, no `key_id` and no signature, so there
        is nothing for a verifier to check even though a key could now sign one."""
        schema = json.loads((ROOT / "schemas" / "control-room-command.schema.json")
                            .read_text(encoding="utf-8"))
        for field in ("artifact_type", "key_id", "signature"):
            with self.subTest(field=field):
                self.assertNotIn(field, schema["properties"])


if __name__ == "__main__":
    unittest.main()
