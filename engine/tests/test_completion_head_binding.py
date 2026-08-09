"""O-5 — the evidence high-water mark must live in signed state, not only on disk.

Before this, `_check_manifest`'s strict required set carried no `evidence_head_sha256` and no
`head_sequence`, and every production entry point passed `min_head_sequence=None`. The whole
anti-rollback property therefore rested on a directory of small JSON files: the signed artifact
the builder produced said nothing at all about which evidence head it was claiming against.

These tests pin the three things that changed:

* the manifest MUST name the head it completes against, by monotonic sequence and by the digest
  of the signed head document, and both are checked against the store;
* a rollback is still caught when the floor directory is wiped and re-provisioned, because the
  recorder-signed events the builder wants to forget are still in the store and it cannot
  re-mint them;
* a high-water mark this deployment cannot establish is a REFUSAL that names the
  owner-provided key which would close it — never a silent default of zero.
"""

import json
import os
import pathlib
import shutil
import subprocess
import sys
import stat
import tempfile
import time
import unittest
import unittest.mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))

from bro_contracts import canonical_json_sha256
from broctl import build_registry, sign_payload
# EvidenceFixture carries no test methods, so importing it does not re-run another
# module's suite under this one's name.
from test_evidence_chain import YEAR, EvidenceFixture
import _self_owned_ack

TASK = {
    "task_id": "task-1",
    "agent_id": "agt-p01-r01",
    "risk": "low",
    "done_criteria": ["work recorded"],
    "verification": {"required": False, "commands": ["python -m unittest"]},
}


class HeadBindingFixture(EvidenceFixture):
    """A real signed chain plus a real trusted-key registry valid against the real clock.

    `_check_manifest` runs the manifest freshness window against `time.time()`, so the
    registry cannot be pinned at the frozen NOW the pure evidence tests use.
    """

    def setUp(self):
        super().setUp()
        real_now = int(time.time())
        self.repo = self.tmp / "repo"
        (self.repo / "config").mkdir(parents=True)
        (self.repo / "config" / "trusted-keys.json").write_text(
            json.dumps(build_registry(list(self.keys.values()), real_now - 60, YEAR)),
            encoding="utf-8")
        from bro_signature import load_trusted_keys
        self.live_keys = load_trusted_keys(self.repo)
        # `_check_verifier_receipt` reads the independence floor straight off disk.
        (self.repo / "agents").mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / "agents" / "authority-policy.json",
                    self.repo / "agents" / "authority-policy.json")

        import bro_completion
        self.completion = bro_completion

        self.provision_floor()
        # A test process is a deployment with no principal separation: it owns the floor that
        # polices it, which the R-06 custody rule refuses by default. Say so rather than
        # weaken the rule. This is load-bearing on EVERY platform now: the rule used to
        # return early unless `os.name == "posix"`, so on Windows it refused nothing and
        # this acknowledgement was decorative. `FloorCustodyTests` below pins that.
        # Through the FILE form: the raw variable is honoured only under `BRO_ENV=ci` now,
        # and a test host is not CI.
        ack = _self_owned_ack.patch(self.tmp)
        ack.start()
        self.addCleanup(ack.stop)

    # ---- fixture helpers -----------------------------------------------------------

    def provision_floor(self):
        """Bootstrap the anti-rollback floor the way a deployment deliberately would."""
        directory = self.store / "head-floor"
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "_index.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")

    def head_document(self, task_id="task-1"):
        return json.loads(
            (self.store / f"{task_id}.head.json").read_text(encoding="utf-8"))

    def binding(self, task_id="task-1"):
        document = self.head_document(task_id)
        return {
            "evidence_head_sha256": canonical_json_sha256(document),
            "head_sequence": document["payload"]["head_sequence"],
        }

    def reseal_head(self, head_sequence, task_id="task-1"):
        """Re-sign the existing head with a different ``head_sequence``.

        Every signature stays genuine — that is the point. A rollback is not forgery, it is
        re-presenting an authentic older anchor.
        """
        payload = self.head_document(task_id)["payload"]
        payload["head_sequence"] = head_sequence
        (self.store / f"{task_id}.head.json").write_text(
            json.dumps(sign_payload(self.keys["evidence-recorder"]["private_key"], payload)),
            encoding="utf-8")

    def manifest(self, *, event_ids=None, task_id="task-1", **overrides):
        ids = list(self.chain if event_ids is None else event_ids)
        now = int(time.time())
        payload = {
            "schema": 1,
            "task_id": task_id,
            "agent_id": TASK["agent_id"],
            "task_contract_sha256": canonical_json_sha256(TASK),
            "candidate_head": "a" * 40,
            "candidate_tree": "b" * 64,
            "done_criteria": [{"criterion": "work recorded", "status": "satisfied",
                               "evidence_event_ids": [ids[0]]}],
            "tests": [{"command": ["python", "-m", "unittest"], "status": "passed",
                       "evidence_event_id": ids[-1],
                       "execution_receipt_id": "rcpt-0000000000000001"}],
            "evidence_event_ids": ids,
            **self.binding(task_id),
            "open_risks": [],
            "rollback_ready": True,
            "nonce": "nonce-head-binding-0001",
            "issued_at_epoch": now,
            "expires_at_epoch": now + 3600,
        }
        payload.update(overrides)
        for key in [k for k, v in overrides.items() if v is _ABSENT]:
            payload.pop(key)
        return payload

    def check(self, manifest, task=None):
        """Run the real `_check_manifest`, with only the execution-receipt lookup stubbed.

        Receipts are a separate signed artifact with their own suite; everything this file
        is about — the shape, the head binding, the floor — runs for real.
        """
        with unittest.mock.patch.object(self.completion, "_require_signer_identity"), \
                unittest.mock.patch.object(self.completion, "_validate_execution_receipts",
                                           return_value=[]):
            return self.completion._check_manifest(
                task or TASK, TASK["agent_id"], manifest, root=self.repo, now=None,
                keys=self.live_keys, evidence_store=self.store, receipt_store=self.store,
                require_live=False)

    def refusal(self, manifest, task=None):
        from bro_completion import CompletionError
        with self.assertRaises(CompletionError) as caught:
            self.check(manifest, task)
        return str(caught.exception)


