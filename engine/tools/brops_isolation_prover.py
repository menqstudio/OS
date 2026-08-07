"""Wave 3b-1 — same-login-user isolation PROVER (design §1.1, §5; audit P0-1, P1-4).

Run as the sidecar/desktop LOGIN user (the in-scope attacker). It attempts the four
denials the design requires. It exits 0 ONLY if every attack was **refused by the
containment, attributably**; if any attack SUCCEEDS it exits 1; if any attack could not be
attempted at all it exits 2 and prints INCONCLUSIVE — never "PASSED".

The Linux CI job `signer-isolation` runs this against real, separately-owned signer +
supervisor services (dedicated principals), so the boundary is machine-proven — never
skip-guarded or documentation-only.

Attacks (all must be DENIED):
  1. connect to the SIGNER socket + request a signature  -> denied by SO_PEERCRED
     (the signer admits only the supervisor UID, and hangs up without answering);
  2. read the receipt-signing / supervisor-attestation private keys -> EACCES
     (owner-only 0700 dirs of the service principals);
  3. read or write the protected evidence store          -> EACCES
     (2770, owned by a service group the login user is not in);
  4. make the SUPERVISOR sign caller-supplied evidence    -> refused `malformed`
     (the supervisor's P0-2 shape gate accepts ONLY {run_id, execution_attempt_id}).

WHY THIS FILE LOOKS THE WAY IT DOES — the defect it exists to not have
------------------------------------------------------------------------------------
Until this round every attack scored a bare `except Exception` as "denied = good", and
attack 2 scored `FileNotFoundError` as "not reachable is also denied". A mistyped key
path, a service that never started, a renamed socket, a platform without `AF_UNIX`, or a
typo in this file all rendered as a **successful containment proof**: run the old code
with five nonexistent paths on a box with no services at all and it printed
`ISOLATION PROOF PASSED` and exited 0. A proof that cannot fail for the right reason is
worth less than no proof, because it gets quoted as evidence.

So every attack here answers TWO questions, separately:

  * POSITIVE CONTROL — *is the attack path live?* Evidence that the target exists, is
    foreign, and would have answered or yielded had the containment not been there. An
    attack that cannot reach its target proves nothing about containment, and that is
    exactly the state the old code reported as success. A failed control is INCONCLUSIVE.
  * ATTRIBUTION — *was the refusal the containment doing its job?* The specific errno
    (EACCES, not ENOENT), the specific wire behaviour (accepted the connection, then hung
    up without a byte — which is what `brops_socket._serve_one` does on an ACL deny), the
    specific refusal reason (`malformed` from the shape gate, not `run_binding_invalid`
    from a later stage). Anything else is INCONCLUSIVE, never DENIED.

This is the same shape as `expect_blocked()` in `engine/ci/live/run_live_turn.sh`: a
refusal that does not name its expected cause certifies nothing about the check it names.

Attack 4 additionally fixes a recorded audit finding (R2/P2): it used to send the
SIGNER's protocol name to the SUPERVISOR, so the refusal was decided by a protocol-name
mismatch and the P0-2 *shape* guard — the thing "no evidence oracle" actually means — was
never reached. It now sends a well-formed evidence-request that differs from the honest
control in EXACTLY one way (a caller-supplied `evidence` member) and requires the shape
gate to be the thing that names the refusal.

Env: BROPS_SIGNER_SOCKET, BROPS_SUPERVISOR_SOCKET, BROPS_PROVE_SIGNER_KEY,
     BROPS_PROVE_ATTESTATION_KEY, BROPS_PROVE_STORE_DIR.
     (Read up front, outside every `try`: a missing variable is an operator error that
     must abort, never an attack that "was denied".)
"""

from __future__ import annotations

import dataclasses
import errno
import os
import pathlib
import socket
import stat
import sys
import uuid
from typing import Any, BinaryIO, Callable

_HERE = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_HERE / "runtime"))
sys.path.insert(0, str(_HERE / "tools"))

import brops_protocol

