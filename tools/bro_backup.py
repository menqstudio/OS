"""Integrity-checked backup and restore for machine-local runtime state.

The runtime keeps its durable state OUTSIDE Git, by contract: the execution-lease
ledger, the recovery/transaction store, the task-lock ledger, and the append-only
audit / shadow ledgers all live on operator-controlled paths. Operational rollout
needs those to survive a host move or disk loss without silently losing — or
silently corrupting — the audit history.

This tool snapshots a named set of those stores into an archive with a per-file
SHA-256 manifest, and restores them back with the manifest re-verified. It is
fail-closed on integrity: every append-only ledger (``*.jsonl``, verified through
bro_audit_log's hash chain + head anchor) is chain-verified at BOTH backup and
restore time, so a tampered or truncated ledger is never archived and never
restored. Non-ledger files are checksummed against the manifest, which detects
corruption and truncation (it is not a defence against an adversary who rewrites
both the file and its manifest entry — the append-only ledgers carry that
property cryptographically, ordinary state files do not).

Pure standard library plus bro_audit_log. No repository writes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

from bro_audit_log import AuditError, verify as verify_audit_chain

MANIFEST_NAME = "backup-manifest.json"


class BackupError(ValueError):
    pass


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(source: pathlib.Path) -> list[tuple[str, pathlib.Path]]:
    """Return (relpath, absolute) for every regular file under a source.

    A source may be a single file (e.g. an audit ledger) or a directory (e.g. the
    recovery store). Relative paths are taken from the source's parent for a file
    and from the source itself for a directory, so restore is uniform: everything
    lands under a single target directory.
    """
    source = source.expanduser()
    if source.is_file():
        files = [(source.name, source)]
        # An audit ledger's head anchor (.jsonl.head) is required for chain
        # verification; carry it alongside a single-file ledger source.
        if source.suffix == ".jsonl":
            head = source.with_name(source.name + ".head")
            if head.is_file():
                files.append((head.name, head))
        return files
    if source.is_dir():
        out = []
        for path in sorted(source.rglob("*")):
            if path.is_symlink():
                raise BackupError(f"refusing to back up a symlink: {path}")
            if path.is_file():
                out.append((path.relative_to(source).as_posix(), path))
        return out
    raise BackupError(f"backup source does not exist: {source}")


def _chain_count(path: pathlib.Path) -> int | None:
    """Chain-verify an append-only ledger; return its record count, or None for a
    file that is not a ``*.jsonl`` ledger. A broken chain fails closed."""
    if path.suffix != ".jsonl":
        return None
    try:
        return verify_audit_chain(path)
    except AuditError as exc:
        raise BackupError(f"append-only ledger failed chain verification: {path}: {exc}") from exc


def backup(sources: dict[str, pathlib.Path], dest: pathlib.Path, *, now: int) -> dict:
    """Archive each named source under ``dest/<name>/`` with an integrity manifest."""
    dest = dest.expanduser()
    if dest.exists() and any(dest.iterdir()):
        raise BackupError(f"backup destination is not empty: {dest}")
    manifest: dict = {"schema": 1, "created_at_epoch": int(now), "sources": {}}
    for name, source in sources.items():
        if "/" in name or "\\" in name or name in {"", ".", ".."}:
            raise BackupError(f"invalid source name: {name!r}")
        files = _iter_files(pathlib.Path(source))
        entries = []
        for rel, absolute in files:
            target = dest / name / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(absolute, target)
            entries.append({
                "rel": rel,
                "sha256": _sha256(absolute),
                "bytes": absolute.stat().st_size,
                "audit_chain": (lambda c: {"count": c} if c is not None else None)(_chain_count(absolute)),
            })
        manifest["sources"][name] = {
            "kind": "file" if pathlib.Path(source).expanduser().is_file() else "dir",
            "files": entries,
        }
    (dest / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def verify_archive(archive: pathlib.Path) -> dict:
    """Re-verify an archive against its manifest without restoring. Raises on any
    checksum mismatch, missing file, or broken ledger chain."""
    archive = archive.expanduser()
    manifest_path = archive / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackupError(f"unreadable backup manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise BackupError("unsupported backup manifest schema")
    for name, spec in manifest.get("sources", {}).items():
        for entry in spec.get("files", []):
            archived = archive / name / entry["rel"]
            if not archived.is_file():
                raise BackupError(f"archived file is missing: {name}/{entry['rel']}")
            if _sha256(archived) != entry["sha256"]:
                raise BackupError(f"archived file checksum mismatch: {name}/{entry['rel']}")
            if entry.get("audit_chain") is not None:
                count = _chain_count(archived)
                if count != entry["audit_chain"]["count"]:
                    raise BackupError(f"archived ledger chain length changed: {name}/{entry['rel']}")
    return manifest


def restore(archive: pathlib.Path, targets: dict[str, pathlib.Path], *, force: bool = False) -> dict:
    """Restore named sources from a verified archive into their target directories.

    Every file is checksum-verified and every ledger chain re-verified before any
    write. Existing target files are not clobbered unless ``force`` is set.
    """
    archive = archive.expanduser()
    manifest = verify_archive(archive)
    restored: dict[str, int] = {}
    for name, target in targets.items():
        spec = manifest.get("sources", {}).get(name)
        if spec is None:
            raise BackupError(f"archive has no source named {name!r}")
        target = pathlib.Path(target).expanduser()
        for entry in spec["files"]:
            out = target / entry["rel"]
            if out.exists() and not force:
                raise BackupError(f"refusing to overwrite existing file (use force): {out}")
        for entry in spec["files"]:
            out = target / entry["rel"]
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(archive / name / entry["rel"], out)
        restored[name] = len(spec["files"])
    return restored


def _parse_named(pairs: list[str]) -> dict[str, pathlib.Path]:
    out: dict[str, pathlib.Path] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise BackupError(f"expected name=path, got: {pair!r}")
        name, path = pair.split("=", 1)
        out[name] = pathlib.Path(path)
    return out


def main(argv: list[str] | None = None) -> int:
    import time
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    b = sub.add_parser("backup", help="archive named runtime-state sources")
    b.add_argument("--dest", required=True)
    b.add_argument("--source", action="append", metavar="name=path", help="repeatable")

    v = sub.add_parser("verify", help="re-verify an archive against its manifest")
    v.add_argument("--archive", required=True)

    r = sub.add_parser("restore", help="restore named sources from an archive")
    r.add_argument("--archive", required=True)
    r.add_argument("--target", action="append", metavar="name=path", help="repeatable")
    r.add_argument("--force", action="store_true")

    args = parser.parse_args(argv)
    try:
        if args.command == "backup":
            manifest = backup(_parse_named(args.source), pathlib.Path(args.dest), now=int(time.time()))
            print(f"GREEN: backed up sources={len(manifest['sources'])} to {args.dest}")
        elif args.command == "verify":
            manifest = verify_archive(pathlib.Path(args.archive))
            print(f"GREEN: archive verified sources={len(manifest['sources'])}")
        elif args.command == "restore":
            restored = restore(pathlib.Path(args.archive), _parse_named(args.target), force=args.force)
            print(f"GREEN: restored {restored}")
    except BackupError as exc:
        print(f"RED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
