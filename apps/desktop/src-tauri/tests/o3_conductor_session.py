"""O-3, both directions, against the REAL engine, driven by the REAL exported environment.

    python o3_conductor_session.py <engine-root> <another-deployments-registry-root>

Nothing here sets a trust variable. Every one of them arrives in `os.environ` because
`brops_lib::engine_trust::resolve` put it there — the same function, with the same
precedence rule, that `ai::governed_sidecar_call` runs before it spawns the engine. So a
variable missing from `Provisioned::engine_env()`, or dropped by the resolver, is a red
test here rather than a deployment that silently reads the wrong registry.

What is proved
--------------
1. `bro_policy.verify_conductor_session_token` ACCEPTS the `conductor-session` the Rust
   installer minted, with `root` = the engine's own tree, i.e. through exactly the path
   `bro_hook` -> `bro_completion.authorize_conductor_stop` takes. Nothing is staged, copied
   or substituted: the registry stays where provisioning put it and the engine is redirected
   to it.
2. The SAME token is REFUSED with `BRO_TRUSTED_REGISTRY_ROOT` unset — and the refusal names
   the operator-pin disagreement, which is the proof that what answered instead was
   `engine/config/trusted-keys.json`, a registry signed by a key this machine never minted.
   That refusal is O-3 as it stood.
3. The SAME token is REFUSED when the variable points at another install's registry root:
   a registry that is operator-signed, `production: true`, current and well-formed — just
   not this deployment's. Redirecting is not accepting whatever is found.
4. Each exported variable is dropped in turn and the effect on (1) is recorded. Four of the
   five are load-bearing for O-3; the fifth is not, and this says which and why instead of
   implying the set is uniformly critical.

The one thing this proof does NOT establish
-------------------------------------------
Custody. The store under test is the UNSEALED mint (`mint_store_without_custody_proof`),
because sealing is one-way for the account that applies it and a test must not permanently
seal a directory on the machine running it. A temp directory is writable by this account, so
`bro_signature._pin_from_file` and `_refuse_writable_registry_root` would refuse it — the
harness therefore sets `BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged` for this process ONLY.
It is asserted below that the acknowledgement is NOT in the exported set, and the application
refuses to export anything at all while it is present in the ambient environment
(`engine_trust`, rule 5). Custody is proved separately, with it unset, by
`audit-signer/tests/anchor_end_to_end.py`.
"""

from __future__ import annotations

import contextlib
import os
import pathlib
import sys

CHECKS: list[str] = []

# The exported set, named here so a variable silently disappearing from
# `Provisioned::engine_env()` fails this proof instead of quietly changing what the engine
# reads. Kept in the order the Rust side returns it.
EXPECTED_EXPORTS = (
    "BRO_TRUSTED_REGISTRY_ROOT",
    "BRO_OPERATOR_ROOT_PUBKEY_FILE",
    "BRO_OPERATOR_REGISTRY_MIN_FILE",
    "BRO_CONDUCTOR_SESSION_TOKEN",
    "BRO_SESSION_ID",
)

# The acknowledgement that switches every custody rule off. It must never be exported —
# under EITHER name. The raw variable is honoured only under `BRO_ENV=ci` now, and a
# production deployment declares the posture in the `_FILE` form; a check that knew only the
# raw name would leave the new one an unwatched way to disable every custody rule at once.
NEVER_EXPORTED = "BRO_OPERATOR_ROOT_PIN_SELF_OWNED"
NEVER_EXPORTED_FILE = "BRO_OPERATOR_ROOT_PIN_SELF_OWNED_FILE"


def ok(message: str) -> None:
    CHECKS.append(message)
    print(f"  PASS  {message}")


def fail(message: str) -> None:
    print(f"  FAIL  {message}", file=sys.stderr)
    raise SystemExit(1)


def require(condition: bool, message: str) -> None:
    ok(message) if condition else fail(message)


@contextlib.contextmanager
def without(name: str):
    """Drop one variable for the duration of a check, then restore it exactly."""
    had = name in os.environ
    saved = os.environ.get(name)
    os.environ.pop(name, None)
    try:
        yield
    finally:
        if had:
            os.environ[name] = saved  # type: ignore[assignment]
        else:
            os.environ.pop(name, None)