# ----- verdicts -----------------------------------------------------------------------
# DENIED is the ONLY verdict that contributes to a proof. INCONCLUSIVE exists precisely so
# that "I could not attempt this" can never be spelled the same way as "the containment
# refused me".
DENIED = "DENIED"
BREACH = "BREACH"
INCONCLUSIVE = "INCONCLUSIVE"

_PROTOCOL_EVIDENCE_REQUEST = "brops.evidence-request.v1"
_PROTOCOL_SIGN_REQUEST = "brops.sign-request.v1"

# The supervisor's refusal reasons. `malformed` is the P0-2 shape gate — the wall attack 4
# exists to test. `run_binding_invalid` is a LATER stage (no such run): it is the honest
# control's expected answer, and seeing it for the ATTACK means the shape gate did not
# decide, i.e. the guard is gone or bypassed.
REASON_SHAPE_GATE = "malformed"
REASON_NO_SUCH_RUN = "run_binding_invalid"


class TransportUnavailable(OSError):
    """This host cannot even speak the transport the boundary is built on."""


@dataclasses.dataclass(frozen=True)
class Outcome:
    """One attack's result. `control` is the positive-control evidence — why we believe
    the attack path was live — and is printed even for a DENIED row, because a denial
    whose control is unstated is indistinguishable from an unreachable target."""

    verdict: str
    detail: str
    control: str

    @property
    def denied(self) -> bool:
        return self.verdict == DENIED


def _errno_name(exc: BaseException | None) -> str:
    if exc is None:
        return "no error"
    number = getattr(exc, "errno", None)
    if number is None:
        return type(exc).__name__
    return f"{type(exc).__name__}/{errno.errorcode.get(number, number)}"


# ----- the AF_UNIX exchange primitive ---------------------------------------------------
# `brops_socket.request` cannot be used for the attacks: it collapses "the socket does not
# exist", "nobody is listening", "the peer hung up on me" and "the peer answered" into one
# raised/returned pair, and it is exactly that collapse the old prover scored as denial.
# We need connect-vs-reply separated, plus a byte count, to attribute the refusal.


class _CountingReader:
    """Wraps a binary reader and counts the bytes actually delivered, so an EOF at byte 0
    (the ACL deny) is distinguishable from a truncated/garbled reply (inconclusive)."""

    def __init__(self, inner: BinaryIO) -> None:
        self._inner = inner
        self.count = 0

    def read(self, size: int = -1) -> bytes:
        chunk = self._inner.read(size)
        self.count += len(chunk)
        return chunk


@dataclasses.dataclass(frozen=True)
class Exchange:
    """The observable facts of one socket attempt, kept separate on purpose.

    `connected` is the positive control for both socket attacks: a completed connect()
    means the socket is bound, the service is listening, and the path from the attacker
    to it is open — so whatever happens next is the service's choice, not the plumbing's.
    """

    connected: bool
    reply: dict[str, Any] | None  # a decoded frame ⇒ the peer chose to talk to us
    reply_bytes: int
    error: BaseException | None


def unix_exchange(socket_path: str, frame: dict[str, Any], timeout: float = 5.0) -> Exchange:
    """Connect, send one frame, read one frame — reporting each step's outcome distinctly."""
    if not hasattr(socket, "AF_UNIX"):
        # Not a denial. The transport the boundary is built on does not exist here, so the
        # attack was never attempted. (The old code scored this as DENIED, which is how a
        # host with no AF_UNIX at all could "prove" a Linux SO_PEERCRED boundary.)
        return Exchange(False, None, 0, TransportUnavailable("AF_UNIX unavailable on this host"))
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.settimeout(timeout)
    counter: _CountingReader | None = None
    try:
        try:
            conn.connect(socket_path)
        except OSError as exc:
            return Exchange(False, None, 0, exc)
        try:
            conn.sendall(brops_protocol.encode_frame(frame))
            counter = _CountingReader(conn.makefile("rb"))
            return Exchange(True, brops_protocol.read_frame(counter), counter.count, None)
        except BaseException as exc:  # noqa: BLE001 — classified by the caller, not swallowed
            return Exchange(True, None, counter.count if counter else 0, exc)
    finally:
        conn.close()


