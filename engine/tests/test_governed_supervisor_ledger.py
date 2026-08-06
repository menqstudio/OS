"""Offline tests for the supervisor's DURABLE acceptance/lease/completion ledger.

These are the regression tests for the independent audit's **F-01 (P0)**: the supervisor
used to hold no run state, so ``attest-run`` was a sign-arbitrary-facts oracle for the
broker uid. The property proven here is the one that makes an attestation mean something:

    **a fabricated run has no durable state, so no evidence can be built for it.**

Everything runs on an in-memory SQLite database with injected clocks — no socket, no
signer, no OS trust chain.
"""

import pathlib
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_supervisor_ledger as gsl  # noqa: E402

H_A = "a" * 64
H_B = "b" * 64
H_C = "c" * 64


_OPEN = []


def _conn():
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    gsl.apply_schema(conn)
    _OPEN.append(conn)
    return conn


def tearDownModule():
    # In-memory databases vanish with the process anyway; closing them keeps the suite's
    # output free of ResourceWarnings so a REAL warning stays visible.
    while _OPEN:
        try:
            _OPEN.pop().close()
        except sqlite3.Error:
            pass


def _acceptance(attempt="att-1", **over):
    fields = dict(
        install_id="install-1",
        request_nonce="nonce-%s" % attempt,
        challenge_handle="chal-%s" % attempt,
        run_id="run-1",
        task_id="task-1",
        workspace_id="ws-1",
        execution_attempt_id=attempt,
        challenge_accepted_at_ms=1_000_000,
        challenge_registry_handle="reg-h",
        challenge_registry_hash="reg-hash",
        challenge_registry_epoch=7,
        challenge_registry_root_key_id="root-1",
        lease_payload_bytes=b"lease-payload-bytes",
        lease_id="lease-%s" % attempt,
        lease_issued_at_ms=1_000_000,
        lease_expires_at_ms=1_000_000 + gsl.LEASE_DURATION_MS,
        receipt_id="receipt-%s" % attempt,
        supervisor_id="supervisor-1",
        requested_at_ms=999_000,
        request_sha256=H_A,
        system_handle=H_A,
        history_handle=H_B,
        generation_config_handle=H_C,
    )
    fields.update(over)
    return gsl.NewAcceptance(**fields)


#: The three handles the SUPERVISOR derives and publishes (F-02) — never part of `produced`.
# What the SUPERVISOR contributes: the three terminal handles it publishes (F-02) and the
# evidence head it reads out of the recorder's chain (F-01). None of it comes from the wire.
DERIVED = {
    "record_handle": H_C,
    "lease_handle": H_A,
    "execution_receipt_handle": H_B,
    "evidence_final_event_hash": H_C,
    "evidence_event_count": 3,
    "evidence_last_sequence": 3,
    "evidence_head_sequence": 12,
}


def _derived(**over):
    d = dict(DERIVED)
    d.update(over)
    return d


def _produced(**over):
    facts = dict(
        output_handle=H_A,
        containment_evidence_handle=H_B,
        completed_at_ms=1_050_000,
    )
    facts.update(over)
    return facts


def _drive_to_executing(conn, attempt="att-1", acceptance=None):
    gsl.accept_prepare(conn, acceptance or _acceptance(attempt), 10)
    gsl.mark_lease_ready(conn, attempt, "lease-h", 20)
    gsl.gate_and_start(conn, attempt, 1_000_000)
    gsl.mark_executing(conn, attempt, process_group_id="pg", cgroup_id="cg",
                       execution_started_marker=None, now_ms=30)


# ---------------------------------------------------------------------------
# Acceptance CAS — one signed challenge is worth exactly ONE execution attempt.
# ---------------------------------------------------------------------------


