from __future__ import annotations

import json
import os
import pathlib
import time
from dataclasses import asdict, dataclass

AUTHORIZED = "authorized"
FROZEN = "authority-frozen"


class FreezeError(Exception):
    pass


@dataclass(frozen=True)
class Freeze:
    session_id: str
    task_id: str
    digest_before: str
    frozen_at_epoch: int


def _state_dir() -> pathlib.Path:
    """Freeze markers live outside the repository: the repository is itself a
    protected root, so a marker stored inside it would be unwritable by the very
    mutation that needs to record the freeze."""
    raw = os.getenv("BRO_SESSION_STATE_DIR")
    if not raw:
        raise FreezeError("missing BRO_SESSION_STATE_DIR")
    path = pathlib.Path(raw)
    if not path.is_absolute():
        raise FreezeError("BRO_SESSION_STATE_DIR must be an absolute path")
    return path


def _marker(session_id: str) -> pathlib.Path:
    if not session_id or "/" in session_id or "\\" in session_id or "." in session_id:
        raise FreezeError(f"unusable session id for a freeze marker: {session_id!r}")
    return _state_dir() / f"{session_id}.freeze.json"


def load_freeze(session_id: str) -> Freeze | None:
    path = _marker(session_id)
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return Freeze(
            session_id=str(value["session_id"]),
            task_id=str(value["task_id"]),
            digest_before=str(value["digest_before"]),
            frozen_at_epoch=int(value["frozen_at_epoch"]),
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise FreezeError(f"freeze marker is unreadable; failing closed: {exc}") from exc


def freeze_authority(session_id: str, task_id: str, digest_before: str) -> Freeze:
    """Record that a security-maintenance task has mutated a protected path.

    From this point the session holds no further mutation authority: the control
    plane it was authorised against no longer exists. Only settlement remains.
    """
    freeze = Freeze(session_id, task_id, digest_before, int(time.time()))
    path = _marker(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(asdict(freeze), handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise FreezeError(f"cannot record freeze marker: {exc}") from exc
    return freeze


def authorize_under_freeze(freeze: Freeze, classification) -> tuple[bool, str]:
    """AUTHORIZED -> PROTECTED_MUTATION -> AUTHORITY_FROZEN -> SETTLEMENT_ONLY.

    Reads still pass so evidence can be gathered and handed off. Every mutation
    and every push is denied: a new control plane requires a new owner-issued
    binding, a new session and a new lease.
    """
    if getattr(classification, "push", False) or getattr(classification, "mutating", False):
        return False, (f"authority frozen after protected mutation under task "
                       f"{freeze.task_id}; settlement only, new authority required")
    return True, f"settlement-only read permitted under authority frozen at {freeze.frozen_at_epoch}"
