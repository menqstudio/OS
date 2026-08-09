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

from bro_signature import (ARTIFACT_AUTHORITY, AUTHORITY_TYPES, CONTROL_ROOM, EVIDENCE_FLOOR,
                           OPERATOR, SignatureError, _parse_key, load_trusted_keys,
                           verify_artifact)
from broctl import build_registry, generate_key, sign_payload
from _operator_pin import use_operator_pin

# The two types this change registers, each against its OWN delegated authority.
#
# They started life bound to `operator-root`, which is what forced a deployment that wanted
# to use either of them to keep the registry-signing root online. On the desktop shape that
# root sat in the app's own trust directory, and holding it is holding the ability to admit
# an `audit-anchor` key of one's own choosing — i.e. the ability to re-sign the record of
# what one did. The delegation is what lets the root be destroyed at the end of provisioning
# while the two routine powers survive.
CONTROL_ROOM_COMMAND = "control-room-command"
EVIDENCE_FLOOR_ANCHOR = "evidence-floor-anchor"
NEW_TYPES = (CONTROL_ROOM_COMMAND, EVIDENCE_FLOOR_ANCHOR)
#: artifact type -> the ONE authority that may sign it.
DELEGATED_AUTHORITY = {CONTROL_ROOM_COMMAND: CONTROL_ROOM,
                       EVIDENCE_FLOOR_ANCHOR: EVIDENCE_FLOOR}

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

    def test_each_type_is_bound_to_its_own_delegated_authority(self) -> None:
        """One authority per artifact, and neither of them the trust root.

        The second assertion is the load-bearing one. If either type drifted back onto
        `operator-root`, a deployment would have to hold the registry-signing key online to
        use it, and `brops_provision` could not destroy the root at the end of the mint.
        """
        for artifact, authority in DELEGATED_AUTHORITY.items():
            with self.subTest(artifact=artifact):
                self.assertEqual(ARTIFACT_AUTHORITY.get(artifact), authority)
                self.assertNotEqual(ARTIFACT_AUTHORITY.get(artifact), OPERATOR)
        # And they are not the SAME authority: one key that could do both would be
        # strictly more powerful than either delegation.
        self.assertNotEqual(DELEGATED_AUTHORITY[CONTROL_ROOM_COMMAND],
                            DELEGATED_AUTHORITY[EVIDENCE_FLOOR_ANCHOR])

    def test_an_operator_registry_entry_may_name_each_type(self) -> None:
        """This is the wall that made both closures impossible: before the registration,
        `_parse_key` raised `unknown artifact type` and the whole registry failed to load,
        so the owner could not be given a key even offline."""
        for artifact, authority in DELEGATED_AUTHORITY.items():
            with self.subTest(artifact=artifact):
                key = _parse_key(self.entry(authority, [artifact]))
                self.assertIn(artifact, key.allowed_artifact_types)

    def test_no_other_authority_may_be_granted_either_type(self) -> None:
        """The delegation did not become a blanket grant — in BOTH directions.

        `operator-root` is deliberately inside this loop now. The root may sign the registry
        that introduces these keys and may not sign what they sign, so a store that has
        destroyed its root has lost nothing these two types need, and a store that still has
        one cannot use it to shortcut them.
        """
        for artifact, allowed in DELEGATED_AUTHORITY.items():
            for authority in sorted(AUTHORITY_TYPES - {allowed}):
                with self.subTest(artifact=artifact, authority=authority):
                    with self.assertRaises(SignatureError) as caught:
                        _parse_key(self.entry(authority, [artifact]))
                    self.assertIn("may not", str(caught.exception))

    def test_neither_delegated_authority_may_sign_a_registry_or_a_session(self) -> None:
        """What the delegation must NOT carry with it.

        A `control-room` or `evidence-floor` key that could sign a `trusted-key-registry`
        would be the operator root under a different name, and destroying the root would
        buy nothing at all.
        """
        for authority in (CONTROL_ROOM, EVIDENCE_FLOOR):
            for artifact in ("trusted-key-registry", "conductor-session",
                             "workspace-binding", "protected-authority"):
                with self.subTest(authority=authority, artifact=artifact):
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
        delegates = [generate_key(a, f"dev-{a}", False)
                     for a in (CONTROL_ROOM, EVIDENCE_FLOOR)]
        use_operator_pin(self, operator["public_key"])
        registry = build_registry([operator, *delegates], int(time.time()) - 60, 86_400)
        # Strip the two grants back out: a deployment that has registered the types AND
        # minted the delegated keys, but whose operator has not yet granted them anything.
        # `_parse_key` allows an empty grant for the out-of-registry authorities alone, so
        # the delegates are dropped entirely rather than left allowing nothing.
        registry["payload"]["keys"] = [
            entry for entry in registry["payload"]["keys"]
            if not set(entry["allowed_artifact_types"]) & set(NEW_TYPES)]
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

    def setUp(self) -> None:
        super().setUp()
        # The delegated authority the anchor is now bound to. `EvidenceFixture` mints one
        # key per registry authority it knows about and does not know about this one, so it
        # is minted here and the fixture registry is re-signed to carry it. The operator
        # root still signs that registry — it simply may no longer sign a floor anchor,
        # which `test_the_operator_root_that_signs_the_registry_may_not_sign_an_anchor`
        # exercises against this very fixture.
        self.keys[EVIDENCE_FLOOR] = generate_key(EVIDENCE_FLOOR, f"dev-{EVIDENCE_FLOOR}",
                                                 False)
        self.resign_registry(list(self.keys.values()))

    def resign_registry(self, keys: list[dict]) -> None:
        path = self.repo / "config" / "trusted-keys.json"
        path.write_text(
            json.dumps(build_registry(keys, int(time.time()) - 60, 365 * 24 * 60 * 60)),
            encoding="utf-8")
        from bro_signature import load_trusted_keys as _load
        self.live_keys = _load(self.repo)

    def wipe_floor(self) -> None:
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()

    def advance_to(self, head_sequence: int) -> None:
        self.check(self.manifest())
        self.reseal_head(head_sequence)
        self.check(self.manifest())

    def anchor(self, *, authority: str = EVIDENCE_FLOOR, tamper: bool = False,
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
        self.resign_registry([k for k in self.keys.values()
                              if k["authority_type"] not in
                              (CONTROL_ROOM, EVIDENCE_FLOOR)])

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

        The signature is genuine and the key really was minted under the right authority;
        it is simply not in the registry the deployment reads. Authority to sign an
        artifact comes from the per-key grant in the operator-signed registry, and nobody
        has issued one.
        """
        self.wipe_floor()
        self.restrict_registry()
        message = self.refuse(self.anchor())
        self.assertIn("does not verify as an owner-signed evidence-floor-anchor", message)
        self.assertIn("unknown signing key", message)
        self.assertIn("none is compiled in", message)

    def test_the_operator_root_that_signs_the_registry_may_not_sign_an_anchor(self) -> None:
        """The delegation, in the direction that decides whether it was worth doing.

        `operator-root` is present, active, and is the very key this registry is signed
        with — the strongest key the deployment has. It is refused BY AUTHORITY, which is
        what makes destroying it at the end of provisioning cost the floor anchor nothing.
        """
        self.wipe_floor()
        message = self.refuse(self.anchor(authority="operator-root"))
        self.assertIn("does not verify as an owner-signed", message)
        self.assertIn("(operator-root) may not sign evidence-floor-anchor", message)

    def test_an_anchor_from_any_other_authority_is_refused(self) -> None:
        for authority in ("builder", "evidence-recorder", "issuer", "verifier", "release",
                          "operator-root"):
            with self.subTest(authority=authority):
                self.setUp()
                self.wipe_floor()
                message = self.refuse(self.anchor(authority=authority))
                self.assertIn("does not verify as an owner-signed", message)
                self.assertIn(f"({authority}) may not sign", message)

    def test_a_tampered_anchor_is_refused(self) -> None:
        self.wipe_floor()
        message = self.refuse(self.anchor(tamper=True))
        self.assertIn("does not verify as an owner-signed", message)

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
        self.assertIn("does not verify as an owner-signed", message)

    # ---- the closure the registration makes possible -----------------------------------

    def test_a_genuinely_delegated_signed_anchor_establishes_the_mark(self) -> None:
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
from bro_control_room_api import (ACTOR_PROVEN_PER_COMMAND, ControlRoomAPIError,  # noqa: E402
                                  ControlRoomAPIV1)
from bro_orchestration_runtime_v1 import DurableOrchestrationRuntimeV1  # noqa: E402
from bro_policy import CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE  # noqa: E402
from test_control_room_api import cancel_command, task_contract  # noqa: E402


class ControlRoomCommandTypeOpensNoPathTests(unittest.TestCase):
    """O-4: the owner path is closed in code, and what remains is the Owner's signature.

    These tests were written when registering `control-room-command` was a prerequisite and
    nothing consumed one, so they asserted that even a flawless artifact was refused. That was
    true then. `_prove_command_actor` now verifies the artifact and binds it to this exact
    command, and the schema carries `artifact_type` / `key_id` / `signature`, so the assertions
    were rewritten to the new truth rather than deleted — a test that pins a state which changed
    deliberately is how the old state survives in everyone's head.

    What is NOT closed: no `control-room-command` key is pinned in the shipped
    `config/trusted-keys.json`, so on a real deployment an owner command still refuses. That is
    the Owner's ceremony, not a code gap, and `test_an_unpinned_key_still_refuses` holds it.
    """

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = pathlib.Path(self.temp.name)
        self.now = int(time.time())
        self.keys = {authority: generate_key(authority, f"dev-{authority}", False)
                     for authority in (OPERATOR, "builder", CONTROL_ROOM)}
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

    def signed_command_artifact(self, command: dict,
                                authority: str = CONTROL_ROOM) -> dict:
        """A flawless `control-room-command`: real Ed25519, a `control-room` key granted
        the type by the operator-signed registry, bound to this exact command."""
        payload = {
            "artifact_type": CONTROL_ROOM_COMMAND,
            "key_id": self.keys[authority]["key_id"],
            "role": "owner",
            "agent_id": "owner-gev",
            "session_id": "s-owner",
            "command_id": command["command_id"],
            "task_id": command["task_id"],
            "command": command["command"],
            "issued_at_epoch": self.now - 10,
            "expires_at_epoch": self.now + 3600,
        }
        return sign_payload(self.keys[authority]["private_key"], payload)

    def test_the_registry_can_now_grant_the_type(self) -> None:
        # Precondition for the test below: the artifact really is verifiable here, so the
        # refusal that follows is about the consuming path, not about a broken fixture.
        command = self.owner_command()
        payload = verify_artifact(self.signed_command_artifact(command),
                                  CONTROL_ROOM_COMMAND, self.trusted, now=self.now)
        self.assertEqual(payload["command_id"], command["command_id"])

    def test_a_bound_owner_command_is_now_proven(self) -> None:
        """The closure. A flawless artifact bound to this command is accepted, and reports its
        own basis — a per-command proof, not the conductor's session."""
        command = self.owner_command()
        reply = self.api.validate_command_intent(
            command, now_epoch=self.now + 1,
            actor_attestation=self.signed_command_artifact(command))
        self.assertTrue(reply["valid"])
        self.assertEqual(reply["actor_identity"], ACTOR_PROVEN_PER_COMMAND)

    def test_the_same_artifact_cannot_be_replayed_against_another_command(self) -> None:
        """What makes it per-command rather than a session under another name."""
        signed_for = self.owner_command()
        artifact = self.signed_command_artifact(signed_for)
        other = self.owner_command()
        other["command_id"] = "cmd-a-different-one"
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(other, now_epoch=self.now + 1,
                                             actor_attestation=artifact)
        self.assertIn("different command", str(caught.exception))

    def test_an_unpinned_key_still_refuses(self) -> None:
        """The part that is the OWNER's, not the code's.

        Same artifact, same signature, same everything — but signed by a key the operator-signed
        registry does not grant `control-room-command`. It refuses. Registering the artifact type
        did not open a path; pinning a key is what opens it, and only the Owner can do that.
        """
        command = self.owner_command()
        payload = {
            "artifact_type": CONTROL_ROOM_COMMAND,
            "key_id": self.keys["builder"]["key_id"],
            "role": "owner",
            "agent_id": "owner-gev",
            "session_id": "s-owner",
            "command_id": command["command_id"],
            "task_id": command["task_id"],
            "command": command["command"],
            "issued_at_epoch": self.now - 10,
            "expires_at_epoch": self.now + 3600,
        }
        forged = sign_payload(self.keys["builder"]["private_key"], payload)
        with self.assertRaises(ControlRoomAPIError) as caught:
            self.api.validate_command_intent(command, now_epoch=self.now + 1,
                                             actor_attestation=forged)
        self.assertIn("RED", str(caught.exception))

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

    def test_the_control_room_command_schema_carries_the_signature_fields(self) -> None:
        """It asserted their ABSENCE, which was the honest state until they were added.

        `signature` is optional on purpose: a conductor-issued command carries none — it is proven
        by a separate `conductor-session` credential — so requiring it here would have made the
        schema describe only half the documents it governs. The strictness lives where it can see
        who is asking: `bro_control_room_api` refuses an OWNER command without one.
        """
        schema = json.loads(
            (ROOT / "schemas" / "control-room-command.schema.json").read_text(encoding="utf-8"))
        for field in ("artifact_type", "key_id", "signature"):
            self.assertIn(field, schema["properties"], field)
        self.assertNotIn("signature", schema["required"],
                         "a conductor command is proven by a session credential and carries none")
        self.assertEqual(schema["properties"]["artifact_type"]["const"], CONTROL_ROOM_COMMAND)
        self.assertEqual(schema["properties"]["signature"]["pattern"], "^[0-9a-f]{128}$")

