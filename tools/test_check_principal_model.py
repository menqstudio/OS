"""Self-tests for the principal-model gate.

A gate is only worth its GREEN if it is proven to go RED. These drive `read_model()` against
literal Rust snippets — no repository, because the question is a function of the source text, and
taking that as data is what makes every arm reachable including the ones the real tree cannot
produce without a compile error.

The last test is the one that matters most: an eighth principal must be refused **by name**, with
§2.6 and the word AMENDMENT in the message, because the failure this gate exists to prevent is a
normative clause being widened by a commit that nobody read as an amendment.
"""
from __future__ import annotations

import contextlib
import io
import pathlib
import tempfile
import unittest

import check_principal_model as gate

GOOD = """
pub enum Principal {
    Broker,      // trusted desktop verifier
    Authority,   // desktop-challenge-authority
    Sidecar,     // in-scope RCE actor
    Supervisor,  // lease issuer
    Recorder,    // evidence-recorder runner
    Executor,    // contained model executor
    Signer,      // isolated receipt signer
}

pub const RUNTIME_PRINCIPALS: [Principal; 7] = [
    Principal::Broker, Principal::Authority, Principal::Sidecar, Principal::Supervisor,
    Principal::Recorder, Principal::Executor, Principal::Signer,
];
"""


class ReadsTheModel(unittest.TestCase):
    def test_the_shipped_source_parses_into_the_normative_seven(self):
        source = gate.SOURCE.read_text(encoding="utf-8")
        variants, members, declared, failure = gate.read_model(source)
        self.assertIsNone(failure)
        self.assertEqual(members, gate.NORMATIVE_PRINCIPALS)
        self.assertEqual(variants, gate.NORMATIVE_PRINCIPALS)
        self.assertEqual(declared, 7)

    def test_a_comment_naming_a_principal_is_not_a_principal(self):
        # The variants carry `// trusted desktop verifier` style comments; counting words out of
        # them would have found more principals than the enum declares.
        variants, _, _, _ = gate.read_model(GOOD)
        self.assertEqual(variants, gate.NORMATIVE_PRINCIPALS)

    def test_a_source_without_the_array_is_a_failure_not_an_empty_model(self):
        _, _, _, failure = gate.read_model("pub enum Principal { Broker, }")
        self.assertIn("RUNTIME_PRINCIPALS", failure)

    def test_a_source_without_the_enum_is_a_failure(self):
        _, _, _, failure = gate.read_model("pub const RUNTIME_PRINCIPALS: [Principal; 0] = [];")
        self.assertIn("enum Principal", failure)


EIGHTH_IN_ENUM = GOOD.replace("    Signer,      // isolated receipt signer\n",
                              "    Signer,      // isolated receipt signer\n    FloorWriter,\n")
EIGHTH_EVERYWHERE = EIGHTH_IN_ENUM.replace("[Principal; 7]", "[Principal; 8]").replace(
    "Principal::Signer,\n", "Principal::Signer, Principal::FloorWriter,\n")


class TheVerdictOnTheModel(unittest.TestCase):
    """`model_problems` -- the gate's REFUSALS, which is what the docstring above promises.

    `RefusesTheDrift` below only shows that `read_model()` parses a drifted source faithfully.
    The four comparisons that turn that into a refusal lived in `main()`, which reads the
    shipped file, so no test reached them: deleting all four left 12 of 12 green.
    """

    def problems(self, source: str) -> list[str]:
        variants, members, declared, failure = gate.read_model(source)
        self.assertIsNone(failure)
        return gate.model_problems(variants, members, declared)

    def test_the_control_has_no_problems(self):
        self.assertEqual(self.problems(GOOD), [])

    def test_an_eighth_principal_is_refused_BY_NAME_as_an_amendment_to_2_6(self):
        """The one that matters most. It compiles; the count and the array agree with each
        other; and it widens a normative clause."""
        problems = self.problems(EIGHTH_EVERYWHERE)
        named = [p for p in problems if "FloorWriter" in p and "is not the normative set" in p]
        self.assertEqual(len(named), 1, problems)
        self.assertIn("extra ['FloorWriter']", named[0])
        self.assertIn("§2.6", named[0])
        self.assertIn("AMENDMENT", named[0])
        self.assertIn("ratifiable only by the Architect", named[0])
        self.assertTrue(any("declared [Principal; 8] and the normative count is 7" in p
                            for p in problems), problems)
        self.assertTrue(any("not the normative order" in p for p in problems), problems)

    def test_a_variant_the_array_omits_is_refused(self):
        """The silent one: it compiles, and verify_distinct_principals() iterates the ARRAY."""
        problems = self.problems(EIGHTH_IN_ENUM)
        self.assertTrue(any("the enum has 8 variant(s) and the array 7 member(s)" in p
                            for p in problems), problems)
        self.assertTrue(any("extra ['FloorWriter']" in p for p in problems), problems)

    def test_a_renamed_principal_keeps_the_count_and_is_still_refused(self):
        """`[Principal; 7]` pins the COUNT. A rename keeps seven and changes which seven."""
        problems = self.problems(GOOD.replace("Recorder", "Auditor"))
        self.assertTrue(any("extra ['Auditor'], missing ['Recorder']" in p for p in problems),
                        problems)

    def test_a_reordered_array_is_refused_and_nothing_else_is(self):
        source = GOOD.replace("Principal::Broker, Principal::Authority",
                              "Principal::Authority, Principal::Broker")
        problems = self.problems(source)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("not the normative order", problems[0])

    def test_a_declared_length_that_is_not_seven_is_refused_and_nothing_else_is(self):
        problems = self.problems(GOOD.replace("[Principal; 7]", "[Principal; 9]"))
        self.assertEqual(problems, ["RUNTIME_PRINCIPALS is declared [Principal; 9] and the "
                                    "normative count is 7"])


