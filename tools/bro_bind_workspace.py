"""Issue a workspace binding for a repository checkout.

The binding is the operator-controlled artifact that grants a session its scope.
It is deliberately written outside the repository: a binding stored inside the
tree it authorises could be widened by the very agent it constrains.

In Phase A the binding is plain JSON and its authority rests on filesystem
permissions, so it must live where the agent account cannot write. Phase B
replaces that with an Ed25519 signature from an offline operator key, at which
point the file's location stops carrying the trust on its own.

    python tools/bro_bind_workspace.py --root . --out C:\\BroControl\\binding.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

from bro_protected import compute_control_plane_digest, load_protected_manifest
from bro_workspace import WorkspaceError, git_config_path, normalize_remote

DEFAULT_TTL_SECONDS = 8 * 60 * 60

DEFAULT_PROHIBITED = [
    ".git/config",
    ".git/credentials",
    "**/.env",
    "**/*secret*",
    "**/*credential*",
    "**/*private-key*",
]


def detect_remote(root: pathlib.Path) -> str:
    config = git_config_path(root)
    try:
        text = config.read_text(encoding="utf-8")
    except OSError as exc:
        raise WorkspaceError(f"cannot read {config}: {exc}") from exc
    urls = re.findall(r"^\s*url\s*=\s*(.+?)\s*$", text, re.MULTILINE)
    if not urls:
        raise WorkspaceError("repository has no remote url")
    remotes = {normalize_remote(url) for url in urls}
    if len(remotes) != 1:
        raise WorkspaceError(f"repository has ambiguous remotes: {sorted(remotes)}")
    return remotes.pop()


def build_binding(root: pathlib.Path, workspace_id: str, issued_by: str,
                  ttl_seconds: int, now: int) -> dict:
    manifest = load_protected_manifest(root)
    repository = detect_remote(root)
    return {
        "schema": 1,
        "workspace_id": workspace_id,
        "repository": repository,
        "root": str(root),
        "control_plane_digest": compute_control_plane_digest(root, manifest),
        "allowed_paths": ["**"],
        "prohibited_paths": list(DEFAULT_PROHIBITED),
        "allowed_remotes": ["origin"],
        "allowed_remote_repository": repository,
        "issued_by": issued_by,
        "issued_at_epoch": now,
        "expires_at_epoch": now + ttl_seconds,
        "active": True,
        "authority": "phase-a-filesystem-permissions-only; NOT cryptographically signed",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository checkout to bind")
    parser.add_argument("--out", help="binding path; must be outside --root")
    parser.add_argument("--workspace-id", default="bro-primary")
    parser.add_argument("--issued-by", default="owner-gev")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--print-digest-only", action="store_true",
                        help="emit the current control-plane digest and exit")
    args = parser.parse_args(argv)

    root = pathlib.Path(args.root).resolve()
    try:
        if args.print_digest_only:
            print(compute_control_plane_digest(root, load_protected_manifest(root)))
            return 0
        if not args.out:
            parser.error("--out is required unless --print-digest-only is given")
        out = pathlib.Path(args.out).resolve()
        if out.is_relative_to(root):
            print(f"RED: {out} is inside {root}; a binding must live outside the "
                  f"repository it authorises", file=sys.stderr)
            return 1
        binding = build_binding(root, args.workspace_id, args.issued_by,
                                args.ttl_seconds, int(time.time()))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(binding, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    except WorkspaceError as exc:
        print(f"RED: {exc}", file=sys.stderr)
        return 1

    print(f"GREEN: workspace binding issued for {binding['repository']}")
    print(f"  path:    {out}")
    print(f"  digest:  {binding['control_plane_digest']}")
    print(f"  expires: {binding['expires_at_epoch']}")
    print(f"\nExport it before starting a session:\n  BRO_WORKSPACE_BINDING={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