class AcceptanceCasTests(unittest.TestCase):
    def test_first_acceptance_is_created(self):
        conn = _conn()
        self.assertEqual(gsl.accept_prepare(conn, _acceptance(), 10), gsl.CREATED)
        self.assertEqual(gsl._current_state(conn, "att-1"), gsl.ACCEPTED_PREPARED)

    def test_identical_replay_is_idempotent_not_a_second_attempt(self):
        conn = _conn()
        a = _acceptance()
        self.assertEqual(gsl.accept_prepare(conn, a, 10), gsl.CREATED)
        self.assertEqual(gsl.accept_prepare(conn, a, 11), gsl.IDEMPOTENT)
        count = conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0]
        self.assertEqual(count, 1)

    def test_replayed_nonce_bound_to_a_different_turn_is_refused(self):
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        clash = _acceptance("att-2", request_nonce="nonce-att-1")
        with self.assertRaises(gsl.Conflict):
            gsl.accept_prepare(conn, clash, 20)

    def test_replayed_challenge_with_a_fresh_nonce_is_refused(self):
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        clash = _acceptance("att-3", challenge_handle="chal-att-1")
        with self.assertRaises(gsl.Conflict):
            gsl.accept_prepare(conn, clash, 20)

    def test_retry_with_a_different_request_binding_is_refused(self):
        # Same nonce/challenge/attempt but a different signed request digest: this is NOT
        # the same turn, so it must not silently reuse the accepted attempt.
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        with self.assertRaises(gsl.Conflict):
            gsl.accept_prepare(conn, _acceptance(request_sha256=H_B), 20)

    def test_receipt_id_is_unique_across_attempts(self):
        # receipt_id is the §7.1(d) global-unique replay key; two attempts must never share one.
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        with self.assertRaises(gsl.Conflict):
            gsl.accept_prepare(conn, _acceptance("att-2", receipt_id="receipt-att-1"), 20)


class ReuseOrPrepareTests(unittest.TestCase):
    """The front-door operation: accept a challenge ONCE, tolerate an honest retry."""

    def test_a_fresh_challenge_creates_the_attempt(self):
        conn = _conn()
        outcome, row = gsl.reuse_or_prepare(conn, _acceptance(), 10)
        self.assertEqual(outcome, gsl.CREATED)
        self.assertEqual(row["execution_attempt_id"], "att-1")

    def test_a_replayed_challenge_returns_the_ORIGINAL_attempt_not_a_second_one(self):
        # This is the property F-01 depends on. The supervisor mints fresh ids every call,
        # so a resubmitted challenge arrives with a brand-new attempt/lease/receipt id — and
        # must still resolve to the attempt already accepted, never to an additional one.
        conn = _conn()
        first, row1 = gsl.reuse_or_prepare(conn, _acceptance("att-1"), 10)
        retry = _acceptance(
            "att-SECOND",
            request_nonce="nonce-att-1",
            challenge_handle="chal-att-1",  # the same signed challenge
            receipt_id="receipt-SECOND",
            lease_id="lease-SECOND",
        )
        second, row2 = gsl.reuse_or_prepare(conn, retry, 20)
        self.assertEqual((first, second), (gsl.CREATED, gsl.IDEMPOTENT))
        self.assertEqual(row2["execution_attempt_id"], row1["execution_attempt_id"])
        self.assertEqual(row2["receipt_id"], "receipt-att-1")
        count = conn.execute("SELECT COUNT(*) FROM governed_turn_acceptance").fetchone()[0]
        self.assertEqual(count, 1)

    def test_a_challenge_rebound_to_a_different_turn_is_refused(self):
        conn = _conn()
        gsl.reuse_or_prepare(conn, _acceptance("att-1"), 10)
        rebound = _acceptance("att-2", challenge_handle="chal-att-1")  # fresh nonce
        with self.assertRaises(gsl.Conflict):
            gsl.reuse_or_prepare(conn, rebound, 20)


# ---------------------------------------------------------------------------
# The launch gate now runs against the supervisor's OWN persisted lease window.
# ---------------------------------------------------------------------------


