"""External supervisor: the party that issues leases, so the agent never does.

Delegation is authorised in the control plane but nothing issues the lease it
asks for, so dynamic capability escalation does not exist yet. This is that
missing party.

The whole design turns on one rule: the conductor must never hold the lease. If
Bro requests a lease and the lease lands in Bro's environment, Bro holds write
authority for its lifetime and "temporary" carries the entire argument. Worse, a
role switch inside one process is a variable, and prompt injection that flips a
variable is escalation. So the supervisor runs outside both processes, spawns a
separate builder, injects the lease only into that builder's environment, and
returns results and evidence to the conductor. Never the lease.

It lives in tools/ rather than runtime/ for the same reason bro_signature only
verifies: a component the agent can reach is a component the agent controls.

    python tools/bro_supervisor.py run --request req.json --keydir KEYS \\
        --registry KEYS/trusted-keys.json --workspace . --builder-command "..."
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "tools"))

from bro_protected import SECURITY, STANDARD, TASK_CLASSES
from bro_signature import SignatureError, load_trusted_keys, verify_artifact

from broctl import sign_payload

DEFAULT_LEASE_SECONDS = 15 * 60

DENIED = "denied"
COMPLETED = "completed"
FAILED = "failed"
EXPIRED = "expired"


class SupervisorError(Exception):
    pass


@dataclass(frozen=True)
class TaskRequest:
    task_id: str
    task_class: str
    rationale: str
    protected_scope: tuple[str, ...] = ()

    @staticmethod
    def load(value: dict) -> "TaskRequest":
        for field_name in ("task_id", "task_class", "rationale"):
            if not isinstance(value.get(field_name), str) or not value[field_name]:
                raise SupervisorError(f"task request missing {field_name}")
        if value["task_class"] not in TASK_CLASSES:
            raise SupervisorError(f"unknown task class: {value['task_class']!r}")
        scope = value.get("protected_scope") or []
        if not isinstance(scope, list) or any(not isinstance(p, str) for p in scope):
            raise SupervisorError("protected_scope must be a list of exact paths")
        for path in scope:
            if any(ch in path for ch in "*?["):
                raise SupervisorError(
                    f"protected_scope must contain exact paths, not patterns: {path!r}")
        return TaskRequest(value["task_id"], value["task_class"], value["rationale"],
                           tuple(scope))


@dataclass(frozen=True)
class SupervisorResult:
    """What the conductor is allowed to learn.

    Deliberately carries no lease, no key, no environment. Bro receives outcomes
    and evidence; anything else would hand it the authority the split exists to
    withhold.
    """
    task_id: str
    status: str
    message: str
    exit_code: int | None = None
    evidence: tuple[str, ...] = field(default_factory=tuple)


def authorize_request(request: TaskRequest, approval: dict | None,
                      keys: dict, *, now: int | None = None) -> str:
    """A standard task needs no approval. A security-maintenance task needs the
    owner's, bound to this exact task and this exact path list, because the paths
    it touches are the ones that define every other boundary."""
    if request.task_class == STANDARD:
        if request.protected_scope:
            raise SupervisorError(
                "a standard-builder task may not carry a protected scope")
        return "standard-builder task; no owner approval required"
    if request.task_class != SECURITY:
        raise SupervisorError(f"unknown task class: {request.task_class!r}")
    if not request.protected_scope:
        raise SupervisorError(
            "a security-maintenance task must name the exact paths it needs")
    if approval is None:
        raise SupervisorError(
            "a security-maintenance task requires an owner-signed approval")
    payload = verify_artifact(approval, "protected-authority", keys, now=now)
    if payload.get("task_id") != request.task_id:
        raise SupervisorError("owner approval is bound to a different task")
    if payload.get("owner_approval") is not True:
        raise SupervisorError("owner approval does not approve")
    approved = payload.get("protected_scope")
    if not isinstance(approved, list):
        raise SupervisorError("owner approval carries no protected scope")
    extra = sorted(set(request.protected_scope) - set(approved))
    if extra:
        raise SupervisorError(f"paths requested beyond the owner's approval: {extra}")
    return f"security-maintenance task approved by {payload.get('key_id')}"


def issue_lease(request: TaskRequest, issuer_key: dict, *, workspace_id: str,
                repository: str, worktree: str, agent_id: str, session_id: str,
                control_plane_digest: str, ttl_seconds: int, now: int) -> dict:
    """Sign a lease bound to exactly one task, agent, session, worktree and
    control plane. A lease that outlives its control plane authorises work
    against a system that no longer exists."""
    if issuer_key["authority_type"] != "issuer":
        raise SupervisorError(
            f"a {issuer_key['authority_type']} key may not issue execution leases")
    payload = {
        "artifact_type": "execution-lease",
        "key_id": issuer_key["key_id"],
        "lease_id": f"lease-{uuid.uuid4().hex[:16]}",
        "task_id": request.task_id,
        "task_class": request.task_class,
        "protected_scope": list(request.protected_scope),
        "agent_id": agent_id,
        "session_id": session_id,
        "workspace_id": workspace_id,
        "repository": repository,
        "worktree": worktree,
        "control_plane_digest": control_plane_digest,
        "issued_at_epoch": now,
        "expires_at_epoch": now + ttl_seconds,
    }
    return sign_payload(issuer_key["private_key"], payload)


def prepare_worktree(repository_root: pathlib.Path, task_id: str,
                     base: str = "HEAD") -> tuple[pathlib.Path, str]:
    """A fresh isolated worktree per task, so two builders cannot collide and a
    failed builder cannot leave the conductor's checkout dirty."""
    parent = pathlib.Path(tempfile.mkdtemp(prefix=f"bro-wt-{task_id}-"))
    worktree = parent / "work"
    branch = f"supervised/{task_id}-{uuid.uuid4().hex[:8]}"
    result = subprocess.run(
        ["git", "-C", str(repository_root), "worktree", "add", "-b", branch,
         str(worktree), base],
        capture_output=True, text=True)
    if result.returncode != 0:
        shutil.rmtree(parent, ignore_errors=True)
        raise SupervisorError(f"cannot create worktree: {result.stderr.strip()}")
    return worktree, branch


