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
