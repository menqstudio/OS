"""Live health monitor for the runtime's machine-local state.

Operational rollout, step 5. Shadow mode, the recovery journal and the execution
lease all leave their state on operator-controlled paths outside the repository
(see docs/OPERATOR_RUNBOOK.md). This tool reads that state — it never mutates it —
and reports a single health summary an operator or a cron/alerting probe can act
on:

- shadow ledger: total would-block records, a breakdown by decision kind, and
  whether the append-only chain still verifies;
- recovery store: transaction journals counted by phase, and how many sit in a
  BLOCKING phase (an interrupted or failed transaction fences further mutation);
- execution-lease ledger: active / used / quarantined (.ambiguous) reservations;
- task-lock ledger: active worktree locks.

Health is ATTENTION (non-zero exit) when anything needs a human: a blocking
recovery journal, a quarantined lease, or a shadow ledger whose chain no longer
verifies. Otherwise GREEN. Pure standard library plus bro_audit_log / bro_recovery.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

from bro_audit_log import AuditError, read_all as read_ledger, verify as verify_chain
from bro_recovery import BLOCKING

GREEN = "GREEN"
ATTENTION = "ATTENTION"


def _is_json_object(path: pathlib.Path) -> bool:
    try:
        return isinstance(json.loads(path.read_text(encoding="utf-8")), dict)
    except (OSError, json.JSONDecodeError, ValueError):
        return False


def _validate_store(path: pathlib.Path | None, *, want_dir: bool, kind: str, problems: list) -> pathlib.Path | None:
    """Distinguish "not configured" (None -> nothing to watch) from "configured
    but unusable" (missing / wrong type). A configured store the monitor cannot
    read is a blind spot, so it is a problem, not silent GREEN."""
    if path is None:
        return None
    if not path.exists():
        problems.append(f"{kind} is configured but missing: {path}")
        return None
    if want_dir and not path.is_dir():
        problems.append(f"{kind} is configured but is not a directory: {path}")
        return None
    if not want_dir and not path.is_file():
        problems.append(f"{kind} is configured but is not a file: {path}")
        return None
    return path


def _shadow(ledger: pathlib.Path | None) -> dict:
    if ledger is None:
        return {"records": 0, "by_kind": {}, "chain_ok": True, "readable": True}
    # A shadow ledger the monitor cannot fully account for is a blind spot, not
    # GREEN. `read_all` does a bare `json.loads` per line, so corrupt content raises
    # `json.JSONDecodeError`/`OSError`/`ValueError`, NOT `AuditError`; and a line
    # that parses to a non-object (`[]`, `"record"`, `null`) or one whose `payload`
    # is not an object then blows up the by-kind pass with `AttributeError`. Guard
    # the ENTIRE parse + shape phase: read once, and require every record and its
    # payload to be a JSON object. Any failure -> unreadable -> ATTENTION.
    try:
        records = read_ledger(ledger)
        for rec in records:
            if not isinstance(rec, dict):
                raise ValueError("shadow record is not a JSON object")
            if not isinstance(rec.get("payload", {}), dict):
                raise ValueError("shadow record payload is not a JSON object")
    except (OSError, ValueError, json.JSONDecodeError, AuditError, AttributeError):
        return {"records": 0, "by_kind": {}, "chain_ok": False, "readable": False}
    # Records read and well-shaped; a chain that does not verify is ATTENTION but
    # still "readable" (distinct from corrupt content). But verify_chain indexes
    # record fields (e.g. `kind`) directly, so a record missing an expected field
    # raises KeyError/TypeError/AttributeError — an unexpected shape the monitor
    # cannot account for, which must degrade to unreadable, not crash the scan.
    try:
        count = verify_chain(ledger)
        chain_ok = True
    except AuditError:
        count, chain_ok = len(records), False
    except (OSError, ValueError, json.JSONDecodeError, KeyError, TypeError, AttributeError):
        return {"records": 0, "by_kind": {}, "chain_ok": False, "readable": False}
    by_kind: dict[str, int] = {}
    for rec in records:
        kind = str(rec.get("payload", {}).get("kind") or rec.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {"records": count, "by_kind": by_kind, "chain_ok": chain_ok, "readable": True}


# A real execution-lease record (bro_execution_lease.reserve_execution_lease)
# always carries schema==1 and a sha256 hexdigest lease id. Validating the VALUES,
# not just key presence, keeps a placeholder (`{}`, or null-valued keys) out of the
# healthy count. This is a health invariant, not full schema authority: deep
# lease-schema validation is owned by the Supervisor lease-schema alignment
# (deployment blocker 8).
# No `$` anchor: `$` matches before a trailing newline, so a 64-hex id with a
# stray "\n" would slip through. `fullmatch` requires the whole string.
_SHA256_HEX = re.compile(r"[0-9a-f]{64}")


def _is_lease_record(path: pathlib.Path) -> bool:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(doc, dict):
        return False
    schema = doc.get("schema")
    # `True == 1` in Python, so bool must be rejected explicitly (type check).
    if type(schema) is not int or schema != 1:
        return False
    lease_id = doc.get("lease_id_sha256")
    return isinstance(lease_id, str) and _SHA256_HEX.fullmatch(lease_id) is not None


# Phases that are a normal resting state and need no action. Every other phase —
# a BLOCKING one, an unreadable/corrupt journal, or an unrecognised value — is a
# condition a human must see: monitoring a self-defending runtime must fail closed
# on state it cannot account for, not silently report GREEN.
_RESTING_PHASES = frozenset({"MUTATION_RECORDED", "REWORK_REQUIRED"})


def _recovery(store: pathlib.Path | None) -> dict:
    by_phase: dict[str, int] = {}
    blocking = 0
    degraded = 0  # unreadable, non-object, missing-phase, or an unrecognised phase
    if store is not None and store.is_dir():
        for path in sorted(store.glob("*.state.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(doc, dict):
                    raise ValueError("recovery journal is not a JSON object")
                phase = str(doc.get("phase") or "unknown")
            except (OSError, json.JSONDecodeError, ValueError):
                phase = "unreadable"
            by_phase[phase] = by_phase.get(phase, 0) + 1
            if phase in BLOCKING:
                blocking += 1
            elif phase not in _RESTING_PHASES:
                degraded += 1
    return {"journals": sum(by_phase.values()), "by_phase": by_phase,
            "blocking": blocking, "degraded": degraded}


def _leases(ledger: pathlib.Path | None) -> dict:
    counts = {"active": 0, "used": 0, "ambiguous": 0, "degraded": 0}
    if ledger is not None and ledger.is_dir():
        for path in sorted(ledger.iterdir()):
            suffix = path.suffix.lstrip(".")
            if suffix in ("active", "used", "ambiguous") and path.is_file():
                counts[suffix] += 1
                if not _is_lease_record(path):  # object AND carries lease identity
                    counts["degraded"] += 1
    return counts


def _locks(ledger: pathlib.Path | None) -> dict:
    counts = {"active": 0, "degraded": 0}
    if ledger is not None and ledger.is_dir():
        for path in sorted(ledger.glob("*.json")):
            if path.is_file():
                counts["active"] += 1
                if not _is_json_object(path):
                    counts["degraded"] += 1
    return counts


def scan(*, shadow_ledger: pathlib.Path | None = None, recovery_store: pathlib.Path | None = None,
         lease_ledger: pathlib.Path | None = None, task_lock_ledger: pathlib.Path | None = None) -> dict:
    attention: list[str] = []
    shadow_ledger = _validate_store(shadow_ledger, want_dir=False, kind="shadow ledger", problems=attention)
    recovery_store = _validate_store(recovery_store, want_dir=True, kind="recovery store", problems=attention)
    lease_ledger = _validate_store(lease_ledger, want_dir=True, kind="lease ledger", problems=attention)
    task_lock_ledger = _validate_store(task_lock_ledger, want_dir=True, kind="task-lock ledger", problems=attention)
    shadow = _shadow(shadow_ledger)
    recovery = _recovery(recovery_store)
    leases = _leases(lease_ledger)
    locks = _locks(task_lock_ledger)
    if not shadow["readable"]:
        attention.append("shadow ledger is unreadable or corrupt")
    elif not shadow["chain_ok"]:
        attention.append("shadow ledger chain does not verify")
    if recovery["blocking"]:
        attention.append(f"{recovery['blocking']} recovery journal(s) in a blocking phase")
    if recovery["degraded"]:
        attention.append(f"{recovery['degraded']} recovery journal(s) unreadable or in an unrecognised phase")
    if leases["ambiguous"]:
        attention.append(f"{leases['ambiguous']} quarantined execution lease(s)")
    if leases["degraded"]:
        attention.append(f"{leases['degraded']} unreadable execution lease record(s)")
    if locks["degraded"]:
        attention.append(f"{locks['degraded']} unreadable task-lock record(s)")
    return {
        "schema": 1,
        "health": ATTENTION if attention else GREEN,
        "attention": attention,
        "shadow": shadow,
        "recovery": recovery,
        "leases": leases,
        "locks": locks,
    }


def _p(value: str | None) -> pathlib.Path | None:
    return pathlib.Path(value).expanduser() if value else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shadow-ledger")
    parser.add_argument("--recovery-store")
    parser.add_argument("--lease-ledger")
    parser.add_argument("--task-lock-ledger")
    parser.add_argument("--json", action="store_true", help="emit the full report as JSON")
    args = parser.parse_args(argv)
    report = scan(
        shadow_ledger=_p(args.shadow_ledger),
        recovery_store=_p(args.recovery_store),
        lease_ledger=_p(args.lease_ledger),
        task_lock_ledger=_p(args.task_lock_ledger),
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        s, r, le = report["shadow"], report["recovery"], report["leases"]
        print(f"{report['health']}: shadow_records={s['records']} chain_ok={s['chain_ok']}; "
              f"recovery_journals={r['journals']} blocking={r['blocking']} degraded={r['degraded']}; "
              f"leases active={le['active']} used={le['used']} quarantined={le['ambiguous']}; "
              f"locks={report['locks']['active']}")
        for note in report["attention"]:
            print(f"  ATTENTION: {note}")
    return 2 if report["health"] == ATTENTION else 0


if __name__ == "__main__":
    raise SystemExit(main())