def _hung_up_without_answering(ex: Exchange) -> bool:
    """True iff the peer accepted the connection and then closed it without sending a
    single byte — the exact wire signature of `brops_socket._serve_one`'s ACL deny."""
    if not ex.connected or ex.reply is not None or ex.reply_bytes != 0:
        return False
    exc = ex.error
    if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
        return True
    # `read_frame` on a cleanly-closed connection: EOF before the 4-byte length prefix.
    return isinstance(exc, brops_protocol.ProtocolError) and "unexpected EOF" in str(exc)


def _unreachable(label: str, ex: Exchange) -> Outcome:
    """A connect() that never completed. Spelled out by errno, because the whole point is
    that "not there" and "refused me" must not share a verdict."""
    exc = ex.error
    if isinstance(exc, TransportUnavailable):
        why = f"this host has no AF_UNIX, so the {label} boundary under test cannot exist here"
    elif getattr(exc, "errno", None) == errno.ENOENT:
        why = (
            f"the {label} socket path is not there — mistyped, renamed, or never "
            "provisioned. A path that does not exist denies nothing."
        )
    elif getattr(exc, "errno", None) == errno.ECONNREFUSED:
        why = (
            f"nothing is listening on the {label} socket — the service is down. A service "
            "that is not running denies nothing."
        )
    else:
        why = f"connect() to the {label} failed"
    return Outcome(
        INCONCLUSIVE,
        f"could not attempt: {why} ({_errno_name(exc)}: {exc})",
        "none — the attack never reached its target",
    )


# ----- attack 1: connect to the isolated signer -----------------------------------------


def attack_connect_signer(
    socket_path: str, *, exchange: Callable[..., Exchange] = unix_exchange
) -> Outcome:
    """The login user must not be able to make the SIGNER talk to it at all.

    Note the bar: **any** reply is a BREACH, not merely a `signed` one. The boundary under
    test is SO_PEERCRED — "only the supervisor connects to the signer". If the signer
    answered us, its UID allow-list admitted the attacker and the boundary is gone; that
    the answer happened to be `refused` only means our fabricated frame failed the
    signer's *input* validation, which is a different wall and not the one named here.
    Scoring `status != "signed"` as denial (the old bar) stayed green with
    `allowed_peer_uids` deleted entirely, because a garbage frame is refused either way.
    """
    frame = {
        "protocol": _PROTOCOL_SIGN_REQUEST,
        "attestation": {"attestation_protocol": "brops.run-attestation.v1",
                        "supervisor_key_id": "x", "sig": "AAAA"},
        "evidence": {"run_id": "x"},
    }
    ex = exchange(socket_path, frame)
    if not ex.connected:
        return _unreachable("signer", ex)
    live = (
        f"connect() to {socket_path} succeeded — the signer is bound, listening, and "
        "reachable from the attacking uid, so what follows is the signer's choice"
    )
    if ex.reply is not None:
        return Outcome(
            BREACH,
            f"the signer ANSWERED the login user (status={ex.reply.get('status')!r}); "
            "SO_PEERCRED admitted a peer that is not the supervisor",
            live,
        )
    if _hung_up_without_answering(ex):
        return Outcome(
            DENIED,
            "accepted the connection, then closed it without a byte "
            f"({_errno_name(ex.error)}) — the SO_PEERCRED allow-list refused the peer UID",
            live,
        )
    return Outcome(
        INCONCLUSIVE,
        f"connected, but the outcome is not a recognizable ACL deny: {_errno_name(ex.error)}: "
        f"{ex.error} (bytes received: {ex.reply_bytes})",
        live,
    )


# ----- the custody positive control -----------------------------------------------------


