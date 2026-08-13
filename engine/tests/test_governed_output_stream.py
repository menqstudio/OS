"""Offline tests for the §4.10(f) durable output-stream table (+ §2.3/Appendix B).

No socket, no key material, no network, no real clock — an in-memory SQLite carrying the
CANONICAL ``supervisor_ledger.sql`` and an injected ``now_ms`` everywhere.

The subject is a table that is INSERT-ONCE and whose logical state is DERIVED rather than
stored, so most of what is worth proving is about what the database refuses:

  * a row cannot be UPDATEd at all, so the two timestamps every read verdict is computed
    from cannot be moved after commit;
  * a row's lifetime FOLLOWS from ``created_at_ms`` rather than being chosen, so a token
    that would read LIVE forever cannot be minted;
  * a row's digest IS the handle it serves from (Appendix B), so the bytes served and the
    digest announced cannot be two different things;
  * a row cannot name an attempt this supervisor never accepted (the FOREIGN KEY), and one
    attempt gets exactly one capability, forever (the two UNIQUEs).

Each of those is exercised through a raw SQL statement as well as through the module, so a
writer that bypassed ``governed_output_stream`` entirely still could not produce the state.

The boundary tests are at the exact instant, both sides. §4.10(f) fixes an INCLUSIVE expiry
(``now_ms == expires_at_ms`` is LIVE) and the deleted Rust ladder had it the other way round
— with a test pinning the wrong side — so "expiry works" is not a claim this file is willing
to make without naming the instant.

No prerequisite here is optional. Everything is stdlib plus repo modules, imported at module
scope with no ``try``/``except`` and no ``skipIf``, so a missing prerequisite is an
unmissable hard error rather than a green run with a quiet skip. (There is no
``BROPS_TEST_MISSING_PREREQUISITES`` declaration anywhere in this tree, so nothing is
declared in it and nothing here may be softened.)
"""

import pathlib
import re
import sqlite3
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "runtime"))

import governed_output_stream as gos  # noqa: E402
import governed_supervisor_ledger as gsl  # noqa: E402

DDL = ROOT / "runtime" / "supervisor_ledger.sql"

HANDLE_A = "a" * 64
HANDLE_B = "b" * 64
TOKEN_A = "A" * 43
TOKEN_B = "B" * 43


def ledger() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:", isolation_level=None)
    conn.row_factory = sqlite3.Row
    gsl.apply_schema(conn)
    return conn


def accept(conn, attempt="attempt-1", *, install_id="inst-1", nonce="nonce-1",
           receipt_id="rcpt-1", handle=None, now_ms=1_000_000) -> str:
    """Create the acceptance row a stream's FOREIGN KEY requires.

    Streams hang off accepted attempts by design (see the DDL note): §4.10(f) declares no
    parent, and the FK is a deliberate strengthening, so every test here has to walk the real
    §5 CAS to get one rather than inserting a bare row.
    """
    gsl.accept_prepare(conn, gsl.NewAcceptance(
        install_id=install_id, request_nonce=nonce,
        challenge_handle=handle or ("c" * 63 + str(abs(hash(attempt)) % 10)),
        run_id="run-1", task_id="task-1", workspace_id="ws-1",
        execution_attempt_id=attempt, challenge_accepted_at_ms=now_ms,
        challenge_registry_handle="d" * 64, challenge_registry_hash="e" * 64,
        challenge_registry_epoch=7, challenge_registry_root_key_id="root-1",
        lease_payload_bytes=b"{}", lease_id="lease-1",
        lease_issued_at_ms=now_ms, lease_expires_at_ms=now_ms + 210_000,
        receipt_id=receipt_id, supervisor_id="sup-1", requested_at_ms=now_ms - 10,
        request_sha256="f" * 64, system_handle="1" * 64, history_handle="2" * 64,
        generation_config_handle="3" * 64,
    ), now_ms)
    return attempt


