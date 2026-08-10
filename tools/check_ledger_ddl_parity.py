#!/usr/bin/env python3
"""Fail-closed CI gate: the supervisor durable-ledger DDL has exactly ONE source.

The governed supervisor's durable state (independent audit **F-01**) is enforced by the
SQL itself — the three `UNIQUE`s that make one signed challenge mint exactly one
execution attempt, the `state` CHECK plus the BEFORE-UPDATE transition trigger, the
completion table's write-once PRIMARY KEY, and the evidence-head anti-rollback floor.
Two components must obey byte-identical rules:

  * ``engine/runtime/supervisor_ledger.sql`` — CANONICAL. Loaded by
    ``engine/runtime/governed_supervisor_ledger.py``, the Python supervisor that OWNS
    this state and is its only production writer.
  * ``apps/desktop/src-tauri/core/schema/supervisor_ledger.sql`` — a MIRROR, compiled
    into ``brops-core`` with ``include_str!`` so the Rust half still builds standalone
    (CLAUDE.md §4 keeps each half independently buildable).

If those two ever diverge, the supervisor and the Rust ledger disagree about what the
durable acceptance state IS — which is precisely the class of drift that let F-01 exist.
So this gate hard-fails on divergence AND on a missing/unreadable file: it never reports
GREEN for a comparison it did not perform. Edit the CANONICAL file, then re-run
``python tools/check_ledger_ddl_parity.py`` (or just copy it over the mirror).

Exit 0 = identical. Exit 1 = divergence or a missing copy. No other outcome exists.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys

CANONICAL = "engine/runtime/supervisor_ledger.sql"
MIRROR = "apps/desktop/src-tauri/core/schema/supervisor_ledger.sql"

# Substrings that MUST survive in the DDL. Byte-equality alone would still pass if
# someone deleted an enforcement clause from BOTH copies in one commit, so the gate
# also asserts that each load-bearing constraint is still present. This is a floor,
# not a parser: it cannot prove the SQL is correct, only that these were not removed.
REQUIRED_CLAUSES = (
    "UNIQUE (install_id, request_nonce)",
    "UNIQUE (challenge_handle)",
    "UNIQUE (execution_attempt_id)",
    "idx_governed_turn_acceptance_receipt",
    "trg_governed_turn_acceptance_transition",
    "RAISE(ABORT, 'illegal acceptance state transition')",
    "CREATE TABLE IF NOT EXISTS governed_turn_completion",
    "execution_attempt_id        TEXT PRIMARY KEY NOT NULL",
    "CREATE TABLE IF NOT EXISTS governed_evidence_head_floor",
    "PRAGMA foreign_keys = ON",
    # §2.4 / §4.10(a0) pre-accept staging. The two triggers are the reason an
    # `INPUTS_READY` row cannot be conjured: one forbids any INSERT that is not
    # `VERIFYING`, the other forbids any edge that is not VERIFYING->UPLOADING or
    # UPLOADING->INPUTS_READY. Deleting either from both copies in one commit would
    # restore exactly the "declare the end state, publish nothing" hole.
    "CREATE TABLE IF NOT EXISTS governed_turn_staging",
    "trg_governed_turn_staging_insert_state",
    "RAISE(ABORT, 'staging row must be created VERIFYING')",
    # A row born VERIFYING may still have been born with its three `*_handle` columns
    # already filled: VERIFYING says nothing about them, and pre-set handles that already
    # equal the committed digests pass the handle-binding trigger on every later UPDATE.
    # Without this the row could walk to INPUTS_READY having published nothing -- exactly
    # the "declare the end state, do nothing" hole the SESSION insert trigger closes, and
    # exactly the state the §4.10(d) evidence-request gate reads as proof of upload.
    "trg_governed_turn_staging_insert_handles",
    "RAISE(ABORT, 'staging row must be created with no published input handles')",
    "trg_governed_turn_staging_transition",
    "RAISE(ABORT, 'illegal staging state transition')",
    "trg_governed_turn_staging_immutable_binding",
    "RAISE(ABORT, 'staging row binding is immutable')",
    # §4.10(a)(b)(c) chunked staging upload. Each of these is a rule that, if it
    # lived only in Python, a writer bypassing the handlers could ignore -- which is
    # exactly how a "finished" upload could be declared over bytes nobody sent:
    #   * the session is born empty, so ARTIFACT_READY cannot be an INSERT;
    #   * the cursor advances by exactly one recorded chunk, so `byte_count` is
    #     provably SUM(chunk_len) and `next_seq` provably their count;
    #   * a chunk is recorded only AT the cursor and never UPDATEd, so the sequence
    #     is gapless and an already-counted chunk cannot be re-described;
    #   * a published input handle must BE the challenge-committed digest, and
    #     INPUTS_READY cannot be reached until all three are set -- which is what
    #     makes §4.10(d)'s reading of that state true rather than merely asserted
    #     (the gate re-derives none of it; the DDL refuses to produce a state it could
    #     misread).
    "CREATE TABLE IF NOT EXISTS governed_turn_staging_session",
    "CREATE TABLE IF NOT EXISTS governed_turn_staging_chunk",
    "artifact           TEXT NOT NULL CHECK (artifact IN (",
    "next_seq           INTEGER NOT NULL CHECK (next_seq >= 0 AND next_seq <= 46)",
    "chunk_len >= 1 AND chunk_len <= 184320",
    "seq                INTEGER NOT NULL CHECK (seq >= 0 AND seq <= 45)",
    "UNIQUE (challenge_handle, artifact)",
    "trg_governed_turn_staging_session_insert_state",
    "RAISE(ABORT, 'staging session must be created empty and UPLOADING')",
    "trg_governed_turn_staging_session_transition",
    "RAISE(ABORT, 'illegal staging session state transition')",
    "trg_governed_turn_staging_session_cursor",
    "RAISE(ABORT, 'staging cursor must advance by exactly one recorded chunk')",
    "trg_governed_turn_staging_session_immutable",
    "RAISE(ABORT, 'staging session binding is immutable')",
    "trg_governed_turn_staging_chunk_gapless",
    "RAISE(ABORT, 'staging chunk must be recorded at the current cursor')",
    "trg_governed_turn_staging_chunk_immutable",
    "RAISE(ABORT, 'recorded staging chunks are immutable')",
    "trg_governed_turn_staging_handle_binding",
    "RAISE(ABORT, 'published input handle must be the challenge-committed digest')",
    "trg_governed_turn_staging_inputs_ready",
    "RAISE(ABORT, 'INPUTS_READY requires all three published input handles')",
    # §4.10(f) governed output streams -- the ONLY egress. Everything above guards
    # what may ENTER; these guard the one way anything leaves, and each is a rule
    # the design states that Python alone could not make true:
    #   * the row is INSERT-ONCE, so the two timestamps a read verdict is DERIVED
    #     from cannot be moved after commit -- a live capability can never be
    #     renewed and an expired one never revived;
    #   * the lifetime FOLLOWS from `created_at_ms` rather than being chosen, so a
    #     row that would read LIVE forever cannot be minted at all;
    #   * the digest IS the handle (Appendix B), so the bytes served and the digest
    #     announced in the §4.10(e) summary cannot be two different things;
    #   * the two UNIQUEs ARE §4.10(f)'s "minted exactly once" create-if-absent key,
    #     so a COMPLETED retry re-reads its token instead of minting a second one.
    "CREATE TABLE IF NOT EXISTS governed_output_streams",
    "length(output_stream_id) = 43",
    "receipt_id           TEXT NOT NULL UNIQUE",
    "execution_attempt_id TEXT NOT NULL UNIQUE",
    "output_bytes >= 0 AND output_bytes <= 8388608",
    "trg_governed_output_streams_immutable",
    "RAISE(ABORT, 'output stream rows are insert-once')",
    "trg_governed_output_streams_lifetime",
    "RAISE(ABORT, 'output stream lifetime must be the fixed TTL + retention')",
    "trg_governed_output_streams_digest",
    "RAISE(ABORT, 'output stream digest must be the handle it serves from')",
)


def _read(root: pathlib.Path, rel: str) -> bytes | None:
    try:
        return (root / rel).read_bytes()
    except OSError:
        return None


def check(root: pathlib.Path) -> list[str]:
    problems: list[str] = []

    canonical = _read(root, CANONICAL)
    mirror = _read(root, MIRROR)

    # A missing copy is a HARD failure, never a skip: a gate that quietly passes when its
    # subject is absent is a gate that attests to nothing (see the audit's F-16/F-19 class).
    if canonical is None:
        problems.append(f"missing canonical ledger DDL: {CANONICAL}")
    if mirror is None:
        problems.append(f"missing mirrored ledger DDL: {MIRROR}")
    if canonical is None or mirror is None:
        return problems

    if canonical != mirror:
        problems.append(
            "supervisor ledger DDL DIVERGED — the Python supervisor and the Rust ledger would "
            "enforce different durable rules.\n"
            f"    {CANONICAL}  sha256={hashlib.sha256(canonical).hexdigest()}  ({len(canonical)} bytes)\n"
            f"    {MIRROR}  sha256={hashlib.sha256(mirror).hexdigest()}  ({len(mirror)} bytes)\n"
            f"    Fix: copy the CANONICAL file over the mirror ({CANONICAL} -> {MIRROR})."
        )

    text = canonical.decode("utf-8", errors="replace")
    for clause in REQUIRED_CLAUSES:
        if clause not in text:
            problems.append(
                f"load-bearing ledger constraint removed from {CANONICAL}: {clause!r}"
            )

    return problems


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    problems = check(root)
    if problems:
        print("RED: supervisor ledger DDL gate failed")
        for p in problems:
            print(f"  - {p}")
        return 1
    digest = hashlib.sha256((root / CANONICAL).read_bytes()).hexdigest()
    print(
        f"GREEN: supervisor ledger DDL single-source ({CANONICAL} == {MIRROR}; "
        f"sha256={digest[:16]}…; {len(REQUIRED_CLAUSES)} load-bearing constraints present)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