def _control_foreign_dir(directory: str, label: str) -> tuple[Outcome | None, str]:
    """POSITIVE CONTROL for the custody attacks: the containing directory exists, is a
    directory, and belongs to somebody else with group/other locked out — i.e. there is a
    real, foreign secret store there to steal from. Without this, "I could not read it" is
    equally consistent with "there was nothing to read", and the old code could not tell
    those apart at all."""
    try:
        info = os.stat(directory)
    except OSError as exc:
        return (
            Outcome(
                INCONCLUSIVE,
                f"could not attempt: the {label} directory {directory} is not there "
                f"({_errno_name(exc)}). A mistyped or unprovisioned path is not a denial.",
                "none — the target does not exist",
            ),
            "none",
        )
    if not stat.S_ISDIR(info.st_mode):
        return (
            Outcome(INCONCLUSIVE, f"could not attempt: {directory} is not a directory",
                    "none — the target is not a directory"),
            "none",
        )
    perms = stat.S_IMODE(info.st_mode)
    if os.name != "posix":  # pragma: no cover — main() gates the platform before we get here
        return None, f"{label} {directory} exists (ownership unverifiable off POSIX)"
    if info.st_uid == os.getuid():
        # Not "inconclusive": a secret store owned by the attacking uid IS the custody
        # failure, whatever the file mode happens to say this second.
        return (
            Outcome(
                BREACH,
                f"the {label} directory {directory} is OWNED by the attacking uid "
                f"{os.getuid()} — custody is the attacker's to change",
                f"{label} exists at {directory}",
            ),
            "none",
        )
    return (
        None,
        f"{label} {directory} exists, is owned by uid {info.st_uid} (not our "
        f"{os.getuid()}), mode {perms:04o} — a real, foreign store to steal from",
    )


# ----- attack 2: read a service principal's private key ---------------------------------


def attack_read_file(
    path: str,
    *,
    opener: Callable[..., Any] = open,
    control_fn: Callable[[str, str], tuple["Outcome | None", str]] = _control_foreign_dir,
) -> Outcome:
    """The login user must not be able to read a service principal's private key.

    `FileNotFoundError` is INCONCLUSIVE, not denial. That single line is the defect this
    round exists to remove: it made a renamed key, a typo'd env var, or a provisioning
    step that silently did nothing all read as proof of custody.
    """
    control, control_text = control_fn(str(pathlib.Path(path).parent), "key store")
    if control is not None:
        return control
    try:
        with opener(path, "rb") as handle:
            handle.read(1)
    except PermissionError as exc:
        return Outcome(
            DENIED,
            f"open() refused with {_errno_name(exc)} — the key is inside the service "
            "principal's owner-only directory",
            control_text,
        )
    except FileNotFoundError as exc:
        return Outcome(
            INCONCLUSIVE,
            f"could not attempt: {_errno_name(exc)} for {path}. The containing directory "
            "denies us, yet this path resolved to 'absent' rather than 'forbidden' — so "
            "the path is wrong or the key was never provisioned. Not reachable is NOT "
            "denied.",
            control_text,
        )
    except OSError as exc:
        return Outcome(
            INCONCLUSIVE, f"could not attempt: unexpected {_errno_name(exc)}: {exc}", control_text
        )
    return Outcome(BREACH, f"the login user READ {path}", control_text)


# ----- attack 3: read/write the protected evidence store --------------------------------


def _probe_write(probe: pathlib.Path) -> tuple[str, str]:
    try:
        probe.write_bytes(b"x")
    except PermissionError as exc:
        return DENIED, f"refused with {_errno_name(exc)}"
    except FileNotFoundError as exc:
        return INCONCLUSIVE, f"could not attempt ({_errno_name(exc)}) — the store path is wrong"
    except OSError as exc:
        return INCONCLUSIVE, f"unexpected {_errno_name(exc)}: {exc}"
    try:
        probe.unlink()
    except OSError:  # pragma: no cover — the write already proved the breach
        pass
    return BREACH, f"WROTE {probe.name} into the protected store"


def _probe_list(store_dir: str) -> tuple[str, str]:
    try:
        entries = os.listdir(store_dir)
    except PermissionError as exc:
        return DENIED, f"refused with {_errno_name(exc)}"
    except FileNotFoundError as exc:
        return INCONCLUSIVE, f"could not attempt ({_errno_name(exc)}) — the store path is wrong"
    except OSError as exc:
        return INCONCLUSIVE, f"unexpected {_errno_name(exc)}: {exc}"
    return BREACH, f"LISTED the protected store ({len(entries)} entries)"