class LaunchGateTests(unittest.TestCase):
    def test_budget_boundary_matches_the_rust_twin(self):
        issued = 1_000
        expires = issued + gsl.LEASE_DURATION_MS
        self.assertEqual(
            gsl.lease_launch_gate(expires - (gsl.MIN_LAUNCH_REMAINING_MS - 1), issued, expires),
            "insufficient_remaining_budget",
        )
        self.assertIsNone(
            gsl.lease_launch_gate(expires - gsl.MIN_LAUNCH_REMAINING_MS, issued, expires)
        )
        self.assertEqual(gsl.lease_launch_gate(expires + 1, issued, expires), "lease_expired")
        self.assertEqual(gsl.lease_launch_gate(issued - 1, issued, expires), "lease_not_yet_valid")

    def test_gate_proceeds_and_starts(self):
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        gsl.mark_lease_ready(conn, "att-1", "lease-h", 20)
        self.assertEqual(gsl.gate_and_start(conn, "att-1", 1_000_000), gsl.EXECUTION_STARTING)

    def test_gate_expires_the_attempt_when_the_persisted_window_ran_out(self):
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        gsl.mark_lease_ready(conn, "att-1", "lease-h", 20)
        too_late = 1_000_000 + gsl.LEASE_DURATION_MS + 1
        self.assertEqual(gsl.gate_and_start(conn, "att-1", too_late), gsl.EXPIRED)
        # EXPIRED is terminal: no launch, and no path back.
        with self.assertRaises(gsl.IllegalTransition):
            gsl.mark_executing(conn, "att-1", process_group_id="pg", cgroup_id="cg",
                               execution_started_marker=None, now_ms=40)

    def test_gate_on_a_fabricated_attempt_is_not_found(self):
        conn = _conn()
        with self.assertRaises(gsl.NotFound):
            gsl.gate_and_start(conn, "ghost", 1_000_000)


# ---------------------------------------------------------------------------
# Completion — write-once, only for an attempt that legally reached EXECUTING.
# ---------------------------------------------------------------------------


class CompletionTests(unittest.TestCase):
    def test_completion_requires_the_legal_lifecycle(self):
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)  # ACCEPTED_PREPARED, never executed
        with self.assertRaises(gsl.IllegalTransition):
            gsl.record_completion(conn, "att-1", _produced(), 50, derived=DERIVED)
        # Nothing was written: no completion row, no floor row.
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_completion").fetchone()[0], 0
        )
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_evidence_head_floor").fetchone()[0], 0
        )

    def test_completion_for_a_fabricated_attempt_is_not_found(self):
        conn = _conn()
        with self.assertRaises(gsl.NotFound):
            gsl.record_completion(conn, "ghost", _produced(), 50, derived=DERIVED)

    def test_completion_is_write_once_and_idempotent_on_identical_retry(self):
        conn = _conn()
        _drive_to_executing(conn)
        self.assertEqual(gsl.record_completion(conn, "att-1", _produced(), 50, derived=DERIVED), gsl.CREATED)
        self.assertEqual(gsl.record_completion(conn, "att-1", _produced(), 51, derived=DERIVED), gsl.IDEMPOTENT)
        self.assertEqual(
            conn.execute("SELECT COUNT(*) FROM governed_turn_completion").fetchone()[0], 1
        )

    def test_a_second_completion_with_different_facts_is_refused(self):
        conn = _conn()
        _drive_to_executing(conn)
        gsl.record_completion(conn, "att-1", _produced(), 50, derived=DERIVED)
        with self.assertRaises(gsl.Conflict):
            gsl.record_completion(conn, "att-1", _produced(output_handle=H_B), 51, derived=DERIVED)
        # The originally recorded output survives — a retry cannot rewrite what was attested.
        stored = conn.execute(
            "SELECT output_handle FROM governed_turn_completion WHERE execution_attempt_id='att-1'"
        ).fetchone()[0]
        self.assertEqual(stored, H_A)

    def test_completion_refuses_facts_the_supervisor_already_owns(self):
        # Smuggling an id/nonce/identity back in through the completion door would re-open
        # F-01, so the fixed shape rejects every extra key.
        conn = _conn()
        _drive_to_executing(conn)
        for smuggled in ("run_id", "request_nonce", "receipt_id", "supervisor_id",
                         "executor_id", "requested_at", "challenge_accepted_at_ms"):
            with self.subTest(field=smuggled):
                facts = _produced()
                facts[smuggled] = "x"
                with self.assertRaises(gsl.LedgerError):
                    gsl.record_completion(conn, "att-1", facts, 50, derived=DERIVED)

    def test_completion_rejects_malformed_handles_and_counts(self):
        conn = _conn()
        _drive_to_executing(conn)
        for field, bad in (
            ("output_handle", "not-hex"),
            ("output_handle", H_A.upper()),
            ("evidence_event_count", 0),
            ("completed_at_ms", -1),
            ("evidence_final_event_hash", "abc"),
        ):
            with self.subTest(field=field, bad=bad):
                with self.assertRaises(gsl.LedgerError):
                    gsl.record_completion(conn, "att-1", _produced(**{field: bad}), 50, derived=DERIVED)


