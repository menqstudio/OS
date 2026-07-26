"""AF_UNIX service wrapper for the dedicated desktop challenge authority."""
from __future__ import annotations

import os

import brops_socket
from brops_challenge_authority import ChallengeAuthority, load_config


def _allowed(env=None) -> frozenset[int]:
    e = os.environ if env is None else env
    return frozenset(int(x) for x in e.get("BROPS_CHALLENGE_ALLOWED_PEER_UIDS", "").split(",") if x.strip())


def run(env=None, *, max_requests: int | None = None, ready=None) -> int:
    e = os.environ if env is None else env
    authority = ChallengeAuthority(e["BROPS_CHALLENGE_DB"], load_config(e))
    try:
        authority.sweep()
        brops_socket.serve_forever(
            e["BROPS_CHALLENGE_SOCKET"], authority.handle,
            allowed_peer_uids=_allowed(e), max_requests=max_requests, ready=ready,
        )
    finally:
        authority.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