_ABSENT = object()


class ManifestRequiresTheHeadBindingTests(HeadBindingFixture):
    """The required-field half: the binding cannot be omitted or mistyped."""

    def test_a_manifest_carrying_the_binding_is_accepted(self):
        manifest, _hash, _receipts = self.check(self.manifest())
        self.assertEqual(manifest["head_sequence"], 1)

    def test_a_manifest_without_head_sequence_is_refused(self):
        message = self.refusal(self.manifest(head_sequence=_ABSENT))
        self.assertIn("invalid completion manifest shape", message)

    def test_a_manifest_without_the_evidence_head_digest_is_refused(self):
        message = self.refusal(self.manifest(evidence_head_sha256=_ABSENT))
        self.assertIn("invalid completion manifest shape", message)

    def test_a_manifest_omitting_the_binding_entirely_fails_the_shape_check(self):
        # The strict set is exact, so dropping ONE field is refused whatever the required set
        # says — the manifest simply stops matching it. Dropping BOTH is the case that
        # actually pins membership: with the fields out of the required set this manifest is
        # a perfectly well-shaped one, and the refusal has to come from somewhere else.
        message = self.refusal(
            self.manifest(head_sequence=_ABSENT, evidence_head_sha256=_ABSENT))
        self.assertIn("invalid completion manifest shape", message)

    def test_head_sequence_must_be_a_positive_integer(self):
        for bad in ("1", 0, -3, True, 1.0):
            with self.subTest(bad=bad):
                message = self.refusal(self.manifest(head_sequence=bad))
                self.assertIn("head_sequence must be a positive integer", message)

    def test_the_evidence_head_digest_must_be_a_sha256(self):
        for bad in ("not-a-digest", "A" * 64, 12, "a" * 63):
            with self.subTest(bad=bad):
                message = self.refusal(self.manifest(evidence_head_sha256=bad))
                self.assertIn("evidence_head_sha256 must be a sha256 digest", message)


