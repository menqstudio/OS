from __future__ import annotations

import json
import os
import pathlib
import re
import shlex
import subprocess
import time
from typing import Any

from bro_authority import AuthorityError, validate_verifier_assignment
from bro_contracts import (
    ContractError,
    canonical_json_sha256,
    load_contract_bundle_from_env,
    load_mode_grant_from_env,
)
from bro_evidence import EvidenceError, load_head, validate_chain, validate_criterion_evidence
from bro_recovery import RecoveryError, _load_state
from bro_repository_state import resolve_state
from bro_signature import SignatureError, load_trusted_keys

ROOT = pathlib.Path(__file__).resolve().parents[1]
LEVELS = ["L1", "L2", "L3", "L4", "L5"]


class CompletionError(ValueError):
    pass


def _json(path: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompletionError(f"{path} must contain an object")
    return value


def _signed_env(path_env: str, artifact_type: str, root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    # Ed25519, not HMAC: completion manifests and verifier receipts are presented
    # to the Stop gate from the builder's process, so a symmetric key would let a
    # builder mint its own GREEN completion or verifier receipt. verify_artifact
    # checks them against the operator-signed trusted-key registry, so a
    # completion is signed by the builder authority and a receipt by the verifier
    # authority — neither of which a policed builder process holds.
    from bro_signature import SignatureError, load_trusted_keys, verify_artifact
    raw = os.getenv(path_env)
    if not raw:
        raise CompletionError(f"missing {path_env}")
    try:
        return verify_artifact(_json(pathlib.Path(raw)), artifact_type, load_trusted_keys(root), now=now)
    except SignatureError as exc:
        raise CompletionError(str(exc)) from exc


_RECEIPT_ID = re.compile(r"rcpt-[0-9a-f]{16}")

# L-13: completion-manifest nonce discipline. Same alphabet and length bounds as
# the grant nonces (bro_security / mode grants), and the schema's own pattern.
_MANIFEST_NONCE = re.compile(r"[A-Za-z0-9._-]{16,128}")

# Tolerated clock skew for artifacts issued at a slightly-ahead runner clock.
_CLOCK_SKEW = 60

# L-5: a completion manifest carries issued_at_epoch but no expiry, so without a
# freshness window a stale GREEN manifest replays forever — roll the repository
# back to the old candidate and the old completion authorizes a stop again. The
# window mirrors the verifier-receipt clock discipline (future-issue rejection via
# _CLOCK_SKEW) and bounds the replay surface to one hour, matching the default
# mode-grant/lease TTL used across the harness.
_MANIFEST_MAX_AGE = 3600


def _resolved_keys(keys: dict | None, root: pathlib.Path) -> dict:
    from bro_signature import load_trusted_keys
    return keys if keys is not None else load_trusted_keys(root)


def _require_signer_identity(keys: dict, payload: dict[str, Any], expected_agent_id: str,
                             label: str) -> None:
    """The trusted key that signed `payload` must be cryptographically bound
    (subject_agent_id) to the identity the payload claims.

    Otherwise any holder of a builder- or verifier-authority key could sign as any
    agent by simply writing that agent's id into the artifact, and builder != verifier
    would be a string comparison one key could satisfy on both sides. Binding the
    claimed identity to the signing key closes that."""
    key = keys.get(payload.get("key_id")) if isinstance(keys, dict) else None
    subject = getattr(key, "subject_agent_id", None) if key is not None else None
    if not subject:
        raise CompletionError(f"{label} signing key is not bound to an agent identity")
    if subject != expected_agent_id:
        raise CompletionError(
            f"{label} is signed by a key bound to {subject!r}, not the claimed {expected_agent_id!r}")


def _required_commands(task: dict[str, Any]) -> list[list[str]]:
    """The commands that MUST have a passing receipt, taken ONLY from the signed
    task contract's verification.commands. There is no fallback to the test catalog:
    tests/catalog.json is a plain committed file, not a protected/signed source, and
    a generic discovery command the builder can satisfy trivially (a `true` that
    exits 0) would reopen the very bypass this closes. An empty command set is a hard
    failure — a completion cannot be checked against nothing."""
    declared = (task.get("verification") or {}).get("commands") or []
    commands = [shlex.split(c) for c in declared if isinstance(c, str) and c.strip()]
    if not commands:
        raise CompletionError(
            "the signed task contract declares no verification.commands; a completion "
            "cannot be verified against a required command set")
    return commands


def _validate_execution_receipts(task: dict[str, Any], tests: list[dict[str, Any]], candidate_head: str,
                                 candidate_tree: str, root: pathlib.Path, now: int | None,
                                 *, keys: dict | None = None, store: pathlib.Path | None = None) -> list[str]:
    """Make "the tests passed" a checked execution receipt, not a builder's claim.

    Each completion-manifest test cites an execution receipt id. The receipt is an
    EVIDENCE-signed artifact produced by the runner (bro_run_receipt), not the
    builder, and it binds the exact command (argv), the candidate HEAD/tree and the
    registered test catalog. Beyond verifying each receipt, the set of commands that
    actually passed must cover the trusted required-command set (contract/catalog),
    so a green `true` — which the builder controls in both the manifest and the
    signed receipt — cannot stand in for the suite. The cited id must match the
    receipt's own signed receipt_id (a copy under another filename is rejected) and
    is unique by signed id, so one execution cannot back two claims. Returns the
    ordered list of verified receipt ids so the completion proof can persist them."""
    from bro_receipt import ReceiptError, verify_receipt
    trusted = _resolved_keys(keys, root)
    receipt_store = store if store is not None else _external_dir("BRO_EXECUTION_RECEIPTS")
    required = _required_commands(task)
    seen_ids: list[str] = []
    passed: list[list[str]] = []
    for test in tests:
        cited = test.get("execution_receipt_id")
        if not isinstance(cited, str) or not _RECEIPT_ID.fullmatch(cited):
            raise CompletionError("completion test cites a malformed execution receipt id")
        path = receipt_store / f"{cited}.json"
        try:
            payload = verify_receipt(_json(path), trusted, task_id=task["task_id"],
                                     candidate_head=candidate_head, candidate_tree=candidate_tree,
                                     root=root, now=now)
        except ReceiptError as exc:
            raise CompletionError(f"execution receipt {cited} RED: {exc}") from exc
        # The receipt's own signed id must be the id cited (and the filename it was
        # loaded from): a signed receipt copied under a second filename is rejected.
        if payload["receipt_id"] != cited:
            raise CompletionError(
                f"execution receipt id mismatch: signed {payload['receipt_id']!r}, cited {cited!r}")
        if payload["receipt_id"] in seen_ids:
            raise CompletionError(f"execution receipt cited more than once: {payload['receipt_id']}")
        seen_ids.append(payload["receipt_id"])
        if payload["exit_code"] != 0:
            raise CompletionError(f"execution receipt {cited} records a non-zero exit code")
        if payload["command"] != test.get("command"):
            raise CompletionError(
                f"execution receipt {cited} ran a different command than the test claims")
        passed.append(payload["command"])
    for command in required:
        if command not in passed:
            raise CompletionError(f"no passing execution receipt for required command: {command}")
    return seen_ids


def _external_dir(env_name: str) -> pathlib.Path:
    raw = os.getenv(env_name)
    if not raw:
        raise CompletionError(f"missing external {env_name}")
    path = pathlib.Path(raw).expanduser()
    if not path.is_absolute():
        raise CompletionError(f"{env_name} must be absolute")
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(ROOT.resolve())
    except ValueError:
        return resolved
    raise CompletionError(f"{env_name} must be outside the repository")


def validate_evidence_chain(task_id: str, event_ids: list[str],
                            root: pathlib.Path = ROOT, *, keys: dict | None = None,
                            store: pathlib.Path | None = None,
                            min_head_sequence: int | None = None) -> str:
    """Prove the submitted events are the whole chain, not a flattering prefix.

    The previous implementation checked backward linkage over a caller-supplied
    list. That catches dropping events from the front, because the first must
    have no predecessor, and says nothing about the back. A builder holding
    genuine signed events for work-started, tests-passed, tests-failed and
    rolled-back submitted the first two, and every check passed: the failure and
    the rollback that hid it were simply never mentioned. No forgery, just
    selective disclosure.

    It also verified with HMAC, which made the flaw unfixable in place. The
    verifying key is the signing key and the hook runs in the builder's own
    process, so any anchor the builder had to present it could also mint.
    Delegating to the Ed25519 path is what makes the head an authority.

    L-4 (binding half): ``min_head_sequence`` is the caller's high-water mark
    for the signed head's monotonic ``head_sequence``. A genuinely signed but
    OLDER head — the retained anchor of a self-consistent truncated chain — is
    rejected as stale.
    """
    resolved_keys = keys if keys is not None else load_trusted_keys(root)
    resolved_store = store if store is not None else _external_dir("BRO_EVIDENCE_STORE")
    try:
        if min_head_sequence is None:
            # TODO(L-4): no run-recorded high-water mark exists yet and the
            # completion-manifest schema carries no head sequence, so the floor
            # is anchored on the store's own current head. That never leaves the
            # parameter unset and rejects a head swapped for an older one during
            # this validation, but it cannot see a rollback that happened before
            # the call — once a durable high-water source (run state or a
            # manifest-bound head sequence) lands, thread it through here.
            min_head_sequence = load_head(resolved_store, task_id, resolved_keys).head_sequence
        return validate_chain(task_id, event_ids, resolved_keys,
                              store=resolved_store,
                              min_head_sequence=min_head_sequence)
    except (EvidenceError, SignatureError) as exc:
        raise CompletionError(str(exc)) from exc


def _no_pending_execution() -> None:
    ledger = _external_dir("BRO_EXECUTION_LEASE_LEDGER")
    if any(ledger.glob("*.active")) or any(ledger.glob("*.ambiguous")):
        raise CompletionError("pending or ambiguous execution lease exists")


def _no_pending_recovery(task_id: str) -> None:
    try:
        state = _load_state(task_id)
    except RecoveryError as exc:
        raise CompletionError(str(exc)) from exc
    if state and state.get("phase") != "MUTATION_RECORDED":
        raise CompletionError(f"unresolved recovery state blocks completion: {state.get('phase')}")


def _clean_repository(root: pathlib.Path) -> None:
    try:
        dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True, encoding="utf-8").strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise CompletionError("cannot inspect repository cleanliness") from exc
    if dirty:
        raise CompletionError("repository is dirty")


def _check_manifest(task: dict[str, Any], agent_id: str, manifest: dict[str, Any], *,
                    root: pathlib.Path, now: int | None, keys: dict | None,
                    evidence_store: pathlib.Path | None, receipt_store: pathlib.Path | None,
                    require_live: bool,
                    min_head_sequence: int | None = None) -> tuple[dict[str, Any], str, list[str]]:
    """Artifact-only validation of a completion manifest, shared by the Stop gate
    (env + live repository) and the durable runtime (in-process keys/store). When
    ``require_live`` the manifest candidate must equal the current repository state;
    otherwise it is bound internally (the durable runtime holds no checkout)."""
    required = {"schema", "task_id", "agent_id", "task_contract_sha256", "candidate_head", "candidate_tree", "done_criteria", "tests", "evidence_event_ids", "open_risks", "rollback_ready", "nonce", "issued_at_epoch", "expires_at_epoch"}
    if set(manifest) - {"artifact_type", "key_id"} != required or manifest.get("schema") != 1:
        raise CompletionError("invalid completion manifest shape")
    task_hash = canonical_json_sha256(task)
    for key, value in {"task_id": task["task_id"], "agent_id": agent_id, "task_contract_sha256": task_hash}.items():
        if manifest.get(key) != value:
            raise CompletionError(f"completion manifest binding mismatch: {key}")
    trusted = _resolved_keys(keys, root)
    # The manifest's builder identity must be the identity its signing key is bound
    # to, not merely a string it wrote.
    _require_signer_identity(trusted, manifest, manifest["agent_id"], "completion manifest")
    # L-13: the manifest carries a single-use nonce (replay discrimination) and
    # an explicit builder-declared expiry. The nonce must match the schema's own
    # pattern; the expiry mirrors the verifier-receipt window discipline
    # (integer timestamps, non-empty validity window, hard rejection once past)
    # and can only TIGHTEN the L-5 freshness bound below, never extend it.
    nonce = manifest.get("nonce")
    if not isinstance(nonce, str) or not _MANIFEST_NONCE.fullmatch(nonce):
        raise CompletionError("completion manifest nonce is malformed")
    # L-5: mirror the verifier-receipt clock check — a manifest issued in the
    # future is rejected, and a manifest older than the freshness window is
    # stale and cannot authorize a completion, even against a matching candidate.
    issued = manifest.get("issued_at_epoch")
    if not isinstance(issued, int):
        raise CompletionError("completion manifest issued_at_epoch must be an integer")
    expires = manifest.get("expires_at_epoch")
    if not isinstance(expires, int):
        raise CompletionError("completion manifest expires_at_epoch must be an integer")
    moment = int(time.time()) if now is None else now
    if issued >= expires:
        raise CompletionError("completion manifest has an empty validity window")
    if issued > moment + _CLOCK_SKEW:
        raise CompletionError("completion manifest is issued in the future")
    if moment - issued > _MANIFEST_MAX_AGE:
        raise CompletionError(
            f"completion manifest is stale (issued {moment - issued}s ago; "
            f"freshness window is {_MANIFEST_MAX_AGE}s)")
    if expires <= moment:
        raise CompletionError("completion manifest expired")
    if require_live:
        state = resolve_state(root)
        if manifest["candidate_head"] != state.head_sha or manifest["candidate_tree"] != state.tree_identity:
            raise CompletionError("completion candidate does not match current repository state")
    criteria = manifest.get("done_criteria")
    if not isinstance(criteria, list) or [x.get("criterion") for x in criteria if isinstance(x, dict)] != task["done_criteria"]:
        raise CompletionError("completion done criteria do not exactly match task")
    if any(not isinstance(x, dict) or x.get("status") != "satisfied" or not x.get("evidence_event_ids") for x in criteria):
        raise CompletionError("completion criterion lacks satisfied evidence")
    tests = manifest.get("tests")
    if not isinstance(tests, list) or not tests or any(
            not isinstance(x, dict) or x.get("status") != "passed"
            or not isinstance(x.get("command"), list) or not x.get("command")
            or any(not isinstance(arg, str) for arg in x.get("command"))
            # evidence_event_id is dereferenced below (test["evidence_event_id"]); require
            # it here so a manifest omitting it fails closed as a CompletionError rather
            # than escaping the gate with an unhandled KeyError.
            or not isinstance(x.get("evidence_event_id"), str) or not x.get("evidence_event_id")
            for x in tests):
        raise CompletionError("completion tests are not all passed")
    if manifest.get("open_risks") or manifest.get("rollback_ready") is not True:
        raise CompletionError("completion has open risks or rollback is not ready")
    chain_ids = manifest["evidence_event_ids"]
    # L-4 (binding half): the caller's recorded high-water mark rides along so a
    # genuinely signed but OLDER evidence head cannot anchor this completion.
    validate_evidence_chain(task["task_id"], chain_ids, root, keys=trusted, store=evidence_store,
                            min_head_sequence=min_head_sequence)
    # The criteria above only had to cite *some* evidence id. Nothing tied those
    # ids to the chain that was just proven, so a criterion could rest on a real,
    # signed event belonging to a different chain entirely.
    try:
        for criterion in criteria:
            validate_criterion_evidence(task["task_id"], criterion["evidence_event_ids"], chain_ids)
        for test in tests:
            validate_criterion_evidence(task["task_id"], [test["evidence_event_id"]], chain_ids)
    except EvidenceError as exc:
        raise CompletionError(str(exc)) from exc
    # Execution receipts feed the verdict: each test's "passed" must rest on a
    # runner-signed receipt against this exact candidate, not the builder's word.
    receipt_ids = _validate_execution_receipts(task, tests, manifest["candidate_head"],
                                               manifest["candidate_tree"], root, now,
                                               keys=trusted, store=receipt_store)
    return manifest, task_hash, receipt_ids


def validate_completion(task: dict[str, Any], agent_id: str, root: pathlib.Path = ROOT) -> tuple[dict[str, Any], str]:
    manifest = _signed_env("BRO_COMPLETION_MANIFEST", "completion-manifest", root)
    manifest, task_hash, _receipt_ids = _check_manifest(task, agent_id, manifest, root=root, now=None,
                                                        keys=None, evidence_store=None, receipt_store=None,
                                                        require_live=True)
    _clean_repository(root)
    _no_pending_execution()
    _no_pending_recovery(task["task_id"])
    return manifest, task_hash


def _check_verifier_receipt(task: dict[str, Any], manifest: dict[str, Any], task_hash: str,
                            receipt: dict[str, Any], *, root: pathlib.Path, now: int | None,
                            keys: dict | None, evidence_store: pathlib.Path | None,
                            min_head_sequence: int | None = None) -> dict[str, Any]:
    """Artifact-only validation of an independent verifier receipt, shared by the
    Stop gate and the durable runtime: bound to the manifest and candidate, GREEN and
    unexpired, builder != verifier, independence meeting the risk floor."""
    required = {"schema", "receipt_id", "task_id", "builder_agent_id", "verifier_agent_id", "verifier_role", "independence_level", "task_contract_sha256", "completion_manifest_sha256", "candidate_head", "candidate_tree", "evidence_event_ids", "verdict", "issued_at_epoch", "expires_at_epoch"}
    if set(receipt) - {"artifact_type", "key_id"} != required or receipt.get("schema") != 1 or receipt.get("verdict") != "GREEN":
        raise CompletionError("invalid verifier receipt shape or verdict")
    verification = task["verification"]
    expected = {"task_id": task["task_id"], "builder_agent_id": task["agent_id"], "verifier_agent_id": verification["verifier_agent_id"], "verifier_role": verification["verifier_role"], "task_contract_sha256": task_hash, "completion_manifest_sha256": canonical_json_sha256(manifest), "candidate_head": manifest["candidate_head"], "candidate_tree": manifest["candidate_tree"]}
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise CompletionError(f"verifier receipt binding mismatch: {key}")
    # The verifier identity must be the one its signing key is bound to; otherwise
    # any verifier-authority key could sign claiming to be the designated verifier.
    trusted = _resolved_keys(keys, root)
    _require_signer_identity(trusted, receipt, receipt["verifier_agent_id"], "verifier receipt")
    # Runtime-owned clock (moment is int(time.time()) unless a trusted caller pins
    # it): reject a future-issued receipt, an empty validity window, expiry, and one
    # that predates the manifest it verifies. The durable runtime passes now=None so
    # a caller cannot rewind the clock to revive an expired or future receipt.
    issued, expires = receipt["issued_at_epoch"], receipt["expires_at_epoch"]
    if not isinstance(issued, int) or not isinstance(expires, int):
        raise CompletionError("verifier receipt timestamps must be integers")
    moment = int(time.time()) if now is None else now
    if issued >= expires:
        raise CompletionError("verifier receipt has an empty validity window")
    if issued > moment + _CLOCK_SKEW:
        raise CompletionError("verifier receipt is issued in the future")
    if expires <= moment:
        raise CompletionError("verifier receipt expired")
    manifest_issued = manifest.get("issued_at_epoch")
    if isinstance(manifest_issued, int) and issued < manifest_issued:
        raise CompletionError("verifier receipt predates the completion manifest")
    try:
        validate_verifier_assignment(builder_agent_id=task["agent_id"], verifier_agent_id=receipt["verifier_agent_id"], verifier_role=receipt["verifier_role"], risk=task["risk"], root=root)
    except AuthorityError as exc:
        raise CompletionError(str(exc)) from exc
    policy = _json(root / "agents" / "authority-policy.json")
    minimum = policy["independence_minimum_by_risk"][task["risk"]]
    level = receipt["independence_level"]
    if level not in LEVELS or LEVELS.index(level) < LEVELS.index(minimum):
        raise CompletionError("verifier independence level is insufficient")
    validate_evidence_chain(task["task_id"], receipt["evidence_event_ids"], root,
                            keys=trusted, store=evidence_store,
                            min_head_sequence=min_head_sequence)
    return receipt


def validate_verifier_receipt(task: dict[str, Any], manifest: dict[str, Any], task_hash: str, root: pathlib.Path = ROOT) -> dict[str, Any]:
    receipt = _signed_env("BRO_VERIFIER_RECEIPT", "verifier-receipt", root)
    return _check_verifier_receipt(task, manifest, task_hash, receipt, root=root, now=None,
                                   keys=None, evidence_store=None)


def _verify_doc(document: Any, artifact_type: str, keys: dict, now: int | None) -> dict[str, Any]:
    from bro_signature import SignatureError, verify_artifact
    if not isinstance(document, dict):
        raise CompletionError(f"{artifact_type} document is required")
    try:
        return verify_artifact(document, artifact_type, keys, now=now)
    except SignatureError as exc:
        raise CompletionError(str(exc)) from exc


def authorize_completion_docs(task: dict[str, Any], agent_id: str, *, manifest_doc: Any,
                              receipt_doc: Any, keys: dict, evidence_store: pathlib.Path,
                              root: pathlib.Path = ROOT, now: int | None = None,
                              min_head_sequence: int | None = None) -> tuple[dict[str, Any], str]:
    """In-process completion authorization for the durable runtime — the same
    artifact checks as the Stop gate (builder-signed manifest, execution receipts
    feeding the verdict, and, when verification is required, an independent verifier
    receipt with builder != verifier), keyed off supplied trusted keys and evidence
    store rather than the builder's environment and without the live-repository
    checks. Execution receipts are looked up in the same evidence store."""
    manifest = _verify_doc(manifest_doc, "completion-manifest", keys, now)
    manifest, task_hash, receipt_ids = _check_manifest(
        task, agent_id, manifest, root=root, now=now, keys=keys, evidence_store=evidence_store,
        receipt_store=evidence_store, require_live=False, min_head_sequence=min_head_sequence)
    # The proof carries the WHOLE verified signed documents, not only their hashes:
    # a hash proves a document only to someone who still has the document, and the
    # evidence store is deletable. With the documents persisted in the hash-chained
    # transition, a later audit can re-verify the signatures, key ids, verdict,
    # identity and timestamps from the record alone.
    proof = {
        "task_contract_sha256": task_hash,
        "completion_manifest_sha256": canonical_json_sha256(manifest),
        "completion_manifest_document": manifest_doc,
        "candidate_head": manifest["candidate_head"],
        "candidate_tree": manifest["candidate_tree"],
        "evidence_event_ids": list(manifest["evidence_event_ids"]),
        "execution_receipt_ids": receipt_ids,
    }
    if (task.get("verification") or {}).get("required") is True:
        receipt = _verify_doc(receipt_doc, "verifier-receipt", keys, now)
        _check_verifier_receipt(task, manifest, task_hash, receipt, root=root, now=now,
                                keys=keys, evidence_store=evidence_store,
                                min_head_sequence=min_head_sequence)
        proof.update({
            "verifier_agent_id": receipt["verifier_agent_id"],
            "verifier_receipt_id": receipt["receipt_id"],
            "verifier_receipt_sha256": canonical_json_sha256(receipt),
            "verifier_receipt_document": receipt_doc,
        })
    return manifest, task_hash, proof


def _authenticated_task(agent_id: str, session_id: str, role: str, mode: str,
                        root: pathlib.Path = ROOT, now: int | None = None) -> dict[str, Any]:
    """Return the task contract only after the FULL signed mode-grant path accepts it.

    At Stop the task contract arrives from the environment and is only structurally
    valid, so a builder could present a contract whose verification.commands are a
    cheap `true`. Signature plus task hash is not enough: a grant for another
    session, agent, repository, branch, HEAD or tree, or an expired one, must not
    authorize this completion. Running the whole load_mode_grant_from_env /
    validate_mode_grant path binds the grant to this session, agent, role, the
    agent-profile and skill-receipt hashes, and the current HEAD and tree, and
    enforces its validity window — so the required-command set rests on signed
    authority. The grant's agent must also be the agent finishing the turn."""
    from bro_policy import enforce_grant_bindings
    try:
        bundle = load_contract_bundle_from_env(root, now)
        grant = load_mode_grant_from_env(bundle, session_id, role, root, now)
    except ContractError as exc:
        raise CompletionError(str(exc)) from exc
    if bundle.task.get("agent_id") != agent_id:
        raise CompletionError(
            "the signed mode grant's task is not assigned to the acting agent")
    # validate_mode_grant does not compare the grant's repository, branch or mode
    # against the task; the same shared check the tool path uses must run here too.
    bound, reason = enforce_grant_bindings(grant, bundle.task, mode)
    if not bound:
        raise CompletionError(reason)
    return bundle.task


def authorize_stop(agent_id: str, root: pathlib.Path = ROOT, *, session_id: str,
                   role: str, mode: str, now: int | None = None) -> tuple[bool, str]:
    try:
        task = _authenticated_task(agent_id, session_id, role, mode, root, now)
        manifest, task_hash = validate_completion(task, agent_id, root)
        if task["verification"]["required"]:
            validate_verifier_receipt(task, manifest, task_hash, root)
        return True, "completion and verification evidence GREEN"
    except CompletionError as exc:
        return False, f"completion gate RED: {exc}"


def authorize_conductor_stop(state, root: pathlib.Path = ROOT) -> tuple[bool, str]:
    """Let the conductor end a turn it did not execute.

    Demanding a builder's completion manifest from the conductor is a category
    error: Bro delegates and never builds, so the artifact can never exist and
    the turn can never end. The gate was not strict, it was unsatisfiable.

    This exemption is narrow by construction. It covers exactly one identity, it
    only applies when no task contract is bound, and it refuses a frozen session.
    Anything Bro claimed to complete lives under a task contract, and a bound
    contract routes back to the full gate, so the exemption cannot be used to
    escape evidence for work actually performed.

    Deliberately not covered: whether delegations this turn resolved. That needs
    the supervisor, which does not exist yet, so the honest position is that this
    exemption asserts nothing about delegated work.

    M-4: the conductor identity is environment-derived (BRO_ROLE/BRO_AGENT_ID),
    so the exemption is additionally (a) bound to a signed conductor session
    token whenever one is presented or policy requires one, and (b) written to
    the append-only audit ledger on EVERY grant — an exemption that cannot be
    tamper-evidently recorded is not granted.
    """
    from bro_policy import is_conductor, verify_conductor_session_token

    if not is_conductor(state):
        return False, ("conductor stop exemption requires the canonical conductor; "
                       f"role={state.role!r} agent={state.agent_id!r}")
    if os.getenv("BRO_TASK_CONTRACT"):
        return False, ("conductor holds a task contract and is therefore an "
                       "executor for this turn; the completion gate applies")
    try:
        from bro_freeze import FreezeError, load_freeze

        if load_freeze(state.session_id) is not None:
            return False, ("session authority is frozen after a protected mutation; "
                           "it must terminate rather than finish")
    except FreezeError as exc:
        return False, f"freeze state gate RED: {exc}"
    token_ok, identity_basis = verify_conductor_session_token(state, root)
    if not token_ok:
        return False, f"conductor stop exemption RED: {identity_basis}"
    # The exemption stop is recorded before it is granted. The ledger lives
    # beside the freeze markers in BRO_SESSION_STATE_DIR (which the freeze gate
    # above already proved is configured) unless BRO_AUDIT_LEDGER points
    # elsewhere; both are outside the repository by construction (audit_append
    # enforces it via repo_root). A failed append fails the stop closed.
    try:
        from bro_audit_log import AuditError, append as audit_append

        ledger = pathlib.Path(
            os.getenv("BRO_AUDIT_LEDGER")
            or pathlib.Path(os.environ["BRO_SESSION_STATE_DIR"]) / "conductor-stop-audit.jsonl")
        audit_append(ledger, "conductor-exemption-stop", {
            "session_id": state.session_id,
            "role": state.role,
            "agent_id": state.agent_id,
            "mode": state.mode,
            "identity_basis": identity_basis,
            "stopped_at_epoch": int(time.time()),
        }, repo_root=root)
    except (KeyError, OSError, AuditError) as exc:
        return False, f"conductor stop audit RED: exemption not recorded, not granted: {exc}"
    return True, ("conductor turn: no task contract bound, so no builder evidence "
                  "is owed; startup receipt is current")