def new_stream(attempt="attempt-1", *, install_id="inst-1", receipt_id="rcpt-1",
               handle=HANDLE_A, output_bytes=1000) -> gos.NewStream:
    return gos.NewStream(install_id=install_id, receipt_id=receipt_id,
                         execution_attempt_id=attempt, output_handle=handle,
                         output_bytes=output_bytes)


# ---------------------------------------------------------------------------
# The capability itself
# ---------------------------------------------------------------------------


class CapabilityTokenTests(unittest.TestCase):
    def test_a_minted_token_is_exactly_the_43_char_design_capability(self):
        for _ in range(32):
            token = gos.mint_output_stream_id()
            self.assertEqual(len(token), 43)
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{43}", token), token)

    def test_the_length_is_the_one_governed_turn_result_already_pins(self):
        """§4.10(e) transports this value and already declares its length. Two constants for
        one fact is the drift §4.5's literal-embed rule exists to stop, so the table imports
        the frame's constant rather than restating 43."""
        import governed_turn_result as gtr
        src = (ROOT / "runtime" / "governed_output_stream.py").read_text(encoding="utf-8")
        self.assertIn("from governed_turn_result import MAX_OUTPUT_BYTES, OUTPUT_STREAM_ID_LEN",
                      src)
        self.assertEqual(gtr.OUTPUT_STREAM_ID_LEN, 43)

    def test_tokens_do_not_repeat(self):
        """256 bits, so a collision in 512 draws would mean the entropy source is not one."""
        self.assertEqual(len({gos.mint_output_stream_id() for _ in range(512)}), 512)

    def test_the_token_comes_from_secrets_not_random(self):
        """The difference between the two modules IS the property being claimed: whether an
        observer who has seen previous tokens can predict the next one."""
        src = (ROOT / "runtime" / "governed_output_stream.py").read_text(encoding="utf-8")
        self.assertIn("import secrets", src)
        self.assertIn("secrets.token_bytes(32)", src)
        self.assertNotIn("import random", src)


# ---------------------------------------------------------------------------
# Minting
# ---------------------------------------------------------------------------


