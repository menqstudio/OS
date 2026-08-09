from __future__ import annotations

import hashlib
import json
import re
import time
from collections import Counter
from typing import Any

from bro_evidence import EvidenceError, list_chain_task_ids, read_chains
from bro_identity import IdentityError, all_agent_identities
from bro_orchestration import OrchestrationError, validate_control_room_command
from bro_orchestration_runtime import (ACTOR_ASSIGNEE_LEASE,
                                       ACTOR_PROVEN_BY_SESSION as RUNTIME_ACTOR_PROVEN,
                                       ACTOR_RUNTIME_ORIGINATED, ACTOR_UNPROVEN,
                                       DurableOrchestrationRuntime,
                                       OrchestrationRuntimeError)
from bro_policy import (CANONICAL_CONDUCTOR_ID, CONDUCTOR_ROLE,
                        CONDUCTOR_SESSION_ARTIFACT)
from bro_signature import SignatureError, verify_artifact

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{1,127}$")
FORBIDDEN_SCOPE = {"credential", "deploy", "git", "production", "release", "repository", "brops"}

# --------------------------------------------------------------------------- #
# The governance mirror wire contract (`brops.governance-read.v1`).
#
# The cockpit asks this engine for four read-only surfaces over one request/reply
# document. The reply is deliberately three-valued, not two:
#
#   ok:true  + records:[...]            — the store was read and holds these records
#   ok:true  + records:[] + empty:true  — the store was read and holds NOTHING
#   ok:false + error:"..."              — the engine could not read, and says why
#
# The middle case is the one that is easy to get wrong and the one that matters most.
# "I looked and there is nothing" and "I could not look" are different facts, and a
# surface that collapses them will eventually paint an empty, reassuring page over a
# blind engine. So a refusal never carries a `records` key at all: there is no shape
# in which a refusal can be misread as a satisfied, empty chain.
#
# Nothing here decides anything. No approval is granted, no verdict is issued, no
# state is written; the request carries no key, lease or nonce, and the only input
# that reaches the stores is an optional task-id filter.
# --------------------------------------------------------------------------- #
GOVERNANCE_PROTOCOL = "brops.governance-read.v1"
GOVERNANCE_OP = "governance.read"
GOVERNANCE_SURFACES = ("decisionLedger", "evidenceChain", "verdicts", "approvalQueue")
_GOVERNANCE_REQUEST_FIELDS = frozenset({"protocol", "op", "surface", "task_id", "read_only"})

# How the records on each surface were established. Both are real integrity claims and
# they are not the same claim, so the reply states which one applies rather than
# letting a consumer assume the stronger one.
_ED25519 = "ed25519-signature-verified"
_HASH_CHAIN = "runtime-hash-chain-verified"

# --------------------------------------------------------------------------- #
# The actor identity on a decision record is published with HOW it was established.
#
# The runtime persists `actor_identity_basis` inside every hash-chained transition,
# because `actor_type` / `actor_id` say only who was NAMED, never who proved it. This
# mirror still published those two names alone, so a consumer saw an identity and had
# no way to tell an operator-signed conductor from a caller that can spell `bro-000`
# — the same defect `_prove_command_actor` and `_prove_actor` closed, one layer
# downstream, at the surface a cockpit actually renders.
#
# So the basis travels, in the WRITER's vocabulary: the four values below are imported
# from `bro_orchestration_runtime`, never re-spelled here, so no second name for the
# same fact can drift into existence. This module mints no basis of its own — a record
# whose payload carries none is published with `actor_identity_basis: null`, which is
# exactly what the record says: nothing.
#
# `actor_identity_established` is the derived reading, and it is THREE-valued on
# purpose:
#
#   "proven"    a signature this engine verified established the identity — the
#               operator-root-signed conductor-session artifact, and nothing else.
#   "unproven"  the runtime recorded a basis and it is not a verified signature.
#               `actor_identity_basis` says which: its own bookkeeping, a claim lease
#               it minted, or a bare caller claim. None of the three is a signature,
#               and none may borrow the word "proven".
#   "unknown"   the record does not establish a basis — it predates the field, or
#               carries a value this build cannot read. NOT "unproven": "we never
#               recorded it" is a third fact, and demoting it to either pole tells a
#               reader something the record never said.
#
# Fail-closed both ways: an unrecognised basis is never "proven", and an absent one is
# never quietly ranked as though it had been judged and found wanting. It is a string
# rather than a nullable boolean for the same reason — `if (record.actor_proven)`
# reads null as false, which is precisely the collapse this field exists to prevent.
# --------------------------------------------------------------------------- #
ACTOR_IDENTITY_PROVEN = "proven"
ACTOR_IDENTITY_UNPROVEN = "unproven"
ACTOR_IDENTITY_UNKNOWN = "unknown"

#: The writer's basis vocabulary, imported rather than restated. A basis outside these
#: two sets is not a weaker basis — it is one this build cannot read, and it reads as
#: unknown. `engine/tests/test_governance_read.py` holds these sets against every basis
#: constant the runtime declares, so a fifth one cannot appear unclassified.
_BASIS_PROVEN = frozenset({RUNTIME_ACTOR_PROVEN})
_BASIS_UNPROVEN = frozenset({ACTOR_RUNTIME_ORIGINATED, ACTOR_ASSIGNEE_LEASE,
                             ACTOR_UNPROVEN})

