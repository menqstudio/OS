"""The live kit's ROOT TRUST ANCHOR must state its provenance (audit F-17).

The kit used to mint a root keypair, sign the production ``KeyManifest`` with it, and hand the
matching public key back to the verifier through the same ``config.json`` the verifier read its
own knobs from. That verifies perfectly and proves nothing: the kit supplied both sides of the
signature. These tests pin the two properties that make the difference visible rather than
assumed — the anchor lives in a separate TCB file that says which case it is, and the
self-certifying inline form cannot be re-expressed by editing config.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROVISION = os.path.join(REPO_ROOT, "engine", "ci", "live", "provision_keys.py")
LIVE_DIR = os.path.join(REPO_ROOT, "engine", "ci", "live")

SHA_A = "aa" * 32
SHA_B = "bb" * 32


def _read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _provision(root: str, *extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, PROVISION, "--root-dir", root,
         "--launcher-sha", SHA_A, "--executor-sha", SHA_B, *extra],
        capture_output=True, text=True,
    )


class LiveProvisioningAnchorTests(unittest.TestCase):
    def test_the_default_kit_labels_its_own_anchor_as_kit_generated(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_provision(root).returncode, 0)
            anchor = _read_json(os.path.join(root, "tcb", "root-anchor.json"))
            self.assertEqual(anchor["provenance"], "kit_generated")
            self.assertEqual(len(anchor["public_key_hex"]), 64)

    def test_the_config_cannot_carry_the_anchor_inline(self):
        # The driver refuses a config with an inline anchor, so the provisioner must not write one:
        # if both existed, "which one wins" would be a question again.
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_provision(root).returncode, 0)
            trust = _read_json(os.path.join(root, "config.json"))["trust"]
            self.assertNotIn("root_pub_hex", trust)
            self.assertNotIn("root_key_id", trust)
            self.assertTrue(trust["root_anchor_path"].endswith("root-anchor.json"))

    def test_a_partial_external_anchor_is_refused(self):
        # A public key without the manifest it signed would leave the kit signing the manifest
        # ITSELF while labelling the anchor external — strictly worse than the honest default.
        with tempfile.TemporaryDirectory() as root:
            r = _provision(root, "--root-anchor-key-id", "owner-root-1")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("external root anchor needs ALL", r.stderr)

    def test_an_empty_keys_manifest_is_now_REFUSED_where_it_used_to_be_accepted(self):
        """This was the whole of the external-mode coverage until 2026-09-20, and it proved too little.

        It signed `{"manifest_epoch":2,"root_key_id":"owner-root-1","keys":[]}` — a manifest naming NO
        keys — and asserted the anchor came out labelled `external`. That label was correct and the kit
        was unusable: at run time `live_turn.rs` refuses with `key_resolution`, because the manifest
        names none of the keys the services actually hold. A test that passes on a kit that cannot
        serve a turn is the shape this repository keeps finding.

        The same input is refused now, at provisioning time, by name. That is the change.
        """
        sys.path.insert(0, LIVE_DIR)
        import live_crypto as lc  # noqa: E402  (path-dependent import, as the live runners do)

        owner_root = lc.gen_private()
        with tempfile.TemporaryDirectory() as root:
            manifest_bytes = b'{"manifest_epoch":2,"root_key_id":"owner-root-1","keys":[]}'
            m_path = os.path.join(root, "external-manifest.json")
            s_path = os.path.join(root, "external-manifest.sig")
            with open(m_path, "wb") as f:
                f.write(manifest_bytes)
            with open(s_path, "w", encoding="utf-8") as f:
                f.write(lc.sign_b64std(owner_root, manifest_bytes))

            # Phase 1 first, so the failure is about the manifest's CONTENTS and not about --keys-in.
            r = _provision(root, "--emit-manifest", os.path.join(root, "phase1.json"))
            self.assertEqual(r.returncode, 0, r.stderr)

            r = _provision(
                root,
                "--keys-in", os.path.join(root, "keys"),
                "--root-anchor-key-id", "owner-root-1",
                "--root-anchor-pub-hex", lc.pub_hex(owner_root),
                "--manifest-in", m_path,
                "--manifest-sig-in", s_path,
            )
            self.assertEqual(r.returncode, 4, r.stderr)
            self.assertIn("does not name the serving key", r.stderr)
            self.assertIn("no public keys at all", r.stderr)
            # And nothing was written: a refusal must not leave a half-provisioned kit behind.
            self.assertFalse(os.path.exists(os.path.join(root, "config.json")))


class TwoPhaseExternalRootCeremonyTests(unittest.TestCase):
    """The ceremony that makes `trusted_verified` reachable on Linux at all.

    Until 2026-09-20 it was unreachable BY CONSTRUCTION, and the measurement is three lines long:
    `provision_keys.py` minted the signer and supervisor-attestation keys fresh on every invocation;
    `build_manifest_bytes(signer_pub_hex, sup_pub_hex)` proves the manifest must NAME those two public
    hexes; and external mode consumed a pre-signed manifest verbatim. An offline signature therefore had
    to name keys that did not exist when it was made. There was no `--emit-manifest`, no `--keys-in`.

    Phase 1 mints and emits. The Owner signs those bytes offline with `sign_manifest.py`. Phase 2
    reuses the SAME keys and refuses unless the signature verifies AND the signed manifest names them.

    Nothing here needs root, a socket, or a service account: it is the provisioning arithmetic, which is
    the half a test on this box can reach.
    """

    def setUp(self):
        sys.path.insert(0, LIVE_DIR)
        import live_crypto as lc  # noqa: E402
        self.lc = lc
        box = tempfile.TemporaryDirectory(prefix="ceremony-")
        self.addCleanup(box.cleanup)
        self.box = box.name
        self.kit = os.path.join(self.box, "live")
        self.manifest = os.path.join(self.box, "offline", "manifest.json")
        self.sig = os.path.join(self.box, "offline", "manifest.sig")

    # ---- helpers ---------------------------------------------------------------------------------

    def _phase1(self, *extra):
        return _provision(self.kit, "--emit-manifest", self.manifest, *extra)

    def _sign(self, root_key, *extra):
        seed = os.path.join(self.box, "root.private.seed")
        with open(seed, "wb") as f:
            f.write(self.lc.priv_raw(root_key))
        return subprocess.run(
            [sys.executable, os.path.join(LIVE_DIR, "sign_manifest.py"),
             "--manifest", self.manifest, "--root-seed", seed, "--sig-out", self.sig, *extra],
            capture_output=True, text=True), seed

    def _phase2(self, root_key, *extra):
        return _provision(
            self.kit,
            "--keys-in", os.path.join(self.kit, "keys"),
            "--root-anchor-key-id", "owner-root-1",
            "--root-anchor-pub-hex", self.lc.pub_hex(root_key),
            "--manifest-in", self.manifest,
            "--manifest-sig-in", self.sig,
            *extra)

    # ---- the property that was unreachable -------------------------------------------------------

    def test_the_whole_ceremony_reaches_an_external_anchor_over_the_kits_own_keys(self):
        root_key = self.lc.gen_private()
        self.assertEqual(self._phase1().returncode, 0)
        phase1_signer = self._pub("signer")
        phase1_sup = self._pub("supervisor_attest")

        signed, _ = self._sign(root_key, "--expect-pub", self.lc.pub_hex(root_key))
        self.assertEqual(signed.returncode, 0, signed.stderr)

        r = self._phase2(root_key)
        self.assertEqual(r.returncode, 0, r.stderr)

        anchor = _read_json(os.path.join(self.kit, "tcb", "root-anchor.json"))
        self.assertEqual(anchor["provenance"], "external")
        self.assertEqual(anchor["public_key_hex"], self.lc.pub_hex(root_key))
        # The keys did NOT move between the phases — that is what `--keys-in` is for, and it is the
        # difference between a signature that names the serving keys and one that cannot.
        self.assertEqual(self._pub("signer"), phase1_signer)
        self.assertEqual(self._pub("supervisor_attest"), phase1_sup)
        # Served verbatim: the kit must not rebuild a manifest it cannot re-sign.
        with open(os.path.join(self.kit, "manifest.json"), "rb") as f:
            with open(self.manifest, "rb") as g:
                self.assertEqual(f.read(), g.read())

    def _pub(self, name):
        with open(os.path.join(self.kit, "keys", name + ".pub.hex"), "r", encoding="ascii") as f:
            return f.read().strip()

    # ---- no root private on the serving box, in either phase -------------------------------------

    def test_neither_phase_writes_a_root_private_key_onto_the_serving_box(self):
        """This used to be written unconditionally. `root_key = lc.gen_private()` ran in BOTH modes and
        `keys/root.priv` was written in both — in the one mode whose entire purpose is that the root
        private never touches this machine."""
        root_key = self.lc.gen_private()
        self.assertEqual(self._phase1().returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.kit, "keys", "root.priv")),
                         "phase 1 must not write a root private key")
        self._sign(root_key)
        self.assertEqual(self._phase2(root_key).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.kit, "keys", "root.priv")),
                         "phase 2 must not write a root private key")

    def test_the_kit_generated_mode_still_writes_its_own_root_because_it_signs(self):
        """The honest default. It mints a root ON the serving box and self-signs, which is exactly why
        `run_ladder_turn.sh` records that a `kit_generated` anchor may never render
        `production_verified=true`. Removing that would break the mode; the change is that it is no
        longer done in the mode that does not sign."""
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(_provision(root).returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(root, "keys", "root.priv")))
            self.assertEqual(
                _read_json(os.path.join(root, "tcb", "root-anchor.json"))["provenance"],
                "kit_generated")

    # ---- phase 1 stops before it can write half a kit ---------------------------------------------

    def test_phase_1_writes_no_config_and_no_floor(self):
        self.assertEqual(self._phase1().returncode, 0)
        for absent in ("config.json", "floor.json", "manifest.json", "manifest.sig"):
            self.assertFalse(os.path.exists(os.path.join(self.kit, absent)),
                             f"phase 1 must not write {absent}")
        self.assertTrue(os.path.exists(self.manifest), "phase 1 must emit the bytes to sign")

    def test_phase_1_emits_the_bytes_the_broker_will_verify_over_the_keys_it_minted(self):
        self.assertEqual(self._phase1().returncode, 0)
        with open(self.manifest, "rb") as f:
            named = {k["public_key_hex"] for k in json.loads(f.read().decode("utf-8"))["keys"]}
        self.assertIn(self._pub("signer"), named)
        self.assertIn(self._pub("supervisor_attest"), named)

    # ---- the four refusals -------------------------------------------------------------------------

    def test_an_external_anchor_without_keys_in_is_refused_with_the_reason(self):
        """The ordering impossibility, refused at the door instead of at run time."""
        root_key = self.lc.gen_private()
        self.assertEqual(self._phase1().returncode, 0)
        self._sign(root_key)
        r = _provision(
            self.kit,
            "--root-anchor-key-id", "owner-root-1",
            "--root-anchor-pub-hex", self.lc.pub_hex(root_key),
            "--manifest-in", self.manifest, "--manifest-sig-in", self.sig)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("needs --keys-in", r.stderr)

    def test_a_signature_from_a_DIFFERENT_root_is_refused_and_nothing_is_written(self):
        """Before this, external mode checked only that two files existed. A typo in the anchor hex
        produced a kit that looked provisioned and failed later as a stream reason."""
        root_key, impostor = self.lc.gen_private(), self.lc.gen_private()
        self.assertEqual(self._phase1().returncode, 0)
        self._sign(impostor)                              # signed by the wrong root
        r = self._phase2(root_key)                        # ...but claiming the right one
        self.assertEqual(r.returncode, 3, r.stderr)
        self.assertIn("does not verify", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.kit, "config.json")))

    def test_a_VALID_signature_over_a_manifest_about_other_keys_is_refused(self):
        """The check the ordering impossibility hid. A perfectly good signature over a manifest naming
        somebody else's keys is exactly what the old code accepted."""
        root_key = self.lc.gen_private()
        self.assertEqual(self._phase1().returncode, 0)
        # A second kit's keys, signed correctly — valid signature, wrong subject.
        other_kit = os.path.join(self.box, "other")
        other_manifest = os.path.join(self.box, "other.json")
        self.assertEqual(_provision(other_kit, "--emit-manifest", other_manifest).returncode, 0)
        with open(other_manifest, "rb") as f:
            foreign = f.read()
        with open(self.manifest, "wb") as f:
            f.write(foreign)
        self._sign(root_key)
        r = self._phase2(root_key)
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("does not name the serving key", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.kit, "config.json")))

    def test_phase_1_refuses_the_anchor_flags_and_refuses_keys_in(self):
        root_key = self.lc.gen_private()
        self.assertEqual(self._phase1().returncode, 0)
        self._sign(root_key)
        r = self._phase1("--root-anchor-key-id", "owner-root-1",
                         "--root-anchor-pub-hex", self.lc.pub_hex(root_key),
                         "--manifest-in", self.manifest, "--manifest-sig-in", self.sig)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("PHASE 1 and takes no anchor flags", r.stderr)
        r = self._phase1("--keys-in", os.path.join(self.kit, "keys"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MINTS the serving keys", r.stderr)

    def test_keys_in_pointing_at_nothing_says_so_rather_than_minting_quietly(self):
        """The failure mode that would undo the whole change: silently minting fresh keys when the
        reuse target is missing would put us back where we started, with a green run."""
        root_key = self.lc.gen_private()
        self.assertEqual(self._phase1().returncode, 0)
        self._sign(root_key)
        r = _provision(
            self.kit,
            "--keys-in", os.path.join(self.box, "no-such-directory"),
            "--root-anchor-key-id", "owner-root-1",
            "--root-anchor-pub-hex", self.lc.pub_hex(root_key),
            "--manifest-in", self.manifest, "--manifest-sig-in", self.sig)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot read", r.stderr)


LADDER = os.path.join(LIVE_DIR, "provision_ladder.py")
LADDER_UIDS = ("--sidecar-uid", "5101", "--supervisor-uid", "5102", "--broker-uid", "5103",
               "--recorder-user", "brops-recorder")


class LadderRegistryExternalRootTests(unittest.TestCase):
    """The ladder kit's root signs TWO things, and the ceremony signed one (T-126).

    `run_ladder_turn.sh` runs `provision_ladder.py` after `provision_keys.py`, and it signed the §4.2
    challenge-key registry with `keys/root.priv` — a file external mode does not write. So a kit whose
    key manifest the Owner's offline root had signed crashed provisioning on a missing file, and the
    only way to make it provision would have been to let the kit sign its own registry under a root
    it does not hold. Phase 1 now also emits the registry payload; the Owner signs it with the same
    `sign_manifest.py`; phase 2 verifies it under the external anchor and refuses before writing.
    """

    def setUp(self):
        sys.path.insert(0, LIVE_DIR)
        import live_crypto as lc  # noqa: E402
        self.lc = lc
        box = tempfile.TemporaryDirectory(prefix="ladder-ceremony-")
        self.addCleanup(box.cleanup)
        self.box = box.name
        self.kit = os.path.join(self.box, "live")
        self.off = os.path.join(self.box, "offline")
        os.makedirs(self.off)
        self.root_key = lc.gen_private()
        self.seed = os.path.join(self.off, "root.private.seed")
        with open(self.seed, "w", encoding="ascii") as f:
            f.write(lc.priv_raw(self.root_key).hex())

    def _run(self, *argv):
        return subprocess.run([sys.executable, *argv], capture_output=True, text=True)

    def _sign(self, message, sig):
        r = self._run(os.path.join(LIVE_DIR, "sign_manifest.py"), "--manifest", message,
                      "--root-seed", self.seed, "--sig-out", sig,
                      "--expect-pub", self.lc.pub_hex(self.root_key))
        self.assertEqual(r.returncode, 0, r.stderr)

    def _external_kit(self):
        """Both phases of provision_keys plus the registry emission; returns the registry sig path."""
        manifest = os.path.join(self.off, "manifest.json")
        registry = os.path.join(self.off, "registry.bytes")
        self.assertEqual(_provision(self.kit, "--emit-manifest", manifest).returncode, 0)
        r = self._run(LADDER, "--root-dir", self.kit, "--emit-registry", registry,
                      "--keys-in", os.path.join(self.kit, "keys"),
                      "--root-key-id", "brops-tcb-root-1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self._sign(manifest, os.path.join(self.off, "manifest.sig"))
        self._sign(registry, os.path.join(self.off, "registry.sig"))
        r = _provision(self.kit, "--keys-in", os.path.join(self.kit, "keys"),
                       "--root-anchor-key-id", "brops-tcb-root-1",
                       "--root-anchor-pub-hex", self.lc.pub_hex(self.root_key),
                       "--manifest-in", manifest,
                       "--manifest-sig-in", os.path.join(self.off, "manifest.sig"))
        self.assertEqual(r.returncode, 0, r.stderr)
        return os.path.join(self.off, "registry.sig")

    def _registry_verifies_under(self, pub_hex):
        sys.path.insert(0, os.path.join(REPO_ROOT, "engine", "runtime"))
        import challenge_key_registry as ckr  # noqa: E402
        doc = _read_json(os.path.join(self.kit, "tcb", "challenge-key-registry.json"))
        return self.lc.verify_b64url(self.lc.load_public_hex(pub_hex),
                                     ckr.canonical_bytes(doc["payload"]), doc["root_sig"])

    def test_the_offline_signature_becomes_the_registry_and_no_root_private_is_read(self):
        sig = self._external_kit()
        r = self._run(LADDER, "--root-dir", self.kit, *LADDER_UIDS, "--registry-sig-in", sig)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self._registry_verifies_under(self.lc.pub_hex(self.root_key)))
        self.assertFalse(os.path.exists(os.path.join(self.kit, "keys", "root.priv")))
        ladder = _read_json(os.path.join(self.kit, "tcb", "ladder.json"))
        self.assertEqual(ladder["registry"]["root_key_id"], "brops-tcb-root-1")

    def test_an_external_anchor_without_the_registry_signature_writes_nothing(self):
        self._external_kit()
        before = open(os.path.join(self.kit, "config.json"), "rb").read()
        r = self._run(LADDER, "--root-dir", self.kit, *LADDER_UIDS)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("must be signed by that root", r.stderr)
        self.assertEqual(open(os.path.join(self.kit, "config.json"), "rb").read(), before)
        self.assertFalse(os.path.exists(os.path.join(self.kit, "tcb", "ladder.json")))
        self.assertFalse(os.path.exists(os.path.join(self.kit, "tcb", "challenge-key-registry.json")))

    def test_a_valid_root_signature_over_OTHER_bytes_is_refused(self):
        # The manifest signature is a perfectly good signature by the right root — over the wrong
        # message. It must not pass as the registry's.
        self._external_kit()
        r = self._run(LADDER, "--root-dir", self.kit, *LADDER_UIDS,
                      "--registry-sig-in", os.path.join(self.off, "manifest.sig"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not verify", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.kit, "tcb", "ladder.json")))

    def test_the_kit_generated_mode_still_signs_its_own_registry_and_refuses_a_supplied_one(self):
        self.assertEqual(_provision(self.kit).returncode, 0)
        refused = self._run(LADDER, "--root-dir", self.kit, *LADDER_UIDS,
                            "--registry-sig-in", os.path.join(self.off, "nope.sig"))
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not external", refused.stderr)
        r = self._run(LADDER, "--root-dir", self.kit, *LADDER_UIDS)
        self.assertEqual(r.returncode, 0, r.stderr)
        anchor = _read_json(os.path.join(self.kit, "tcb", "root-anchor.json"))
        self.assertEqual(anchor["provenance"], "kit_generated")
        self.assertTrue(self._registry_verifies_under(anchor["public_key_hex"]))


class OfflineManifestSignerTests(unittest.TestCase):
    """`sign_manifest.py` — the tool the Linux path had a specification for and no implementation of.

    The Builder never generates, reads, holds or transports a production root private half. This tool
    reads a seed the OWNER already has, on a machine the Owner controls. What is tested here is that it
    refuses every way of getting it wrong, and that it never puts the private half anywhere.
    """

    def setUp(self):
        sys.path.insert(0, LIVE_DIR)
        import live_crypto as lc  # noqa: E402
        self.lc = lc
        box = tempfile.TemporaryDirectory(prefix="signer-")
        self.addCleanup(box.cleanup)
        self.box = box.name
        self.manifest = os.path.join(self.box, "m.json")
        with open(self.manifest, "wb") as f:
            f.write(b'{"manifest_epoch":2,"root_key_id":"owner-root-1","keys":[]}')

    def _run(self, *extra):
        return subprocess.run(
            [sys.executable, os.path.join(LIVE_DIR, "sign_manifest.py"), *extra],
            capture_output=True, text=True)

    def _seed(self, data: bytes) -> str:
        path = os.path.join(self.box, "seed")
        with open(path, "wb") as f:
            f.write(data)
        return path

    def test_it_signs_the_seed_file_win_gen_root_actually_writes(self):
        """`win_gen_root` writes 64 lowercase hex characters. This tool accepted only 32 raw bytes and
        told the Owner `win_gen_root` wrote those — so the two Owner tools could not be chained
        (measured 2026-09-30, exit 3). Mutant: drop the hex branch and this goes red."""
        root = self.lc.gen_private()
        hex_seed = self.lc.priv_raw(root).hex().encode("ascii")
        for label, data in (("as written", hex_seed), ("editor newline", hex_seed + b"\n")):
            with self.subTest(label):
                out = os.path.join(self.box, "m-%d.sig" % len(data))
                r = self._run("--manifest", self.manifest, "--root-seed", self._seed(data),
                              "--sig-out", out, "--expect-pub", self.lc.pub_hex(root))
                self.assertEqual(r.returncode, 0, r.stderr)
                with open(out, "r", encoding="utf-8") as f:
                    sig = f.read().strip()
                with open(self.manifest, "rb") as f:
                    message = f.read()
                self.assertTrue(self.lc.verify_b64std(
                    self.lc.load_public_hex(self.lc.pub_hex(root)), message, sig))

    def test_a_seed_file_that_is_neither_shape_is_refused(self):
        hex_seed = self.lc.priv_raw(self.lc.gen_private()).hex()
        for label, data in (("63 hex", hex_seed[:-1].encode()), ("uppercase", hex_seed.upper().encode()),
                            ("two newlines", hex_seed.encode() + b"\n\n"), ("31 raw", b"x" * 31),
                            ("not hex", b"g" * 64)):
            with self.subTest(label):
                r = self._run("--manifest", self.manifest, "--root-seed", self._seed(data))
                self.assertEqual(r.returncode, 3, r.stderr)
                self.assertNotIn(hex_seed, r.stdout + r.stderr, "the seed was echoed")

    def test_it_signs_and_the_signature_verifies_under_the_derived_public(self):
        root = self.lc.gen_private()
        out = os.path.join(self.box, "m.sig")
        r = self._run("--manifest", self.manifest, "--root-seed",
                      self._seed(self.lc.priv_raw(root)), "--sig-out", out)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, "r", encoding="utf-8") as f:
            sig = f.read().strip()
        with open(self.manifest, "rb") as f:
            self.assertTrue(self.lc.verify_b64std(
                self.lc.load_public_hex(self.lc.pub_hex(root)), f.read(), sig))

    def test_it_prints_the_derived_public_and_never_the_private(self):
        root = self.lc.gen_private()
        raw = self.lc.priv_raw(root)
        r = self._run("--manifest", self.manifest, "--root-seed", self._seed(raw))
        self.assertEqual(r.returncode, 0, r.stderr)
        both = r.stdout + r.stderr
        self.assertIn(self.lc.pub_hex(root), both, "the Owner has to be able to check it against the pin")
        self.assertNotIn(raw.hex(), both, "the private half must never be printed")
        self.assertNotIn(raw.hex().upper(), both)

    def test_a_seed_that_is_not_32_bytes_is_refused_and_its_bytes_are_not_echoed(self):
        for length in (0, 31, 33, 64):
            with self.subTest(length=length):
                raw = b"\x5a" * length
                r = self._run("--manifest", self.manifest, "--root-seed", self._seed(raw))
                self.assertNotEqual(r.returncode, 0)
                if length:
                    self.assertNotIn(raw.hex(), r.stdout + r.stderr)

    def test_the_wrong_seed_file_is_caught_by_expect_pub(self):
        root, other = self.lc.gen_private(), self.lc.gen_private()
        r = self._run("--manifest", self.manifest, "--root-seed",
                      self._seed(self.lc.priv_raw(root)),
                      "--expect-pub", self.lc.pub_hex(other))
        self.assertEqual(r.returncode, 4, r.stderr)
        self.assertIn("not the --expect-pub", r.stderr)

    def test_an_empty_manifest_is_refused_rather_than_signed(self):
        empty = os.path.join(self.box, "empty.json")
        open(empty, "wb").close()
        r = self._run("--manifest", empty, "--root-seed",
                      self._seed(self.lc.priv_raw(self.lc.gen_private())))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("nothing to sign", r.stderr)

    def test_a_refusal_writes_no_signature_file(self):
        out = os.path.join(self.box, "never.sig")
        r = self._run("--manifest", self.manifest, "--root-seed", self._seed(b"\x01" * 31),
                      "--sig-out", out)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse(os.path.exists(out))



class ExternalAnchorPassthroughTests(unittest.TestCase):
    """`run_live_turn.sh` can now pass the anchor it has always described.

    Its F-17 note told the reader to "Re-provision with --root-anchor-key-id/--root-anchor-pub-hex plus
    the externally-signed manifest" for as long as the note existed, while its one `provision_keys.py`
    call site carried five arguments and none of those flags. The instruction named an outcome no
    command in the tree could reach.

    This script cannot RUN here — it needs root, seven accounts and a setuid launcher — and it is the
    one required context `Linux · LIVE 7-service governed turn` executes, so a broken edit blocks every
    merge. What a test on this box can do is prove the script still PARSES and that the wiring is
    all-or-none, which is where the danger is: four flags without `--keys-in` provisions fresh keys the
    signed manifest cannot name.
    """

    LIVE_SH = os.path.join(os.path.dirname(LIVE_DIR), "live")

    def _script(self) -> str:
        with open(os.path.join(LIVE_DIR, "run_live_turn.sh"), "r", encoding="utf-8") as f:
            return f.read()

    def test_every_live_shell_script_parses(self):
        """The syntax gate this tree did not have. `bash -n` costs milliseconds and is the only thing
        on this box that can tell a broken orchestrator from a working one before Linux CI does."""
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash on this host, so syntax cannot be checked here")
        scripts = sorted(f for f in os.listdir(LIVE_DIR) if f.endswith(".sh"))
        self.assertGreaterEqual(len(scripts), 2, scripts)
        for name in scripts:
            with self.subTest(script=name):
                r = subprocess.run([bash, "-n", os.path.join(LIVE_DIR, name)],
                                   capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, f"{name}: {r.stderr}")

    def test_the_provision_call_site_forwards_the_anchor_arguments(self):
        invocation = [l for l in self._script().splitlines() if "ANCHOR_ARGS[@]" in l]
        self.assertTrue(invocation, "the call site forwards nothing, so the flags cannot arrive")
        # The `+` form, because `set -u` is in force (run_live_turn.sh:18) and an empty array under
        # older bash would abort the run before it provisioned anything.
        self.assertIn('${ANCHOR_ARGS[@]+"${ANCHOR_ARGS[@]}"}', self._script())

    def test_the_five_variables_are_all_or_none(self):
        script = self._script()
        for var in ("BROPS_KEYS_IN", "BROPS_ROOT_ANCHOR_KEY_ID", "BROPS_ROOT_ANCHOR_PUB_HEX",
                    "BROPS_MANIFEST_IN", "BROPS_MANIFEST_SIG_IN"):
            with self.subTest(var=var):
                self.assertIn(var, script)
        self.assertIn("needs ALL of", script)

    def _anchor_block(self) -> str:
        """The block AS IT IS IN THE SCRIPT, not a copy of it.

        The first version of this test inlined its own copy of the logic and ran that. It passed while
        a mutant that made the script accept a PARTIAL set survived untouched — the test was asserting
        about a duplicate, which is the exact defect this repository has spent a week removing. The
        block is extracted from the real file now, so an edit to the script is an edit to what runs
        here.
        """
        script = self._script()
        first = script.index('ANCHOR_VARS="BROPS_KEYS_IN')
        last = script.index("# ----- keys + manifest + store + shared config", first)
        return script[first:last]

    def test_the_all_or_none_logic_actually_refuses_a_partial_set(self):
        """The script's own bytes, run under a real bash. A partial set must refuse; the full set must
        pass; and unset must add NOTHING, because this script is a required context and the default
        path has to stay byte-identical."""
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash on this host")
        block = "\n".join(["set -u", self._anchor_block(), 'echo "COUNT=${#ANCHOR_ARGS[@]}"'])
        full = {"BROPS_KEYS_IN": "/k", "BROPS_ROOT_ANCHOR_KEY_ID": "id1",
                "BROPS_ROOT_ANCHOR_PUB_HEX": "ab" * 32,
                "BROPS_MANIFEST_IN": "/m", "BROPS_MANIFEST_SIG_IN": "/s"}

        def run(env_extra):
            env = {k: v for k, v in os.environ.items() if not k.startswith("BROPS_")}
            env.update(env_extra)
            return subprocess.run([bash, "-c", block], capture_output=True, text=True, env=env)

        unset = run({})
        self.assertEqual(unset.returncode, 0, unset.stderr)
        self.assertIn("COUNT=0", unset.stdout,
                      "with nothing set the invocation must be the one it has always been")

        complete = run(full)
        self.assertEqual(complete.returncode, 0, complete.stderr)
        self.assertIn("COUNT=10", complete.stdout, "five flags and five values")

        for missing in sorted(full):
            with self.subTest(missing=missing):
                partial = run({k: v for k, v in full.items() if k != missing})
                self.assertEqual(partial.returncode, 1,
                                 f"a set missing {missing} must refuse: {partial.stdout}")
                self.assertIn("needs ALL of", partial.stdout + partial.stderr)

    def test_the_note_no_longer_promises_what_nothing_could_do(self):
        script = self._script()
        self.assertIn("THAT IS NOW REACHABLE FROM HERE", script)
        self.assertIn("sign_manifest.py", script,
                      "the note has to name the command that produces the signature")

class LadderKitAnchorPassthroughTests(unittest.TestCase):
    """`run_ladder_turn.sh` — the kit that starts the real `brops-broker` — takes the external anchor.

    It read none of the five variables until T-126, and it needs a SIXTH: the ladder kit's root also
    signs the §4.2 registry. Every assertion runs the script's own bytes or reads its own text.
    """

    SIX = {"BROPS_KEYS_IN": "/k", "BROPS_ROOT_ANCHOR_KEY_ID": "brops-tcb-root-1",
           "BROPS_ROOT_ANCHOR_PUB_HEX": "ab" * 32, "BROPS_MANIFEST_IN": "/m",
           "BROPS_MANIFEST_SIG_IN": "/s", "BROPS_REGISTRY_SIG_IN": "/r"}

    def _script(self) -> str:
        with open(os.path.join(LIVE_DIR, "run_ladder_turn.sh"), "r", encoding="utf-8") as f:
            return f.read()

    def _block(self) -> str:
        script = self._script()
        first = script.index('ANCHOR_VARS="BROPS_KEYS_IN')
        last = script.index("# ----- keys + manifest + store + shared config", first)
        return script[first:last]

    def _run(self, env_extra):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash on this host")
        block = "\n".join(["set -u", self._block(),
                           'echo "COUNT=${#ANCHOR_ARGS[@]} LADDER=${#LADDER_ANCHOR_ARGS[@]} '
                           'MODE=$ANCHOR_MODE"'])
        env = {k: v for k, v in os.environ.items() if not k.startswith("BROPS_")}
        env.update(env_extra)
        return subprocess.run([bash, "-c", block], capture_output=True, text=True, env=env)

    def test_unset_changes_nothing_and_stays_kit_generated(self):
        r = self._run({})
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("COUNT=0 LADDER=0 MODE=kit_generated", r.stdout)

    def test_all_six_forward_to_both_provisioners(self):
        r = self._run(self.SIX)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("COUNT=10 LADDER=2 MODE=external", r.stdout)

    def test_any_five_of_six_refuse(self):
        for missing in sorted(self.SIX):
            with self.subTest(missing=missing):
                r = self._run({k: v for k, v in self.SIX.items() if k != missing})
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertIn("needs ALL of", r.stdout)

    def test_both_call_sites_forward_what_the_block_builds(self):
        script = self._script()
        self.assertIn('${ANCHOR_ARGS[@]+"${ANCHOR_ARGS[@]}"}', script)
        self.assertIn('${LADDER_ANCHOR_ARGS[@]+"${LADDER_ANCHOR_ARGS[@]}"}', script)

    def test_the_throwaway_negative_names_the_refusal_the_driver_actually_emits(self):
        # The outcome string is built from two languages: `setup_blocked` prefixes `root_anchor_`
        # to the reason `check_declared_external_anchor` returns. A rename on either side would
        # leave the kit expecting an outcome nothing produces.
        script = self._script()
        self.assertIn("blocked:setup:root_anchor_external_not_the_pinned_root", script)
        tcb = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri", "broker", "src", "tcb.rs")
        with open(tcb, "r", encoding="utf-8") as f:
            self.assertIn('Err("external_not_the_pinned_root")', f.read())
        ladder = os.path.join(REPO_ROOT, "apps", "desktop", "src-tauri", "proof", "src", "bin",
                              "ladder_turn.rs")
        with open(ladder, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("check_declared_external_anchor", text)
        self.assertIn('format!("root_anchor_{why}")', text)


class KeysInSurvivesTheWipeTests(unittest.TestCase):
    """Both kits `rm -rf /opt/brops-live` before provisioning, and `--keys-in` is read AFTER that.

    The ceremony document said `BROPS_KEYS_IN=/opt/brops-live/keys` until T-126 — the one directory
    guaranteed to be gone by the time phase 2 reads it. The kits now refuse that before the wipe.
    """

    def _guard(self, script):
        with open(os.path.join(LIVE_DIR, script), "r", encoding="utf-8") as f:
            text = f.read()
        first = text.index("# Phase 1's keys must survive the wipe below.")
        last = text.index('rm -rf "$LIVE"', first)
        return text[first:last]

    def test_a_keys_directory_the_wipe_would_delete_is_refused_in_both_kits(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("no bash on this host")
        cases = {"/opt/brops-live/keys": 1, "/opt/brops-live": 1,
                 "/opt/brops-live/../brops-live/keys": 1,
                 "/var/lib/brops-ceremony/keys": 0, "/opt/brops-live-x/keys": 0}
        for script in ("run_ladder_turn.sh", "run_live_turn.sh"):
            block = "LIVE=/opt/brops-live\n" + self._guard(script)
            for keys_in, want in cases.items():
                with self.subTest(script=script, keys_in=keys_in):
                    env = {k: v for k, v in os.environ.items() if not k.startswith("BROPS_")}
                    env["BROPS_KEYS_IN"] = keys_in
                    r = subprocess.run([bash, "-c", block], capture_output=True, text=True, env=env)
                    self.assertEqual(r.returncode, want, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
