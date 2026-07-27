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

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))
sys.path.insert(0, str(ROOT / "tools"))

import brops_canonical as bc

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

    def test_output_formula(self):
        self.assertEqual(bc.output_sha256(OUTPUT), OUTPUT_SHA)

    def test_generation_config_formula(self):
        self.assertEqual(bc.generation_config_sha256(GEN_CONFIG), GEN_SHA)

    def test_containment_formula(self):
        self.assertEqual(bc.containment_evidence_sha256(CONTAINMENT), CONTAINMENT_SHA)

    def test_policy_bundle_formula(self):
        self.assertEqual(bc.policy_bundle_sha256(POLICY_BUNDLE), POLICY_SHA)

    def test_request_envelope_formula(self):
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


if __name__ == "__main__":
    unittest.main()