class ManifestIsBoundToOneSignedHeadTests(HeadBindingFixture):
    """The binding half: the store must hold exactly the head the manifest names."""

    def test_a_manifest_naming_a_different_signed_head_is_refused(self):
        # Same sequence, different signed document: the recorder re-anchored the chain and
        # the builder is completing against the head it remembers.
        stale = self.binding()["evidence_head_sha256"]
        self.write_chain("task-1", ["work-started", "tests-passed", "tests-failed",
                                    "rolled-back", "re-anchored"])
        message = self.refusal(self.manifest(
            event_ids=[f"task-1-e{n}" for n in range(1, 6)],
            evidence_head_sha256=stale))
        self.assertIn("a different signed head", message)

    def test_a_manifest_left_behind_by_a_re_anchor_is_refused(self):
        # The store moved on to head_sequence 3; a manifest still binding 1 is not a
        # completion of the state that exists.
        self.reseal_head(3)
        message = self.refusal(self.manifest(head_sequence=1))
        self.assertIn("head_sequence 1", message)
        self.assertIn("is at 3", message)

    def test_the_verifier_receipt_inherits_the_manifest_binding(self):
        # The receipt is bound to the manifest by hash, so it must anchor at the same head
        # rather than carry a second, independently forgeable copy of the mark.
        from bro_completion import CompletionError
        manifest = self.manifest()
        receipt = {
            "schema": 1, "receipt_id": "rcpt-0000000000000002", "task_id": "task-1",
            "builder_agent_id": TASK["agent_id"], "verifier_agent_id": "agt-p01-r02",
            "verifier_role": "Independent Verifier", "independence_level": "L4",
            "task_contract_sha256": canonical_json_sha256(TASK),
            "completion_manifest_sha256": canonical_json_sha256(manifest),
            "candidate_head": "a" * 40, "candidate_tree": "b" * 64,
            "evidence_event_ids": list(self.chain), "verdict": "GREEN",
            "issued_at_epoch": manifest["issued_at_epoch"],
            "expires_at_epoch": manifest["expires_at_epoch"],
        }
        # Roll the store's head forward underneath both artifacts.
        self.reseal_head(9)
        with unittest.mock.patch.object(self.completion, "_require_signer_identity"), \
                unittest.mock.patch.object(self.completion, "validate_verifier_assignment"), \
                self.assertRaises(CompletionError) as caught:
            self.completion._check_verifier_receipt(
                dict(TASK, verification={"required": True,
                                         "verifier_agent_id": "agt-p01-r02",
                                         "verifier_role": "Independent Verifier"}),
                manifest, canonical_json_sha256(TASK), receipt,
                root=self.repo, now=None, keys=self.live_keys, evidence_store=self.store)
        self.assertIn("is at 9", str(caught.exception))


class RollbackTests(HeadBindingFixture):
    """The anti-rollback half, including with the floor deleted."""

    def advance_to(self, head_sequence):
        """Walk the deployment up to ``head_sequence`` the way a real one gets there.

        A task is first measured at the recorder's first anchor (sequence 1) and only then
        re-anchored upward; the mark is what makes the later, higher sequence establishable.
        """
        self.check(self.manifest())
        self.reseal_head(head_sequence)
        self.check(self.manifest())

    def test_a_completion_that_rolls_the_sequence_backwards_is_refused(self):
        # The attack the mark exists for: reach 5, retain the genuinely-signed head 1, and
        # re-present it later. Every signature verifies; only a mark that outlives the call
        # can see it.
        self.advance_to(5)
        self.reseal_head(1)
        message = self.refusal(self.manifest())
        self.assertIn("stale", message)

    def test_deleting_the_floor_does_not_hide_a_rolled_back_chain(self):
        # Wipe the floor AND re-provision it, which is the residual R-06 left open: a
        # deleted floor refuses, but a deleted-and-re-bootstrapped one reads as brand new.
        # The rollback is still caught, because the recorder-signed events the builder wants
        # to forget are still in the store and it cannot re-mint them against an older head.
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()
        self.assertEqual(json.loads((self.store / "head-floor" / "_index.json")
                                    .read_text(encoding="utf-8")), {"tasks": []})

        # The retained older anchor, describing only the first two events.
        self.write_head("task-1", self.event_digest(2), 2, 2, head_sequence=1)
        message = self.refusal(self.manifest(event_ids=self.chain[:2]))
        self.assertIn("the evidence store holds signed events for task-1", message)
        self.assertIn("task-1-e3", message)

    def test_a_wiped_floor_cannot_silently_re_establish_a_high_water_mark(self):
        # The other half of the same wipe: a manifest binding a re-anchored head (>1) with
        # no durable mark behind it is unprovable, so it refuses and names the owner key.
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()
        message = self.refusal(self.manifest())
        self.assertIn("cannot establish the evidence high-water mark", message)
        self.assertIn("BRO_EVIDENCE_FLOOR_ANCHOR", message)
        self.assertIn("'evidence-floor' authority", message)
        self.assertIn("deliberately NOT operator-root", message)
        self.assertIn("none is compiled in", message)

    def test_a_presented_floor_anchor_that_cannot_verify_refuses(self):
        # A presented anchor is never a fallback: one this deployment cannot verify is a
        # refusal that says what the owner must mint. `evidence-floor-anchor` is now a
        # registered artifact type (bro_signature.ARTIFACT_AUTHORITY) bound to the
        # delegated `evidence-floor` authority, so the anchor is signed here by an
        # authority that may NOT sign it — registering the type gave nobody a key, and
        # this is what that looks like from the consuming side. The matching positive
        # path, the operator-root refusal and the case where the type is registered but no
        # key is pinned for it live in test_owner_artifact_registration.py.
        from bro_completion import CompletionError
        self.advance_to(5)
        shutil.rmtree(self.store / "head-floor")
        self.provision_floor()
        anchor = self.tmp / "floor-anchor.json"
        anchor.write_text(json.dumps(sign_payload(
            self.keys["builder"]["private_key"],
            {"artifact_type": "evidence-floor-anchor",
             "key_id": self.keys["builder"]["key_id"],
             "task_id": "task-1", "head_sequence": 5})), encoding="utf-8")
        with unittest.mock.patch.dict(os.environ,
                                      {"BRO_EVIDENCE_FLOOR_ANCHOR": str(anchor)}):
            with self.assertRaises(CompletionError) as caught:
                self.check(self.manifest())
        message = str(caught.exception)
        self.assertIn("does not verify as an owner-signed evidence-floor-anchor", message)
        self.assertIn("none is compiled in", message)

    def test_a_second_signed_head_at_the_same_sequence_is_refused(self):
        # A counter that does not move is not a high-water mark. Two genuinely signed heads
        # sharing one sequence means the sequence has stopped ordering anything.
        self.check(self.manifest())
        self.write_chain("task-1", ["work-started", "tests-passed", "tests-failed",
                                    "rolled-back", "re-anchored"])
        message = self.refusal(
            self.manifest(event_ids=[f"task-1-e{n}" for n in range(1, 6)]))
        self.assertIn("changed without advancing head_sequence", message)

    def test_a_mark_that_names_no_signed_head_is_refused(self):
        # The mark points at signed bytes; a record reduced to a bare number cannot say
        # which head it measured, and a number alone is what an attacker can write.
        self.check(self.manifest())
        mark = self.store / "head-floor" / "task-1.floor.json"
        record = json.loads(mark.read_text(encoding="utf-8"))
        self.assertEqual(record["evidence_head_sha256"],
                         self.binding()["evidence_head_sha256"])
        del record["evidence_head_sha256"]
        mark.write_text(json.dumps(record), encoding="utf-8")
        message = self.refusal(self.manifest())
        self.assertIn("records no signed head digest", message)

    # ---- helper ---------------------------------------------------------------------

    def event_digest(self, position, task_id="task-1"):
        """The event hash of the chain's ``position``-th event, for a truncated head."""
        from bro_evidence import event_hash
        document = json.loads(
            (self.store / f"{task_id}-e{position}.json").read_text(encoding="utf-8"))
        return event_hash(document["payload"])