@contextlib.contextmanager
def pointing(name: str, value: str):
    saved = os.environ.get(name)
    os.environ[name] = value
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = saved


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    engine = pathlib.Path(argv[1]).resolve()
    elsewhere = pathlib.Path(argv[2])

    print("== what the application actually exported, before anything is imported ==")
    for name in EXPECTED_EXPORTS:
        value = os.environ.get(name)
        require(bool(value),
                f"{name} arrived in the child environment from engine_trust::resolve "
                f"({value!r})")
    for name in (NEVER_EXPORTED, NEVER_EXPORTED_FILE):
        require(name not in os.environ,
                f"{name} is NOT in the exported set — the application refuses to "
                f"export anything at all while it is present, because it switches every "
                f"custody rule in the runtime off at once")
    # Set by the harness, never by the resolver — see the module docstring. Through the FILE
    # form, because the raw variable is honoured only under BRO_ENV=ci and this is not CI.
    _ack = elsewhere.parent / "self-owned-acknowledgement"
    _ack.write_text("acknowledged", encoding="utf-8")
    os.environ[NEVER_EXPORTED_FILE] = str(_ack)

    sys.path.insert(0, str(engine / "runtime"))
    sys.path.insert(0, str(engine / "tools"))

    import bro_signature
    from bro_policy import (
        CANONICAL_CONDUCTOR_ID,
        CONDUCTOR_ROLE,
        State,
        conductor_session_token_required,
        verify_conductor_session_token,
    )

    require(bro_signature.ROOT.resolve() == engine,
            f"the engine module under test is the one at {engine}, so `root=ROOT` callers "
            f"and this proof are talking about the same tree")

    required, why = conductor_session_token_required(engine)
    require(required, f"the SHIPPED .bro/policy.json makes the token mandatory: {why}")

    def check() -> tuple[bool, str]:
        """The real verifier, through the real engine root, with whatever env is current."""
        state = State(mode="review", role=CONDUCTOR_ROLE,
                      session_id=os.environ.get("BRO_SESSION_ID", "unknown"),
                      agent_id=CANONICAL_CONDUCTOR_ID)
        return verify_conductor_session_token(state, engine)

    print("== (1) O-3 closes: the minted conductor session is accepted by the real engine ==")
    accepted, note = check()
    require(accepted,
            f"verify_conductor_session_token(root=engine) ACCEPTED the installer-minted "
            f"conductor-session: {note}")
    require("verified against the trusted-key registry" in note, note)

    print("== (2) the same token, with the redirect gone: the committed registry answers ==")
    with without("BRO_TRUSTED_REGISTRY_ROOT"):
        refused, why = check()
        require(not refused,
                f"without BRO_TRUSTED_REGISTRY_ROOT the very same token is REFUSED: {why}")
        require("does not match the external operator pin" in why,
                f"and the refusal names WHY — the engine read engine/config/trusted-keys.json, "
                f"a registry signed by an operator key this machine never minted: {why}")

    print("== (3) pointed at another install's registry root: refused, not accepted ==")
    with pointing("BRO_TRUSTED_REGISTRY_ROOT", str(elsewhere)):
        refused, why = check()
        require(not refused,
                f"a registry that is operator-signed, production and current — but another "
                f"deployment's — does not authorise this token: {why}")
        require("RED" in why, why)

    print("== (4) which members of the exported set are load-bearing for O-3 ==")
    # The claim `engine_trust` makes is that the set is exported WHOLE. This measures what
    # dropping each member costs, so the claim is backed by an observation rather than by
    # the assertion that all five must matter equally.
    load_bearing = {
        "BRO_TRUSTED_REGISTRY_ROOT",
        "BRO_OPERATOR_ROOT_PUBKEY_FILE",
        "BRO_CONDUCTOR_SESSION_TOKEN",
        "BRO_SESSION_ID",
    }
    for name in EXPECTED_EXPORTS:
        with without(name):
            accepted_without, note_without = check()
        if name in load_bearing:
            require(not accepted_without,
                    f"dropping {name} alone REFUSES the token: {note_without}")
        else:
            require(accepted_without,
                    f"dropping {name} does NOT refuse the token, and pretending otherwise "
                    f"would be a false claim about the set: {note_without}")

    print("== and what the one non-load-bearing member actually buys ==")
    # `BRO_OPERATOR_REGISTRY_MIN_FILE` is the anti-rollback floor. Its absence cannot show up
    # in an authentication check, because an operator-signed registry stays operator-signed
    # after it is superseded — which is the engine's own stated reason for calling the absent
    # floor "the only permissive default in this module, and explicitly weaker".
    floor = bro_signature.resolve_registry_floor(env=os.environ, root=engine)
    require(floor is not None,
            f"with BRO_OPERATOR_REGISTRY_MIN_FILE exported, a floor IS pinned: {floor}")
    with without("BRO_OPERATOR_REGISTRY_MIN_FILE"):
        require(bro_signature.resolve_registry_floor(env=os.environ, root=engine) is None,
                "and without it NO floor is enforced, so a superseded but still "
                "operator-signed registry would replay cleanly — which is what dropping "
                "it costs, and it is not something a session check can notice")

    print(f"\nGREEN: {len(CHECKS)} checks passed. O-3 closes through the real engine on the "
          f"environment the application exports, and reopens the moment it does not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
