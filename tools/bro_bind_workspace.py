"""Issue an operator-signed workspace binding for a repository checkout.

The binding is the operator-controlled artifact that grants a session its scope.
It is deliberately written outside the repository: a binding stored inside the
tree it authorises could be widened by the very agent it constrains.

The runtime (bro_workspace.load_workspace) verifies the binding as a signed
"workspace-binding" artifact against the operator-pinned trusted-key registry
before trusting any field, so the default output here is `{payload, signature}`
minted with the operator-root private key. The unsigned Phase A shape is kept
only behind an explicit --unsigned dev flag and is rejected by the runtime.

    python tools/bro_bind_workspace.py --root . --operator-key KEYDIR \\
        --out C:\\BroControl\\binding.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from bro_signature import OPERATOR, SignatureError
from bro_workspace import WorkspaceError, git_config_path, normalize_remote
from broctl import sign_payload
from bro_protected import compute_control_plane_digest, load_protected_manifest

DEFAULT_TTL_SECONDS = 8 * 60 * 60

# The file broctl keygen writes for the operator authority inside a keydir; an
# --operator-key naming a directory resolves to this standard location.
OPERATOR_KEY_FILENAME = f"{OPERATOR}.json"

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
    """The binding payload; carries artifact_type from the start so the signing
    step only adds the operator key_id and wraps `{payload, signature}` — the
    shape verify_artifact binds the signature to."""
    manifest = load_protected_manifest(root)
    repository = detect_remote(root)
    return {
        "schema": 1,
        "artifact_type": "workspace-binding",
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
    }


def load_operator_key(path: pathlib.Path) -> dict:
    """The operator private key, from a key file or a keydir holding one.

    Only the operator authority may issue a binding: verify_artifact will refuse
    any other authority at load time, so refusing here fails at mint instead of
    at first use, with the operator still at the keyboard.
    """
    resolved = pathlib.Path(path).expanduser()
    if resolved.is_dir():
        resolved = resolved / OPERATOR_KEY_FILENAME
    try:
        key = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SignatureError(f"cannot load operator key {resolved}: {exc}") from exc
    if key.get("authority_type") != OPERATOR:
        raise SignatureError(
            f"a {key.get('authority_type')!r} key may not issue a workspace "
            f"binding: that requires {OPERATOR} authority")
    if not isinstance(key.get("private_key"), str):
        raise SignatureError(f"{resolved} carries no private key material")
    return key


def sign_binding(binding: dict, operator_key: dict) -> dict:
    payload = dict(binding)
    payload["key_id"] = operator_key["key_id"]
    return sign_payload(operator_key["private_key"], payload)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", default=".", help="repository checkout to bind")
    parser.add_argument("--out", help="binding path; must be outside --root")
    parser.add_argument("--workspace-id", default="bro-primary")
    parser.add_argument("--issued-by", default="owner-gev")
    parser.add_argument("--ttl-seconds", type=int, default=DEFAULT_TTL_SECONDS)
    parser.add_argument("--operator-key",
                        help="operator-root key file, or the keydir holding "
                             f"{OPERATOR_KEY_FILENAME} (as written by broctl keygen)")
    parser.add_argument("--unsigned", action="store_true",
                        help="DEV ONLY: emit the raw unsigned payload; the runtime "
                             "rejects it, this exists only for offline inspection")
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
        if not args.unsigned and not args.operator_key:
            parser.error("--operator-key is required to issue a signed binding "
                         "(or pass --unsigned for a dev-only inspection copy)")
        out = pathlib.Path(args.out).resolve()
        if out.is_relative_to(root):
            print(f"RED: {out} is inside {root}; a binding must live outside the "
                  f"repository it authorises", file=sys.stderr)
            return 1
        binding = build_binding(root, args.workspace_id, args.issued_by,
                                args.ttl_seconds, int(time.time()))
        if args.unsigned:
            binding["authority"] = ("phase-a-filesystem-permissions-only; "
                                    "NOT cryptographically signed")
            document = binding
        else:
            document = sign_binding(binding, load_operator_key(
                pathlib.Path(args.operator_key)))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                       encoding="utf-8")
    except (WorkspaceError, SignatureError) as exc:
        print(f"RED: {exc}", file=sys.stderr)
        return 1

    if args.unsigned:
        print("GREEN: UNSIGNED dev binding written; load_workspace will refuse it")
    else:
        print(f"GREEN: operator-signed workspace binding issued for "
              f"{binding['repository']}")
        print(f"  key_id:  {document['payload']['key_id']}")
    print(f"  path:    {out}")
    print(f"  digest:  {binding['control_plane_digest']}")
    print(f"  expires: {binding['expires_at_epoch']}")
    print(f"\nExport it before starting a session:\n  BRO_WORKSPACE_BINDING={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