class FloorCustodyTests(unittest.TestCase):
    """R-06 custody: a floor the policed account can rewrite is not a floor.

    This lives here rather than in ``test_completion_gate`` because the floor is head-binding
    machinery — ``_head_floor_dir`` is reached only through ``_load_head_floor`` /
    ``_advance_head_floor``, which this module already drives, and because the fixture above
    depends on the acknowledgement escape these tests pin. A reader who changes one sees the
    other in the same file.

    Every test here gives the SAME verdict on Windows and POSIX. That is the whole point: the
    rule used to open with ``if not directory.exists() or os.name != "posix": return``, so on
    Windows the entire R-06 custody rule was a no-op and handed the F-13/F-14 attack its one
    required capability — write access to the evidence store — for free. Where a configuration
    genuinely cannot be built without elevation, the test SKIPS with that reason instead of
    passing on whatever the ambient account happens to be, because "it passed on my box" is
    the same defect one level up.
    """

    def setUp(self):
        import bro_completion
        self.completion = bro_completion
        self.base = pathlib.Path(
            tempfile.mkdtemp(prefix="bro-floor-custody-")).resolve()
        self.addCleanup(shutil.rmtree, self.base, ignore_errors=True)
        self.floor = self.base / "head-floor"
        self.floor.mkdir()
        if os.name == "posix":
            # `mkdir` takes 0o777 masked by the AMBIENT UMASK. On Debian's stock 0002 — the
            # default for an account whose primary group is its own — the floor comes out 0775,
            # `_refuse_self_owned_floor` refuses at its FIRST branch (group/other-writable), and
            # the branch each test below exists to pin never executes. The tests still passed on
            # a 0022 box, so this was coverage that depended on whose machine ran it.
            #
            # chmod, not a mode= argument: umask masks the argument too.
            os.chmod(self.floor, 0o700)
            mode = stat.S_IMODE(os.stat(self.floor).st_mode)
            self.assertFalse(
                mode & (stat.S_IWGRP | stat.S_IWOTH),
                f"the fixture floor is {mode:04o}; while it is group/other-writable the "
                "group-writable refusal pre-empts every branch these tests assert, and they "
                "would pass on the wrong refusal")
        # The ambient environment must not decide this. `test_orchestration_runtime` sets the
        # acknowledgement at IMPORT time, so in a single discovery process it leaks in here
        # and turns every refusal below into a silent pass — which is precisely the failure
        # mode under test, one level up. Remove it explicitly and restore on cleanup.
        env = _self_owned_ack.suppress()
        env.start()
        self.addCleanup(env.stop)

    def refusal(self, directory=None):
        with self.assertRaises(self.completion.CompletionError) as caught:
            self.completion._refuse_self_owned_floor(
                self.floor if directory is None else directory)
        return str(caught.exception)

    def test_a_floor_this_process_can_write_is_refused_on_every_platform(self):
        """The universal configuration: a directory this very process just created.

        No elevation, no second principal, nothing platform-specific to construct — which is
        exactly why the Windows early return was so expensive. The refusal must name the right
        and the principal, because a reader who hits it on their own box has to know what to
        change; asserting only "it raised" would pass against a refusal that says nothing.
        """
        message = self.refusal()
        self.assertIn(str(self.floor), message)
        self.assertIn("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", message)
        self.assertIn("polices", message)
        if os.name == "nt":
            # WHICH right and WHICH principal varies with the account (a workstation user
            # owns what it creates; an administrator's directories are owned by
            # BUILTIN\\Administrators and the grant arrives through a group ACE or a
            # privilege). Assert that a route is named, not that one particular route is.
            self.assertRegex(
                message,
                r"(granted (FILE_ADD_FILE|FILE_ADD_SUBDIRECTORY|FILE_DELETE_CHILD|DELETE|"
                r"WRITE_DAC|WRITE_OWNER) on it through .+|holds Se\w+Privilege)")
        else:
            self.assertIn("owned by the very account it polices", message)

    def test_the_acknowledgement_still_admits_a_self_owned_floor(self):
        """The escape is a deployment posture, not a test knob — and it must still work.

        Broadening WHAT counts as "the policed account can rewrite it", and extending the rule
        to a platform where it never ran, must not narrow what a site with genuinely no second
        principal can declare. Same verdict on both platforms: admitted, silently.
        """
        with _self_owned_ack.patch(self.base):
            self.completion._refuse_self_owned_floor(self.floor)  # must NOT raise

    def test_a_floor_that_does_not_exist_is_left_to_the_index_to_refuse(self):
        """Not an exemption — the refusal simply belongs to `_load_floor_index`, with the
        message that says how to bootstrap a floor deliberately. Pinned so the early return
        cannot quietly grow into "and also skip the check when convenient": the very next call
        still refuses, and it refuses for the missing floor."""
        missing = self.base / "never-provisioned"
        self.completion._refuse_self_owned_floor(missing)  # must NOT raise
        with self.assertRaises(self.completion.CompletionError) as caught:
            self.completion._load_floor_index(missing)
        self.assertIn("not provisioned", str(caught.exception))

    def test_no_platform_is_exempt_from_the_rule(self):
        """A platform this runtime cannot interrogate must REFUSE, not return.

        The defect was not "the Windows branch was wrong", it was "there was no Windows
        branch". A third platform arriving later must fail closed rather than inherit the
        same silence, so the else-branch is asserted rather than assumed.
        """
        # Patched at `bro_completion.platform_name` rather than at `os.name`, which would
        # also re-point `pathlib.Path` at the wrong flavour and fail for the wrong reason.
        with unittest.mock.patch.object(self.completion, "platform_name",
                                        lambda: "themythicalos"):
            message = self.refusal()
        self.assertIn("cannot be checked on themythicalos", message)
        self.assertIn("an unchecked floor is not a floor", message)

    # ---- Windows: the rights a DIRECTORY needs asked about ---------------------------

    @unittest.skipUnless(os.name == "nt", "Windows ACL model")
    def test_deleting_the_marks_is_a_right_the_file_list_would_have_missed(self):
        """FILE_DELETE_CHILD is the cheapest rollback and has no file analogue.

        A directory ACE carrying only FILE_DELETE_CHILD lets its holder delete every mark
        inside the floor without holding DELETE or write on any of them — the mark is not
        rewritten, it is removed, and the floor restarts at zero. Reusing the pin's FILE right
        list here would have looked correct and missed it, so both lists are asked and the
        difference is asserted.

        The descriptor is built from SDDL rather than stamped on a real directory: assigning
        an owner needs elevation, and a test that can only run elevated is a test that does
        not run.

        The owner is SYSTEM, and that is load-bearing. The first version used
        BUILTIN\\Administrators, reasoning that the old "is the owner me?" proxy would then
        answer NO. It does on an unelevated workstation, where the token carries
        Administrators DENY_ONLY. On the CI runner the token IS Administrators, so the process
        is the owner, collects the owner's implicit WRITE_DAC, and the FILE list stops being
        blind — the assertion below failed against a completely correct implementation. SYSTEM
        is never the caller on either box.
        """
        import bro_custody
        from test_signature_authority import _descriptor_from_sddl

        # Owner SYSTEM, so the old "is the owner literally me?" proxy answers NO on any token
        # this suite can run under; FILE_DELETE_CHILD granted to Authenticated Users, which
        # every token carries.
        held = _descriptor_from_sddl("O:SYG:SYD:(A;;0x00000040;;;AU)")
        directory = pathlib.Path(r"C:\nowhere\head-floor")
        grant = bro_custody.windows_rewrite_grant(
            directory, "the evidence head floor", held.descriptor, held.owner, held.dacl,
            self.completion.CompletionError,
            rights=bro_custody.WINDOWS_DIRECTORY_REWRITE_RIGHTS)
        self.assertIsNotNone(grant, "a descriptor letting this token delete the marks was "
                                    "read as un-rewritable — the refusal would not apply")
        self.assertEqual(grant[0], "FILE_DELETE_CHILD")
        self.assertIn("S-1-5-11", grant[1])  # asserted as the SID: the name is localised
        # ...and the reason the directory list exists: the file list cannot see this at all.
        self.assertIsNone(bro_custody.windows_rewrite_grant(
            directory, "the evidence head floor", held.descriptor, held.owner, held.dacl,
            self.completion.CompletionError,
            rights=bro_custody.WINDOWS_REWRITE_RIGHTS))

    @unittest.skipUnless(os.name == "nt", "Windows ACL model")
    def test_a_floor_this_token_cannot_touch_is_not_refused(self):
        """The rule must be a check, not a blanket ban.

        A floor held by a principal this process cannot impersonate is exactly the deployment
        posture R-06 asks for; if the answer were always "rewritable" the refusal would carry
        no information and every site would be pushed into the acknowledgement.
        """
        import bro_custody
        from test_signature_authority import _descriptor_from_sddl

        held = _descriptor_from_sddl("O:SYG:SYD:(A;;FA;;;SY)")
        self.assertIsNone(bro_custody.windows_rewrite_grant(
            pathlib.Path(r"C:\nowhere\head-floor"), "the evidence head floor",
            held.descriptor, held.owner, held.dacl, self.completion.CompletionError,
            rights=bro_custody.WINDOWS_DIRECTORY_REWRITE_RIGHTS))

    # ---- POSIX: the two cases the ownership proxy answered "no" to -------------------

    @unittest.skipUnless(os.name == "posix",
                         "POSIX ownership model (os.geteuid); the Windows counterpart of "
                         "both cases is the AccessCheck grant asserted above, which asks "
                         "the kernel the same question without reference to ownership")
    def test_write_permission_that_does_not_come_from_ownership_is_caught(self):
        """The root case, in the only form a test can construct without being root.

        `os.geteuid` is patched so the floor's owner is NOT this account — which is all that
        running as root changes about the first question. Everything after that is answered by
        the real kernel against the real directory: `os.access` says this process may write it
        anyway. Under the old `st_uid == os.geteuid()` proxy this configuration was silently
        exempt, and root is precisely the account for which no filesystem mark polices
        anything.
        """
        with unittest.mock.patch.object(os, "geteuid", lambda: os.stat(self.floor).st_uid + 1):
            message = self.refusal()
        self.assertIn("has write permission on it anyway", message)
        self.assertIn("delete or rewind the mark", message)
        self.assertIn("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", message)

    @unittest.skipUnless(os.name == "posix",
                         "POSIX ownership model (os.geteuid); on Windows renaming the floor "
                         "away requires DELETE on it, which the AccessCheck grant already "
                         "asks about by name")
    def test_a_floor_inside_a_writable_directory_is_caught(self):
        """The floor's own mode is irrelevant if its PARENT can be written.

        A read-only floor is one `mv` away from being an empty floor: rename it, put a fresh
        directory with an empty index in its place, and the anti-rollback mark restarts at
        zero without a single write to the floor itself. The proxy answered "not mine, and not
        writable" and let it through.
        """
        os.chmod(self.floor, 0o500)
        self.addCleanup(os.chmod, self.floor, 0o700)
        with unittest.mock.patch.object(os, "geteuid", lambda: os.stat(self.floor).st_uid + 1):
            message = self.refusal()
        self.assertIn("rename the whole floor away", message)
        self.assertIn(str(self.base), message)
        self.assertIn("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", message)


