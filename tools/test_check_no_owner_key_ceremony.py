"""Self-tests for check_no_owner_key_ceremony. Each case builds a throwaway git tree.

This file is also the gate's CONTROL: it names forbidden tokens (win_gen_root, sign_manifest.py,
BROPS_MANIFEST_SIG_IN) and is exempt by path, so the real sweep must find them here or go red.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import check_no_owner_key_ceremony as gate  # noqa: E402

#: The six phrases the gate had before T-145, each with a sentence of the shape it was written for.
ORIGINAL = {
    "owner's offline": "// the private half is the Owner's OFFLINE root\n",
    "offline-root-custodian": 'Provisioner::X => "offline-root-custodian",\n',
    "owner-provided key": "the manifest is signed with an Owner-provided key\n",
    "owner mints a key": "first the Owner mints a key\n",
    "only the owner can make": "an artifact only the Owner can make\n",
    "the owner must export": "the Owner must export the pin\n",
}

#: Every phrase T-145 added, beside the sentence it was added FOR -- copied from the tree as it
#: stood, line breaks, comment leaders and emphasis included, because that layout is what let
#: several of them through. Each was GREEN under the six phrases above.
SURVIVORS = {
    "your offline root":
        "| labelled for the custody it has (`trusted_verified` only under your offline root) |\n",
    "held offline by the operator":
        'production root whose private half "is held OFFLINE by the operator … never appears in a\n',
    "root private is held offline":
        "    // the driver pins only the root PUBLIC key. In production the root private is\n"
        "    // held offline entirely — nothing about the root private lands on the serving box.\n",
    "private key is held offline":
        "which remain yours: the `recovery` private key is held **offline** (the registry\n",
    "is offline, not on this box":
        "    // any config whose `pubs` disagree — and the root private that could re-sign the manifest is\n"
        "    // offline, not on this box.\n",
    "trusted_verified without the offline root":
        "/// manifest (e.g. reviving a since-revoked signer key) → `trusted_verified` WITHOUT the\n"
        "/// offline root. The floor signature therefore only detects ACCIDENTAL corruption\n",
    "offline operator":
        "The trusted key registry is signed by the offline operator root key, but the\n",
    "offline issuer":
        "    against the operator-signed trusted-key registry, not HMAC. Only the offline\n"
        "    issuer key can grant execution capabilities; a builder holding the public\n",
    "owner-held recovery":
        "   the offline owner-held `recovery` authority, bound to the task/record/before-state/\n",
    "the owner holds":
        "        # The Owner holds ONE offline root, so one of two production anchors is undeployable.\n",
    "only the owner can mint":
        "  items remain OPEN, three of them waiting on an artifact only the Owner can mint.\n",
    "only the owner can provide":
        "the anchor requires signing custody only the Owner can provide, so until it is provisioned\n",
    "is the owner's step":
        'signs proves nothing"). Provisioning that signer is the Owner\'s step, tracked as **O-2**.\n',
    "owner's out-of-band":
        "the caller is the owner's out-of-band signing command, reached through the signer variable\n",
    "the owner's ceremony":
        "    `config/trusted-keys.json`, so on a real deployment an owner command still refuses. That is\n"
        "    the Owner's ceremony, not a code gap\n",
    "is the owner's signature":
        "        following that message would have gone off to build what already existed. What is missing\n"
        "        now is the Owner's signature, and only one of those two is actionable by whoever hits it.\n",
    "owner mints the artifact":
        "    leaves behind; the hand-back behaviour returns — with its own tests — when the\n"
        "    owner mints the artifact that message names.\n",
    "owner must mint":
        "        environment's word — and the refusal names the artifact the owner must\n"
        "        mint, because nothing in this repository can mint it.\n",
    "owner has to mint":
        "        # registry entry the owner has to mint are all named.\n",
    "signed offline by the owner":
        "`conductor-session` token — it is signed offline by the owner's operator-root key\n",
    "the owner has run steps":
        "  a correctly signed anchor is what Step 3 produces — so until the Owner has run Steps 1, 3 and 4\n",
    "mint, offline":
        "**Exactly what Gev must provide.** Mint, offline with the operator-root key, an artifact of the form\n",
    "anchoring a ledger by hand":
        "    The out-of-band path, for an operator anchoring a ledger by hand. This module\n",
}

#: Sentences that are TRUE and in the tree today. A phrase list that reddens one of these would be
#: fixed by deleting the phrase, so they are held green here.
HONEST = (
    "No person holds or carries a root key: the Owner decided on 2026-08-09 (#78) that the install\n"
    "mints trust.\n",
    "Nobody holds an offline root; the install mints trust.\n",
    '"""Verify a signed recovery-proof artifact (an owner authorisation, not an owner-held key).\n',
    "provisioning mints the `conductor-session` artifact, so **no Owner-minted artifact is needed**\n",
    "> What is CONFIGURED in the repo vs what the **Owner must provide** (secrets) to cut a signed release\n",
    "elevated install action — not a key the Owner has to hold.\n",
    "/// key) generated verifies exactly as well as one signed by an operator's offline root: the arithmetic\n",
    "# no elevation and no offline root key, so it runs HERE\n",
)


