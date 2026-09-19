"""Wave 3b-1 — cross-language JCS parity (design §3(d), §4.0a).

Every hashed artifact and the 21-field receipt envelope MUST hash identically in this
Python signer and the Rust desktop verifier, or the desktop's `bind` against `Expected`
fails and the turn Blocks. These fixed vectors are the cross-language anchor: the Rust
test `receipt.rs::brops_all_formula_parity_matches_python` asserts the SAME hex from the
Rust primitives. If you change a formula, both sides must change together.

The five formulas the Rust side also computes (`system`, `history`, `output`,
`generation_config`, `request_sha256`) plus the full receipt envelope are pinned on both
sides. `containment_evidence` and `policy_bundle` are net-new in 3b-1 (the desktop has no
formula yet — design §4.0a), so they are pinned here Python-internally only.
"""

import hashlib
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

import brops_canonical as bc
import isolated_signer as signer

# --- The shared fixture (identical values in the Rust parity test) ---
SYSTEM = "You are Bro."
HISTORY = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello é✈"}]
OUTPUT = "the answer"
GEN_CONFIG = '{"model":"claude","temperature":0}'
CONTAINMENT = {"contained": True, "group": "pg-1"}
POLICY_BUNDLE = b"policy-bundle-bytes"
WORKSPACE_ID = "ws-1"
INSTALL_ID = "install-1"
REQUEST_NONCE = "11111111-1111-4111-8111-111111111111"
RECEIPT_ID = "22222222-2222-4222-8222-222222222222"
REQUESTED_AT = "1000"
COMPLETED_AT = "2000"

# --- Pinned cross-language vectors (Rust asserts the starred ones) ---
SYSTEM_SHA = "245560397a2a5124423b16d544dfda343392cced1fa0981aefb833fba1f8d032"  # *
HISTORY_SHA = "fbd46857ec1ed759024d56430d5f00214e9a478b6f94ec3933f498aa7cd14c80"  # *
OUTPUT_SHA = "a7c9985d46ca5719357525cc365641e45d6882fb66949d4c08989883f8148c8b"  # *
GEN_SHA = "963be7a4e0b02ab18478b28a969f38f6c5c5b7f7bbe6bccf67ec9495cb377234"  # *
CONTAINMENT_SHA = "4added8a71b943254639a80deadff9a4e62e7a39b31e247b44007e3596677d16"
POLICY_SHA = "1ba910c02817ad322145351bb70efdbfcb2589fe989ebe6b190ce1e8cd7a61e1"
REQUEST_SHA = "6cce48e660b34938e9f3e98dd12f20f0e4d3d29d0539fff82bc15369062d4a66"  # *
RECEIPT_ENV_SHA = "37075e5fd925e78cd386eef4d548d0b940c3e23ad1b9c22c5ee88dda9c518f00"  # *


class BropsParityTests(unittest.TestCase):
    def test_system_formula(self):
        self.assertEqual(bc.system_sha256(SYSTEM), SYSTEM_SHA)

    def test_history_formula_preserves_unicode_verbatim(self):
        self.assertEqual(bc.history_sha256(HISTORY), HISTORY_SHA)
        # ensure_ascii=False: non-ASCII is raw UTF-8, keys ordered content<role, compact.
        self.assertEqual(
            bc.history_bytes(HISTORY),
            b'[{"content":"hi","role":"user"},{"content":"hello \xc3\xa9\xe2\x9c\x88","role":"assistant"}]',
        )

    def test_nm_parity_03_output_formula(self):
        """NM-PARITY-03"""
        self.assertEqual(bc.output_sha256(OUTPUT), OUTPUT_SHA)

    def test_generation_config_formula(self):
        self.assertEqual(bc.generation_config_sha256(GEN_CONFIG), GEN_SHA)

    def test_containment_formula(self):
        self.assertEqual(bc.containment_evidence_sha256(CONTAINMENT), CONTAINMENT_SHA)

    def test_policy_bundle_formula(self):
        self.assertEqual(bc.policy_bundle_sha256(POLICY_BUNDLE), POLICY_SHA)

    def test_nm_parity_08_request_envelope_formula(self):
        """NM-PARITY-08"""
        self.assertEqual(
            bc.request_sha256(
                workspace_id=WORKSPACE_ID,
                install_id=INSTALL_ID,
                request_nonce=REQUEST_NONCE,
                system_sha256=SYSTEM_SHA,
                history_sha256=HISTORY_SHA,
                generation_config_sha256=GEN_SHA,
                requested_at=REQUESTED_AT,
            ),
            REQUEST_SHA,
        )

    def test_receipt_envelope_jcs(self):
        fields = {
            "protocol": bc.RECEIPT_PROTOCOL,
            "key_id": "receipt-key-1",
            "receipt_id": RECEIPT_ID,
            "decision": "completed",
            "request_nonce": REQUEST_NONCE,
            "request_sha256": REQUEST_SHA,
            "requested_at": REQUESTED_AT,
            "completed_at": COMPLETED_AT,
            "workspace_id": WORKSPACE_ID,
            "install_id": INSTALL_ID,
            "supervisor_id": "sup-1",
            "executor_id": "exec-1",
            "builder_id": "builder-1",
            "policy_id": "policy-1",
            "policy_version": "1",
            "system_sha256": SYSTEM_SHA,
            "history_sha256": HISTORY_SHA,
            "output_sha256": OUTPUT_SHA,
            "generation_config_sha256": GEN_SHA,
            "containment_evidence_sha256": CONTAINMENT_SHA,
            "policy_bundle_sha256": POLICY_SHA,
        }
        self.assertEqual(bc.sha256_hex(bc.receipt_envelope_bytes(fields)), RECEIPT_ENV_SHA)