def attack_store(
    store_dir: str,
    *,
    writer: Callable[[pathlib.Path], tuple[str, str]] = _probe_write,
    lister: Callable[[str], tuple[str, str]] = _probe_list,
    control_fn: Callable[[str, str], tuple["Outcome | None", str]] = _control_foreign_dir,
) -> Outcome:
    """The login user must be able neither to WRITE nor to LIST the protected store.

    The old version caught `(PermissionError, FileNotFoundError, OSError)` for both halves
    and returned `not wrote and not listed`, so a store directory that simply did not
    exist scored as a perfect denial on both counts.
    """
    control, control_text = control_fn(store_dir, "evidence store")
    if control is not None:
        return control
    write_verdict, write_detail = writer(
        pathlib.Path(store_dir) / f"attacker-probe-{uuid.uuid4().hex}"
    )
    list_verdict, list_detail = lister(store_dir)
    detail = f"write: {write_detail}; list: {list_detail}"
    for verdict in (BREACH, INCONCLUSIVE):  # worst verdict wins; a breach is never masked
        if verdict in (write_verdict, list_verdict):
            return Outcome(verdict, detail, control_text)
    return Outcome(DENIED, detail, control_text)


# ----- attack 4: make the supervisor sign caller-supplied evidence ----------------------


def attack_supervisor_oracle(
    socket_path: str, *, exchange: Callable[..., Exchange] = unix_exchange
) -> Outcome:
    """The supervisor must refuse a frame that carries caller-supplied evidence — and must
    refuse it AT THE SHAPE GATE (`malformed`), which is what P0-2 actually claims.

    Unlike attack 1, the supervisor legitimately admits this UID (we are the sidecar), so
    here a structured *answer* is the positive control and the refusal reason is the
    attribution. The control frame is the same request with the `evidence` member removed,
    for a run that does not exist: it must come back `run_binding_invalid`, proving our
    frames are parsed and dispatched past the protocol gate and deep into the handler. The
    attack then differs from the control in EXACTLY one way, so `malformed` is
    attributable to the shape gate and nothing else. Delete the shape gate and the attack
    falls through to `run_binding_invalid` — identical to the control — and this check goes
    INCONCLUSIVE instead of quietly passing on "well, it refused".
    """
    run_id = f"brops-prover-absent-{uuid.uuid4().hex}"
    attempt_id = f"brops-prover-attempt-{uuid.uuid4().hex}"
    honest = {
        "protocol": _PROTOCOL_EVIDENCE_REQUEST,
        "run_id": run_id,
        "execution_attempt_id": attempt_id,
    }
    control_ex = exchange(socket_path, honest)
    if not control_ex.connected:
        return _unreachable("supervisor", control_ex)
    if control_ex.reply is None:
        return Outcome(
            INCONCLUSIVE,
            "could not attempt: the supervisor did not answer a well-formed handle "
            f"({_errno_name(control_ex.error)}: {control_ex.error}). A supervisor that "
            "will not talk to us refuses nothing.",
            "none — the honest control frame got no structured answer",
        )
    control_reason = control_ex.reply.get("reason")
    if control_ex.reply.get("status") != "refused" or control_reason != REASON_NO_SUCH_RUN:
        return Outcome(
            INCONCLUSIVE,
            "could not attempt: the honest control frame for a nonexistent run answered "
            f"{control_ex.reply.get('status')!r}/{control_reason!r}, not "
            f"'refused'/{REASON_NO_SUCH_RUN!r} — the deep path is not in the state this "
            "attack's attribution depends on",
            "none — the control did not behave as specified",
        )
    live = (
        "the honest handle {run_id, execution_attempt_id} reached the handler and came "
        f"back refused/{REASON_NO_SUCH_RUN} — the entry point is alive and parses our frames"
    )

    forged = dict(honest)
    forged["evidence"] = {"forged": True, "decision": "completed", "output": "attacker text"}
    ex = exchange(socket_path, forged)
    if ex.reply is None:
        return Outcome(
            INCONCLUSIVE,
            f"no structured answer to the forged frame: {_errno_name(ex.error)}: {ex.error}",
            live,
        )
    status = ex.reply.get("status")
    reason = ex.reply.get("reason")
    if status == "signed":
        return Outcome(BREACH, "the supervisor SIGNED caller-supplied evidence", live)
    if status != "refused":
        return Outcome(INCONCLUSIVE, f"neither signed nor refused: status={status!r}", live)
    if reason != REASON_SHAPE_GATE:
        return Outcome(
            INCONCLUSIVE,
            f"refused, but for the wrong reason ({reason!r}, wanted {REASON_SHAPE_GATE!r}). "
            "It refused the caller-supplied evidence exactly the way it refuses the honest "
            "control, so the P0-2 shape gate is not what decided — a negative that passes "
            "on any refusal certifies nothing about the check it names.",
            live,
        )
    return Outcome(
        DENIED,
        f"refused with reason={REASON_SHAPE_GATE!r} — the P0-2 shape gate rejected the "
        "caller-supplied evidence member, while the identical frame without it reaches the "
        "handler",
        live,
    )


