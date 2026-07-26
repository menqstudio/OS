"""Pure (socket-free) tests for the §4.10(h) diagnostic vocabulary + transport-failure frame.

These run on every platform (no AF_UNIX dependency): they exercise the bounded_diagnostic /
transport_failure helpers that carry internal refusals and transport failures to the desktop.
"""
from __future__ import annotations

import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
for sub in ("runtime", "tools"):
    sys.path.insert(0, str(ROOT / sub))

from bro_signature import canonical_bytes  # noqa: E402
from brops_governed_common import (  # noqa: E402
    DIAGNOSTIC_STAGES, MAX_DIAGNOSTIC_BYTES, TRANSPORT_FAILURE_PROTOCOL,
    bounded_diagnostic, transport_failure,
)

_DIAGNOSTIC_PROTOCOL = "bridge.governed-turn-diagnostic.v1"
_FORBIDDEN = ("envelope_jcs_b64", "signature_b64", "output_stream_id", "ok", "receipt", "error")


class DiagnosticVocabularyTests(unittest.TestCase):
    def test_exactly_the_five_locked_stages(self):
        self.assertEqual(
            set(DIAGNOSTIC_STAGES),
            {"governed-turn-open", "staging-open", "staging-chunk", "staging-final", "evidence-request"},
        )

    def test_each_stage_produces_a_bounded_three_field_diagnostic(self):
        for stage in DIAGNOSTIC_STAGES:
            obj = bounded_diagnostic(stage, "malformed")
            self.assertEqual(obj["protocol"], _DIAGNOSTIC_PROTOCOL)
            self.assertEqual(obj["stage"], stage)
            self.assertEqual(set(obj), {"protocol", "stage", "upstream_reason"})
            self.assertLessEqual(len(canonical_bytes(obj)), MAX_DIAGNOSTIC_BYTES)

    def test_invalid_stage_degrades_to_transport_failure(self):
        # The old collapsed vocabulary (authority/supervisor/transport) is no longer a valid
        # diagnostic stage: any such value degrades to a transport_failure frame (rule-4 catch-all).
        for bad in ("authority", "supervisor", "transport", "", "bogus-stage"):
            obj = bounded_diagnostic(bad, "boom")
            self.assertEqual(obj["protocol"], TRANSPORT_FAILURE_PROTOCOL)
            self.assertNotIn("stage", obj)

    def test_diagnostic_can_never_look_signed(self):
        obj = bounded_diagnostic("staging-final", "sha_mismatch")
        for forbidden in _FORBIDDEN:
            self.assertNotIn(forbidden, obj)

    def test_reason_is_truncated_to_keep_the_frame_bounded(self):
        obj = bounded_diagnostic("governed-turn-open", "y" * 10_000)
        self.assertEqual(obj["stage"], "governed-turn-open")
        self.assertLessEqual(len(canonical_bytes(obj)), MAX_DIAGNOSTIC_BYTES)

    def test_transport_failure_is_a_distinct_bounded_two_field_frame(self):
        obj = transport_failure("x" * 10_000)
        self.assertEqual(obj["protocol"], TRANSPORT_FAILURE_PROTOCOL)
        self.assertEqual(set(obj), {"protocol", "detail"})
        self.assertNotEqual(obj["protocol"], _DIAGNOSTIC_PROTOCOL)
        self.assertLessEqual(len(canonical_bytes(obj)), MAX_DIAGNOSTIC_BYTES)
        for forbidden in _FORBIDDEN:
            self.assertNotIn(forbidden, obj)


if __name__ == "__main__":
    unittest.main()