# ---------------------------------------------------------------------------
# Negative-matrix rows NM-PARITY-01 / -02 / -09 -- the Python half
# ---------------------------------------------------------------------------

#: The formula fixture, chosen so EVERY mutation NM-PARITY-01 names changes the bytes. The spec
#: section lives on the registry row, not here: `check_spec_references.py` reads a § in the source
#: as a claim that the whole section holds, and what this pins is one formula.
#: Placement is measured, not decorative: a LEADING NUL so `strip('\x00')` is visible, a TRAILING
#: SPACE so a bare `rstrip()` is too (NUL is not whitespace, so a NUL at the end would leave
#: `rstrip()` invisible), an INTERIOR NUL for a mid-string filter, and a DECOMPOSED `e` + U+0301 so
#: NFC/NFKC composes it. 26 bytes, 18 code points.
PARITY_SYSTEM = "\x00Bro\x00e\u0301 \u0535\u057d \u2708 \U0001f6e0 ok "
PARITY_SYSTEM_SHA256 = "f853ac54b4c6c3c832a7801cd165adcaadbc1ccba2239b894d7551cc10aef8bd"

#: NM-PARITY-02. The Unicode vector is already pinned on both sides; the EMPTY list was not, and
#: an empty history is the case a `null`/omit special-case would quietly change.
PARITY_HISTORY_UNICODE = [
    {"content": "hi", "role": "user"},
    {"content": "hello é✈", "role": "assistant"},
]
PARITY_HISTORY_UNICODE_SHA256 = "fbd46857ec1ed759024d56430d5f00214e9a478b6f94ec3933f498aa7cd14c80"
PARITY_HISTORY_EMPTY_SHA256 = "4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"

#: NM-PARITY-09. 2**53 - 1 is Rust's `MAX_GOVERNED_MS` and the largest integer a JSON double
#: carries exactly.
MAX_GOVERNED_MS = (1 << 53) - 1
PARITY_MS_OBJECT = {
    "challenge_accepted_at_ms": 1_700_000_000_000,
    "completed_at": MAX_GOVERNED_MS,
    "requested_at": 0,
}
PARITY_MS_JCS = (b'{"challenge_accepted_at_ms":1700000000000,'
                 b'"completed_at":9007199254740991,"requested_at":0}')
PARITY_MS_SHA256 = "b839b7c13fcc32d5483cfbf90409973870e1308160ed83b164f3ca04cfb06c52"


