"""Run the Floor Writer as its own principal — FW-1, Linux.

The process a service manager starts as the ``brops-floor`` account (§1.1). It exists as a
separate entry point because the principal boundary is a PROCESS boundary: a service importable
into the policed process is one an operator will eventually run there.

**One input, and it is the service's own.** Everything — the install scope, the marks root, the
endpoint and the per-op peer allowlist — comes from the TCB-owned config named by
``BROPS_FLOOR_WRITER_CONFIG`` (§4.4), which mirrors ``BROPS_BROKER_CONFIG``'s shape. The policed
process contributes nothing. There is no default socket path, no default store and no default
allowlist, because each of those would be a way for a misconfigured deployment to come up looking
provisioned.

**Custody is proved before the endpoint exists.** The marks directory and the socket's directory
are both checked (§1.2, §1.7) before ``bind``. A socket that exists is a promise, and a service
that cannot show its state is protected must not make one.

**Refusing to start is the healthy failure.** Every early return here is an error: a healthy Floor
Writer serves until it is stopped.

Exit codes: 2 configuration, 3 platform, 4 custody. There is no exit 0 path.
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


def start(argv=None) -> int:
    """Load, prove custody, bind, serve. Returns only on failure."""
    try:
        floor_writer.require_linux("cannot start the Floor Writer")
    except floor_writer.FloorWriterError as exc:
        print(exc.detail, file=sys.stderr)
        return EXIT_PLATFORM

    try:
        config = floor_writer.load_service_config()
    except floor_writer.FloorWriterError as exc:
        print(exc.detail, file=sys.stderr)
        return EXIT_CONFIG

    # §1.2 and §1.7, in that order and both before the socket exists.
    try:
        floor_writer.require_private_directory(config.marks_dir, "the Floor Writer marks store")
        floor_writer.require_private_directory(
            config.socket_path.parent, "the Floor Writer socket directory")
    except floor_writer.FloorWriterError as exc:
        print(exc.detail, file=sys.stderr)
        return EXIT_CUSTODY

    # The authoritative document must already exist: §4.2 says a floor is not
    # client-bootstrappable, and it is not service-bootstrappable at start either. Provisioning
    # writes the first one, deliberately, so that "no state" is never confused with "empty state".
    try:
        floor_writer.load_state(config)
    except floor_writer.FloorWriterError as exc:
        print(exc.detail, file=sys.stderr)
        return EXIT_CONFIG

    try:
        server = floor_writer.bind(config.socket_path)
    except floor_writer.FloorWriterError as exc:
        print(exc.detail, file=sys.stderr)
        return EXIT_CUSTODY

    print(f"floor writer: install {config.install_id} generation {config.generation} on "
          f"{config.socket_path} from {config.marks_dir} as uid {os.geteuid()}", file=sys.stderr,
          flush=True)
    try:
        floor_writer.serve_forever(server, config)
    finally:
        try:
            server.close()
        finally:
            try:
                config.socket_path.unlink()
            except OSError:
                pass
    return EXIT_CONFIG


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(start(sys.argv[1:]))
