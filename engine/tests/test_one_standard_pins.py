"""One contract, one standard — the pins that make a second implementation visible.

Six times in three days this repository shipped the same defect: one contract with two
implementations, agreement asserted only in a comment, discovered by accident after it had
already cost a failed run or a false green. `challenge_handle` hashed two ways. Two spawn
seams. An isolated-signer transport whose wire reply was not its own documented shape. A
§4.10(f) ladder whose `create_schema` silently no-op'd the canonical DDL.

Every one of those pairs was **documented as agreeing**. None of them was **checked**.

This module is the check, for the pairs that remain deliberate — and for the ones that are
duplicates only because the two halves are compiled by different toolchains and no
type-checker ever sees both.

Three kinds of assertion live here, and the difference matters:

  1. **AGREEMENT** — several sites that must produce byte-identical output. Asserted over a
     corpus that includes the exact inputs on which a plausible wrong implementation would
     diverge (non-ASCII, in particular: every one of these formulas is `json.dumps` with a
     different `ensure_ascii`, and for ASCII-only input all of them agree, which is why the
     divergence has never been noticed in production data).
  2. **A PINNED DIFFERENCE** — pairs that are deliberately NOT the same and must stay that
     way. Collapsing them would silently change what gets signed. `brops_canonical` already
     holds one such pair (the frozen raw-string generation-config form versus the governed
     object form) and pins it; these are the others.
  3. **CROSS-LANGUAGE CONSTANTS** — the Python constant and the Rust `pub const` read out of
     the Rust source file. Two languages, two builds, no shared header: a literal that moves
     on one side and not the other is invisible to both compilers and to every unit test on
     either side. This reads the other side's source text, which is the only mechanism that
     can see it at all.

No prerequisite here is optional. The pure-Python classes import at module scope with no
``try``/``except`` and no ``skipIf``, so a missing prerequisite is a hard error rather than a
quiet skip. The cross-language class declares ``DESKTOP_GOVERNED_SOURCE`` through
``_prerequisites.require``, which SKIPS only off a CI runner (a deployed box copies
``engine/`` alone) and FAILS on one. There is no ``BROPS_TEST_MISSING_PREREQUISITES``
declaration anywhere in this tree, so nothing here may be softened.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
sys.path.insert(0, str(ROOT / "runtime"))

import _prerequisites  # noqa: E402
import bro_audit_log  # noqa: E402
import bro_security  # noqa: E402
import bro_signature  # noqa: E402
import brops_canonical  # noqa: E402
import challenge_authority  # noqa: E402
import challenge_key_registry  # noqa: E402
import governed_staging_upload  # noqa: E402
import governed_supervisor  # noqa: E402
import governed_supervisor_ledger  # noqa: E402
import governed_supervisor_server  # noqa: E402
import governed_turn_open  # noqa: E402
import isolated_signer  # noqa: E402
import isolated_signer_server  # noqa: E402
from challenge_authority_server import MAX_FRAME_BYTES as AUTHORITY_FRAME_CAP  # noqa: E402
from challenge_authority_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES as AUTHORITY_PREFIX,
    OP_CREATE_PENDING,
    OP_ISSUE,
)
from governed_supervisor_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES as SUPERVISOR_PREFIX,
    MAX_FRAME_BYTES as SUPERVISOR_FRAME_CAP,
    OP_ACCEPT_OPEN,
    OP_ATTEST_RUN,
    OP_COMPLETE_RUN,
    OP_EXECUTION_STARTED,
    OP_LAUNCH_GATE,
)
from isolated_signer_server import (  # noqa: E402
    LENGTH_PREFIX_BYTES as SIGNER_PREFIX,
    MAX_FRAME_BYTES as SIGNER_FRAME_CAP,
    OP_SIGN_RESULT,
)

TAURI = REPO_ROOT / "apps" / "desktop" / "src-tauri"

# ---------------------------------------------------------------------------
# The corpus. Every value that distinguishes the two encodings is in here on purpose.
# ---------------------------------------------------------------------------

#: Objects an agreement assertion is worthless without. `NON_ASCII` is the one that
#: separates `ensure_ascii=True` from `ensure_ascii=False`; the rest cover key ordering,
#: nesting, bare integers, and the two Unicode line terminators.
NON_ASCII = {"a": "é✈", "n": {"b": [1, " x"]}, "z": 1}
CORPUS = (
    {},
    {"b": "2", "a": "1"},
    {"protocol": "brops.request.v1", "requested_at": "1000"},
    {"i": 0, "j": -1, "k": 2 ** 53},
    {"nested": {"deep": {"deeper": ["x", 1, {"y": "z"}]}}},
    NON_ASCII,
    {"terminators": "  ", "quote": '"', "back": "\\", "ctl": ""},
)


def _reference_governed(value) -> bytes:
    """The governed family's formula, written out once here so the assertion compares each
    module against the FORMULA and not merely against its neighbours (five copies of the
    same mistake agree with each other perfectly)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _reference_rust_facing(value) -> bytes:
    """The Rust-facing formula: the same, with `ensure_ascii=False`. This is what
    `serde_json::to_vec` of a sorted map emits, so it is the encoding a Rust verifier
    reconstructs."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# 1. AGREEMENT — the governed family's canonicalizer
# ---------------------------------------------------------------------------


class TheGovernedCanonicalizerHasOneStandard(unittest.TestCase):
    """Five modules each spell `canonical_bytes` out for themselves.

    That is DELIBERATE and must stay: the challenge authority, the supervisor, the ledger,
    the key registry and the isolated signer are separate trusted principals, each running
    in its own process; making four of them import the fifth would put the fifth's code
    inside the others' TCB to save four lines. So the duplication is the right call — but
    "byte-identical" was, until now, asserted only in their docstrings, and the whole
    governed chain's signatures verify only while it is true.
    """

    FAMILY = {
        "challenge_authority._canonical_bytes": challenge_authority._canonical_bytes,
        "challenge_key_registry.canonical_bytes": challenge_key_registry.canonical_bytes,
        "governed_supervisor._canonical_bytes": governed_supervisor._canonical_bytes,
        "governed_supervisor_ledger.canonical_bytes": governed_supervisor_ledger.canonical_bytes,
        "isolated_signer._canonical_bytes": isolated_signer._canonical_bytes,
        "bro_audit_log._canonical": lambda v: bro_audit_log._canonical(v).encode("utf-8"),
    }

    def test_every_governed_canonicalizer_is_byte_identical_to_the_formula(self):
        for value in CORPUS:
            expected = _reference_governed(value)
            for name, fn in self.FAMILY.items():
                with self.subTest(fn=name, value=value):
                    self.assertEqual(fn(value), expected)

    def test_the_corpus_can_actually_tell_the_two_encodings_apart(self):
        """A guard on the guard. If every corpus entry were ASCII, the assertion above
        would pass against an `ensure_ascii=False` implementation too — it would prove
        nothing at all. This fails if someone ever trims the corpus down to that."""
        distinguishing = [
            v for v in CORPUS if _reference_governed(v) != _reference_rust_facing(v)
        ]
        self.assertTrue(
            distinguishing,
            "the corpus contains no value on which ensure_ascii matters, so the "
            "agreement assertions above cannot fail for the reason they exist",
        )


# ---------------------------------------------------------------------------
# 2. A PINNED DIFFERENCE — the two encoding families are NOT interchangeable
# ---------------------------------------------------------------------------


class TheTwoEncodingFamiliesMustStayDifferent(unittest.TestCase):
    """`bro_signature.canonical_bytes` and the governed family differ in exactly one
    argument (`ensure_ascii`), and for every ASCII input they are the same bytes.

    They are used for different signatures: the governed chain signs the `ensure_ascii=True`
    encoding end to end, while the receipt-envelope / request-envelope formulas sign the
    `ensure_ascii=False` one because a Rust `serde_json` verifier reconstructs THAT. Swapping
    one for the other is a one-word edit that no ASCII fixture can catch and that turns every
    non-ASCII-bearing signature into a signature the verifier reconstructs differently.

    So this pins the DIFFERENCE, rather than collapsing the pair.
    """

    def test_the_governed_encoding_is_not_the_rust_facing_encoding(self):
        self.assertNotEqual(
            governed_supervisor._canonical_bytes(NON_ASCII),
            bro_signature.canonical_bytes(NON_ASCII),
            "the governed family must escape non-ASCII and the Rust-facing family must "
            "not; if these are equal, one of the two families has been 'unified' and a "
            "whole class of signatures now reconstructs differently on the other side",
        )

    def test_the_rust_facing_family_agrees_with_itself(self):
        for value in CORPUS:
            expected = _reference_rust_facing(value)
            with self.subTest(value=value):
                self.assertEqual(bro_signature.canonical_bytes(value), expected)
                self.assertEqual(bro_security.canonical_bytes(value), expected)
                self.assertEqual(isolated_signer._jcs_bytes(value), expected)

    def test_the_isolated_signers_own_two_encoders_are_a_deliberate_pair(self):
        """`isolated_signer` holds BOTH: `_canonical_bytes` for the evidence digest the
        supervisor signed, `_jcs_bytes` for the receipt payload the Rust broker
        reconstructs. Real evidence carries only hex/ids/ints, so on production data the two
        produce identical bytes — a swap would be invisible to every fixture in the signer's
        own suite. This is the assertion that sees it."""
        self.assertNotEqual(
            isolated_signer._canonical_bytes(NON_ASCII),
            isolated_signer._jcs_bytes(NON_ASCII),
        )


# ---------------------------------------------------------------------------
# 3. AGREEMENT — the §2.2 request envelope is computed in three places
# ---------------------------------------------------------------------------


class TheRequestEnvelopeHasOneFormula(unittest.TestCase):
    """`request_sha256` is recomputed independently by the challenge authority (§2.1: it
    derives the digest, never accepts one), by the isolated signer (§4.9: it never trusts a
    transported one), and by `brops_canonical` (the signer-side single source). That
    independence is the point — but all three must land on the same 32 bytes or the broker's
    final `verify_and_accept` binding fails and every turn Blocks.

    `challenge_authority._request_envelope_bytes` does NOT use its own module's
    `_canonical_bytes`: it inlines `ensure_ascii=False`, because this envelope belongs to the
    Rust-facing family. A reader who "tidied" that into the module's neighbouring helper
    would break the chain for any non-ASCII `workspace_id`/`install_id` and no ASCII fixture
    would notice. Hence the non-ASCII ids below.
    """

    FACTS = {
        "workspace_id": "ws-é",
        "install_id": "install-✈",
        "request_nonce": "11111111-1111-4111-8111-111111111111",
        "system_sha256": "a" * 64,
        "history_sha256": "b" * 64,
        "generation_config_sha256": "c" * 64,
        "requested_at_ms": 1000,
    }

    def _all_three(self):
        authority = challenge_authority.recompute_request_sha256(self.FACTS)
        canonical = brops_canonical.request_sha256(
            workspace_id=self.FACTS["workspace_id"],
            install_id=self.FACTS["install_id"],
            request_nonce=self.FACTS["request_nonce"],
            system_sha256=self.FACTS["system_sha256"],
            history_sha256=self.FACTS["history_sha256"],
            generation_config_sha256=self.FACTS["generation_config_sha256"],
            requested_at=str(self.FACTS["requested_at_ms"]),
        )
        # An unbound call: `_recompute_request_sha256` reads only its two arguments, so this
        # exercises the SHIPPED method rather than a re-derivation of it.
        signer = isolated_signer.IsolatedSigner._recompute_request_sha256(
            None,
            {
                "workspace_id": self.FACTS["workspace_id"],
                "install_id": self.FACTS["install_id"],
                "request_nonce": self.FACTS["request_nonce"],
                "requested_at": self.FACTS["requested_at_ms"],
            },
            {
                "system_sha256": self.FACTS["system_sha256"],
                "history_sha256": self.FACTS["history_sha256"],
                "generation_config_sha256": self.FACTS["generation_config_sha256"],
            },
        )
        return authority, canonical, signer

    def test_all_three_recomputations_agree_including_non_ascii_ids(self):
        authority, canonical, signer = self._all_three()
        self.assertEqual(authority, canonical)
        self.assertEqual(canonical, signer)

    def test_the_declared_request_field_set_is_the_one_that_is_hashed(self):
        """`brops_canonical._REQUEST_FIELDS` had no reader in the whole tree: it declared the
        §2.2 field set while `request_sha256` built its own dict literal beside it. A field
        added to one and not the other would have changed nothing and warned nobody. It now
        has exactly one reader, and it is this."""
        envelope = {
            "protocol": brops_canonical.REQUEST_PROTOCOL,
            "workspace_id": "w",
            "install_id": "i",
            "request_nonce": "n",
            "system_sha256": "a" * 64,
            "history_sha256": "b" * 64,
            "generation_config_sha256": "c" * 64,
            "requested_at": "1000",
        }
        self.assertEqual(set(brops_canonical._REQUEST_FIELDS), set(envelope))
        # ... and the digest of exactly that field set is what `request_sha256` returns.
        import hashlib

        self.assertEqual(
            brops_canonical.request_sha256(
                workspace_id="w",
                install_id="i",
                request_nonce="n",
                system_sha256="a" * 64,
                history_sha256="b" * 64,
                generation_config_sha256="c" * 64,
                requested_at="1000",
            ),
            hashlib.sha256(_reference_rust_facing(envelope)).hexdigest(),
        )


# ---------------------------------------------------------------------------
# 4. AGREEMENT — the wire lease is derived, not retyped
# ---------------------------------------------------------------------------


class TheWireLeaseIsTheDataclass(unittest.TestCase):
    def test_lease_fields_is_derived_from_the_dataclass(self):
        import dataclasses

        self.assertEqual(
            governed_supervisor_server.LEASE_FIELDS,
            tuple(f.name for f in dataclasses.fields(governed_supervisor.Lease)),
        )

    def test_the_marshalled_lease_carries_exactly_the_dataclass_fields(self):
        lease = governed_supervisor.Lease(
            lease_id="L1",
            execution_attempt_id="A1",
            lease_expires_at_ms=1000,
            launcher_executable_sha256="a" * 64,
            executor_executable_sha256="b" * 64,
        )
        wire = governed_supervisor_server._lease_to_dict(lease)
        self.assertEqual(set(wire), set(governed_supervisor_server.LEASE_FIELDS))
        for name in governed_supervisor_server.LEASE_FIELDS:
            self.assertEqual(wire[name], getattr(lease, name))


# ---------------------------------------------------------------------------
# 5. AGREEMENT — one id cap, one lease budget, one set of protocol names
# ---------------------------------------------------------------------------


class ThePythonHalfHasOneNumberPerRule(unittest.TestCase):
    def test_max_id_len_is_one_number(self):
        self.assertEqual(
            {
                challenge_authority.MAX_ID_LEN,
                challenge_key_registry.MAX_ID_LEN,
                governed_staging_upload.MAX_ID_LEN,
                governed_turn_open.MAX_ID_LEN,
            },
            {128},
        )

    def test_the_supervisor_stamps_the_window_the_ledger_gates(self):
        """`governed_supervisor` stamps `lease_expires_at_ms = now + LEASE_DURATION_MS`;
        `governed_supervisor_ledger` refuses a launch under `MIN_LAUNCH_REMAINING_MS`. Two
        different literals would issue a lease for a window the gate will not honour."""
        self.assertIs(
            governed_supervisor.LEASE_DURATION_MS,
            governed_supervisor_ledger.LEASE_DURATION_MS,
        )
        self.assertIs(
            governed_supervisor.MIN_LAUNCH_REMAINING_MS,
            governed_supervisor_ledger.MIN_LAUNCH_REMAINING_MS,
        )

    def test_the_protocol_names_are_one_string_each(self):
        self.assertEqual(
            challenge_authority.CHALLENGE_PROTOCOL, governed_supervisor.CHALLENGE_PROTOCOL
        )
        self.assertEqual(
            governed_supervisor.ATTESTATION_PROTOCOL, isolated_signer.ATTESTATION_PROTOCOL
        )
        self.assertEqual(
            {
                challenge_authority.REQUEST_ENVELOPE_PROTOCOL,
                governed_supervisor.REQUEST_ENVELOPE_PROTOCOL,
                isolated_signer.REQUEST_PROTOCOL,
                brops_canonical.REQUEST_PROTOCOL,
            },
            {"brops.request.v1"},
        )


# ---------------------------------------------------------------------------
# 6. CROSS-LANGUAGE — the Rust `pub const` read out of the Rust source
# ---------------------------------------------------------------------------

_PUB_CONST = re.compile(
    r"^\s*pub const (?P<name>[A-Z0-9_]+)\s*:\s*[^=]+=\s*(?P<value>[^;]+);", re.M
)


def rust_consts(relative: str) -> dict[str, str]:
    """Every `pub const NAME: T = VALUE;` in a Rust source file, as raw text.

    Reading source text is a weak mechanism and this says so rather than implying otherwise:
    it cannot see a constant behind a `cfg`, a macro, or an expression. What it CAN see is a
    literal that moved on one side of the language boundary and not the other, which is the
    only failure this pins and is a failure nothing else in either build can observe.
    """
    path = TAURI / relative
    source = path.read_text(encoding="utf-8")
    found = {m.group("name"): m.group("value").strip() for m in _PUB_CONST.finditer(source)}
    if not found:
        raise AssertionError(
            f"no `pub const` found in {path} — the file moved or the shape changed, and a "
            "silently-empty extraction would make every assertion below vacuously true"
        )
    return found


def rust_int(consts: dict[str, str], name: str) -> int:
    if name not in consts:
        raise AssertionError(f"Rust const {name} is gone; the pin below covers nothing")
    return int(consts[name].replace("_", ""))


def rust_str(consts: dict[str, str], name: str) -> str:
    if name not in consts:
        raise AssertionError(f"Rust const {name} is gone; the pin below covers nothing")
    return json.loads(consts[name])


@_prerequisites.requires(_prerequisites.DESKTOP_GOVERNED_SOURCE)
class ThePythonAndRustHalvesShareOneNumber(unittest.TestCase):
    """Neither compiler sees both halves. A unit test on either side sees only its own
    literal. This is the only place a divergence between them is observable at all."""

    def setUp(self):
        self.ledger = rust_consts("core/src/supervisor_ledger.rs")
        self.prepare = rust_consts("core/src/governed_prepare.rs")
        self.framing = rust_consts("core/src/ipc_framing.rs")
        self.receipt = rust_consts("core/src/receipt.rs")
        self.verification = rust_consts("core/src/governed_verification.rs")
        self.servers = rust_consts("win-live/src/servers.rs")

    def test_the_lease_budget_is_the_same_number_in_both_languages(self):
        self.assertEqual(
            governed_supervisor_ledger.LEASE_DURATION_MS,
            rust_int(self.ledger, "LEASE_DURATION_MS"),
        )
        self.assertEqual(
            governed_supervisor_ledger.MIN_LAUNCH_REMAINING_MS,
            rust_int(self.ledger, "MIN_LAUNCH_REMAINING_MS"),
        )
    def test_the_id_cap_is_the_same_number_in_both_languages(self):
        self.assertEqual(challenge_authority.MAX_ID_LEN, rust_int(self.prepare, "MAX_ID_LEN"))

    def test_the_windows_twin_re_exports_rather_than_re_declares(self):
        """The Windows twin used to carry its OWN `MAX_ID_LEN` / `LEASE_DURATION_MS` /
        `MIN_LAUNCH_REMAINING_MS` literals. They are now `pub use` re-exports of the
        `brops-core` constants, which is strictly stronger than this file's source-text pin:
        `rustc` refuses to let a second value exist. This asserts the re-export is still
        there, so a future edit that "simplifies" it back into a local literal reintroduces
        a second copy loudly instead of silently."""
        source = (TAURI / "win-live" / "src" / "servers.rs").read_text(encoding="utf-8")
        self.assertIn("pub use brops_core::governed_prepare::MAX_ID_LEN;", source)
        self.assertIn(
            "pub use brops_core::supervisor_ledger::{LEASE_DURATION_MS, MIN_LAUNCH_REMAINING_MS};",
            source,
        )
        for redeclared in ("pub const MAX_ID_LEN", "pub const LEASE_DURATION_MS",
                           "pub const MIN_LAUNCH_REMAINING_MS"):
            self.assertNotIn(redeclared, source)

    def test_the_challenge_ttl_cap_is_the_same_number_in_both_languages(self):
        self.assertEqual(
            challenge_authority.MAX_CHALLENGE_TTL_MS, rust_int(self.servers, "CHALLENGE_TTL_MS")
        )
        self.assertEqual(
            challenge_authority.PENDING_TTL_MS, rust_int(self.servers, "PENDING_TTL_MS")
        )
        self.assertEqual(
            governed_supervisor.MAX_CHALLENGE_TTL_MS,
            challenge_authority.MAX_CHALLENGE_TTL_MS,
        )

    def test_the_protocol_names_are_the_same_string_in_both_languages(self):
        self.assertEqual(
            brops_canonical.REQUEST_PROTOCOL, rust_str(self.receipt, "REQUEST_PROTOCOL")
        )
        self.assertEqual(
            brops_canonical.RECEIPT_PROTOCOL, rust_str(self.receipt, "RECEIPT_PROTOCOL")
        )
        self.assertEqual(
            challenge_authority.CHALLENGE_PROTOCOL, rust_str(self.servers, "CHALLENGE_PROTOCOL")
        )
        self.assertEqual(
            isolated_signer.ATTESTATION_PROTOCOL, rust_str(self.servers, "ATTESTATION_PROTOCOL")
        )
        self.assertEqual(
            isolated_signer.SIGN_REQUEST_PROTOCOL,
            rust_str(self.servers, "SIGN_REQUEST_PROTOCOL"),
        )
        self.assertEqual(
            isolated_signer.ENVELOPE_ARTIFACT_TYPE,
            rust_str(self.servers, "ENVELOPE_ARTIFACT_TYPE"),
        )
        self.assertEqual(
            isolated_signer.ENVELOPE_ARTIFACT_TYPE,
            rust_str(self.verification, "RECEIPT_ENVELOPE_ARTIFACT_TYPE"),
        )

    def test_the_frame_prefix_width_is_the_same_in_both_languages(self):
        rust_prefix = rust_int(self.framing, "LENGTH_PREFIX_BYTES")
        self.assertEqual({AUTHORITY_PREFIX, SUPERVISOR_PREFIX, SIGNER_PREFIX}, {rust_prefix})


@_prerequisites.requires(_prerequisites.DESKTOP_GOVERNED_SOURCE)
class TheFrameCapAsymmetryIsPinnedNotAssumed(unittest.TestCase):
    """The three Python servers declare three different whole-frame caps, and the Rust
    broker — the only production client of all three — declares a fourth.

    `isolated_signer_server` documents its 512 KiB cap as sitting "comfortably above" the
    signer's own limit "so a well-formed request always reaches the signer's own oversize
    gate". On the deployed path that sentence is FALSE: `ipc_framing::encode_frame` refuses
    anything over 8192 before it is sent, and `decode_one` refuses a reply that declares more,
    so no frame between 8193 and 524288 bytes can ever cross. The signer's own suite exercises
    sizes the deployment cannot deliver.

    This is fail-closed in both directions, so it is not a hole — but it IS two contracts for
    one hop, and the file says the opposite of what ships. Reserved as a mapped item rather
    than silently widened or narrowed: changing either number changes what the deployment
    accepts. What is pinned here is the asymmetry itself, so it is a fact the suite states
    rather than a surprise the next live run discovers.
    """

    def test_the_broker_cap_is_the_binding_one_on_every_hop(self):
        broker_cap = rust_int(rust_consts("core/src/ipc_framing.rs"), "MAX_FRAME_PAYLOAD_BYTES")
        self.assertEqual(AUTHORITY_FRAME_CAP, broker_cap)
        self.assertEqual(SUPERVISOR_FRAME_CAP, broker_cap)
        # The signer is the outlier, and it is the LOOSER of the pair, so the broker's cap
        # binds. If this ever inverts, a server would accept a frame its only client cannot
        # send — or, worse, emit a reply its only client cannot decode.
        self.assertGreater(SIGNER_FRAME_CAP, broker_cap)
        self.assertEqual(min(AUTHORITY_FRAME_CAP, SUPERVISOR_FRAME_CAP, SIGNER_FRAME_CAP),
                         broker_cap)


@_prerequisites.requires(_prerequisites.DESKTOP_GOVERNED_SOURCE)
class TheThreePrincipalsAnswerToOneOpVocabulary(unittest.TestCase):
    """The op names are the whole routing contract, and they exist in THREE places in two
    languages: the Python servers' `OP_*` constants, the Rust Windows twin's `dispatch` match
    arms, and the broker's request builders. Nothing links them. An op added to one and not
    the others is a hop that silently fails closed on one platform only — which is exactly
    how the isolated-signer transport shipped with a `dispatch` that refused a bare
    sign-request.
    """

    PY_OPS = frozenset(
        {
            OP_CREATE_PENDING,
            OP_ISSUE,
            OP_ACCEPT_OPEN,
            OP_LAUNCH_GATE,
            OP_EXECUTION_STARTED,
            OP_COMPLETE_RUN,
            OP_ATTEST_RUN,
            OP_SIGN_RESULT,
        }
    )

    def test_the_windows_twin_dispatches_exactly_the_python_ops(self):
        source = (TAURI / "win-live" / "src" / "servers.rs").read_text(encoding="utf-8")
        arms = frozenset(re.findall(r'Some\("([a-z][a-z-]*)"\)\s*=>\s*self\.', source))
        self.assertTrue(arms, "no dispatch arms extracted; the pin would be vacuous")
        self.assertEqual(arms, self.PY_OPS)

    def test_the_broker_requests_exactly_the_python_ops(self):
        source = (TAURI / "broker" / "src" / "chain_executor.rs").read_text(encoding="utf-8")
        ops = frozenset(re.findall(r'"op":\s*"([a-z][a-z-]*)"', source))
        self.assertTrue(ops, "no broker ops extracted; the pin would be vacuous")
        self.assertEqual(ops, self.PY_OPS)


if __name__ == "__main__":
    unittest.main()