# ---------------------------------------------------------------------------
# Evidence-head anti-rollback / anti-fork floor.
# ---------------------------------------------------------------------------


class EvidenceFloorTests(unittest.TestCase):
    def test_a_stale_head_refuses_the_whole_completion(self):
        conn = _conn()
        _drive_to_executing(conn, "att-1")
        gsl.record_completion(conn, "att-1", _produced(), 50, derived=_derived(evidence_head_sequence=12))

        _drive_to_executing(conn, "att-2", _acceptance("att-2"))
        with self.assertRaises(gsl.StaleEvidence):
            gsl.record_completion(conn, "att-2", _produced(), 60, derived=_derived(evidence_head_sequence=11))
        # Rolled back entirely: the stale attempt has no completion to attest over.
        self.assertIsNone(gsl.load_attestation_state(conn, "run-1", "att-2"))

    def test_an_equal_head_with_divergent_content_is_a_fork(self):
        conn = _conn()
        _drive_to_executing(conn, "att-1")
        gsl.record_completion(conn, "att-1", _produced(), 50, derived=DERIVED)

        _drive_to_executing(conn, "att-2", _acceptance("att-2"))
        with self.assertRaises(gsl.EvidenceFork):
            gsl.record_completion(
                conn, "att-2", _produced(), 60, derived=_derived(evidence_final_event_hash=H_A)
            )
        self.assertIsNone(gsl.load_attestation_state(conn, "run-1", "att-2"))

    def test_a_strictly_higher_head_advances_the_floor(self):
        conn = _conn()
        _drive_to_executing(conn, "att-1")
        gsl.record_completion(conn, "att-1", _produced(), 50, derived=_derived(evidence_head_sequence=12))
        _drive_to_executing(conn, "att-2", _acceptance("att-2"))
        gsl.record_completion(conn, "att-2", _produced(), 60, derived=_derived(evidence_head_sequence=13))
        floor = conn.execute(
            "SELECT highest_head_sequence FROM governed_evidence_head_floor"
        ).fetchone()[0]
        self.assertEqual(floor, 13)


# ---------------------------------------------------------------------------
# THE F-01 PROPERTY: attestation state exists only for a real, completed run.
# ---------------------------------------------------------------------------


