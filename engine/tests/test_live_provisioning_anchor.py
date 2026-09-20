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


if __name__ == "__main__":
    unittest.main()