class MintTests(unittest.TestCase):
    def setUp(self):
        self.conn = ledger()
        accept(self.conn)

    def test_a_completing_turn_gets_one_stream_bound_to_its_attempt(self):
        outcome, row = gos.mint_stream(self.conn, new_stream(), 5_000)
        self.assertEqual(outcome, gos.CREATED)
        self.assertEqual(row["execution_attempt_id"], "attempt-1")
        self.assertEqual(row["receipt_id"], "rcpt-1")
        self.assertEqual(row["output_handle"], HANDLE_A)
        self.assertEqual(row["output_bytes"], 1000)
        self.assertEqual(len(row["output_stream_id"]), 43)

    def test_the_digest_column_is_written_from_the_handle(self):
        """Appendix B: a raw-artifact handle IS its digest. The row carries both because the
        design names both; they can never disagree because only one is an input."""
        _outcome, row = gos.mint_stream(self.conn, new_stream(), 5_000)
        self.assertEqual(row["output_sha256"], row["output_handle"])

    def test_the_lifetime_is_the_two_design_constants_and_nothing_else(self):
        _outcome, row = gos.mint_stream(self.conn, new_stream(), 5_000)
        self.assertEqual(row["created_at_ms"], 5_000)
        self.assertEqual(row["expires_at_ms"], 5_000 + 360_000)
        self.assertEqual(row["retained_until_ms"], 5_000 + 360_000 + 360_000)
        self.assertEqual(gos.OUTPUT_STREAM_TTL_MS, 360_000)
        self.assertEqual(gos.OUTPUT_STREAM_RETENTION_MS, 360_000)

    def test_a_completed_retry_re_reads_the_same_token_and_never_re_mints(self):
        """§4.10(f): "a ``COMPLETED`` retry re-reads, never re-mints"."""
        _first, row1 = gos.mint_stream(self.conn, new_stream(), 5_000)
        outcome, row2 = gos.mint_stream(self.conn, new_stream(), 900_000)
        self.assertEqual(outcome, gos.IDEMPOTENT)
        self.assertEqual(row2["output_stream_id"], row1["output_stream_id"])
        # …and the retry did NOT extend the capability's life on the later clock.
        self.assertEqual(row2["expires_at_ms"], 5_000 + 360_000)

    def test_a_retry_naming_a_different_output_is_a_conflict_not_a_second_capability(self):
        gos.mint_stream(self.conn, new_stream(), 5_000)
        for changed in (new_stream(handle=HANDLE_B),
                        new_stream(output_bytes=2000),
                        new_stream(receipt_id="rcpt-other"),
                        new_stream(install_id="inst-other")):
            with self.assertRaises(gos.StreamConflict):
                gos.mint_stream(self.conn, changed, 6_000)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM governed_output_streams").fetchone()[0], 1)

    def test_one_receipt_id_cannot_belong_to_two_streams(self):
        accept(self.conn, "attempt-2", nonce="nonce-2", receipt_id="rcpt-2",
               handle="9" * 64)
        gos.mint_stream(self.conn, new_stream(), 5_000)
        with self.assertRaises(gos.StreamConflict):
            gos.mint_stream(self.conn, new_stream("attempt-2", receipt_id="rcpt-1"), 5_000)

    def test_a_stream_for_an_unaccepted_attempt_is_refused(self):
        """The FOREIGN KEY. An orphan stream — egress for a turn this supervisor never
        accepted — cannot be created even by a caller holding the connection."""
        with self.assertRaises(gos.StreamConflict):
            gos.mint_stream(self.conn, new_stream("attempt-never-accepted"), 5_000)

    def test_output_bytes_is_bounded_BEFORE_the_transaction_and_again_in_the_database(self):
        """Two walls at two layers, and the test distinguishes them — otherwise either one
        alone keeps this green and a mutation of the first is invisible behind the second.

        The Python bound refuses before a transaction is opened and raises a plain
        `LedgerError` naming the field; the DDL `CHECK` is what a writer bypassing this module
        would still hit, and it surfaces as `StreamConflict` (an IntegrityError). Asserting
        the FIRST kind is what pins the first wall."""
        for bad in (8_388_609, -1):
            with self.assertRaises(gsl.LedgerError) as caught:
                gos.mint_stream(self.conn, new_stream(output_bytes=bad), 5_000)
            self.assertNotIsInstance(caught.exception, gos.StreamConflict)
            self.assertIn("output_bytes", str(caught.exception))

    def test_a_zero_byte_output_still_gets_a_stream(self):
        """§4.10(f): "when ``output_bytes == 0`` the ``governed_output_streams`` row still
        exists". An empty reply is a result, not an absence."""
        outcome, row = gos.mint_stream(self.conn, new_stream(output_bytes=0), 5_000)
        self.assertEqual(outcome, gos.CREATED)
        self.assertEqual(row["output_bytes"], 0)

    def test_a_non_digest_handle_is_refused_before_the_database_sees_it(self):
        with self.assertRaises(gsl.LedgerError):
            gos.mint_stream(self.conn, new_stream(handle="not-a-digest"), 5_000)

    def test_the_clock_must_be_a_real_epoch_ms(self):
        for bad in (None, "5000", -1, True):
            with self.assertRaises(gsl.LedgerError):
                gos.mint_stream(self.conn, new_stream(), bad)


# ---------------------------------------------------------------------------
# The three phases, at the instant
# ---------------------------------------------------------------------------


class PhaseBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.conn = ledger()
        accept(self.conn)
        _outcome, self.row = gos.mint_stream(self.conn, new_stream(), 1_000)
        self.expires = self.row["expires_at_ms"]

    def test_the_expiry_boundary_is_inclusive_and_the_instant_is_named(self):
        """§4.10(f): "**inclusive boundary**, ``now_ms == expires_at_ms`` LIVE". The deleted
        Rust ladder used ``now_ms >= expires`` and had a test asserting the wrong side of
        exactly this instant, so both sides are asserted here."""
        self.assertFalse(gos.is_expired(self.row, self.expires - 1))
        self.assertFalse(gos.is_expired(self.row, self.expires))
        self.assertTrue(gos.is_expired(self.row, self.expires + 1))

    def test_a_logically_expired_row_is_still_PRESENT_until_retention_passes(self):
        """Phase 2 is a tombstone, and the difference from Phase 3 is the whole point: "your
        capability aged out" and "no such capability" are different facts."""
        gos.sweep_streams(self.conn, self.expires + 1)
        self.assertIsNotNone(gos.load_stream(self.conn, self.row["output_stream_id"]))

    def test_the_install_sweep_at_mint_uses_the_same_inclusive_boundary(self):
        """The per-install sweep that runs BEFORE the quota is counted has its own copy of the
        boundary, and a row exactly AT `retained_until_ms` must survive it — otherwise a mint
        one millisecond early silently destroys a stream that is still readable."""
        retained = self.row["retained_until_ms"]
        accept(self.conn, "attempt-2", nonce="nonce-2", receipt_id="rcpt-2", handle="8" * 64)
        gos.mint_stream(self.conn, new_stream("attempt-2", receipt_id="rcpt-2",
                                              handle=HANDLE_B), retained)
        self.assertIsNotNone(gos.load_stream(self.conn, self.row["output_stream_id"]))
        accept(self.conn, "attempt-3", nonce="nonce-3", receipt_id="rcpt-3", handle="7" * 64)
        gos.mint_stream(self.conn, new_stream("attempt-3", receipt_id="rcpt-3",
                                              handle="%064x" % 3), retained + 1)
        self.assertIsNone(gos.load_stream(self.conn, self.row["output_stream_id"]))

    def test_the_sweep_boundary_is_inclusive_too(self):
        retained = self.row["retained_until_ms"]
        self.assertEqual(gos.sweep_streams(self.conn, retained), 0)
        self.assertIsNotNone(gos.load_stream(self.conn, self.row["output_stream_id"]))
        self.assertEqual(gos.sweep_streams(self.conn, retained + 1), 1)
        self.assertIsNone(gos.load_stream(self.conn, self.row["output_stream_id"]))

    def test_the_transition_is_one_way(self):
        """§4.10(f): the one-way ``stream_expired → stream_unknown`` transition.

        Once swept, no later clock brings the row back — not even one INSIDE the original TTL,
        which is the only way a two-way transition could have been expressed."""
        gos.sweep_streams(self.conn, self.row["retained_until_ms"] + 1)
        self.assertIsNone(gos.load_stream(self.conn, self.row["output_stream_id"]))
        self.assertEqual(gos.sweep_streams(self.conn, self.expires - 1), 0)
        self.assertIsNone(gos.load_stream(self.conn, self.row["output_stream_id"]))

    def test_a_swept_token_is_never_re_minted_for_the_same_attempt(self):
        """§4.10(f) Phase 2: "**NEVER mint a replacement token**". After a sweep the attempt
        can technically mint again — the row is gone — so the property that actually holds is
        the one asserted here: it is a NEW token, and the OLD one stays unknown forever."""
        old = self.row["output_stream_id"]
        gos.sweep_streams(self.conn, self.row["retained_until_ms"] + 1)
        _outcome, again = gos.mint_stream(self.conn, new_stream(), 9_000_000)
        self.assertNotEqual(again["output_stream_id"], old)
        self.assertIsNone(gos.load_stream(self.conn, old))


# ---------------------------------------------------------------------------
# The quota
# ---------------------------------------------------------------------------