class AttestationStateTests(unittest.TestCase):
    def test_a_fabricated_attempt_has_no_attestation_state(self):
        conn = _conn()
        self.assertIsNone(gsl.load_attestation_state(conn, "run-1", "att-fabricated"))

    def test_an_accepted_but_unfinished_run_has_no_attestation_state(self):
        conn = _conn()
        _drive_to_executing(conn)
        self.assertIsNone(gsl.load_attestation_state(conn, "run-1", "att-1"))

    def test_a_completed_run_yields_state_built_entirely_from_the_ledger(self):
        conn = _conn()
        _drive_to_executing(conn)
        gsl.record_completion(conn, "att-1", _produced(), 50, derived=DERIVED)
        state = gsl.load_attestation_state(conn, "run-1", "att-1")
        self.assertIsNotNone(state)
        # The identity/binding half came from the SIGNED challenge at acceptance time...
        self.assertEqual(state.run_id, "run-1")
        self.assertEqual(state.task_id, "task-1")
        self.assertEqual(state.request_nonce, "nonce-att-1")
        self.assertEqual(state.receipt_id, "receipt-att-1")
        self.assertEqual(state.workspace_id, "ws-1")
        self.assertEqual(state.install_id, "install-1")
        self.assertEqual(state.supervisor_id, "supervisor-1")
        self.assertEqual(state.requested_at_ms, 999_000)
        self.assertEqual(state.challenge_accepted_at_ms, 1_000_000)
        self.assertEqual(state.system_handle, H_A)
        self.assertEqual(state.history_handle, H_B)
        self.assertEqual(state.generation_config_handle, H_C)
        # ...and only the run-produced half came from the write-once completion.
        self.assertEqual(state.output_handle, H_A)
        self.assertEqual(state.completed_at_ms, 1_050_000)
        self.assertEqual(state.evidence_head_sequence, 12)

    def test_a_mismatched_run_id_yields_no_state(self):
        # attest-run names {run_id, execution_attempt_id}; both must agree with the ledger.
        conn = _conn()
        _drive_to_executing(conn)
        gsl.record_completion(conn, "att-1", _produced(), 50, derived=DERIVED)
        self.assertIsNone(gsl.load_attestation_state(conn, "run-OTHER", "att-1"))

    def test_a_failed_run_yields_no_attestation_state(self):
        conn = _conn()
        _drive_to_executing(conn)
        gsl.advance(conn, "att-1", gsl.FAILED, 50, failure_reason="executor refused")
        self.assertIsNone(gsl.load_attestation_state(conn, "run-1", "att-1"))

    def test_empty_ids_yield_no_state(self):
        conn = _conn()
        _drive_to_executing(conn)
        gsl.record_completion(conn, "att-1", _produced(), 50, derived=DERIVED)
        self.assertIsNone(gsl.load_attestation_state(conn, "", "att-1"))
        self.assertIsNone(gsl.load_attestation_state(conn, "run-1", ""))


# ---------------------------------------------------------------------------
# The closed lifecycle itself.
# ---------------------------------------------------------------------------


class LifecycleTests(unittest.TestCase):
    def test_illegal_jump_is_refused_and_does_not_mutate(self):
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        with self.assertRaises(gsl.IllegalTransition):
            gsl.mark_executing(conn, "att-1", process_group_id="pg", cgroup_id="cg",
                               execution_started_marker=None, now_ms=20)
        self.assertEqual(gsl._current_state(conn, "att-1"), gsl.ACCEPTED_PREPARED)

    def test_no_edge_leaves_a_terminal_state(self):
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        gsl.advance(conn, "att-1", gsl.BLOCKED, 20, failure_reason="policy")
        with self.assertRaises(gsl.IllegalTransition):
            gsl.mark_lease_ready(conn, "att-1", "lease-h", 30)
        self.assertEqual(gsl._current_state(conn, "att-1"), gsl.BLOCKED)

    def test_the_ddl_trigger_is_an_independent_second_wall(self):
        # Even a direct UPDATE that bypasses the Python predecessor guard is refused by the
        # DDL trigger — the enforcement lives in the shared SQL, not in one language.
        conn = _conn()
        gsl.accept_prepare(conn, _acceptance(), 10)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute(
                "UPDATE governed_turn_acceptance SET state='COMPLETED'"
                " WHERE execution_attempt_id='att-1'"
            )

    def test_a_nested_transaction_is_refused(self):
        conn = _conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            with self.assertRaises(gsl.LedgerError):
                gsl.accept_prepare(conn, _acceptance(), 10)
        finally:
            conn.execute("ROLLBACK")


if __name__ == "__main__":
    unittest.main()
