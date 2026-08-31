"""Run the Floor Writer as its own principal.

This is the process an installer starts as the Floor Writer account. It exists as a separate
entry point for the same reason ``run_supervisor.py`` does: the principal boundary is a PROCESS
boundary, and a service importable into the policed process is one an operator will eventually
run there.

Configuration is explicit and every value is REQUIRED. There is no default socket path, no
default store and no default allowlist, because each of those defaults would be a way for a
misconfigured deployment to come up looking provisioned:

    BRO_FLOOR_WRITER_SOCKET   the AF_UNIX path to serve on
    BRO_FLOOR_WRITER_STORE    the authoritative per-task floor store, owned by THIS account
    BRO_INSTALL_ID            the one install this writer serves
    BRO_FLOOR_WRITER_CALLERS  comma-separated uids permitted to request an advancement

It refuses to start on any platform where ``SO_PEERCRED`` is not available. That is a stop, not
a degradation: see ``floor_writer``'s module docstring on why a weaker mechanism under the same
name would be worse than an unsupported platform.

Exit codes: 0 never (it serves until killed), 2 configuration, 3 platform, 4 custody.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import floor_writer

EXIT_CONFIG = 2
EXIT_PLATFORM = 3
EXIT_CUSTODY = 4


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"{name} is required and unset; refusing to start a Floor Writer that would "
              "guess part of its own configuration", file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return value


def _callers(raw: str) -> frozenset:
    uids = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            uids.add(int(piece))
        except ValueError:
            print(f"BRO_FLOOR_WRITER_CALLERS contains {piece!r}, which is not a uid",
                  file=sys.stderr)
            raise SystemExit(EXIT_CONFIG)
    if not uids:
        print("BRO_FLOOR_WRITER_CALLERS names no uid; a writer with an empty allowlist would "
              "refuse every caller, which is a misconfiguration rather than a posture",
              file=sys.stderr)
        raise SystemExit(EXIT_CONFIG)
    return frozenset(uids)


def main(argv: list) -> int:  # pragma: no cover - exercised as a process, not imported
    socket_path = pathlib.Path(_required("BRO_FLOOR_WRITER_SOCKET"))
    store = pathlib.Path(_required("BRO_FLOOR_WRITER_STORE"))
    install_id = _required("BRO_INSTALL_ID")
    callers = _callers(_required("BRO_FLOOR_WRITER_CALLERS"))

    try:
        floor_writer.require_linux("cannot start the Floor Writer")
    except floor_writer.FloorWriterError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_PLATFORM

    # Prove custody BEFORE binding. A socket that exists is a promise, and a writer that cannot
    # protect its own state must not make one. The check is run against each permitted caller,
    # because "the store is not the caller's" is a statement about a specific caller.
    try:
        for uid in sorted(callers):
            floor_writer.require_writer_custody(store, uid)
    except floor_writer.FloorWriterError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CUSTODY

    try:
        server = floor_writer.bind(socket_path)
    except floor_writer.FloorWriterError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_CONFIG

    print(f"floor writer: serving {install_id} on {socket_path} from {store} "
          f"as uid {os.geteuid()} for callers {sorted(callers)}", file=sys.stderr)
    try:
        floor_writer.serve_forever(server, store=store, served_install_id=install_id,
                                   allowed_caller_uids=callers)
    finally:
        try:
            server.close()
        finally:
            try:
                socket_path.unlink()
            except OSError:
                pass
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
