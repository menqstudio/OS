"""Self-tests for `check_root_anchor_custody.py` — one case per rule, plus this repository today.

A gate whose RED path has never run is a control whose failure prevents nothing, so each case here drives
ONE rule and asserts WHICH rules fired rather than only that the exit code was 1. A case that reddens for
the wrong reason is then visible instead of counted as a pass.

Every case builds a throwaway git tree in a tempdir. None of them mutates this repository: a self-test
that edits `tcb.rs` and restores it is one interrupted run away from leaving a forged anchor behind.

The seed/public pairs below are literals rather than computed, so these tests need no crypto library of
their own — only the gate does, and one case asserts what it does when that is missing.
"""

import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
GATE = ROOT / "tools" / "check_root_anchor_custody.py"

# Ed25519 seed -> public, fixed pairs. Verified against `cryptography` when it is importable (see
# `TheFixturesThemselves`), so a wrong constant here fails loudly instead of weakening every case.
SEED_A = "7e" * 32
PUB_A = "51bfae7fa92c515512cd3ad442760e41612e59dfec3913f670b721c04255b068"
SEED_B = "3f" * 32
PUB_B = "3f0dda81e6abbcc5f17c359df8517177769d2dfff3d4ce942e7ce9a82dfb0db2"
# A public half whose seed is NOT written anywhere below: the shape a real production anchor has.
PUB_OFFLINE = "3c83c2bc0e72c068824e2eebf663b6ed4cda337ff806c0b46e534aee19da0df5"

TCB_TEMPLATE = '''//! A throwaway anchor file.
pub const ROOT_KEY_ID: &str = "brops-tcb-root-1";
pub const {prod_const}: &str =
    "{prod}";
pub const DEMO_ROOT_KEY_ID: &str = "brops-tcb-demo-root-1";
pub const DEMO_ROOT_PUBLIC_KEY_HEX: &str =
    "{demo}";
'''

TCB_PATHS = (
    "apps/desktop/src-tauri/broker/src/tcb.rs",
    "apps/desktop/src-tauri/win-live/src/tcb.rs",
)


def _rules(text: str) -> list[int]:
    """Which of the gate's five rules the output names, by the phrase each is stated in."""
    fired = []
    if "no `pub const" in text or "absent, but this gate" in text:
        fired.append(1)
    if "the SAME key" in text:
        fired.append(2)
    if "IS the PRODUCTION anchor pinned by" in text:
        fired.append(3)
    if "was NOT found by the sweep" in text:
        fired.append(4)
    if "DIFFERENT production anchors" in text:
        fired.append(5)
    return fired


