"""Run a command and sign what actually happened.

This is the other half of runtime/bro_receipt.py. It runs in the runner, holds
the evidence key, and observes the execution rather than being told about it. The
verifier only checks; a component that could sign could forge, so the two halves
never live in the same process.

It reads HEAD and the tree from git itself rather than accepting them as
arguments. A runner that is told which commit it ran against can be told
anything, and the whole point is to bind the transcript to the state that
actually produced it.

    python tools/bro_run_receipt.py --key KEYS/evidence-recorder.json \\
        --task-id task-1 --out receipts/tests.json -- python -m unittest discover -s tests
"""

from __future__ import annotations

import argparse
import json
import pathlib
import platform
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from bro_receipt import ReceiptError, catalog_sha256, transcript_sha256

from broctl import sign_payload


def git(root: pathlib.Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise ReceiptError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def candidate_state(root: pathlib.Path) -> tuple[str, str]:
    """Read HEAD and the tree from git, and refuse a dirty worktree.

    A receipt from a dirty tree names a commit that does not describe what ran, so
    the signature would attest to a state that never existed.
    """
    if git(root, "status", "--porcelain"):
        raise ReceiptError(
            "worktree is dirty; a receipt from it would name a commit that does "
            "not describe what actually ran")
    return git(root, "rev-parse", "HEAD"), git(root, "rev-parse", "HEAD^{tree}")


def run_and_sign(command: list[str], *, key: dict, task_id: str,
                 root: pathlib.Path, runner_id: str, now: int | None = None) -> dict:
    if key["authority_type"] != "evidence-recorder":
        raise ReceiptError(
            f"a {key['authority_type']} key may not sign execution receipts: that "
            f"requires evidence-recorder authority")
    head, tree = candidate_state(root)
    started = int(time.time()) if now is None else now
    completed = subprocess.run(command, cwd=str(root), capture_output=True, text=True)
    finished = int(time.time()) if now is None else now

    payload = {
        "artifact_type": "evidence-event",
        "key_id": key["key_id"],
        "receipt_id": f"rcpt-{uuid.uuid4().hex[:16]}",
        "task_id": task_id,
        "command": list(command),
        "working_directory": str(root),
        "candidate_head": head,
        "candidate_tree": tree,
        "exit_code": completed.returncode,
        "stdout_sha256": transcript_sha256(completed.stdout),
        "stderr_sha256": transcript_sha256(completed.stderr),
        "runner_id": runner_id,
        "runner_platform": f"{platform.system()}-{platform.machine()}-"
                           f"py{platform.python_version()}",
        "started_at_epoch": started,
        "finished_at_epoch": finished,
        "test_catalog_sha256": catalog_sha256(root),
        "issued_at_epoch": finished,
    }
    return sign_payload(key["private_key"], payload), completed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--key", required=True, help="evidence-recorder key")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--root", default=".")
    parser.add_argument("--runner-id", default=platform.node() or "unknown-runner")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    command = [a for a in args.command if a != "--"]
    if not command:
        print("RED: no command given", file=sys.stderr)
        return 2

    try:
        key = json.loads(pathlib.Path(args.key).read_text(encoding="utf-8"))
        document, completed = run_and_sign(
            command, key=key, task_id=args.task_id,
            root=pathlib.Path(args.root).resolve(), runner_id=args.runner_id)
    except (ReceiptError, OSError, json.JSONDecodeError) as exc:
        print(f"RED: {exc}", file=sys.stderr)
        return 2

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    sys.stdout.write(completed.stdout)
    sys.stderr.write(completed.stderr)
    payload = document["payload"]
    print(f"\nreceipt: {payload['receipt_id']} exit={payload['exit_code']} "
          f"head={payload['candidate_head'][:12]} -> {out}")
    # The receipt records the outcome; it does not launder it. A failing run
    # produces a signed receipt saying so, and this exits non-zero anyway.
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
