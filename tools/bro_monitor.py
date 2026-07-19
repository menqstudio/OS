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
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

from bro_audit_log import AuditError, read_all as read_ledger, verify as verify_chain
from bro_recovery import BLOCKING

GREEN = "GREEN"
ATTENTION = "ATTENTION"


def _shadow(ledger: pathlib.Path | None) -> dict:
    if ledger is None or not ledger.exists():
        return {"records": 0, "by_kind": {}, "chain_ok": True}
    try:
        count = verify_chain(ledger)
        chain_ok = True
    except AuditError:
        count, chain_ok = len(read_ledger(ledger)), False
    by_kind: dict[str, int] = {}
    for rec in read_ledger(ledger):
        kind = str(rec.get("payload", {}).get("kind") or rec.get("kind") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {"records": count, "by_kind": by_kind, "chain_ok": chain_ok}


def _recovery(store: pathlib.Path | None) -> dict:
    by_phase: dict[str, int] = {}
    blocking = 0
    if store is not None and store.is_dir():
        for path in sorted(store.glob("*.state.json")):
            try:
                phase = str(json.loads(path.read_text(encoding="utf-8")).get("phase") or "unknown")
            except (OSError, json.JSONDecodeError):
                phase = "unreadable"
            by_phase[phase] = by_phase.get(phase, 0) + 1
            if phase in BLOCKING:
                blocking += 1
    return {"journals": sum(by_phase.values()), "by_phase": by_phase, "blocking": blocking}


def _leases(ledger: pathlib.Path | None) -> dict:
    counts = {"active": 0, "used": 0, "ambiguous": 0}
    if ledger is not None and ledger.is_dir():
        for path in ledger.iterdir():
            if path.suffix.lstrip(".") in counts and path.is_file():
                counts[path.suffix.lstrip(".")] += 1
    return counts


def _locks(ledger: pathlib.Path | None) -> dict:
    active = 0
    if ledger is not None and ledger.is_dir():
        active = sum(1 for p in ledger.glob("*.json") if p.is_file())
    return {"active": active}


def scan(*, shadow_ledger: pathlib.Path | None = None, recovery_store: pathlib.Path | None = None,
         lease_ledger: pathlib.Path | None = None, task_lock_ledger: pathlib.Path | None = None) -> dict:
    shadow = _shadow(shadow_ledger)
    recovery = _recovery(recovery_store)
    leases = _leases(lease_ledger)
    locks = _locks(task_lock_ledger)
    attention = []
    if not shadow["chain_ok"]:
        attention.append("shadow ledger chain does not verify")
    if recovery["blocking"]:
        attention.append(f"{recovery['blocking']} recovery journal(s) in a blocking phase")
    if leases["ambiguous"]:
        attention.append(f"{leases['ambiguous']} quarantined execution lease(s)")
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
              f"recovery_journals={r['journals']} blocking={r['blocking']}; "
              f"leases active={le['active']} used={le['used']} quarantined={le['ambiguous']}; "
              f"locks={report['locks']['active']}")
        for note in report["attention"]:
            print(f"  ATTENTION: {note}")
    return 2 if report["health"] == ATTENTION else 0


if __name__ == "__main__":
    raise SystemExit(main())
