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

from bro_audit_log import append as audit_append
from bro_authorize_specialist import build_mode_grant_payload, sign_mode_grant
from bro_execution_lease import CLASS_CAPABILITIES
from bro_skill_receipt import build_skill_receipt
from bro_protected import SECURITY, STANDARD, TASK_CLASSES
from bro_repository_state import RepositoryStateError, resolve_state
from bro_signature import SignatureError, load_trusted_keys, verify_artifact
from bro_stop_controller import register, terminate_group

from broctl import sign_payload

DEFAULT_LEASE_SECONDS = 15 * 60
# A supervised build makes many tool calls; the lease bounds them so a stolen lease
# cannot drive an unbounded session. Generous but finite, within the schema ceiling.
DEFAULT_MAX_TOOL_CALLS = 1000

DENIED = "denied"
COMPLETED = "completed"
FAILED = "failed"
EXPIRED = "expired"
# The builder finished, but its process group could not be confirmed stopped: a
# live orphan remains. Never reported as COMPLETED — an uncontained result is not
# a successful one.
UNCONTAINED = "uncontained"


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
                repository: str, worktree: str, branch: str, head_sha: str,
                tree_identity: str, agent_id: str, session_id: str,
                control_plane_digest: str, ttl_seconds: int, now: int,
                nonce: str | None = None,
                max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS) -> dict:
    """Sign the canonical execution lease the runtime actually consumes.

    One shape, verified by validate_execution_lease inside the builder: the runtime
    bindings (branch, head_sha, tree_identity, capabilities, nonce, max_tool_calls)
    that bind the lease to this exact worktree state, PLUS the delegation bindings
    (task_class, protected_scope, control_plane_digest, workspace_id). Capabilities
    are fixed by the task class, so a lease cannot grant more than its class allows.
    A lease that outlives its control plane authorises work against a system that no
    longer exists — control_plane_digest is what lets the consumer reject that."""
    if issuer_key["authority_type"] != "issuer":
        raise SupervisorError(
            f"a {issuer_key['authority_type']} key may not issue execution leases")
    if request.task_class not in CLASS_CAPABILITIES:
        raise SupervisorError(f"unknown task class: {request.task_class!r}")
    payload = {
        "schema": 1,
        "artifact_type": "execution-lease",
        "key_id": issuer_key["key_id"],
        "lease_id": f"lease-{uuid.uuid4().hex[:16]}",
        "nonce": nonce or f"nonce-{uuid.uuid4().hex}",
        "task_id": request.task_id,
        "agent_id": agent_id,
        "session_id": session_id,
        "repository": repository,
        "branch": branch,
        "worktree": worktree,
        "head_sha": head_sha,
        "tree_identity": tree_identity,
        "allowed_capabilities": sorted(CLASS_CAPABILITIES[request.task_class]),
        "issued_at_epoch": now,
        "expires_at_epoch": now + ttl_seconds,
        "max_tool_calls": max_tool_calls,
        "task_class": request.task_class,
        "protected_scope": list(request.protected_scope),
        "control_plane_digest": control_plane_digest,
        "workspace_id": workspace_id,
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


class _WindowsJobObject:
    """Kill-on-close Job Object that reaps the builder's whole tree on Windows.

    There are no POSIX process groups here, and ``taskkill /T`` walks a
    parent-chain snapshot: a grandchild whose parent already exited is reparented
    and escapes the walk, keeping the injected BRO_EXECUTION_LEASE context alive.
    Job membership is inherited by every descendant regardless of reparenting, so
    TerminateJobObject reaps the true tree, the job's accounting counter confirms
    zero live members (a confirmation, not taskkill's word for it), and the
    KILL_ON_JOB_CLOSE limit makes even a supervisor crash reap the tree when the
    handle is closed.
    """

    _KILL_ON_JOB_CLOSE = 0x2000
    _EXTENDED_LIMIT_INFORMATION = 9
    _BASIC_ACCOUNTING_INFORMATION = 1

    def __init__(self) -> None:
        import ctypes

        class _BasicLimits(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32),
            ]

        class _IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _ExtendedLimits(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BasicLimits),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        class _BasicAccounting(ctypes.Structure):
            _fields_ = [
                ("TotalUserTime", ctypes.c_int64),
                ("TotalKernelTime", ctypes.c_int64),
                ("ThisPeriodTotalUserTime", ctypes.c_int64),
                ("ThisPeriodTotalKernelTime", ctypes.c_int64),
                ("TotalPageFaultCount", ctypes.c_uint32),
                ("TotalProcesses", ctypes.c_uint32),
                ("ActiveProcesses", ctypes.c_uint32),
                ("TotalTerminatedProcesses", ctypes.c_uint32),
            ]

        self._ctypes = ctypes
        self._accounting_type = _BasicAccounting
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        job = self._kernel32.CreateJobObjectW(None, None)
        if not job:
            raise OSError(f"CreateJobObject failed: {ctypes.get_last_error()}")
        info = _ExtendedLimits()
        info.BasicLimitInformation.LimitFlags = self._KILL_ON_JOB_CLOSE
        if not self._kernel32.SetInformationJobObject(
                job, self._EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            self._kernel32.CloseHandle(job)
            raise OSError(f"SetInformationJobObject failed: {error}")
        self._job = job

    def assign(self, process_handle: int) -> None:
        if not self._kernel32.AssignProcessToJobObject(self._job, int(process_handle)):
            raise OSError(
                f"AssignProcessToJobObject failed: {self._ctypes.get_last_error()}")

    def kill_and_confirm(self, grace_seconds: float = 2.0, poll: float = 0.05) -> bool:
        """Terminate every member and return True only on confirmed zero live members."""
        if self._job is None:
            return True
        self._kernel32.TerminateJobObject(self._job, 1)
        deadline = time.monotonic() + grace_seconds
        while True:
            info = self._accounting_type()
            ok = self._kernel32.QueryInformationJobObject(
                self._job, self._BASIC_ACCOUNTING_INFORMATION,
                self._ctypes.byref(info), self._ctypes.sizeof(info), None)
            if ok and info.ActiveProcesses == 0:
                return True
            if time.monotonic() >= deadline:
                # A failed query or a survivor both mean "not confirmed stopped".
                return False
            time.sleep(poll)

    def close(self) -> None:
        if self._job is not None:
            self._kernel32.CloseHandle(self._job)  # KILL_ON_JOB_CLOSE reaps stragglers
            self._job = None


def _teardown_group(pgid: int | None, *, task_id: str,
                    audit_path: pathlib.Path | None, repo_root: pathlib.Path | None,
                    job: "_WindowsJobObject | None" = None) -> bool:
    """Stop the builder's whole process group and confirm it stopped.

    This is the single teardown every exit path funnels through — timeout, clean
    exit, or exception — so the invariant holds everywhere: a group that cannot be
    confirmed stopped is written to the append-only audit ledger and reported as
    False. A live orphan is never silently accepted, and never only on timeout.
    Returns True when the group is confirmed stopped (or there is no group to stop).

    On Windows the Job Object is the authority (it reaps and confirms the whole
    tree, reparented grandchildren included); terminate_group runs as well so the
    root pid is confirmed even when job assignment was lost.
    """
    if pgid is None and job is None:
        return True
    contained = True
    if job is not None:
        try:
            contained = job.kill_and_confirm()
        except OSError:
            contained = False
    if pgid is not None:
        contained = terminate_group(pgid) and contained
    if contained:
        return True
    if audit_path is not None:
        audit_append(
            audit_path, "unstopped-process",
            {"task_id": task_id, "pid": pgid, "pgid": pgid,
             "detail": "builder process group could not be confirmed stopped"},
            repo_root=repo_root)
    return False


def produce_builder_bundle(task_contract: dict, agent_profile: dict, approval: dict | None, *,
                           issuer_key: dict, repository_full_name: str,
                           worktree: pathlib.Path, repo_state, session_id: str,
                           now: int, bundle_dir: pathlib.Path,
                           ttl_seconds: int) -> dict[str, str]:
    """Produce the governed authorization bundle a supervised builder verifies.

    The owner authors WHAT the task is (semantics, agent identity, skills,
    verification); the supervisor binds WHERE it runs. The owner cannot know the
    branch, HEAD and tree identity of the isolated worktree the supervisor creates
    per task, so the supervisor rewrites the contract's repository block to that
    worktree and issuer-signs the mode grant that anchors the contract, profile and
    skill-receipt hashes over the new binding. The builder cannot run this — it holds
    no issuer key — so it can verify this bundle but never widen it.

    Returns the BRO_* environment the builder must be given to verify its authority.
    """
    if agent_profile.get("agent_id") != task_contract.get("agent_id"):
        raise SupervisorError("task contract and agent profile name different agents")
    task = dict(task_contract)
    task["repository"] = {
        "full_name": repository_full_name,
        "branch": repo_state.branch,
        "worktree": str(worktree),
        "base_commit": repo_state.head_sha,
        "tree_identity": repo_state.tree_identity,
    }
    receipt = build_skill_receipt(task, agent_profile, root=worktree, now=now,
                                  ttl_seconds=ttl_seconds)
    grant_payload = build_mode_grant_payload(
        task, agent_profile, receipt, session_id=session_id, role="specialist",
        mode=task["mode"], head_sha=repo_state.head_sha,
        tree_identity=repo_state.tree_identity, now=now, ttl_seconds=ttl_seconds)
    signed_grant = sign_mode_grant(grant_payload, issuer_key, now)

    bundle_dir.mkdir(parents=True, exist_ok=True)
    artifacts = {
        "BRO_TASK_CONTRACT": ("task-contract.json", task),
        "BRO_AGENT_PROFILE": ("agent-profile.json", agent_profile),
        "BRO_SKILL_RECEIPT": ("skill-receipt.json", receipt),
        "BRO_MODE_GRANT": ("mode-grant.signed.json", signed_grant),
    }
    env: dict[str, str] = {}
    for var, (name, obj) in artifacts.items():
        path = bundle_dir / name
        path.write_text(json.dumps(obj), encoding="utf-8")
        env[var] = str(path)
    if approval is not None:
        path = bundle_dir / "protected-authority.json"
        path.write_text(json.dumps(approval), encoding="utf-8")
        env["BRO_PROTECTED_AUTHORITY"] = str(path)
    return env


def spawn_builder(command: list[str], *, worktree: pathlib.Path, lease_path: pathlib.Path,
                  binding_path: pathlib.Path, state_dir: pathlib.Path, agent_id: str,
                  session_id: str, timeout: float, task_id: str,
                  stop_registry: pathlib.Path | None = None,
                  audit_path: pathlib.Path | None = None,
                  repo_root: pathlib.Path | None = None,
                  extra_env: dict[str, str] | None = None) -> tuple[int, str, str, bool, bool]:
    """Run the builder in its own process group with the lease in its environment only.

    Two properties matter here. First, the supervisor's environment is not
    inherited wholesale: the builder gets what it needs and nothing that would let
    it reach the issuer. Second, the builder is launched as a process-group leader
    (``start_new_session``) and torn down by GROUP, never by direct child. A builder
    that spawns its own children would otherwise leak orphaned grandchildren when the
    lease expires — the per-child SIGKILL that ``subprocess.run(timeout=...)`` performs
    reaps only the leader and records nothing about what it left alive. On timeout the
    whole group is stopped, and any group that cannot be confirmed stopped is written
    to the append-only audit ledger; even on a clean exit the group is reaped so no
    daemon outlives the lease.

    Where ``os.killpg`` is unavailable (Windows) the builder is placed in a
    kill-on-close Job Object at spawn, so teardown reaps the whole descendant tree
    — reparented grandchildren included — and confirms zero live members via the
    job's accounting counter; ``pgid`` is the tree-root pid and terminate_group
    (taskkill /T + liveness probe) runs as a second confirmation. If the job
    cannot be created or the builder cannot be assigned to it, the spawn fails
    closed rather than run an uncontainable builder.
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
    # The governed authorization bundle (task contract, agent profile, skill receipt,
    # signed mode grant, protected authority) and the external lease ledger, when the
    # supervisor produced one. Still no issuer key: the builder receives only what it
    # must verify, never what would let it mint its own authority.
    if extra_env:
        env.update(extra_env)
    posix_groups = hasattr(os, "killpg")
    # Fail closed BEFORE the builder exists: a Windows spawn without a Job Object
    # would run a tree the teardown cannot fully reap or confirm.
    job = None if posix_groups else _WindowsJobObject()
    try:
        proc = subprocess.Popen(
            command, cwd=str(worktree), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=posix_groups,
        )
    except Exception:
        if job is not None:
            job.close()
        raise
    # start_new_session makes the child call setsid(), so it leads a new group whose
    # id equals its own pid. Use proc.pid directly rather than os.getpgid(proc.pid):
    # getpgid can race the child's setsid() and return the SUPERVISOR's own group,
    # which a later teardown would then signal — killing the supervisor itself.
    # On Windows pgid is the tree-root pid consumed by taskkill /T.
    pgid = proc.pid
    if job is not None:
        try:
            # Popen._handle is CPython's Windows process HANDLE; assignment must
            # precede any grandchild spawns escaping the job, so it happens
            # immediately after Popen returns.
            job.assign(proc._handle)  # noqa: SLF001
        except OSError:
            # The builder is running unjailed: stop it now and refuse the run.
            _teardown_group(pgid, task_id=task_id, audit_path=audit_path,
                            repo_root=repo_root)
            job.close()
            raise
    if stop_registry is not None:
        register(stop_registry, task_id, proc.pid, pgid)

    timed_out = False
    contained = True
    teardown_done = False
    stdout = stderr = ""
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            # Kill the whole descendant tree, not just the direct child, before
            # draining — otherwise the drain blocks on the still-live leader.
            contained = _teardown_group(
                pgid, task_id=task_id, audit_path=audit_path, repo_root=repo_root,
                job=job)
            teardown_done = True
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""
        else:
            # Clean or failed exit of the leader still leaves its own children in
            # the group. Reap the tree on the same teardown path; a survivor we
            # cannot stop is recorded and reported, exactly as on timeout.
            contained = _teardown_group(
                pgid, task_id=task_id, audit_path=audit_path, repo_root=repo_root,
                job=job)
            teardown_done = True
    finally:
        # Any unexpected error path still must not leave the tree running silently.
        # Capture the result so a group that could not be confirmed stopped here is
        # reported as uncontained, not left at the default True.
        if not teardown_done:
            contained = _teardown_group(
                pgid, task_id=task_id, audit_path=audit_path, repo_root=repo_root,
                job=job)
        if job is not None:
            job.close()

    if timed_out:
        return -1, stdout or "", "builder exceeded its lease and was terminated", True, contained
    code = proc.returncode if proc.returncode is not None else -1
    return code, stdout or "", stderr or "", False, contained


def run_task(request: TaskRequest, *, repository_root: pathlib.Path, keydir: pathlib.Path,
             registry_root: pathlib.Path, binding_path: pathlib.Path,
             builder_command: list[str], approval: dict | None = None,
             agent_id: str = "agt-p01-r01", ttl_seconds: int = DEFAULT_LEASE_SECONDS,
             now: int | None = None,
             audit_path: pathlib.Path | None = None,
             task_contract: dict | None = None,
             agent_profile: dict | None = None) -> SupervisorResult:
    moment = int(time.time()) if now is None else now
    session_id = f"sup-{uuid.uuid4().hex[:12]}"
    # When the owner hands over a task contract + agent profile, the supervisor issues
    # the builder its full governed authorization bundle bound to this worktree; the
    # lease's agent id must then be the contract's, not the caller default.
    if task_contract is not None:
        if agent_profile is None:
            return SupervisorResult(request.task_id, DENIED,
                                    "a task contract requires an agent profile")
        if task_contract.get("task_id") != request.task_id:
            return SupervisorResult(request.task_id, DENIED,
                                    "task contract task_id does not match the request")
        agent_id = task_contract.get("agent_id", agent_id)
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

    # The lease binds to the worktree's real state, exactly as the runtime validator
    # derives it from the builder's task contract — same branch, HEAD sha and tree
    # identity — so the lease the supervisor issues is one the runtime accepts.
    try:
        repo_state = resolve_state(worktree, cwd=worktree)
    except RepositoryStateError as exc:
        remove_worktree(repository_root, worktree)
        return SupervisorResult(request.task_id, DENIED, f"worktree state unusable: {exc}")

    state_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-state-"))
    lease_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-lease-"))
    lease_path = lease_dir / "lease.json"
    # STOP working area: an ephemeral process registry, plus the ledger that
    # records any group the supervisor could not confirm stopped. An operator may
    # point incidents at a central external ledger via ``audit_path``; otherwise
    # they land here, and the directory is kept only when a timeout may have
    # written one — never silently discarded.
    stop_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-stop-"))
    stop_registry = stop_dir / "processes.jsonl"
    incidents = audit_path if audit_path is not None else stop_dir / "incidents.jsonl"
    # The builder's authorization bundle and its external lease ledger, when the owner
    # provided a contract. Both are outside the repository so nothing is committable.
    bundle_dir = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-bundle-"))
    lease_ledger: pathlib.Path | None = None
    try:
        extra_env: dict[str, str] = {}
        if task_contract is not None:
            extra_env = produce_builder_bundle(
                task_contract, agent_profile, approval, issuer_key=issuer_key,
                repository_full_name=binding["repository"], worktree=worktree,
                repo_state=repo_state, session_id=session_id, now=moment,
                bundle_dir=bundle_dir, ttl_seconds=ttl_seconds)
            lease_ledger = pathlib.Path(tempfile.mkdtemp(prefix="bro-sup-leaseledger-"))
            extra_env["BRO_EXECUTION_LEASE_LEDGER"] = str(lease_ledger)

        lease = issue_lease(
            request, issuer_key, workspace_id=binding["workspace_id"],
            repository=binding["repository"], worktree=str(worktree),
            branch=repo_state.branch, head_sha=repo_state.head_sha,
            tree_identity=repo_state.tree_identity,
            agent_id=agent_id, session_id=session_id,
            control_plane_digest=binding["control_plane_digest"],
            ttl_seconds=ttl_seconds, now=moment)
        lease_path.write_text(json.dumps(lease), encoding="utf-8")

        code, stdout, stderr, timed_out, contained = spawn_builder(
            builder_command, worktree=worktree, lease_path=lease_path,
            binding_path=binding_path, state_dir=state_dir, agent_id=agent_id,
            session_id=session_id, timeout=float(ttl_seconds),
            task_id=request.task_id, stop_registry=stop_registry,
            audit_path=incidents, repo_root=repository_root, extra_env=extra_env)
    except (SupervisorError, OSError) as exc:
        remove_worktree(repository_root, worktree)
        shutil.rmtree(stop_dir, ignore_errors=True)
        return SupervisorResult(request.task_id, FAILED, str(exc))
    finally:
        # The lease, the signed authorization bundle and the lease ledger all die with
        # the run. A grant or lease that outlives its builder is a credential on disk.
        shutil.rmtree(lease_dir, ignore_errors=True)
        shutil.rmtree(bundle_dir, ignore_errors=True)
        if lease_ledger is not None:
            shutil.rmtree(lease_ledger, ignore_errors=True)

    # Keep the STOP directory only when an incident may have landed in the default
    # ledger — a timeout OR an uncontained group. With an external audit_path the
    # directory holds nothing but the ephemeral registry, so it is always removable.
    if audit_path is not None or (contained and not timed_out):
        shutil.rmtree(stop_dir, ignore_errors=True)

    evidence = tuple(line for line in stdout.splitlines() if line.startswith("evidence:"))
    if timed_out:
        remove_worktree(repository_root, worktree)
        return SupervisorResult(request.task_id, EXPIRED,
                                "lease expired; builder terminated", None, evidence)
    if not contained:
        # The builder returned, but a member of its group could not be confirmed
        # stopped (the incident is already recorded). A live orphan is not success:
        # never COMPLETED, and the worktree is left in place rather than pulled out
        # from under a process still using it.
        return SupervisorResult(
            request.task_id, UNCONTAINED,
            "builder finished but left a process group that could not be stopped",
            code, evidence)
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