class RefusesTheDrift(unittest.TestCase):
    """Each drifted source is PARSED faithfully; `TheVerdictOnTheModel` is where it is refused."""

    def verdict(self, source):
        variants, members, declared, failure = gate.read_model(source)
        self.assertIsNone(failure, source[:80])
        return variants, members, declared

    def test_the_control_agrees_with_the_normative_set(self):
        variants, members, declared = self.verdict(GOOD)
        self.assertEqual(variants, gate.NORMATIVE_PRINCIPALS)
        self.assertEqual(members, gate.NORMATIVE_PRINCIPALS)
        self.assertEqual(declared, len(gate.NORMATIVE_PRINCIPALS))

    def test_an_eighth_principal_in_the_enum_and_the_array_is_seen(self):
        source = GOOD.replace("    Signer,      // isolated receipt signer\n",
                              "    Signer,      // isolated receipt signer\n    FloorWriter,\n")
        source = source.replace("[Principal; 7]", "[Principal; 8]").replace(
            "Principal::Signer,\n", "Principal::Signer, Principal::FloorWriter,\n")
        variants, members, declared = self.verdict(source)
        self.assertIn("FloorWriter", variants)
        self.assertIn("FloorWriter", members)
        self.assertEqual(declared, 8)

    def test_a_variant_the_array_omits_is_seen(self):
        # The silent one: it compiles, and verify_distinct_principals() iterates the ARRAY, so this
        # principal would sit outside the pairwise-distinctness rule while looking inside it.
        source = GOOD.replace("    Signer,      // isolated receipt signer\n",
                              "    Signer,      // isolated receipt signer\n    FloorWriter,\n")
        variants, members, _ = self.verdict(source)
        self.assertEqual(len(variants), 8)
        self.assertEqual(len(members), 7)
        self.assertNotEqual(len(variants), len(members))

    def test_a_reordered_array_is_seen_because_the_order_is_the_verdict_order(self):
        source = GOOD.replace("Principal::Broker, Principal::Authority",
                              "Principal::Authority, Principal::Broker")
        _, members, _ = self.verdict(source)
        self.assertNotEqual(members, gate.NORMATIVE_PRINCIPALS)