# --------------------------------------------------------------------------- #
# O-4: the control-room command actor is PROVEN, never claimed.
#
# `requested_by_type` / `requested_by` are two strings out of the caller's own
# JSON. Comparing them against the literals "owner-gev" and "bro-000" tests
# nothing except that the caller can spell them, and the reply then echoed the
# claimed identity back inside `"valid": true` — laundering a self-assertion into
# something a downstream reader takes as verified.
#
# So the claim must now be discharged by a signature. The conductor already has
# exactly the credential this needs: the operator-root-signed `conductor-session`
# artifact (M-4 / O-3), which binds a role and an agent id to a key no agent
# process holds. A command claiming `bro` / `bro-000` must present one.
#
# The owner has no equivalent, and this task does not invent one: there is no
# owner-authority artifact type in `bro_signature.ARTIFACT_AUTHORITY`, no
# signature field in `schemas/control-room-command.schema.json`, and no trusted
# key that could sign either. An owner-issued command is therefore REFUSED by
# name rather than validated on its say-so. What would close it is written out in
# OWNER_ACTOR_UNPROVABLE, and all three of those files are outside this change.
#
# Known and deliberate limit: a `conductor-session` artifact proves the caller
# holds an operator-issued session credential; it is not bound to this individual
# command, so within its validity window it authorises any command the caller can
# already reach. That is a session credential's semantics, and it is a strictly
# smaller claim than "anyone who can spell bro-000". Per-command non-repudiation
# needs the signed `control-room-command` artifact type described below.
# --------------------------------------------------------------------------- #
CONTROL_ROOM_ACTORS = {("owner", "owner-gev"), (CONDUCTOR_ROLE, CANONICAL_CONDUCTOR_ID)}

#: The artifact an OWNER-issued command must present: a `control-room-command` bound to this
#: exact command, signed by a key under the dedicated `control-room` authority. Registered in
#: `bro_signature.ARTIFACT_AUTHORITY` against `control-room` — NOT against `operator-root`.
#: Issuing commands is routine; signing the trusted-key registry is not, and a deployment that
#: had to keep the registry-signing root online in order to issue a command was holding a key
#: that can admit any authority it likes. The delegated key signs commands and nothing else.
CONTROL_ROOM_COMMAND_ARTIFACT = "control-room-command"

#: The command fields an owner attestation must reproduce. Chosen as the smallest set that makes a
#: replay useless: WHICH command (`command_id`), on WHAT (`task_id`), and doing WHICH THING
#: (`command`). Binding `command_id` alone would let a signed id be reused against another task if
#: an id ever collided; binding the verb as well means a signed `cancel` cannot become a `retry`.
COMMAND_BOUND_FIELDS = ("command_id", "task_id", "command")

#: How an actor identity was established, published on the governance mirror. `ACTOR_PROVEN_BY_SESSION`
#: is a window; this one is a single command and is therefore the stronger of the two.
ACTOR_PROVEN_PER_COMMAND = "owner-signed-control-room-command"

#: The credential a conductor-issued command must present. Reusing the artifact the
#: operator already signs for M-4/O-3 is deliberate: one owner-minted credential, one
#: authority binding, and no new artifact type invented by the code that consumes it.
CONTROL_ROOM_ACTOR_ARTIFACT = CONDUCTOR_SESSION_ARTIFACT

#: How a proven actor identity is described in the reply. There is deliberately no
#: value here meaning "the caller said so".
ACTOR_PROVEN_BY_SESSION = "operator-signed-conductor-session"

ACTOR_ATTESTATION_MISSING = (
    "control-room command actor identity is self-asserted: the command carries no "
    "proof and this API will not stamp `valid: true` on an identity it cannot "
    "verify. Present the signed artifact document as the `actor_attestation` "
    "argument — for the conductor, the operator-root-signed `conductor-session` "
    "artifact described in engine/runtime/bro_policy.py "
    "(CONDUCTOR_SESSION_PROVISIONING)")

#: Kept for the one case that is still unprovable: an owner command presented with NO attestation.
#: The three changes it used to list are done — `control-room-command` is registered in
#: `bro_signature.ARTIFACT_AUTHORITY`, this module consumes it, and the schema carries the
#: signature fields. What remains is not a code gap: the Owner must mint the artifact offline and
#: pin its key. Saying so precisely is the difference between "we have not built it" and "you have
#: not signed it", and only one of those is actionable by whoever reads the refusal.
OWNER_ACTOR_UNPROVABLE = (
    "an owner-issued control-room command must present a `control-room-command` artifact signed "
    "under the `control-room` authority and bound to this exact command (command_id, task_id, "
    "command). The engine can verify one: the artifact type is registered, this module consumes "
    "it, and the schema carries `artifact_type`/`key_id`/`signature`. What is missing is the "
    "artifact itself — mint it with `broctl sign --artifact control-room-command` using a "
    "`control-room` key and list that key `active` in config/trusted-keys.json. Until then the "
    "owner's identity is a claim, and a claim is refused")


class ControlRoomAPIError(ValueError):
    pass


