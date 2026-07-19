"""Deployment-posture preflight (Execution Surface kind=startup, posture).

The runtime enforces per action; this proves the ENVIRONMENT it runs in is hardened
BEFORE the first action, turning owner configuration from prose in the runbook into a
fail-closed gate. It checks what the per-action gates assume but never verify at
startup:

  * the operator-root trust anchor is pinned from an operator-controlled FILE outside
    the repository (BRO_OPERATOR_ROOT_PUBKEY_FILE) — not the raw CI env var, which a
    process that can set its own environment could also set;
  * the trusted-key registry authenticates against that pin, carries the owner-held
    recovery authority (blocker 7), binds every builder/verifier key to a subject
    agent id (blocker 6b — an unbound signer is not an identity), and ships no private
    key material;
  * every machine-local ledger/store that is configured is an absolute path OUTSIDE
    the repository, so runtime state can never be committed to git, and shadow mode is
    never left without its ledger (which would fail open).

This is a DEPLOYMENT tool, not a CI step: CI legitimately pins via the raw env var, so
running the preflight there would (correctly) report the raw-env posture as un-hardened.

Reads the environment; never mutates. Standard library beyond bro_signature.
"""
from __future__ import annotations

import os
import pathlib
import sys
from typing import Mapping

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "runtime") not in sys.path:
    sys.path.insert(0, str(ROOT / "runtime"))

from bro_signature import (
    BUILDER,
    ENV_PIN,
    ENV_PIN_FILE,
    OPERATOR,
    RECOVERY,
    VERIFIER,
    SignatureError,
    load_trusted_keys,
    resolve_operator_root_pin,
)

# Machine-local ledgers/stores whose value, when configured, must be an absolute path
# outside the repository so runtime state is never committable.
LEDGER_VARS = (
    "BRO_EXECUTION_LEASE_LEDGER",
    "BRO_RECOVERY_STORE",
    "BRO_TASK_LOCK_LEDGER",
    "BRO_EVIDENCE_STORE",
    "BRO_SHADOW_LEDGER",
    "BRO_RELEASE_LEDGER",
)


def _external_absolute(raw: str, root: pathlib.Path) -> str | None:
    """A failure reason if `raw` is not an absolute path outside the repo, else None."""
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        return "must be an absolute path"
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        return None
    return "must be outside the repository"


def check_operator_pin(env: Mapping[str, str], root: pathlib.Path) -> list[str]:
    """Production must pin the operator root from an operator-controlled file."""
    if not env.get(ENV_PIN_FILE):
        return [f"{ENV_PIN_FILE} is not set — a hardened deployment pins the operator "
                f"root from an operator-controlled file, not the CI {ENV_PIN} env var"]
    try:
        resolve_operator_root_pin(env=env, root=root)
    except SignatureError as exc:
        return [f"operator-root pin invalid: {exc}"]
    return []


def check_registry(env: Mapping[str, str], root: pathlib.Path) -> list[str]:
    """The registry must authenticate and carry a hardened set of authorities."""
    try:
        pin = resolve_operator_root_pin(env=env, root=root)
        keys = load_trusted_keys(root=root, operator_public_key=pin)
    except SignatureError as exc:
        return [f"trusted-key registry does not authenticate: {exc}"]

    failures: list[str] = []
    authorities = {key.authority_type for key in keys.values()}
    if OPERATOR not in authorities:
        failures.append("registry carries no operator-root authority")
    if RECOVERY not in authorities:
        failures.append("registry carries no recovery authority — the owner-signed "
                        "recovery proof (blocker 7) cannot be verified")
    for key in keys.values():
        if key.authority_type in (BUILDER, VERIFIER) and not key.subject_agent_id:
            failures.append(
                f"{key.authority_type} key {key.key_id} has no subject_agent_id — its "
                "signatures are not cryptographically bound to an agent identity")
    return failures


def check_ledgers(env: Mapping[str, str], root: pathlib.Path) -> list[str]:
    """Every configured ledger must be external + absolute; shadow needs its ledger."""
    failures: list[str] = []
    for var in LEDGER_VARS:
        raw = env.get(var)
        if not raw:
            continue
        reason = _external_absolute(raw, root)
        if reason:
            failures.append(f"{var} {reason}: {raw}")
    if env.get("BRO_ENFORCEMENT") == "shadow" and not env.get("BRO_SHADOW_LEDGER"):
        failures.append("BRO_ENFORCEMENT=shadow but BRO_SHADOW_LEDGER is not set — "
                        "shadow mode without a usable ledger fails open")
    return failures


CHECKS = (check_operator_pin, check_registry, check_ledgers)


def preflight(env: Mapping[str, str] | None = None, root: pathlib.Path = ROOT) -> list[str]:
    """Return every deployment-posture failure; an empty list means hardened."""
    env = os.environ if env is None else env
    failures: list[str] = []
    for check in CHECKS:
        failures.extend(check(env, root))
    return failures


def main(argv: list[str] | None = None) -> int:
    failures = preflight()
    if failures:
        for reason in failures:
            print(f"RED: {reason}", file=sys.stderr)
        print(f"deployment posture RED: {len(failures)} issue(s) must be fixed before "
              "the runtime may enforce in production", file=sys.stderr)
        return 1
    print("GREEN: deployment posture hardened")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