class Tree:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        # The control must exist in every tree, or "control matched" fails before anything else.
        self.write(gate.CONTROL, "names win_gen_root on purpose\n")

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        subprocess.run(["git", "-C", str(self.root), "add", rel], check=True)

    def close(self):
        self._tmp.cleanup()


class GateTests(unittest.TestCase):
    def setUp(self):
        self.t = Tree()
        self.addCleanup(self.t.close)

    def test_a_clean_tree_is_green(self):
        self.t.write("docs/README.md", "the install mints trust\n")
        problems, control = gate.check(self.t.root)
        self.assertEqual(problems, [])
        self.assertTrue(control)

    def test_a_removed_path_coming_back_is_red(self):
        self.t.write("engine/ci/live/sign_manifest.py", "print('hi')\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any("sign_manifest.py exists" in p for p in problems), problems)

    def test_a_document_naming_a_ceremony_tool_is_red(self):
        self.t.write("docs/HOWTO.md", "export BROPS_MANIFEST_SIG_IN=/media/x\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any(p.startswith("docs/HOWTO.md names BROPS_MANIFEST_SIG_IN") for p in problems),
                        problems)

    def test_prose_claiming_a_person_holds_the_root_is_red_whatever_its_case(self):
        self.t.write("src/preflight.rs", "// the private half is the Owner's OFFLINE root\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any("src/preflight.rs" in p and "owner's offline" in p for p in problems),
                        problems)

    def test_the_retired_provisioner_name_coming_back_is_red(self):
        # T-131 slice C renamed preflight's provisioner for what it now is (an install-minted root)
        # and returned its old `as_str` to the phrase list. A report column that names a custodian
        # is a claim that one exists.
        self.t.write("src/preflight.rs",
                     'Provisioner::X => "offline-root-custodian",\n')
        problems, _ = gate.check(self.t.root)
        self.assertTrue(
            any("src/preflight.rs" in p and "offline-root-custodian" in p for p in problems),
            problems)
        # Case does not hide it, and the CamelCase variant name alone is not the phrase.
        self.t.write("docs/TABLE.md", "one `Offline-Root-Custodian` row\n")
        self.t.write("docs/HISTORY.md", "the variant was called OfflineRootCustodian\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any(p.startswith("docs/TABLE.md") for p in problems), problems)
        self.assertFalse(any(p.startswith("docs/HISTORY.md") for p in problems), problems)

    # ---- T-145 (H2): the custody wording the trust self-test showed on screen ----------------

    #: phrase -> the sentence it was written for, as it stood in the tree (the file is named so a
    #: reader can find where it was). Every phrase added with this batch is a key here, and
    #: `test_each_custody_phrase_is_what_makes_its_sentence_red` proves each one is load-bearing.
    CUSTODY_SURVIVORS = {
        "offline-hsm": (
            "apps/desktop/src-tauri/src/governed_selftest.rs",
            'anchor (a public constant), NOT a secret offline-HSM key — so this proves the machinery\n'),
        "offline-root custody": (
            "apps/desktop/src-tauri/src/governed_selftest.rs",
            "custody. Live AI turns still run fail-closed; production offline-root custody + a live\n"),
        "offline-root-verified": (
            "apps/desktop/src/services/desktop.ts",
            " * compiled-in demonstration anchor, not an offline-root-verified production manifest), so\n"),
        "production offline root": (
            "apps/desktop/src-tauri/core/schema/0099_new.sql",
            "-- compiled-in DEMONSTRATION anchor — NEVER the production offline root, and the executor\n"),
        "the operator's offline root": (
            "apps/desktop/src-tauri/win-live/proof/CROSS_ACCOUNT_PROOF.md",
            ">    the operator's offline root **cannot** reproduce a production `trusted_verified`.\n"),
    }

    def test_each_custody_phrase_is_what_makes_its_sentence_red(self):
        for phrase, (rel, sentence) in self.CUSTODY_SURVIVORS.items():
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, gate.FORBIDDEN_PHRASES)
                t = Tree()
                self.addCleanup(t.close)
                t.write(rel, sentence)
                problems, _ = gate.check(t.root)
                self.assertTrue(
                    any(p.startswith(rel) and f'"{phrase}"' in p for p in problems), problems)
                # Without THIS phrase the same sentence is green: no other phrase or token covers
                # it, so removing the phrase from the list is removing the check.
                kept = gate.FORBIDDEN_PHRASES
                gate.FORBIDDEN_PHRASES = tuple(p for p in kept if p != phrase)
                try:
                    problems, _ = gate.check(t.root)
                finally:
                    gate.FORBIDDEN_PHRASES = kept
                self.assertEqual(problems, [], f"{phrase!r} is not what catches its sentence")

    def test_the_true_custody_note_is_green(self):
        # What replaced it. A gate that also refused the correction would be a gate on a topic.
        self.t.write(
            "apps/desktop/src-tauri/src/governed_selftest.rs",
            "No person holds a production key and none ever will: trust is minted by the install. "
            "A root minted that way commits demonstration_custody, not trusted_verified, until the "
            "Owner accepts install-minted custody after an independent audit.\n"
            "// It contrasted the anchor with a secret key in an HSM kept off the machine.\n")
        self.t.write("docs/WHY.md", "Nobody holds an offline root, and no HSM is involved.\n")
        problems, _ = gate.check(self.t.root)
        self.assertEqual(problems, [])

    def test_a_phrase_exemption_excuses_that_phrase_in_that_file_and_nothing_else(self):
        migration = "apps/desktop/src-tauri/core/schema/0018_demonstration_verified.sql"
        self.assertEqual(gate.PHRASE_EXEMPT[migration], ("production offline root",))
        self.t.write(migration, "-- NEVER the production offline root\n")
        problems, _ = gate.check(self.t.root)
        self.assertEqual(problems, [], "the applied migration's one wording is excused")
        # The same wording in the NEXT migration is not history yet.
        self.t.write("apps/desktop/src-tauri/core/schema/0019_next.sql",
                     "-- NEVER the production offline root\n")
        problems, _ = gate.check(self.t.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith("apps/desktop/src-tauri/core/schema/0019_next.sql"))
        # And the excused file is still swept for every other phrase and every token.
        self.t.write(migration, "-- NEVER the production offline root; ask for the owner's offline key\n"
                                "-- then run win_gen_root\n")
        problems, _ = gate.check(self.t.root)
        mine = [p for p in problems if p.startswith(migration)]
        self.assertEqual(len(mine), 1, problems)
        self.assertIn("owner's offline", mine[0])
        self.assertIn("win_gen_root", mine[0])
        self.assertNotIn("production offline root", mine[0])

    def test_every_phrase_exemption_is_still_needed_in_the_real_tree(self):
        # An exemption whose file has stopped containing its phrase excuses nothing and waits for
        # the wording to come back unseen. Checked against THIS repository, not a throwaway tree.
        root = pathlib.Path(gate.__file__).resolve().parents[1]
        for rel, phrases in gate.PHRASE_EXEMPT.items():
            self.assertFalse(rel.startswith(gate.EXEMPT_PREFIXES), f"{rel} is already exempt whole")
            text = (root / rel).read_text(encoding="utf-8").lower()
            for phrase in phrases:
                with self.subTest(file=rel, phrase=phrase):
                    self.assertIn(phrase, gate.FORBIDDEN_PHRASES, "an exemption for no rule")
                    self.assertIn(phrase, text, f"{rel} no longer says {phrase!r}: drop the entry")

    def test_an_honest_sentence_about_the_removal_is_green(self):
        self.t.write("docs/WHY.md", "Nobody holds an offline root; the install mints trust.\n")
        problems, _ = gate.check(self.t.root)
        self.assertEqual(problems, [])

    def test_a_file_with_no_suffix_is_swept(self):
        # `deb/postinst` has no extension; an installer script is exactly where it would return.
        self.t.write("apps/desktop/src-tauri/deb/postinst", "#!/bin/sh\nwin_gen_root --out x\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any("deb/postinst names win_gen_root" in p for p in problems), problems)

    def test_history_is_exempt(self):
        self.t.write("docs/archive/OLD.md", "win_gen_root --out root.private.seed\n")
        self.t.write("apps/desktop/AUDIT/2026-08-06-x.md", "sign_manifest.py\n")
        problems, _ = gate.check(self.t.root)
        self.assertEqual(problems, [])

    def test_a_sweep_that_misses_its_control_is_red(self):
        # Overwrite the control so it names nothing: the walk can no longer prove it matched.
        self.t.write(gate.CONTROL, "nothing here\n")
        _, control = gate.check(self.t.root)
        self.assertFalse(control)
        # ...and the VERDICT is red. Until T-145 this test stopped at the line above: `check`
        # reported the miss and nothing established that `main` turned it into an exit code, so
        # `if not control_seen` could be replaced by `if False` with every test still passing.
        code, out = self.verdict()
        self.assertEqual(code, 1, out)
        self.assertIn("never matched its control", out)

    def verdict(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = gate.main(self.t.root)
        return code, out.getvalue()

    def test_a_problem_makes_the_verdict_red_and_names_the_file(self):
        self.t.write("docs/HOWTO.md", "export BROPS_MANIFEST_SIG_IN=/media/x\n")
        code, out = self.verdict()
        self.assertEqual(code, 1, out)
        self.assertIn("RED", out)
        self.assertIn("docs/HOWTO.md names BROPS_MANIFEST_SIG_IN", out)

    def test_a_clean_tree_is_a_green_verdict(self):
        # The contrast for the two above: `main` can say 0, so its 1 is a decision.
        self.t.write("docs/README.md", "the install mints trust\n")
        code, out = self.verdict()
        self.assertEqual(code, 0, out)
        self.assertIn("GREEN", out)

    # --- T-145: the phrases, one sentence each ------------------------------------------------

    def test_every_phrase_has_the_sentence_it_was_written_for(self):
        # A phrase added to the gate with no sentence here is a phrase nothing proves can fire.
        self.assertEqual(sorted(gate.FORBIDDEN_PHRASES), sorted({**ORIGINAL, **SURVIVORS}))

    def test_every_phrase_is_already_prose(self):
        # Phrases are matched against `prose(text)`. One written with a backtick, a `*`, a capital
        # or two spaces could never match anything, and would sit in the list looking like a check.
        for phrase in gate.FORBIDDEN_PHRASES:
            self.assertEqual(gate.prose(phrase), phrase)

    def test_each_sentence_is_red_and_green_again_without_its_phrase(self):
        for n, (phrase, sentence) in enumerate({**ORIGINAL, **SURVIVORS}.items()):
            rel = f"src/claim_{n}.rs"
            with self.subTest(phrase=phrase):
                self.t.write(rel, sentence)
                problems, _ = gate.check(self.t.root)
                self.assertTrue(any(p.startswith(rel) and f'"{phrase}"' in p for p in problems),
                                problems)
                # Remove THIS phrase and the same sentence must pass: otherwise some other phrase
                # is doing the work and this one is tested by nothing.
                without = tuple(p for p in gate.FORBIDDEN_PHRASES if p != phrase)
                with mock.patch.object(gate, "FORBIDDEN_PHRASES", without):
                    problems, _ = gate.check(self.t.root)
                self.assertFalse(any(p.startswith(rel) for p in problems), problems)
                self.t.write(rel, "nothing\n")

    def test_true_sentences_about_the_decision_stay_green(self):
        for n, sentence in enumerate(HONEST):
            self.t.write(f"docs/honest_{n}.md", sentence)
        problems, _ = gate.check(self.t.root)
        self.assertEqual(problems, [])

    def test_the_removable_media_path_of_the_deleted_steps_is_red(self):
        self.t.write("docs/RUNBOOK.md", "# NOT from /media/usb/bro-root/operator-root.json\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any(p.startswith("docs/RUNBOOK.md names /media/usb/bro-root") for p in problems),
                        problems)

    # --- T-145: layout does not hide a claim --------------------------------------------------

    def test_a_claim_wrapped_across_comment_lines_is_red_in_every_comment_style(self):
        for n, leader in enumerate(("// ", "/// ", "//! ", "# ", "> ", "-- ", "")):
            rel = f"src/wrapped_{n}.txt"
            with self.subTest(leader=leader):
                self.t.write(rel, f"    {leader}in production the root private is\n"
                                  f"    {leader}held offline entirely\n")
                problems, _ = gate.check(self.t.root)
                self.assertTrue(any(p.startswith(rel) for p in problems), problems)

    def test_emphasis_inside_a_claim_does_not_hide_it(self):
        self.t.write("docs/A.md", "the `recovery` private key is held **offline**\n")
        self.t.write("docs/B.md", "signed by the offline owner-held `recovery` authority\n")
        problems, _ = gate.check(self.t.root)
        self.assertTrue(any(p.startswith("docs/A.md") for p in problems), problems)
        self.assertTrue(any(p.startswith("docs/B.md") for p in problems), problems)

    def test_prose_is_the_sentence_and_nothing_else(self):
        self.assertEqual(gate.prose("  // The Root\n  // is **held**\n\t`here`\n"),
                         "the root is held here")
        # A leader is removed only where a line STARTS: a path keeps its slashes, a flag its dashes.
        self.assertEqual(gate.prose("see a//b and --flag # not a leader"),
                         "see a//b and --flag # not a leader")

    def test_the_file_kinds_only_the_seed_sweep_used_to_read_are_swept(self):
        # One extension set for both gates since T-145; `.mjs` and `.xml` were in neither.
        for rel in ("scripts/build.mjs", "config/app.xml", "deploy/kit.cfg", "deploy/kit.env"):
            self.t.write(rel, "win_gen_root --out x\n")
        problems, _ = gate.check(self.t.root)
        for rel in ("scripts/build.mjs", "config/app.xml", "deploy/kit.cfg", "deploy/kit.env"):
            self.assertTrue(any(p.startswith(f"{rel} names win_gen_root") for p in problems), problems)


if __name__ == "__main__":
    unittest.main()