class QuotaTests(unittest.TestCase):
    def setUp(self):
        self.conn = ledger()

    def _mint(self, i, *, output_bytes=1000, now_ms=None):
        attempt = "attempt-%d" % i
        accept(self.conn, attempt, nonce="nonce-%d" % i, receipt_id="rcpt-%d" % i,
               handle="%064x" % i)
        return gos.mint_stream(
            self.conn, new_stream(attempt, receipt_id="rcpt-%d" % i,
                                  handle="%064x" % (i + 1000), output_bytes=output_bytes),
            now_ms if now_ms is not None else 1_000 + i)

    def test_the_count_limb_evicts_the_OLDEST_and_never_refuses(self):
        """§4.10(f): "a completing turn's stream is **always** created". A refusal here would
        lose the output of a turn that genuinely ran and was genuinely signed."""
        first = self._mint(0)[1]["output_stream_id"]
        for i in range(1, gos.MAX_OUTPUT_STREAMS_PER_INSTALL):
            self._mint(i)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM governed_output_streams").fetchone()[0],
            gos.MAX_OUTPUT_STREAMS_PER_INSTALL)
        outcome, row = self._mint(gos.MAX_OUTPUT_STREAMS_PER_INSTALL)
        self.assertEqual(outcome, gos.CREATED)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM governed_output_streams").fetchone()[0],
            gos.MAX_OUTPUT_STREAMS_PER_INSTALL)
        # The evicted row is GONE, not tombstoned: §4.10(f) says an evicted stream reads
        # `stream_unknown`, and a tombstone would say `stream_expired` — a claim about time
        # that is not true of it.
        self.assertIsNone(gos.load_stream(self.conn, first))
        self.assertIsNotNone(gos.load_stream(self.conn, row["output_stream_id"]))

    def test_the_byte_limb_cannot_bind_before_the_count_limb(self):
        """A DESIGN finding, proved rather than asserted, and the reason two mutants of the
        byte limb survive.

        §4.10(f) states both `MAX_OUTPUT_STREAMS_PER_INSTALL = 64` and
        `MAX_OUTPUT_STREAM_BYTES_PER_INSTALL = 536870912`, and 536870912 is EXACTLY
        `64 x MAX_OUTPUT_BYTES`. Since the DDL caps every row at `MAX_OUTPUT_BYTES`, whenever
        the count limb is satisfied (at most 63 present rows) the sum is at most
        `63 x 8388608 = 528482304` and `total + new` is at most the cap exactly — never over
        it. So the byte condition is FALSE whenever the count condition is false: it can never
        be the limb that fires. The code keeps it because the design states it; this test is
        what stops that from reading as coverage."""
        big = 8_388_608
        cap = gos.MAX_OUTPUT_STREAM_BYTES_PER_INSTALL
        self.assertEqual(cap, gos.MAX_OUTPUT_STREAMS_PER_INSTALL * big)
        worst = (gos.MAX_OUTPUT_STREAMS_PER_INSTALL - 1) * big
        self.assertEqual(worst, 528_482_304)
        self.assertLessEqual(worst + big, cap)   # …so the limb is false at the worst case.
        # And observed on the real table: 64 maximum-size rows sit exactly AT the cap, and the
        # 65th is evicted by the COUNT limb with the byte sum never having been exceeded.
        for i in range(gos.MAX_OUTPUT_STREAMS_PER_INSTALL):
            self._mint(i, output_bytes=big)
        self.assertEqual(self.conn.execute(
            "SELECT SUM(output_bytes) FROM governed_output_streams").fetchone()[0], cap)
        self._mint(gos.MAX_OUTPUT_STREAMS_PER_INSTALL, output_bytes=big)
        self.assertEqual(self.conn.execute(
            "SELECT SUM(output_bytes) FROM governed_output_streams").fetchone()[0], cap)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM governed_output_streams").fetchone()[0],
            gos.MAX_OUTPUT_STREAMS_PER_INSTALL)

    def test_retention_expired_rows_are_swept_BEFORE_anything_is_evicted(self):
        """§4.10(f): "before inserting a new row, sweep this install's ``retained_until_ms``-
        expired rows". Without that order a live turn would be evicted to make room that was
        already free."""
        survivors = []
        for i in range(gos.MAX_OUTPUT_STREAMS_PER_INSTALL):
            survivors.append(self._mint(i, now_ms=1_000)[1]["output_stream_id"])
        later = 1_000 + gos.OUTPUT_STREAM_TTL_MS + gos.OUTPUT_STREAM_RETENTION_MS + 1
        self._mint(gos.MAX_OUTPUT_STREAMS_PER_INSTALL, now_ms=later)
        # Every one of the 64 was past retention, so the sweep removed them all and nothing
        # had to be evicted; exactly one row is left.
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM governed_output_streams").fetchone()[0], 1)
        for token in survivors:
            self.assertIsNone(gos.load_stream(self.conn, token))

    def test_the_quota_is_PER_INSTALL(self):
        for i in range(gos.MAX_OUTPUT_STREAMS_PER_INSTALL):
            self._mint(i)
        attempt = "attempt-other"
        accept(self.conn, attempt, install_id="inst-2", nonce="n-other",
               receipt_id="rcpt-other", handle="7" * 64)
        gos.mint_stream(self.conn, new_stream(attempt, install_id="inst-2",
                                              receipt_id="rcpt-other",
                                              handle="8" * 64), 2_000)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM governed_output_streams WHERE install_id = 'inst-1'"
        ).fetchone()[0], gos.MAX_OUTPUT_STREAMS_PER_INSTALL)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM governed_output_streams WHERE install_id = 'inst-2'"
        ).fetchone()[0], 1)