class HeadFloorConfigurationContradictionTests(unittest.TestCase):
    """**No floor directory satisfies both halves of the design.** This is a contradiction
    pinned as executable fact, NOT a regression test for a fix — there is no fix here.

    `_advance_head_floor` writes the mark **in the process the mark polices**, and any write
    failure raises. `_refuse_self_owned_floor` refuses any floor directory that process owns
    or can write. Those two requirements have no intersection:

    * a floor the builder CAN write fails custody;
    * a floor the builder CANNOT write fails the advance (creating `<task>.floor.json.tmp` and
      renaming it over the mark needs exactly the capability custody refuses);
    * so the only satisfiable posture is the acknowledgement
      (`BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE`, or the raw variable under `BRO_ENV=ci`),
      which `bro_custody` describes as short-circuiting **every rule in that module** — the
      operator-root pin, the redirected registry root, the evidence store and this floor. The
      desktop's `engine_trust::resolve` refuses to export any engine trust material at all
      while that variable is present, for exactly that reason.

    `_head_floor_dir`'s own docstring offers the escape route "a deployment that can put the
    marks under a principal the builder cannot write should do exactly that". That deployment
    cannot be configured: the builder IS the writer.

    Closing it needs a second principal to perform the write -- a floor-writer service or a
    setuid helper. **That is an Owner/Architect decision about where the write happens, not a
    patch**, so this class states the contradiction rather than hiding it: any change that claims
    to resolve it has to come here and say which posture now satisfies both rules.

    DO NOT reach for the supervisor's durable ledger. This text used to name it as a candidate,
    on the grounds that it "already holds an equivalent floor written by the supervisor uid".
    That sentence sent an agent down the route on 2026-08-10, and it is wrong on four counts,
    each of which was established by RUNNING it rather than by reading it:

    1. It measures a different number. The ledger counter is per INSTALL
       (``evidence-head-sequence.json``) and, since bb26822, deliberately an install-wide
       ceiling; this floor is per TASK, and every task's first anchor is 1. Offering two real
       signed heads -- task-1 seq 1 and task-2 seq 1 -- to the ledger refuses the second with
       ``EvidenceFork``. Routing completion there would make the SECOND task in any deployment
       permanently un-completable.
    2. It is not reachable from here. No module on the completion path imports
       ``governed_supervisor_ledger``; the DB is opened only by ``run_supervisor.py`` running as
       the supervisor account, and its only door is ``governed_supervisor_server`` -- AF_UNIX +
       SO_PEERCRED, Linux-only, allowlisting the broker uid alone, with an op set documented as
       exhaustive. Opening that sqlite file directly from here would delete the second principal
       and reproduce this exact contradiction in sqlite instead of JSON.
    3. It does not exist on Windows -- the platform the desktop ships on, and the host where
       this contradiction was proven. ``win-live/src/servers.rs`` keeps supervisor state in a
       ``Mutex<BTreeMap<..>>`` and ``complete_run`` performs no cross-run head comparison. That
       is open finding R-42.
    4. It cannot carry what this floor carries. ``evidence_head_sha256`` -- the digest of the
       signed head document, which drives the "same sequence, different signed head" refusal --
       has no column in that table, and the ``_index.json`` roster,
       ``_require_establishable_mark`` and the owner-signed ``evidence-floor-anchor`` bootstrap
       have no equivalent there at all.

    Each test asks BOTH rules of a real directory on the host running the suite. Where a
    posture cannot be constructed without elevation the test SKIPS with that reason rather
    than passing on whatever the ambient account happens to be.
    """

    DIGEST = "e" * 64

    def setUp(self):
        import bro_completion
        self.completion = bro_completion
        self.store = pathlib.Path(
            tempfile.mkdtemp(prefix="bro-floor-contradiction-")).resolve()
        self.addCleanup(shutil.rmtree, self.store, ignore_errors=True)
        self.floor = self.store / "head-floor"
        self.floor.mkdir()
        if os.name == "posix":
            os.chmod(self.floor, 0o700)  # see FloorCustodyTests.setUp on the ambient umask
        (self.floor / "_index.json").write_text(json.dumps({"tasks": []}), encoding="utf-8")
        env = unittest.mock.patch.dict(os.environ, {}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        for name in ("BRO_OPERATOR_ROOT_PIN_SELF_OWNED",
                     "BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE", "BRO_EVIDENCE_HEAD_FLOOR"):
            os.environ.pop(name, None)

    # -- the two rules, each reported as "did it refuse, and why" -----------------------

    def _custody_refusal(self):
        try:
            self.completion._refuse_self_owned_floor(self.floor)
        except self.completion.CompletionError as exc:
            return str(exc)
        return None

    def _advance_refusal(self):
        """Drive ONLY the write half: the acknowledgement is set so custody cannot be the
        thing that refuses, which is what makes this an independent measurement of the write.
        """
        with _self_owned_ack.patch(self.store):
            try:
                self.completion._advance_head_floor(self.store, "task-1", 5, self.DIGEST)
            except self.completion.CompletionError as exc:
                return str(exc)
        return None

    def _make_unwritable(self):
        """Take this process's ability to create entries in the floor away, for real.

        Returns False when the posture could not be constructed (an account that writes
        regardless — root, or a token no DENY ACE binds), so the caller skips instead of
        asserting against a directory that is still writable.
        """
        if os.name == "posix":
            os.chmod(self.floor, 0o500)
            self.addCleanup(os.chmod, self.floor, 0o700)
        elif os.name == "nt":
            domain, user = os.environ.get("USERDOMAIN"), os.environ.get("USERNAME")
            if not domain or not user:
                return False
            principal = "%s\\%s" % (domain, user)
            # WD/AD/DC: create a file, create a subdirectory, delete a child — the three
            # rights `_advance_head_floor`'s write-temp-then-rename needs.
            if subprocess.run(["icacls", str(self.floor), "/deny", principal + ":(WD,AD,DC)"],
                              capture_output=True, text=True).returncode != 0:
                return False
            self.addCleanup(lambda: subprocess.run(
                ["icacls", str(self.floor), "/remove:d", principal],
                capture_output=True, text=True))
        else:
            return False
        probe = self.floor / "writability-probe"
        try:
            probe.write_text("x", encoding="utf-8")
        except OSError:
            return True
        probe.unlink()
        return False

    # -- the postures -------------------------------------------------------------------

    def test_a_floor_the_builder_can_write_is_refused_by_custody(self):
        message = self._custody_refusal()
        self.assertIsNotNone(message, "a self-owned floor was admitted")
        self.assertIn("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", message)
        # ...and it is exactly the posture in which the write half works.
        self.assertIsNone(self._advance_refusal())
        self.assertTrue((self.floor / "task-1.floor.json").exists())

    def test_a_floor_the_builder_cannot_write_cannot_be_advanced(self):
        if not self._make_unwritable():
            self.skipTest("this account writes the floor regardless (root, or a token no DENY "
                          "ACE binds), so the un-writable posture cannot be constructed here")
        message = self._advance_refusal()
        self.assertIsNotNone(
            message, "the mark was written to a directory this process cannot write")
        self.assertIn("cannot record the evidence head floor for task-1", message)

    def test_no_posture_satisfies_both_rules_without_the_acknowledgement(self):
        """THE contradiction. Both reachable postures, both rules, one verdict each."""
        self.assertIsNotNone(self._custody_refusal(), "posture 1 (writable) passed custody")
        self.assertIsNone(self._advance_refusal(), "posture 1 (writable) failed the write")
        (self.floor / "task-1.floor.json").unlink()

        if not self._make_unwritable():
            self.skipTest("the un-writable posture cannot be constructed under this account")
        self.assertIsNotNone(self._advance_refusal(), "posture 2 (un-writable) wrote the mark")
        # Custody on posture 2 is deliberately not asserted: on Windows this process still
        # OWNS the directory, so it holds WRITE_DAC and custody refuses that posture as well —
        # i.e. on this platform NEITHER posture passes both rules, the contradiction in its
        # strongest form. On POSIX a floor owned by a second principal would pass custody and
        # still fail the write, the contradiction in its weakest form. Either way, no posture
        # passes both.

    def test_the_only_satisfiable_posture_disables_every_custody_rule(self):
        import bro_custody
        with _self_owned_ack.patch(self.store):
            self.completion._refuse_self_owned_floor(self.floor)      # custody: admitted
            self.completion._advance_head_floor(                      # write: succeeds
                self.store, "task-1", 5, self.DIGEST)
            # The price. This is not a floor-scoped knob: the same predicate short-circuits
            # the operator-root pin, the redirected registry root and the evidence store.
            self.assertTrue(bro_custody.self_owned_acknowledged())
        self.assertTrue((self.floor / "task-1.floor.json").exists())
        self.assertFalse(bro_custody.self_owned_acknowledged())


if __name__ == "__main__":
    unittest.main()