def remove_worktree(repository_root: pathlib.Path, worktree: pathlib.Path) -> None:
    subprocess.run(["git", "-C", str(repository_root), "worktree", "remove",
                    "--force", str(worktree)], capture_output=True, text=True)
    shutil.rmtree(worktree.parent, ignore_errors=True)


def spawn_builder(command: list[str], *, worktree: pathlib.Path, lease_path: pathlib.Path,
                  binding_path: pathlib.Path, state_dir: pathlib.Path, agent_id: str,
                  session_id: str, timeout: float) -> tuple[int, str, str, bool]:
    """Run the builder in its own process with the lease in its environment only.

    The supervisor's own environment is not inherited wholesale: the builder gets
    what it needs and nothing that would let it reach the issuer.
    """
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "BRO_MODE": "work",
        "BRO_ROLE": "specialist",
        "BRO_AGENT_ID": agent_id,
        "BRO_SESSION_ID": session_id,
        "BRO_EXECUTION_LEASE": str(lease_path),
        "BRO_WORKSPACE_BINDING": str(binding_path),
        "BRO_SESSION_STATE_DIR": str(state_dir),
    }
    try:
        completed = subprocess.run(command, cwd=str(worktree), env=env,
                                   capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        # Expiry is enforced by killing the process, not by asking it to stop.
        return -1, "", "builder exceeded its lease and was terminated", True
    return completed.returncode, completed.stdout, completed.stderr, False


def run_task(request: TaskRequest, *, repository_root: pathlib.Path, keydir: pathlib.Path,
             registry_root: pathlib.Path, binding_path: pathlib.Path,
             builder_command: list[str], approval: dict | None = None,
             agent_id: str = "agt-p01-r01", ttl_seconds: int = DEFAULT_LEASE_SECONDS,
             now: int | None = None) -> SupervisorResult:
    moment = int(time.time()) if now is None else now
    session_id = f"sup-{uuid.uuid4().hex[:12]}"
    try:
        keys = load_trusted_keys(registry_root)
        reason = authorize_request(request, approval, keys, now=moment)
    except (SignatureError, SupervisorError) as exc:
        return SupervisorResult(request.task_id, DENIED, str(exc))

    try:
        issuer_key = json.loads((keydir / "issuer.json").read_text(encoding="utf-8"))
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return SupervisorResult(request.task_id, DENIED, f"supervisor state unusable: {exc}")

    try:
        worktree, branch = prepare_worktree(repository_root, request.task_id)
    except SupervisorError as exc:
        return SupervisorResult(request.task_id, DENIED, str(exc))

    state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-state-"))
    lease_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-lease-"))
    lease_path = lease_dir / "lease.json"
    try:
        lease = issue_lease(
            request, issuer_key, workspace_id=binding["workspace_id"],
            repository=binding["repository"], worktree=str(worktree),
            agent_id=agent_id, session_id=session_id,
            control_plane_digest=binding["control_plane_digest"],
            ttl_seconds=ttl_seconds, now=moment)
        lease_path.write_text(json.dumps(lease), encoding="utf-8")

        code, stdout, stderr, timed_out = spawn_builder(
            builder_command, worktree=worktree, lease_path=lease_path,
            binding_path=binding_path, state_dir=state_dir, agent_id=agent_id,
            session_id=session_id, timeout=float(ttl_seconds))
    except (SupervisorError, OSError) as exc:
        remove_worktree(repository_root, worktree)
        return SupervisorResult(request.task_id, FAILED, str(exc))
    finally:
        # The lease dies with the run. A lease that outlives its builder is a
        # credential lying on disk.
        shutil.rmtree(lease_dir, ignore_errors=True)

    evidence = tuple(line for line in stdout.splitlines() if line.startswith("evidence:"))
    if timed_out:
        remove_worktree(repository_root, worktree)
        return SupervisorResult(request.task_id, EXPIRED,
                                "lease expired; builder terminated", None, evidence)
    if code != 0:
        return SupervisorResult(request.task_id, FAILED,
                                f"builder exited {code}: {stderr.strip()[:200]}",
                                code, evidence)
    return SupervisorResult(request.task_id, COMPLETED,
                            f"{reason}; builder finished on {branch}", code, evidence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="supervise one delegated task")
    run.add_argument("--request", required=True)
    run.add_argument("--keydir", required=True)
    run.add_argument("--registry-root", required=True)
    run.add_argument("--binding", required=True)
    run.add_argument("--repository-root", default=".")
    run.add_argument("--approval")
    run.add_argument("--ttl-seconds", type=int, default=DEFAULT_LEASE_SECONDS)
    run.add_argument("builder_command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    try:
        request = TaskRequest.load(json.loads(pathlib.Path(args.request).read_text(encoding="utf-8")))
        approval = (json.loads(pathlib.Path(args.approval).read_text(encoding="utf-8"))
                    if args.approval else None)
        command = [a for a in args.builder_command if a != "--"]
        if not command:
            raise SupervisorError("no builder command given")
        result = run_task(
            request, repository_root=pathlib.Path(args.repository_root).resolve(),
            keydir=pathlib.Path(args.keydir), registry_root=pathlib.Path(args.registry_root),
            binding_path=pathlib.Path(args.binding), builder_command=command,
            approval=approval, ttl_seconds=args.ttl_seconds)
    except (SupervisorError, OSError, json.JSONDecodeError) as exc:
        print(f"RED: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), indent=2, sort_keys=True))
    return 0 if result.status == COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(main())
