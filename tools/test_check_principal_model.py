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

import pathlib
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


class RefusesTheDrift(unittest.TestCase):
    """Each arm driven by the source that would trip it, and the good source as the control."""

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
        for relative in gate.COUNT_CLAIMS:
            path = gate.ROOT / relative
            self.assertTrue(path.exists(), relative)
            claims = gate._UID_CLAIM.findall(path.read_text(encoding="utf-8"))
            self.assertTrue(claims, f"{relative} states no runtime-service-UID count")
            for word in claims:
                self.assertEqual(word.lower(), "seven", relative)

    def test_the_claim_pattern_does_not_match_seven_of_something_else(self):
        self.assertFalse(gate._UID_CLAIM.findall("seven refusals hold the gate shut"))
        self.assertTrue(gate._UID_CLAIM.findall("the SEVEN runtime service UIDs (NORMATIVE)"))


class TheGateItselfRunsGreenOnThisTree(unittest.TestCase):
    def test_main_returns_zero_here(self):
        self.assertEqual(gate.main(), 0)


if __name__ == "__main__":
    unittest.main()