# ---------------------------------------------------------------------------
# What the DATABASE refuses, reached by raw SQL
# ---------------------------------------------------------------------------


class DdlEnforcementTests(unittest.TestCase):
    """Every rule below is exercised through a raw statement, not through the module.

    That is the point of putting them in the DDL: §5's F-01 finding was a supervisor whose
    authority lived only in the code path a caller happened to take. A rule that a writer
    holding the connection can step around is a rule about politeness.
    """

    def setUp(self):
        self.conn = ledger()
        accept(self.conn)
        _outcome, self.row = gos.mint_stream(self.conn, new_stream(), 1_000)

    def _insert(self, **cols):
        row = {
            "output_stream_id": TOKEN_B, "install_id": "inst-1", "receipt_id": "rcpt-9",
            "execution_attempt_id": "attempt-9", "output_handle": HANDLE_B,
            "output_bytes": 10, "output_sha256": HANDLE_B, "created_at_ms": 2_000,
            "expires_at_ms": 2_000 + 360_000,
            "retained_until_ms": 2_000 + 720_000,
        }
        row.update(cols)
        accept(self.conn, "attempt-9", nonce="nonce-9", receipt_id="rcpt-9",
               handle="5" * 64)
        self.conn.execute(
            "INSERT INTO governed_output_streams (%s) VALUES (%s)"
            % (",".join(row), ",".join("?" * len(row))), tuple(row.values()))

    def test_no_update_of_any_column_is_permitted(self):
        """INSERT-ONCE, and therefore a capability that can never be renewed. Every column is
        tried, because a trigger scoped to a column list would leave the others open."""
        for column, value in (("expires_at_ms", 9_999_999),
                              ("retained_until_ms", 9_999_999),
                              ("output_bytes", 1),
                              ("output_handle", HANDLE_B),
                              ("output_sha256", HANDLE_B),
                              ("install_id", "inst-2"),
                              ("receipt_id", "rcpt-2"),
                              ("execution_attempt_id", "attempt-2"),
                              ("created_at_ms", 0),
                              ("output_stream_id", TOKEN_A)):
            with self.assertRaises(sqlite3.IntegrityError) as caught:
                self.conn.execute(
                    "UPDATE governed_output_streams SET %s = ?" % column, (value,))
            self.assertIn("insert-once", str(caught.exception))

    def test_a_row_cannot_be_minted_with_a_lifetime_it_chose(self):
        """The capability's life FOLLOWS from ``created_at_ms``. Without this a writer could
        insert a row expiring in the year 3000, and the reader — which derives the verdict
        from exactly this column — would report it LIVE and be right to."""
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            self._insert(expires_at_ms=2_000 + 999_999_999)
        self.assertIn("fixed TTL", str(caught.exception))

    def test_a_row_cannot_be_minted_with_a_retention_it_chose(self):
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            self._insert(retained_until_ms=2_000 + 999_999_999)
        self.assertIn("fixed TTL", str(caught.exception))

    def test_the_digest_may_not_differ_from_the_handle_it_serves_from(self):
        with self.assertRaises(sqlite3.IntegrityError) as caught:
            self._insert(output_sha256=HANDLE_A)
        self.assertIn("digest must be the handle", str(caught.exception))

    def test_a_token_of_the_wrong_length_is_not_a_capability(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert(output_stream_id="short")

    def test_output_bytes_is_bounded_in_the_database_too(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self._insert(output_bytes=8_388_609)

    def test_one_attempt_cannot_hold_two_capabilities(self):
        """`UNIQUE (execution_attempt_id)` IS §4.10(f)'s "minted exactly once" key, and it has
        to hold against a raw writer: `mint_stream` looks the attempt up first, so without a
        DB constraint the module's own check would be the only thing stopping a second
        capability over one turn."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO governed_output_streams (output_stream_id, install_id,"
                " receipt_id, execution_attempt_id, output_handle, output_bytes,"
                " output_sha256, created_at_ms, expires_at_ms, retained_until_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (TOKEN_B, "inst-1", "rcpt-second", self.row["execution_attempt_id"],
                 HANDLE_B, 1, HANDLE_B, 3_000, 3_000 + 360_000, 3_000 + 720_000))

    def test_an_orphan_stream_cannot_be_inserted(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO governed_output_streams (output_stream_id, install_id,"
                " receipt_id, execution_attempt_id, output_handle, output_bytes,"
                " output_sha256, created_at_ms, expires_at_ms, retained_until_ms)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)",
                (TOKEN_B, "inst-1", "rcpt-x", "attempt-never", HANDLE_B, 1, HANDLE_B,
                 0, 360_000, 720_000))

    def test_the_python_constants_are_the_sql_literals(self):
        """The DDL is the single normative source and it spells 360000/720000 as literals.
        Two copies of one number is drift waiting to happen, so the test reads the SQL."""
        ddl = DDL.read_text(encoding="utf-8")
        self.assertIn(
            "NEW.expires_at_ms = NEW.created_at_ms + %d" % gos.OUTPUT_STREAM_TTL_MS, ddl)
        self.assertIn(
            "NEW.retained_until_ms = NEW.created_at_ms + %d"
            % (gos.OUTPUT_STREAM_TTL_MS + gos.OUTPUT_STREAM_RETENTION_MS), ddl)

    def test_the_ddl_parity_gate_holds_these_clauses(self):
        """A byte-identical mirror is not enough: the gate also refuses the DELETION of a
        load-bearing clause from both copies in one commit."""
        gate = (ROOT.parent / "tools" / "check_ledger_ddl_parity.py").read_text(
            encoding="utf-8")
        for clause in ("CREATE TABLE IF NOT EXISTS governed_output_streams",
                       "trg_governed_output_streams_immutable",
                       "trg_governed_output_streams_lifetime",
                       "trg_governed_output_streams_digest",
                       "output stream rows are insert-once",
                       "output stream lifetime must be the fixed TTL + retention",
                       "output stream digest must be the handle it serves from"):
            self.assertIn(clause, gate)


# ---------------------------------------------------------------------------
# What the sweep may NOT do
# ---------------------------------------------------------------------------


class SweepScopeTests(unittest.TestCase):
    def test_the_sweep_cannot_unlink_the_output_because_it_touches_no_filesystem(self):
        """§4.10(f)/§2.3: the sweep removes the ROW and "MUST NOT unlink the content-addressed
        ``store/rec/<output_handle>``" — those bytes are pinned by the terminal record and the
        execution receipt, so output OUTLIVES its stream row.

        Proved structurally rather than by observation: the module imports no filesystem
        module at all, so there is no unlink it could perform even by accident."""
        src = (ROOT / "runtime" / "governed_output_stream.py").read_text(encoding="utf-8")
        for forbidden in ("import os", "import pathlib", "import shutil", "unlink(",
                          "remove(", "rmtree("):
            self.assertNotIn(forbidden, src, forbidden)

    def test_the_sweep_is_install_agnostic_and_deletes_only_past_retention(self):
        conn = ledger()
        accept(conn, "attempt-1", nonce="n1", receipt_id="r1", handle="1" * 64)
        accept(conn, "attempt-2", nonce="n2", receipt_id="r2", handle="2" * 64)
        _o, old = gos.mint_stream(conn, new_stream("attempt-1", receipt_id="r1"), 1_000)
        _o, young = gos.mint_stream(
            conn, new_stream("attempt-2", receipt_id="r2", handle=HANDLE_B), 500_000)
        self.assertEqual(gos.sweep_streams(conn, old["retained_until_ms"] + 1), 1)
        self.assertIsNone(gos.load_stream(conn, old["output_stream_id"]))
        self.assertIsNotNone(gos.load_stream(conn, young["output_stream_id"]))

    def test_the_sweep_interval_is_a_schedule_not_a_correctness_input(self):
        """A read of a retention-expired row the sweep has not reached still answers on the
        row's own timestamps. The interval constant is declared and used by nothing here,
        which is exactly what "asynchronous" has to mean for the verdict to be synchronous."""
        self.assertEqual(gos.OUTPUT_STREAM_SWEEP_INTERVAL_MS, 60_000)
        conn = ledger()
        accept(conn)
        _o, row = gos.mint_stream(conn, new_stream(), 1_000)
        way_past = row["retained_until_ms"] + 10_000_000
        self.assertIsNotNone(gos.load_stream(conn, row["output_stream_id"]))
        self.assertTrue(gos.is_expired(row, way_past))


# ---------------------------------------------------------------------------
# Nothing governed is minted here
# ---------------------------------------------------------------------------


class NothingGovernedIsMintedTests(unittest.TestCase):
    """§5 acceptance mints the identities; this table only records one of its consequences.

    The equivalent class in §4.10(d)/(e) proved the same thing from the import graph. Here
    the module DOES carry entropy — it mints a capability — so the claim has to be narrower
    and is: the entropy produces exactly one value, a transport capability with no authority,
    and every identity in the row arrives from the acceptance ledger.
    """

    def test_the_module_reads_no_clock(self):
        src = (ROOT / "runtime" / "governed_output_stream.py").read_text(encoding="utf-8")
        for forbidden in ("import time", "time.time", "datetime", "monotonic"):
            self.assertNotIn(forbidden, src, forbidden)

    def test_the_only_value_this_module_generates_is_the_transport_capability(self):
        src = (ROOT / "runtime" / "governed_output_stream.py").read_text(encoding="utf-8")
        self.assertEqual(src.count("secrets.token_bytes"), 1)
        for forbidden in ("uuid", "execution_attempt_id=", "receipt_id ="):
            self.assertNotIn(forbidden, src, forbidden)

    def test_the_row_cannot_carry_a_verdict_a_lease_or_a_trust_state(self):
        conn = ledger()
        columns = {r[1] for r in conn.execute(
            "PRAGMA table_info(governed_output_streams)")}
        self.assertEqual(columns, {
            "output_stream_id", "install_id", "receipt_id", "execution_attempt_id",
            "output_handle", "output_bytes", "output_sha256", "created_at_ms",
            "expires_at_ms", "retained_until_ms"})
        for absent in ("state", "trust_state", "lease_id", "signature", "verdict",
                       "capability_token", "broker_turn_id"):
            self.assertNotIn(absent, columns)

    def test_no_gate_moved(self):
        """The three STOP conditions are outside this module by construction: it holds no
        manifest, no key and no platform predicate. Asserted by absence rather than by a
        claim, so a future import of one of them turns this red."""
        src = (ROOT / "runtime" / "governed_output_stream.py").read_text(encoding="utf-8")
        for forbidden in ("trusted_verified", "governed_verification_unconfigured",
                          "connect_broker", "UpstreamBlockedExecutor"):
            self.assertNotIn(forbidden, src, forbidden)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