class TheDocumentsAreHeldToTheSameNumber(unittest.TestCase):
    def test_every_named_document_exists_and_says_seven(self):
        self.assertEqual(gate.document_problems(gate.ROOT, 7), [])
        for relative in gate.COUNT_CLAIMS:
            claims = gate.uid_count_claims((gate.ROOT / relative).read_text(encoding="utf-8"))
            self.assertTrue(claims, f"{relative} states no runtime-service-UID count")

    def test_the_claim_pattern_does_not_match_seven_of_something_else(self):
        self.assertEqual(gate.uid_count_claims("seven refusals hold the gate shut"), [])
        self.assertEqual(gate.uid_count_claims("the SEVEN runtime service UIDs (NORMATIVE)"),
                         [("SEVEN", 7)])

    def test_every_way_a_count_is_written_is_read(self):
        text = ("the **SEVEN** runtime service UIDs, the seven runtime service UIDs, "
                "8 runtime service UIDs, EIGHT runtime service UIDs, and the distinct "
                "runtime service UIDs are not a count")
        self.assertEqual(gate.uid_count_claims(text),
                         [("SEVEN", 7), ("seven", 7), ("8", 8), ("EIGHT", 8)])

    def _root(self, **docs: str) -> pathlib.Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        for relative in gate.COUNT_CLAIMS:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(docs.get(pathlib.PurePosixPath(relative).name,
                                     "The SEVEN runtime service UIDs.\n"), encoding="utf-8")
        return root

    def test_the_control_three_documents_saying_seven_are_green(self):
        self.assertEqual(gate.document_problems(self._root(), 7), [])

    def test_a_document_that_says_EIGHT_beside_a_surviving_seven_is_refused(self):
        """The defect. The pattern matched only "seven", then the code asked whether the match
        was "seven". A second, different number in the same document could not be seen."""
        root = self._root(**{"SECURITY_MODEL.md":
                             "The seven runtime service UIDs ... the EIGHT runtime service UIDs."})
        self.assertEqual(gate.document_problems(root, 7),
                         ["docs/SECURITY_MODEL.md says 'EIGHT runtime service UIDs' while the "
                          "code carries 7"])

    def test_the_documents_are_compared_with_the_CODE_not_with_the_word_seven(self):
        """If the model really had eight, the documents saying seven are what is stale."""
        problems = gate.document_problems(self._root(), 8)
        self.assertEqual(len(problems), 3, problems)
        self.assertTrue(all("'SEVEN runtime service UIDs' while the code carries 8" in p
                            for p in problems), problems)

    def test_a_document_with_no_count_claim_and_a_missing_document_are_refused(self):
        root = self._root(**{"SECURITY_MODEL.md": "the runtime service UIDs are distinct\n"})
        (root / "docs/design/FLOOR_WRITER_SERVICE_DESIGN.md").unlink()
        problems = gate.document_problems(root, 7)
        self.assertEqual(len(problems), 2, problems)
        self.assertIn("docs/SECURITY_MODEL.md states no '<n> runtime service UIDs' claim",
                      problems[0])
        self.assertIn("FLOOR_WRITER_SERVICE_DESIGN.md is named as stating the count and does not "
                      "exist", problems[1])


class TheGateItselfRunsGreenOnThisTree(unittest.TestCase):
    def test_main_returns_zero_here(self):
        self.assertEqual(gate.main(), 0)

    def _main_on(self, source: str) -> tuple[int, str]:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = pathlib.Path(tmp.name) / "windows_broker.rs"
        path.write_text(source, encoding="utf-8")
        original = gate.SOURCE
        gate.SOURCE = path
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = gate.main()
        finally:
            gate.SOURCE = original
        return code, out.getvalue()

    def test_main_is_red_on_a_drifted_source_and_prints_the_refusal(self):
        """The exit code CI reads, on a source the real tree does not hold."""
        code, said = self._main_on(EIGHTH_EVERYWHERE)
        self.assertEqual(code, 1)
        self.assertIn("AMENDMENT", said)
        self.assertIn("FloorWriter", said)

    def test_main_is_red_when_a_document_disagrees_with_the_code(self):
        """The good source, and a tree whose documents do not all say seven."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = pathlib.Path(tmp.name)
        for relative in gate.COUNT_CLAIMS:
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text("The NINE runtime service UIDs.\n", encoding="utf-8")
        original = gate.ROOT
        gate.ROOT = root
        try:
            code, said = self._main_on(GOOD)
        finally:
            gate.ROOT = original
        self.assertEqual(code, 1)
        self.assertIn("says 'NINE runtime service UIDs' while the code carries 7", said)

    def test_main_is_red_on_a_source_it_cannot_parse(self):
        code, said = self._main_on("pub enum Principal { Broker, }")
        self.assertEqual(code, 1)
        self.assertIn("RED: no `pub const RUNTIME_PRINCIPALS", said)



# A gate's message names a repository path, and that spelling is part of the contract: people
# grep it, paste it into an editor, and read it in CI logs from both platforms. `str(Path)` gives
# `a\b` on Windows, which is neither this repository's spelling nor clickable for a Linux reader.
# These tests can only FAIL on Windows -- on Linux the separator is `/` either way -- which is
# exactly why ci.yml now runs the tools suite on windows-latest as well.

class UnreadableSourceMessagePathSpelling(unittest.TestCase):
    def test_the_cannot_read_message_spells_the_path_with_forward_slashes(self):
        import contextlib
        import io

        missing = gate.ROOT / "apps" / "desktop" / "src-tauri" / "core" / "src" / "no-such-file.rs"
        original = gate.SOURCE
        gate.SOURCE = missing
        try:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = gate.main()
        finally:
            gate.SOURCE = original
        self.assertEqual(code, 1)
        said = out.getvalue()
        self.assertIn("cannot read", said)
        # Only the path the GATE renders is ours to spell. What follows the colon is the OSError's
        # own strerror, which names an absolute path in the platform's spelling and is not ours to
        # rewrite -- so the assertion is on our half, not on the whole line.
        ours = said.split(":", 2)[1]
        self.assertNotIn("\\", ours, "the unreadable-source message used OS-native separators")
        self.assertIn("apps/desktop/src-tauri/core/src/no-such-file.rs", said)

if __name__ == "__main__":
    unittest.main()