# ----- adjudication ---------------------------------------------------------------------

_REQUIRED_ENV = (
    "BROPS_SIGNER_SOCKET",
    "BROPS_SUPERVISOR_SOCKET",
    "BROPS_PROVE_SIGNER_KEY",
    "BROPS_PROVE_ATTESTATION_KEY",
    "BROPS_PROVE_STORE_DIR",
)


def run_attacks(env: dict[str, str]) -> dict[str, Outcome]:
    return {
        "1_connect_signer": attack_connect_signer(env["BROPS_SIGNER_SOCKET"]),
        "2_read_signer_key": attack_read_file(env["BROPS_PROVE_SIGNER_KEY"]),
        "2_read_attestation_key": attack_read_file(env["BROPS_PROVE_ATTESTATION_KEY"]),
        "3_store_no_read_write": attack_store(env["BROPS_PROVE_STORE_DIR"]),
        "4_supervisor_oracle": attack_supervisor_oracle(env["BROPS_SUPERVISOR_SOCKET"]),
    }


def report(checks: dict[str, Outcome], stream=None, err=None) -> int:
    """Print every row with its attribution and its positive control, then adjudicate.

    Exit codes: 0 = proven, 1 = a breach, 2 = inconclusive. An INCONCLUSIVE row can never
    produce a 0, and the word PASSED is printed on no other path.
    """
    out = sys.stdout if stream is None else stream
    fail = sys.stderr if err is None else err
    for name, outcome in checks.items():
        print(f"[{outcome.verdict:<12}] {name}: {outcome.detail}", file=out)
        print(f"               positive control: {outcome.control}", file=out)
    breached = [n for n, o in checks.items() if o.verdict == BREACH]
    if breached:
        print(
            f"ISOLATION PROOF FAILED — at least one attack succeeded: {', '.join(breached)}",
            file=fail,
        )
        return 1
    unproven = [n for n, o in checks.items() if o.verdict != DENIED]
    if unproven:
        print(
            "ISOLATION PROOF INCONCLUSIVE — these attacks could not be attempted against a "
            f"live target, so nothing was proven about them: {', '.join(unproven)}. "
            "An unattempted attack is not a denial.",
            file=fail,
        )
        return 2
    print(
        "ISOLATION PROOF PASSED — all four denials hold, each attributable to the "
        "containment and each against a target proven live",
        file=out,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    missing = [name for name in _REQUIRED_ENV if not os.environ.get(name)]
    if missing:
        # Outside every attack's try: an unset variable is an operator error. The old code
        # read two of these INSIDE a `try/except Exception: return True`, so forgetting to
        # export them scored as two clean denials.
        print(
            f"ISOLATION PROOF INCONCLUSIVE — required env not set: {', '.join(missing)}",
            file=sys.stderr,
        )
        return 2
    if os.name != "posix":
        # One platform gate, stated once. Every denial this prover can report is a POSIX
        # ownership / SO_PEERCRED denial; off POSIX there is nothing here to prove, and
        # saying so is the only honest answer. (The old code answered "PASSED".)
        print(
            "ISOLATION PROOF INCONCLUSIVE — this is a POSIX ownership + SO_PEERCRED proof "
            f"and os.name is {os.name!r}; nothing was attempted",
            file=sys.stderr,
        )
        return 2
    return report(run_attacks(dict(os.environ)))


if __name__ == "__main__":
    raise SystemExit(main())