class _Tree:
    """A tracked git tree with two anchor files and one carrier document."""

    def __init__(self, anchors, carrier_seeds=(), prod_const="ROOT_PUBLIC_KEY_HEX"):
        self.dir = pathlib.Path(tempfile.mkdtemp(prefix="anchor-custody-"))
        for rel, (prod, demo) in zip(TCB_PATHS, anchors):
            path = self.dir / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                TCB_TEMPLATE.format(prod=prod, demo=demo, prod_const=prod_const),
                encoding="utf-8", newline="\n")
        notes = self.dir / "NOTES.md"
        body = "# notes\n\n" + "".join(f"a seed: {s}\n" for s in carrier_seeds)
        notes.write_text(body, encoding="utf-8", newline="\n")
        self._git("init", "-q")
        self._git("add", "-A")

    def _git(self, *args):
        subprocess.run(["git", *args], cwd=self.dir, capture_output=True, check=False)

    def run(self, extra_env=None):
        env = {**os.environ, "PYTHONUTF8": "1", **(extra_env or {})}
        out = subprocess.run([sys.executable, str(GATE), str(self.dir)], capture_output=True,
                             text=True, encoding="utf-8", errors="replace", env=env)
        return out.returncode, (out.stdout + out.stderr)

    def close(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TheFixturesThemselves(unittest.TestCase):
    """The seed/public constants above are literals; this is what keeps them honest."""

    def test_each_declared_pair_really_is_a_keypair(self):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        except ImportError:
            self.skipTest("cryptography is not importable; the gate's own fail-closed case covers that")
        for seed, pub in ((SEED_A, PUB_A), (SEED_B, PUB_B)):
            derived = Ed25519PrivateKey.from_private_bytes(
                bytes.fromhex(seed)).public_key().public_bytes_raw().hex()
            self.assertEqual(derived, pub, f"the constant for seed {seed[:8]}... is wrong")

    def test_the_offline_shaped_public_is_not_one_of_the_fixture_seeds(self):
        # Otherwise the green case below would be green by accident.
        self.assertNotIn(PUB_OFFLINE, (PUB_A, PUB_B))


class TheGateOnAWellKeptTree(unittest.TestCase):
    def test_a_tree_whose_production_private_is_offline_is_green(self):
        tree = _Tree(anchors=[(PUB_OFFLINE, PUB_A), (PUB_OFFLINE, PUB_A)], carrier_seeds=[SEED_A])
        try:
            code, out = tree.run()
            self.assertEqual(code, 0, out)
            self.assertIn("GREEN", out)
            # The contrast ran: the demonstration seed was found, and that is stated.
            self.assertIn("demonstration anchor(s) found", out)
        finally:
            tree.close()


class TheGateRefuses(unittest.TestCase):
    """One case per rule. Each asserts the exit code AND which rules fired."""

    def _case(self, tree, expect_rules, expect_code=1):
        try:
            code, out = tree.run()
            self.assertEqual(code, expect_code, out)
            self.assertEqual(_rules(out), expect_rules, out)
            return out
        finally:
            tree.close()

    def test_rule_3_a_committed_production_seed_is_refused_and_located(self):
        # The defect this gate exists for: the private root, in the tree, under any name.
        out = self._case(
            _Tree(anchors=[(PUB_B, PUB_A), (PUB_B, PUB_A)], carrier_seeds=[SEED_A, SEED_B]),
            expect_rules=[3])
        self.assertIn("NOTES.md:", out, "a finding that does not say WHERE is a finding nobody can act on")
        self.assertIn("Rotate the root and re-pin, do not delete the line", out)

    def test_rule_4_a_sweep_that_finds_nothing_refuses_instead_of_reporting_custody(self):
        # No demonstration seed in the tree => the sweep cannot show it works => rule 3's silence
        # establishes nothing, and the gate says exactly that rather than printing GREEN.
        out = self._case(
            _Tree(anchors=[(PUB_OFFLINE, PUB_A), (PUB_OFFLINE, PUB_A)], carrier_seeds=[]),
            expect_rules=[4])
        self.assertIn("it read", out)
        self.assertIn("literals and matched nothing", out)

    def test_rule_5_two_files_pinning_different_production_anchors_are_refused(self):
        # The Owner holds ONE offline root, so one of two production anchors is undeployable.
        self._case(
            _Tree(anchors=[(PUB_OFFLINE, PUB_A), (PUB_B, PUB_A)], carrier_seeds=[SEED_A]),
            expect_rules=[5])

    def test_rule_2_the_same_key_as_both_anchors_is_refused(self):
        # Then a demonstration private IS a production private, and rule 3 would be checking the fixture.
        self._case(
            _Tree(anchors=[(PUB_OFFLINE, PUB_OFFLINE), (PUB_OFFLINE, PUB_OFFLINE)], carrier_seeds=[]),
            expect_rules=[2, 4])

    def test_rule_1_a_file_that_declares_no_production_anchor_is_refused(self):
        self._case(
            _Tree(anchors=[(PUB_OFFLINE, PUB_A), (PUB_OFFLINE, PUB_A)], carrier_seeds=[SEED_A],
                  prod_const="ROOT_PUBLIC_KEY_HEX_RENAMED"),
            expect_rules=[1])

    def test_a_tree_git_cannot_describe_is_refused_rather_than_swept_emptily(self):
        # `git ls-files` in a non-repository returns nothing. A sweep over no files would satisfy
        # rule 3 for every anchor ever pinned.
        tree = _Tree(anchors=[(PUB_OFFLINE, PUB_A), (PUB_OFFLINE, PUB_A)], carrier_seeds=[SEED_A])
        try:
            shutil.rmtree(tree.dir / ".git", ignore_errors=True)
            code, out = tree.run()
            self.assertEqual(code, 1, out)
            self.assertIn("the sweep cannot be told what is in this tree", out)
        finally:
            tree.close()


class TheGateFailsClosed(unittest.TestCase):
    def test_without_cryptography_it_refuses_rather_than_passing(self):
        tree = _Tree(anchors=[(PUB_OFFLINE, PUB_A), (PUB_OFFLINE, PUB_A)], carrier_seeds=[SEED_A])
        shim = tree.dir / "_no_crypto"
        shim.mkdir()
        (shim / "cryptography.py").write_text(
            "raise ImportError('blocked by the self-test')\n", encoding="utf-8")
        try:
            code, out = tree.run({"PYTHONPATH": str(shim)})
            self.assertEqual(code, 2, out)
            self.assertIn("cryptography is not importable", out)
            self.assertNotIn("GREEN", out)
        finally:
            tree.close()


class ThisRepositoryToday(unittest.TestCase):
    def test_the_production_anchors_private_half_is_not_in_this_tree(self):
        out = subprocess.run([sys.executable, str(GATE), str(ROOT)], capture_output=True, text=True,
                             encoding="utf-8", errors="replace",
                             env={**os.environ, "PYTHONUTF8": "1"})
        text = out.stdout + out.stderr
        if out.returncode == 2:
            self.skipTest("cryptography is not importable on this box")
        self.assertEqual(out.returncode, 0, text)
        self.assertIn("GREEN", text)

    def test_the_gate_is_run_by_a_workflow(self):
        """`check_reachability` asks this of every gate; asserted here too, because this gate's whole
        value is that it runs on every pull request rather than when somebody remembers."""
        workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
        self.assertTrue(workflows, "no workflows found")
        hits = [w.name for w in workflows
                if "check_root_anchor_custody.py" in w.read_text(encoding="utf-8")]
        self.assertTrue(hits, "no workflow runs tools/check_root_anchor_custody.py")

    def test_the_context_is_either_required_or_written_down_as_pending(self):
        """A gate that cannot block a merge is the T-056 pattern. Until the Owner promotes it, the ask
        has to be somewhere a person will read — so this holds one of the two to be true."""
        contexts = set(json.loads(
            (ROOT / "config" / "required-checks.json").read_text(encoding="utf-8"))["contexts"])
        name = "Trust anchor · no production root private in this tree"
        if name in contexts:
            return
        owner = (ROOT / "docs" / "OWNER_ACTION_REQUIRED.md").read_text(encoding="utf-8")
        self.assertIn(name, owner,
                      "the context is neither required nor named on the Owner's page as pending")


if __name__ == "__main__":
    unittest.main()