def _governance_request(request: Any) -> tuple[str, str | None]:
    """Parse a governance-read request, fail-closed.

    Field-set equality (not a subset check) is deliberate: an unknown field is a
    request this build does not understand, and quietly ignoring it is how a reader
    ends up answering a question that was not asked.
    """
    if not isinstance(request, dict):
        raise ControlRoomAPIError("governance read request must be a JSON object")
    if set(request) != _GOVERNANCE_REQUEST_FIELDS:
        raise ControlRoomAPIError(
            "governance read request fields do not match "
            f"{GOVERNANCE_PROTOCOL} (expected {sorted(_GOVERNANCE_REQUEST_FIELDS)})")
    if request["protocol"] != GOVERNANCE_PROTOCOL:
        raise ControlRoomAPIError(f"unsupported governance protocol: {request['protocol']!r}")
    if request["op"] != GOVERNANCE_OP:
        raise ControlRoomAPIError(f"unsupported governance op: {request['op']!r}")
    # `is not True` on purpose: 1, "true" and [] are not an assertion of read-only intent.
    if request["read_only"] is not True:
        raise ControlRoomAPIError(
            "a governance read is served only for an explicit read_only:true request")
    surface = request["surface"]
    if surface not in GOVERNANCE_SURFACES:
        raise ControlRoomAPIError(f"unknown governance surface: {surface!r}")
    task_id = request["task_id"]
    if task_id is not None and (not isinstance(task_id, str) or not ID_RE.fullmatch(task_id)):
        raise ControlRoomAPIError("task_id must be null or a canonical id")
    return surface, task_id


def _governance_refusal(surface: str | None, task_id: str | None,
                        now: int, error: str) -> dict[str, Any]:
    """A refusal.

    Note what is absent: there is no `records` key. A consumer cannot accidentally
    read this as a successful read that happened to find nothing, because the field
    it would have to read is not there at all.
    """
    return {
        "protocol": GOVERNANCE_PROTOCOL,
        "schema": 1,
        "ok": False,
        "surface": surface,
        "task_id": task_id,
        "read_at_epoch": now,
        "error": error,
    }


def _evidence_wire(payload: dict[str, Any]) -> dict[str, Any]:
    """Project a signed runtime evidence event onto `evidence-event.schema.json`.

    The two shapes genuinely differ and neither is wrong: the runtime payload carries
    `artifact_type` and `sequence` (it is a signed artifact in a chain), the published
    schema carries `schema` and forbids extras (it is a wire record). `sequence` is not
    dropped information — it is the order of this list, which the read preserves.
    """
    return {
        "schema": 1,
        "event_id": payload["event_id"],
        "previous_event_hash": payload["previous_event_hash"],
        "task_id": payload["task_id"],
        "event_type": payload["event_type"],
        "agent_id": payload["agent_id"],
        "payload_hash": payload["payload_hash"],
        "issued_at_epoch": payload["issued_at_epoch"],
        "key_id": payload["key_id"],
    }


def _actor_identity(payload: dict[str, Any]) -> tuple[str | None, str]:
    """Read a transition's persisted actor basis, and how it should be read.

    Returns `(basis, established)`: the value the runtime actually wrote (or None
    when it wrote none), and the three-valued reading of it. It never raises and
    never guesses — an absent, non-string or unrecognised basis is `unknown`, which
    is a different answer from `unproven` and must stay one.
    """
    basis = payload.get("actor_identity_basis")
    if not isinstance(basis, str) or not basis.strip():
        return None, ACTOR_IDENTITY_UNKNOWN
    if basis in _BASIS_PROVEN:
        return basis, ACTOR_IDENTITY_PROVEN
    if basis in _BASIS_UNPROVEN:
        return basis, ACTOR_IDENTITY_UNPROVEN
    return basis, ACTOR_IDENTITY_UNKNOWN