class NegativeMatrixParityTests(unittest.TestCase):
    """Cross-language formula parity. Each row's Rust half lives in
    `apps/desktop/src-tauri/core/src/receipt.rs::nm_parity_the_same_fixtures_hash_the_same`
    and pins the SAME literal to the SAME hex. One side alone proves nothing about parity:
    both sides drifting together would keep either test green, which is why the fixture and
    the digest are written out in both files rather than derived in one and imported."""

    def test_nm_parity_01_system_formula_is_raw_utf8_across_unicode_emoji_and_nul(self):
        """NM-PARITY-01 -- `system` is the RAW UTF-8 bytes: no normalisation, no trimming.

        The fixture carries a NUL at each end of the meaningful text, an interior NUL, a
        decomposed `e` + combining acute, Armenian, a 3-byte glyph and a 4-byte emoji. Every
        transformation the row names -- NFC, NFKC, `strip('\x00')`, `rstrip()`, dropping the
        NUL -- changes these bytes, which is the only reason the pinned digest means anything.
        """
        case = "NM-PARITY-01"
        raw = PARITY_SYSTEM.encode("utf-8")
        self.assertEqual(len(raw), 26, f"{case}: the fixture is 26 UTF-8 bytes")
        self.assertEqual(bc.system_bytes(PARITY_SYSTEM), raw,
                         f"{case}: system_bytes must be the raw UTF-8 and nothing else")
        self.assertEqual(bc.system_sha256(PARITY_SYSTEM), PARITY_SYSTEM_SHA256, case)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PARITY_SYSTEM_SHA256,
                         f"{case}: the pin is sha256 of the raw bytes, not of a transform")
        # The NUL survives and the decomposed pair is NOT composed -- stated as assertions so a
        # normalising rewrite cannot pass by coincidence.
        self.assertIn(b"\x00", raw, f"{case}: the NUL was dropped")
        self.assertIn("é", PARITY_SYSTEM, f"{case}: the pair must stay decomposed")

    def test_nm_parity_02_history_formula_pins_empty_history_and_unicode(self):
        """NM-PARITY-02 -- `history` is compact JSON of `[{content,role}]`, keys ordered,
        non-ASCII raw UTF-8. The EMPTY list is the arm that was unpinned: `[]` must serialise
        as exactly `b"[]"`, not `null` and not omitted, or a supervisor and a broker
        disagreeing about an empty conversation would hash two different runs alike.
        """
        case = "NM-PARITY-02"
        self.assertEqual(bc.history_bytes([]), b"[]", f"{case}: empty history is `[]`")
        self.assertEqual(bc.history_sha256([]), PARITY_HISTORY_EMPTY_SHA256, case)
        self.assertEqual(hashlib.sha256(b"[]").hexdigest(), PARITY_HISTORY_EMPTY_SHA256, case)
        # The Unicode vector too, so this test fails if the non-empty formula drifts as well.
        self.assertEqual(bc.history_sha256(PARITY_HISTORY_UNICODE),
                         PARITY_HISTORY_UNICODE_SHA256, case)
        body = bc.history_bytes(PARITY_HISTORY_UNICODE)
        self.assertNotIn(rb"\u", body,
                         f"{case}: non-ASCII must stay raw UTF-8, never a backslash-u escape")
        self.assertLess(body.index(b"content"), body.index(b"role"),
                        f"{case}: keys are ordered content < role")

    def test_nm_parity_09_ms_integers_serialize_identically_on_both_sides(self):
        """NM-PARITY-09 -- every `_ms` value is a BARE INTEGER in the canonical form.

        No exponent, no fractional part, no quotes, at the boundary 2**53 - 1. A float
        round-trip is the failure this pins: `9007199254740991` becoming `9.007199254740991e15`
        hashes differently on the two sides while both still 'serialise the same number'.

        It also records an ASYMMETRY rather than asserting it away: `_is_u64_ms` accepts up to
        2**64, while Rust's `MAX_GOVERNED_MS` is 2**53 - 1. The Python predicate is WIDER, so a
        timestamp Python accepts can still be refused across the wall -- measured here so the
        next reader does not discover it from a failing deployment.
        """
        case = "NM-PARITY-09"
        jcs = json.dumps(PARITY_MS_OBJECT, sort_keys=True, separators=(",", ":")).encode("utf-8")
        self.assertEqual(jcs, PARITY_MS_JCS, case)
        self.assertEqual(signer._jcs_bytes(PARITY_MS_OBJECT), PARITY_MS_JCS,
                         f"{case}: the signer's own canonicaliser must agree")
        self.assertEqual(hashlib.sha256(jcs).hexdigest(), PARITY_MS_SHA256, case)
        for forbidden in (b"e+", b"E+", b".0", b'"9007199254740991"'):
            self.assertNotIn(forbidden, jcs, f"{case}: {forbidden!r} in the canonical form")
        # The asymmetry, asserted so it cannot be quietly closed in one direction only.
        self.assertTrue(signer._is_u64_ms(MAX_GOVERNED_MS), case)
        self.assertTrue(signer._is_u64_ms(1 << 53),
                        f"{case}: the Python predicate is wider than MAX_GOVERNED_MS")

if __name__ == "__main__":
    unittest.main()
