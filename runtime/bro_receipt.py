"""Execution receipts: making "I ran the tests" checkable rather than trusted.

Repository integrity answers what the tree contained. It says nothing about what
actually executed against it. A builder reporting "284 tests passed" is making a
claim of exactly the kind this repository exists to refuse, and the completion
manifest accepted it on the strength of an evidence id that proved only that a
string had been written down.

A receipt binds an execution to the state it ran against and the transcript it
produced: the exact command and working directory, the candidate HEAD and tree,
the exit code, hashes of stdout and stderr, the runner's identity and platform,
and start and end times. Change any of them and the receipt stops verifying.

Like every other verifier here this module only checks. Receipts are produced by
tools/bro_run_receipt.py, which runs in the runner and holds the evidence key. An
enforcement point that can sign is an enforcement point that can forge.

The transcript is hashed rather than carried: a receipt should prove what
happened, not reproduce it.
"""

from __future__ import annotations

import hashlib
import pathlib
import time
from typing import Any

from bro_signature import SignatureError, verify_artifact

ROOT = pathlib.Path(__file__).resolve().parents[1]

REQUIRED_FIELDS = {
    "artifact_type", "key_id", "receipt_id", "task_id", "command",
    "working_directory", "candidate_head", "candidate_tree", "exit_code",
    "stdout_sha256", "stderr_sha256", "runner_id", "runner_platform",
    "started_at_epoch", "finished_at_epoch", "test_catalog_sha256",
    "issued_at_epoch",
}


class ReceiptError(Exception):
    pass


def transcript_sha256(text: str) -> str:
    """Normalised to LF before hashing.

    The same command on Windows and Linux must produce the same digest, or a
    receipt could only be verified on the platform that made it, and CI runs both.
    """
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def catalog_sha256(root: pathlib.Path = ROOT) -> str:
    try:
        return hashlib.sha256((root / "tests" / "catalog.json").read_bytes()).hexdigest()
    except OSError as exc:
        raise ReceiptError(f"cannot read the test catalog: {exc}") from exc


def _hex(value: Any, field: str, length: int) -> None:
    if not isinstance(value, str) or len(value) != length:
        raise ReceiptError(f"{field} must be {length} hex characters")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ReceiptError(f"{field} is not hex") from exc


def verify_receipt(document: dict[str, Any], keys: dict, *, task_id: str,
                   candidate_head: str, candidate_tree: str,
                   root: pathlib.Path = ROOT, now: int | None = None) -> dict:
    """Verify a receipt and prove it describes this task and this candidate.

    A receipt that verifies cryptographically but describes another commit is
    worse than none: it carries a valid signature over irrelevant work.
    """
    try:
        payload = verify_artifact(document, "evidence-event", keys, now=now)
    except SignatureError as exc:
        raise ReceiptError(f"receipt signature RED: {exc}") from exc

    missing = REQUIRED_FIELDS - set(payload)
    if missing:
        raise ReceiptError(f"receipt is missing fields: {sorted(missing)}")
    extra = set(payload) - REQUIRED_FIELDS
    if extra:
        raise ReceiptError(f"receipt carries unexpected fields: {sorted(extra)}")

    if payload["task_id"] != task_id:
        raise ReceiptError("receipt belongs to a different task")
    if payload["candidate_head"] != candidate_head:
        raise ReceiptError("receipt was produced against a different HEAD")
    if payload["candidate_tree"] != candidate_tree:
        raise ReceiptError("receipt was produced against a different tree")

    # candidate_head is git's HEAD (SHA-1, 40); the candidate tree is the canonical
    # workspace tree identity (SHA-256, 64) shared with the repository state and the
    # completion manifest, not git's tree object SHA. Lengths are checked apart so a
    # truncated digest cannot be silently accepted.
    _hex(payload["candidate_head"], "candidate_head", 40)
    for field in ("candidate_tree", "stdout_sha256", "stderr_sha256", "test_catalog_sha256"):
        _hex(payload[field], field, 64)

    if payload["test_catalog_sha256"] != catalog_sha256(root):
        raise ReceiptError(
            "receipt was produced against a different test catalog; the set of "
            "tests it claims to have run is not the set registered here")

    if not isinstance(payload["exit_code"], int):
        raise ReceiptError("exit_code must be an integer")
    command = payload["command"]
    if not isinstance(command, list) or not command:
        raise ReceiptError("command must be a non-empty argument list")
    if any(not isinstance(arg, str) for arg in command):
        raise ReceiptError("command arguments must be strings")
    for field in ("working_directory", "runner_id", "runner_platform"):
        if not isinstance(payload[field], str) or not payload[field]:
            raise ReceiptError(f"{field} must be a non-empty string")

    started, finished = payload["started_at_epoch"], payload["finished_at_epoch"]
    if not isinstance(started, int) or not isinstance(finished, int):
        raise ReceiptError("receipt timestamps must be integers")
    if finished < started:
        raise ReceiptError("receipt finished before it started")
    moment = int(time.time()) if now is None else now
    if started > moment + 60:
        raise ReceiptError("receipt claims to have started in the future")
    return payload


def verify_passing_receipt(document: dict[str, Any], keys: dict, **kwargs) -> dict:
    """A receipt proves what happened, not that it went well.

    Completion needs both, and conflating them is how a red run becomes a green
    claim.
    """
    payload = verify_receipt(document, keys, **kwargs)
    if payload["exit_code"] != 0:
        raise ReceiptError(f"receipt records a failing run: exit {payload['exit_code']}")
    return payload


def verify_receipt_set(documents: list[dict[str, Any]], keys: dict, *,
                       required_commands: list[list[str]], **kwargs) -> list[dict]:
    """Prove every required command ran and passed.

    Without this a builder satisfies the gate by running the one cheap command it
    knows will pass and never mentioning the rest.
    """
    payloads = [verify_passing_receipt(document, keys, **kwargs) for document in documents]
    ran = [payload["command"] for payload in payloads]
    for command in required_commands:
        if command not in ran:
            raise ReceiptError(f"no passing receipt for required command: {command}")
    return payloads