def _sha(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _strings(value: Any, field: str, required: bool = False) -> list[str]:
    if not isinstance(value, list) or (required and not value):
        raise ControlRoomAPIError(f"{field} must be a list")
    if not all(isinstance(x, str) and x.strip() for x in value):
        raise ControlRoomAPIError(f"{field} must contain non-empty strings")
    out = [x.strip() for x in value]
    if len(out) != len(set(out)):
        raise ControlRoomAPIError(f"{field} contains duplicates")
    return out


class ControlRoomAPIV1:
    """Read-only, integrity-bound views over Orchestration Runtime V1."""

    def __init__(self, runtime: DurableOrchestrationRuntime):
        if not isinstance(runtime, DurableOrchestrationRuntime):
            raise ControlRoomAPIError("runtime must be DurableOrchestrationRuntime")
        self.runtime = runtime
        self.root = runtime.root
        self.registry = runtime.registry

    @staticmethod
    def _now(value: int) -> int:
        if not isinstance(value, int) or value < 0:
            raise ControlRoomAPIError("time must be a non-negative integer")
        return value

    def _ids(self) -> list[str]:
        try:
            return sorted(p.name for p in self.runtime.tasks_dir.iterdir() if p.is_dir())
        except OSError as exc:
            raise ControlRoomAPIError(f"runtime task directory unreadable: {exc}") from exc

    def _call(self, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except (OrchestrationRuntimeError, OrchestrationError, OSError) as exc:
            raise ControlRoomAPIError(str(exc)) from exc

    def _contract(self, task_id: str) -> dict[str, Any]:
        return self._call(self.runtime._contract, task_id)

    def _records(self, task_id: str) -> list[dict[str, Any]]:
        records = self._call(self.runtime._records, task_id)
        if not records:
            raise ControlRoomAPIError("task has no runtime records")
        return records

    def _snapshot(self, task_id: str, now: int) -> dict[str, Any]:
        return self._call(self.runtime.task_snapshot, task_id, now)

    def _integrity(self) -> dict[str, Any]:
        report = self._call(self.runtime.integrity_report)
        if not re.fullmatch(r"[0-9a-f]{64}", str(report.get("root_sha256", ""))):
            raise ControlRoomAPIError("runtime integrity root invalid")
        return report

    def _snapshots(self, now: int) -> dict[str, dict[str, Any]]:
        return {task_id: self._snapshot(task_id, now) for task_id in self._ids()}

    def _meta(self, view: str, now: int, integrity: dict, tasks: list[str], stale: list[str]) -> dict:
        return {
            "schema": 1,
            "view": view,
            "generated_at_epoch": now,
            "source": {
                "runtime_state_dir": str(self.runtime.state_dir),
                "orchestration_sst": "orchestration/registry.json",
            },
            "freshness": {
                "max_age_seconds": self.registry["checkpoint_policy"]["max_age_seconds"],
                "stale": bool(stale),
                "stale_task_ids": sorted(stale),
            },
            "integrity": integrity,
            "source_integrity_sha256": integrity["root_sha256"],
            "drill_down": {"available": bool(tasks), "task_ids": sorted(tasks)},
        }

    @staticmethod
    def _evidence(records: list[dict]) -> list[str]:
        refs: set[str] = set()
        for record in records:
            value = record.get("payload", {}).get("evidence_refs")
            if isinstance(value, list):
                refs.update(x for x in value if isinstance(x, str) and x)
        return sorted(refs)

    def mission_overview(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        projection = self._call(self.runtime.control_room_snapshot, now_epoch=now)
        snapshots = self._snapshots(now)
        ids = sorted(snapshots)
        stale = [x for x, s in snapshots.items() if s["stale"]]
        queues = Counter(s["queue_class"] for s in snapshots.values())
        agents = Counter(self._contract(x)["agent_id"] for x in ids)
        out = self._meta("mission-overview", now, integrity, ids, stale)
        out.update({
            "health": projection["health"],
            "task_count": len(ids),
            "state_counts": projection["state_counts"],
            "queue_counts": {x: queues.get(x, 0) for x in self.runtime.queue},
            "agent_workload_counts": dict(sorted(agents.items())),
            "approval_count": sum(s["state"] in {"awaiting-approval", "waiting-approval"} for s in snapshots.values()),
            "recovery_count": sum(s["state"] in {"recovery-required", "quarantined"} for s in snapshots.values()),
            "tasks": projection["tasks"],
        })
        return out

    def queue_state(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        tasks = []
        for task_id, snap in self._snapshots(now).items():
            queue = snap["queue_class"]
            policy = next(x for x in self.registry["queue_classes"] if x["id"] == queue)
            tasks.append({
                "task_id": task_id,
                "state": snap["state"],
                "queue_class": queue,
                "priority": policy["priority"],
                "preemptible": policy["preemptible"],
                "agent_id": self._contract(task_id)["agent_id"],
                "stale": snap["stale"],
            })
        tasks.sort(key=lambda x: (-x["priority"], x["task_id"]))
        out = self._meta("queue-state", now, integrity, [x["task_id"] for x in tasks], [x["task_id"] for x in tasks if x["stale"]])
        out.update({"queue_classes": list(self.registry["queue_classes"]), "tasks": tasks})
        return out

    def agent_workload(self, *, now_epoch: int, agent_id: str | None = None) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        try:
            identities = all_agent_identities(self.root)
        except IdentityError as exc:
            raise ControlRoomAPIError(str(exc)) from exc
        if agent_id is not None and agent_id not in identities:
            raise ControlRoomAPIError("agent identity is not canonical")
        snapshots = self._snapshots(now)
        selected = [agent_id] if agent_id else sorted({self._contract(x)["agent_id"] for x in snapshots})
        agents, tasks, stale = [], [], []
        for identity in selected:
            pack, role = identities[identity]
            assigned = []
            for task_id, snap in snapshots.items():
                if self._contract(task_id)["agent_id"] == identity:
                    item = {"task_id": task_id, "state": snap["state"], "queue_class": snap["queue_class"], "stale": snap["stale"]}
                    assigned.append(item)
                    tasks.append(task_id)
                    if snap["stale"]:
                        stale.append(task_id)
            assigned.sort(key=lambda x: x["task_id"])
            agents.append({
                "agent_id": identity,
                "pack_id": pack,
                "role": role,
                "task_count": len(assigned),
                "state_counts": dict(sorted(Counter(x["state"] for x in assigned).items())),
                "tasks": assigned,
            })
        out = self._meta("agent-workload", now, integrity, tasks, stale)
        out["agents"] = agents
        return out

    def checkpoint_status(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        checkpoints = [
            {"record_id": r["record_id"], "observed_at_epoch": r["observed_at_epoch"], **r["payload"]}
            for r in self._records(task_id) if r["kind"] == "checkpoint"
        ]
        out = self._meta("checkpoint-status", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({"task_id": task_id, "state": snap["state"], "last_checkpoint": checkpoints[-1] if checkpoints else None, "checkpoints": checkpoints})
        return out

    def budget_status(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        limits = self._call(self.runtime._config, task_id)["budget_limits"]
        dimensions = []
        for name in self.registry["budget_policy"]["supported_dimensions"]:
            used = snap["usage"].get(name, 0)
            limit = limits.get(name, {"soft": None, "hard": None})
            if limit["hard"] is not None and used > limit["hard"]:
                status = "hard-exceeded"
            elif limit["soft"] is not None and used > limit["soft"]:
                status = "soft-exceeded"
            elif limit["soft"] is None and limit["hard"] is None:
                status = "unbounded"
            else:
                status = "within-limit"
            dimensions.append({"dimension": name, "used": used, "soft": limit["soft"], "hard": limit["hard"], "status": status})
        out = self._meta("budget-status", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({"task_id": task_id, "state": snap["state"], "dimensions": dimensions})
        return out

    def approval_inbox(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        approvals, stale = [], []
        for task_id, snap in self._snapshots(now).items():
            if snap["state"] not in {"awaiting-approval", "waiting-approval"}:
                continue
            latest = [r for r in self._records(task_id) if r["kind"] == "transition"][-1]
            approvals.append({
                "task_id": task_id,
                "state": snap["state"],
                "risk": self._contract(task_id)["risk"],
                "requested_at_epoch": latest["observed_at_epoch"],
                "expires_at_epoch": None,
                "expiry_status": "not-modeled-by-runtime-v1",
                "evidence_refs": list(latest["payload"].get("evidence_refs", [])),
                "allowed_commands": [x["id"] for x in self.registry["commands"] if snap["state"] in x["allowed_states"] and "owner" in x["actors"]],
            })
            if snap["stale"]:
                stale.append(task_id)
        approvals.sort(key=lambda x: (x["requested_at_epoch"], x["task_id"]))
        out = self._meta("approval-inbox", now, integrity, [x["task_id"] for x in approvals], stale)
        out["approvals"] = approvals
        return out

    def recovery_quarantine(self, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        items, stale = [], []
        for task_id, snap in self._snapshots(now).items():
            if snap["state"] not in {"recovery-required", "quarantined"}:
                continue
            latest = [r for r in self._records(task_id) if r["kind"] == "transition"][-1]
            items.append({
                "task_id": task_id,
                "state": snap["state"],
                "original_state": latest["payload"].get("previous_state"),
                "observed_effect": None,
                "observed_effect_status": "not-modeled-by-runtime-v1",
                "proof_refs": list(latest["payload"].get("evidence_refs", [])),
                "ambiguity": snap["state"] == "quarantined",
                "allowed_actions": [x["id"] for x in self.registry["commands"] if snap["state"] in x["allowed_states"]],
            })
            if snap["stale"]:
                stale.append(task_id)
        items.sort(key=lambda x: x["task_id"])
        out = self._meta("recovery-quarantine", now, integrity, [x["task_id"] for x in items], stale)
        out["items"] = items
        return out

    def audit_timeline(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        records = self._records(task_id)
        out = self._meta("audit-timeline", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({"task_id": task_id, "record_count": len(records), "timeline_sha256": _sha({"task_id": task_id, "records": records}), "records": records})
        return out

    def task_detail(self, task_id: str, *, now_epoch: int) -> dict[str, Any]:
        now = self._now(now_epoch)
        integrity = self._integrity()
        snap = self._snapshot(task_id, now)
        contract = self._contract(task_id)
        records = self._records(task_id)
        config = self._call(self.runtime._config, task_id)
        transitions = [r for r in records if r["kind"] == "transition"]
        routing = [r for r in records if r["kind"] in {"claim-lease", "claim-released", "claim-expired"} or (r["kind"] == "transition" and r["payload"].get("next_state") in {"routing", "running"})]
        timeline = _sha({"task_id": task_id, "records": records})
        out = self._meta("task-detail", now, integrity, [task_id], [task_id] if snap["stale"] else [])
        out.update({
            "task_id": task_id,
            "contract": contract,
            "snapshot": snap,
            "queue": {"class": config["queue_class"], "policy": next(x for x in self.registry["queue_classes"] if x["id"] == config["queue_class"])},
            "routing": routing,
            "checkpoints": [r for r in records if r["kind"] == "checkpoint"],
            "budget": {"limits": config["budget_limits"], "usage": snap["usage"]},
            "approvals": [r for r in transitions if r["payload"].get("next_state") in {"awaiting-approval", "waiting-approval"}],
            "recovery": [r for r in transitions if r["payload"].get("next_state") in {"recovery-required", "quarantined"}],
            "evidence_refs": self._evidence(records),
            "audit": {"record_count": len(records), "timeline_sha256": timeline, "record_head_sha256": snap["record_head_sha256"]},
        })
        return out

    # --- governance mirror (brops.governance-read.v1) --------------------------------

    def governance_read(self, request: Any, *, now_epoch: int | None = None) -> dict[str, Any]:
        """Serve one `brops.governance-read.v1` request from the engine's own stores.

        Returns the reply document rather than raising, because the caller is a
        request/reply transport that must always emit a reply. An exception there
        surfaces as "the engine is unreachable", which would report a transport
        failure for what is actually the engine refusing, with a reason worth reading.

        `now_epoch` exists for tests and for a caller that already fixed a clock for a
        batch of reads. It only bounds staleness and ordering; it is deliberately NOT
        forwarded to signature verification, which always uses the runtime's own clock
        so that no caller can rewind time to revive an expired signing key.
        """
        now = int(time.time()) if now_epoch is None else self._now(now_epoch)
        try:
            surface, task_id = _governance_request(request)
        except ControlRoomAPIError as exc:
            return _governance_refusal(None, None, now, str(exc))
        try:
            records, source, empty_reason, authentication = self._governance_surface(
                surface, task_id, now)
        except (ControlRoomAPIError, OrchestrationRuntimeError, OrchestrationError,
                EvidenceError, IdentityError, OSError) as exc:
            return _governance_refusal(surface, task_id, now, str(exc))
        reply = {
            "protocol": GOVERNANCE_PROTOCOL,
            "schema": 1,
            "ok": True,
            "surface": surface,
            "task_id": task_id,
            "read_at_epoch": now,
            "records": records,
            "record_count": len(records),
            # An empty mirror is an answer, not a failure — and not the same answer as
            # a refusal, which never reaches here (it carries no `records` at all).
            "empty": not records,
            "empty_reason": None if records else empty_reason,
            "record_authentication": authentication,
            "source": source,
        }
        if task_id is not None:
            # Lets a consumer tell "this task has recorded nothing" from "the engine
            # has never heard of this id", instead of guessing from an empty list.
            reply["known_task"] = task_id in set(self._ids())
        return reply

    def _governance_surface(self, surface: str, task_id: str | None,
                            now: int) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
        if surface == "decisionLedger":
            return self._governance_decision_ledger(task_id)
        if surface == "evidenceChain":
            return self._governance_evidence_chain(task_id)
        if surface == "verdicts":
            return self._governance_verdicts(task_id)
        return self._governance_approval_queue(task_id, now)

    def _runtime_source(self, kind: str) -> dict[str, Any]:
        return {
            "kind": kind,
            "runtime_state_dir": str(self.runtime.state_dir),
            "source_integrity_sha256": self._integrity()["root_sha256"],
        }

    def _governance_tasks(self, task_id: str | None) -> tuple[list[str], list[str]]:
        known = self._ids()
        return known, ([x for x in known if x == task_id] if task_id is not None else known)

    @staticmethod
    def _governance_empty_reason(known: list[str], task_id: str | None,
                                 targets: list[str], otherwise: str) -> str:
        if not known:
            return "the orchestration runtime holds no tasks, so nothing has been recorded"
        if task_id is not None and not targets:
            return f"the orchestration runtime has no task {task_id!r}"
        return otherwise

    def _governance_decision_ledger(
            self, task_id: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
        """The engine's own governance decisions: its hash-chained state transitions.

        Every transition names who decided, from which state to which state, why, and
        on what evidence, and each is bound into the per-task record chain that
        `_records` re-derives on every read. That is the engine's decision history —
        there is no second, tidier ledger it is holding back.

        It also names how that decider was ESTABLISHED. `actor_type`/`actor_id` are
        the runtime's record of who acted; `actor_identity_basis` /
        `actor_identity_established` are its record of what discharged that identity,
        so a mirror consumer can tell a verified signature from a caller's claim
        instead of reading both as the same fact. See the vocabulary block above.
        """
        known, targets = self._governance_tasks(task_id)
        records: list[dict[str, Any]] = []
        for identifier in targets:
            for record in self._call(self.runtime._records, identifier):
                if record["kind"] != "transition":
                    continue
                payload = record["payload"]
                basis, established = _actor_identity(payload)
                records.append({
                    "id": record["record_id"],
                    "task_id": identifier,
                    "sequence": record["sequence"],
                    "decided_at_epoch": record["observed_at_epoch"],
                    "previous_state": payload.get("previous_state"),
                    "next_state": payload.get("next_state"),
                    "actor_type": payload.get("actor_type"),
                    "actor_id": payload.get("actor_id"),
                    # Not who was named — how that name was established. Without these
                    # two a consumer cannot tell a verified signature from a caller's
                    # claim, and a mirror that cannot tell them apart reads every
                    # identity as the stronger one.
                    "actor_identity_basis": basis,
                    "actor_identity_established": established,
                    "reason_code": payload.get("reason_code"),
                    "evidence_refs": list(payload.get("evidence_refs") or []),
                    "record_sha256": record["record_sha256"],
                    "previous_record_sha256": record["previous_record_sha256"],
                })
        records.sort(key=lambda item: (item["decided_at_epoch"], item["task_id"], item["sequence"]))
        reason = self._governance_empty_reason(
            known, task_id, targets, "no state transition has been recorded yet")
        return (records, self._runtime_source("orchestration-runtime-transitions"),
                reason, _HASH_CHAIN)

    def _governance_evidence_chain(
            self, task_id: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
        """The signed evidence chain, head-anchored, from the runtime's evidence store.

        Both refusals below are refusals on purpose. A runtime with no evidence store
        is blind, and a runtime with no trusted keys cannot tell a signed event from a
        file someone dropped into the directory. Reporting either as an empty chain
        would be the most misleading thing this module could do.
        """
        store, keys = self.runtime.evidence_store, self.runtime.evidence_keys
        if store is None:
            raise ControlRoomAPIError(
                "this runtime is not bound to an evidence store, so the engine cannot "
                "read the evidence chain at all; that is a refusal, not an empty chain")
        if keys is None:
            raise ControlRoomAPIError(
                "this runtime holds no trusted evidence keys, so evidence signatures "
                "cannot be verified; refusing to mirror unverifiable evidence")
        known = set(self._ids())
        if task_id is not None:
            targets = [task_id]
        else:
            # The union, not just the runtime's tasks: a chain in the store for a task
            # the runtime no longer lists is exactly the history a viewer must still see.
            targets = sorted(known | set(list_chain_task_ids(store)))
        # One pass over the store for all of them; a page that asks for every chain
        # should not cost a directory scan per task. now=None: signature validity is
        # judged against the runtime's own clock, never a caller-supplied one.
        chains = read_chains(store, targets, keys, now=None)
        records = [_evidence_wire(payload)
                   for identifier in targets for payload in chains[identifier]]
        source = {
            "kind": "signed-evidence-store",
            "evidence_store": str(store),
            "chain_task_ids": targets,
        }
        if task_id is not None and task_id not in known:
            reason = (f"the engine holds no evidence chain for {task_id!r}, and the "
                      "orchestration runtime has no such task")
        elif task_id is not None:
            reason = f"no evidence event has been recorded for {task_id!r} yet"
        else:
            reason = "no evidence event has been recorded in this store yet"
        return records, source, reason, _ED25519

    def _governance_verdicts(
            self, task_id: str | None) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
        """Independent verifier receipts, re-verified from the persisted documents.

        A completion that required independent verification persists the WHOLE signed
        receipt inside its hash-chained transition, precisely so that a later read does
        not depend on the evidence store still existing. This re-verifies each one
        rather than trusting the record that carries it.

        One unverifiable receipt fails the whole surface. That is the rule the evidence
        chain already uses, for the same reason: a silently shorter list of verdicts
        reads as "fewer verdicts", not as "one of these I could not check".
        """
        known, targets = self._governance_tasks(task_id)
        documents: list[tuple[str, Any]] = []
        for identifier in targets:
            for record in self._call(self.runtime._records, identifier):
                proof = record["payload"].get("completion_proof")
                if not isinstance(proof, dict) or proof.get("verifier_receipt_document") is None:
                    continue
                documents.append((identifier, proof["verifier_receipt_document"]))
        records: list[dict[str, Any]] = []
        if documents:
            keys = self.runtime.evidence_keys
            if keys is None:
                raise ControlRoomAPIError(
                    f"the runtime holds {len(documents)} verifier receipt(s) but was "
                    "constructed without trusted keys; refusing to mirror a verdict "
                    "whose signature cannot be re-verified")
            for identifier, document in documents:
                try:
                    records.append(dict(verify_artifact(document, "verifier-receipt", keys)))
                except SignatureError as exc:
                    raise ControlRoomAPIError(
                        f"the verifier receipt persisted for {identifier} is RED: {exc}") from exc
            records.sort(key=lambda item: (item["issued_at_epoch"], item["receipt_id"]))
        reason = self._governance_empty_reason(
            known, task_id, targets,
            "no task has completed under independent verification, so the engine has "
            "issued no verdict")
        return (records, self._runtime_source("persisted-verifier-receipts"),
                reason, _ED25519)

    def _governance_approval_queue(
            self, task_id: str | None,
            now: int) -> tuple[list[dict[str, Any]], dict[str, Any], str, str]:
        """Tasks the runtime is holding for an owner decision.

        Derived state, not a store: a pending approval IS a task whose latest
        transition parked it in an approval state. This mirrors that queue only — it
        carries no approve/deny authority, and `allowed_commands` names what an owner
        *could* command, never what anything here has done.
        """
        known, targets = self._governance_tasks(task_id)
        approvals = [dict(item, id=item["task_id"])
                     for item in self.approval_inbox(now_epoch=now)["approvals"]
                     if task_id is None or item["task_id"] == task_id]
        reason = self._governance_empty_reason(
            known, task_id, targets, "no task is waiting on an owner approval")
        return (approvals, self._runtime_source("orchestration-runtime-approval-queue"),
                reason, _HASH_CHAIN)

    def _prove_command_actor(self, actor: tuple[str, str],
                             attestation: Any,
                             command: dict[str, Any] | None = None) -> dict[str, Any]:
        """Discharge the actor claim with a signature, or refuse.

        Returns the proof to be recorded in the reply. There is no return path
        for an unproven actor: every failure raises, so `valid: true` cannot be
        reached on an identity nobody verified.

        The credential is judged against the wall clock, NOT the caller-supplied
        `now_epoch` every other view here takes. Every other check in this module
        answers "was this command valid at time T", which is the caller's question
        to ask; whether a signing key and a session credential are live right now
        is not, and a caller that could backdate the clock could revive an expired
        identity.
        """
        moment = int(time.time())
        if actor not in CONTROL_ROOM_ACTORS:
            raise ControlRoomAPIError("command actor identity is not canonical")
        if attestation is None:
            raise ControlRoomAPIError(f"{ACTOR_ATTESTATION_MISSING}; actor claimed: "
                                      f"{actor[0]}/{actor[1]}")
        keys = self.runtime.evidence_keys
        if keys is None:
            raise ControlRoomAPIError(
                "this runtime holds no trusted keys, so it cannot tell a signed actor "
                "attestation from a forged one; refusing to validate a command rather "
                "than accepting the identity claim unverified")
        # The two actors are proven by DIFFERENT artifacts, and the difference is the point.
        #
        # A `conductor-session` says "the holder is the conductor until T". Within that window it
        # authorises any command the caller could already reach — that is what a session credential
        # means, and it is a strictly smaller claim than "anyone who can spell bro-000".
        #
        # The OWNER gets no session. `owner-gev` is the identity that can cancel, recover and
        # retry, so a credential that authorises "any command for the next hour" is the wrong
        # shape for it. The owner presents a `control-room-command` artifact bound to THIS command
        # — per-command non-repudiation. A stolen one replays exactly one command that was already
        # signed, rather than a window.
        artifact_type = (CONTROL_ROOM_ACTOR_ARTIFACT if actor[0] == CONDUCTOR_ROLE
                         else CONTROL_ROOM_COMMAND_ARTIFACT)
        try:
            payload = verify_artifact(attestation, artifact_type, keys, now=moment)
        except (SignatureError, AttributeError, TypeError) as exc:
            raise ControlRoomAPIError(
                f"control-room actor attestation is RED: {exc}") from exc
        for field, claimed in (("role", actor[0]), ("agent_id", actor[1])):
            if payload.get(field) != claimed:
                raise ControlRoomAPIError(
                    f"actor attestation does not speak for this actor: it binds "
                    f"{field}={payload.get(field)!r}, the command claims {claimed!r}")
        if artifact_type == CONTROL_ROOM_COMMAND_ARTIFACT:
            # Bind the attestation to the command in hand. Without this the owner's artifact would
            # be a session credential wearing a different name: sign one cancellation, replay it
            # against any task. `command` is required here rather than optional-with-a-default,
            # because a caller that forgot to pass it would silently get the weaker check.
            if command is None:
                raise ControlRoomAPIError(
                    "an owner command must be proven against the command itself; no command was "
                    "supplied to bind the attestation to")
            for field in COMMAND_BOUND_FIELDS:
                if payload.get(field) != command.get(field):
                    raise ControlRoomAPIError(
                        f"owner attestation is for a different command: it binds "
                        f"{field}={payload.get(field)!r}, this command carries "
                        f"{command.get(field)!r}")
        expires = payload.get("expires_at_epoch")
        if isinstance(expires, bool) or not isinstance(expires, int) or expires <= moment:
            raise ControlRoomAPIError(
                "actor attestation is expired or carries no integer expires_at_epoch")
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            raise ControlRoomAPIError("actor attestation carries no session_id")
        return {
            "identity_basis": (ACTOR_PROVEN_BY_SESSION if artifact_type == CONTROL_ROOM_ACTOR_ARTIFACT
                               else ACTOR_PROVEN_PER_COMMAND),
            "key_id": payload["key_id"],
            "session_id": session_id,
            "expires_at_epoch": expires,
            "attestation_sha256": _sha(attestation),
        }

    def validate_command_intent(self, command: dict[str, Any], *, now_epoch: int,
                                actor_attestation: dict[str, Any] | None = None) -> dict[str, Any]:
        now = self._now(now_epoch)
        required = {"schema", "command_id", "task_id", "command", "requested_by_type", "requested_by", "requested_at_epoch", "expires_at_epoch", "expected_task_state", "scope", "reason", "evidence_refs"}
        if not isinstance(command, dict) or set(command) != required:
            raise ControlRoomAPIError("command fields do not match canonical schema")
        if command["schema"] != 1:
            raise ControlRoomAPIError("command schema must be 1")
        for field in ("command_id", "task_id"):
            if not isinstance(command[field], str) or not ID_RE.fullmatch(command[field]):
                raise ControlRoomAPIError(f"{field} format invalid")
        for field in ("command", "requested_by_type", "requested_by", "expected_task_state", "reason"):
            if not isinstance(command[field], str) or not command[field].strip():
                raise ControlRoomAPIError(f"{field} must be a non-empty string")
        scope = _strings(command["scope"], "scope", True)
        evidence = _strings(command["evidence_refs"], "evidence_refs")
        if any({x for x in re.split(r"[^a-z0-9]+", item.lower()) if x} & FORBIDDEN_SCOPE for item in scope):
            raise ControlRoomAPIError("command scope crosses a forbidden mutation boundary")
        actor = (command["requested_by_type"], command["requested_by"])
        proof = self._prove_command_actor(actor, actor_attestation, command)
        if command["scope"] != scope or command["evidence_refs"] != evidence:
            raise ControlRoomAPIError("command list values must already be normalized")
        snap = self._snapshot(command["task_id"], now)
        before = self._integrity()
        try:
            validate_control_room_command(command, snap["state"], now, self.root)
        except OrchestrationError as exc:
            raise ControlRoomAPIError(str(exc)) from exc
        if before != self._integrity():
            raise ControlRoomAPIError("command validation mutated runtime state")
        return {
            "schema": 1,
            "command_id": command["command_id"],
            "task_id": command["task_id"],
            "command": command["command"],
            "requested_by_type": actor[0],
            "requested_by": actor[1],
            # Not the claim: what verified it. A reader that trusted the two
            # fields above was trusting the caller; these four say which key,
            # which session and which document discharged the claim.
            "actor_identity": proof["identity_basis"],
            "actor_key_id": proof["key_id"],
            "actor_session_id": proof["session_id"],
            "actor_attestation_sha256": proof["attestation_sha256"],
            "current_state": snap["state"],
            "validated_at_epoch": now,
            "valid": True,
            "executed": False,
            "mutation_authorized": False,
            "source_integrity_sha256": before["root_sha256"],
        }
