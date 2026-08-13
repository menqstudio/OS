#!/usr/bin/env python3
"""Canonical full-read receipt -- the rule behind "read every canonical file".

CLAUDE.md has said "load every path in config/canonical-read-manifest.json" and
"a textual claim such as 'I read it' is not evidence" since the repository was
assembled. Nothing at the repository ROOT enforced it: the root
`.claude/settings.json` wired one Stop-hook and no wall. Prose does not bind a
session; a check does. This is the check.

WHAT A RECEIPT IS
  The SHA-256 of every path in the canonical read manifest AS IT WAS at the
  moment the session read it, plus the SHA-256 of the manifest itself. It is
  verified by re-hashing the same files. The instant any canonical file changes
  -- by this session, by another agent, by a merge -- every previously recorded
  receipt stops verifying and the session must take the new bytes before it may
  act again. That content binding is the whole point: a filename list would let a
  session hold a "I read them" proof for documents it has never seen in their
  current form, which is precisely the failure being fixed.

WHERE IT LIVES, AND WHY NOT IN THE REPOSITORY
      <tempdir>/os-canonical-law/<sha256(repo real path)[:16]>/<session-id>.json

  Per session, outside the worktree, deliberately. A receipt inside the tree
  could be committed, and a committed receipt is a REUSABLE one: the next clone
  would inherit a proof it never earned. `receipt_dir()` refuses to return a
  directory inside the repository, so even a mis-set BRO_RECEIPT_DIR cannot
  quietly re-create that hole.

WHAT THIS PROVES, AND WHAT IT DOES NOT
  It proves the canonical bytes a session acts under are the bytes on disk right
  now. It does NOT prove comprehension and cannot: no check can. The
  comprehension half is carried by the SessionStart hook, which injects the full
  text of every canonical file into the session's context in the same breath as
  it records the receipt -- so on the normal path the receipt is honest by
  construction, and the failure it defends against (acting on stale documents,
  never opening the roadmap) is the one that actually happened.

  It is NOT unforgeable against the agent it binds: an agent with shell access
  can call `--record` without reading anything. That hole is reported rather than
  papered over. What removes the incentive is that the hook records the receipt
  and hands over the content for free.

Usage:
  python tools/check_read_receipt.py --verify [--session ID] [--root DIR]
  python tools/check_read_receipt.py --record [--session ID] [--root DIR]
  python tools/check_read_receipt.py --show   [--session ID] [--root DIR]
Exit 0 + "GREEN: ..." when the receipt is valid; exit 1 + the reason otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import tempfile
import time

SCHEMA = 1
KIND = "canonical-read-receipt"
MANIFEST = "config/canonical-read-manifest.json"
RECEIPT_ROOT_NAME = "os-canonical-law"
# The session identity a hook payload carries. Env fallbacks exist so the CLI and
# the hook agree on WHICH receipt they are talking about.
SESSION_ENV = ("CLAUDE_SESSION_ID", "BRO_SESSION_ID")


class ReceiptError(RuntimeError):
    """A receipt cannot even be formed (missing manifest, missing canonical file)."""


def sha256_file(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_paths(root: pathlib.Path) -> list[str]:
    manifest = root / MANIFEST
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ReceiptError(f"canonical read manifest is unreadable: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ReceiptError(f"canonical read manifest is not valid JSON: {exc}") from exc
    paths = document.get("paths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) for p in paths):
        raise ReceiptError("canonical read manifest has no usable 'paths' list")
    return [p.replace("\\", "/") for p in paths]


def canonical_hashes(root: pathlib.Path) -> dict[str, str]:
    """SHA-256 of every canonical path. A missing canonical file is fatal, never
    skipped: a receipt that silently omits an unreadable document proves nothing
    about it while still reading as a full-read proof."""
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for rel in manifest_paths(root):
        try:
            hashes[rel] = sha256_file(root / rel)
        except OSError:
            missing.append(rel)
    if missing:
        raise ReceiptError(f"canonical files are missing or unreadable: {missing}")
    return hashes


def canonical_digest(hashes: dict[str, str]) -> str:
    """One digest over the whole canonical set, order-independent."""
    digest = hashlib.sha256()
    for rel in sorted(hashes):
        digest.update(rel.encode("utf-8") + b"\0" + bytes.fromhex(hashes[rel]) + b"\0")
    return digest.hexdigest()


def session_id(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    for name in SESSION_ENV:
        value = os.getenv(name)
        if value:
            return value
    return "unknown"


def receipt_dir(root: pathlib.Path) -> pathlib.Path:
    """Per-repository receipt folder, outside the worktree by construction."""
    override = os.getenv("BRO_RECEIPT_DIR")
    base = pathlib.Path(override) if override else pathlib.Path(tempfile.gettempdir()) / RECEIPT_ROOT_NAME
    key = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:16]
    path = (base / key).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError:
        pass
    else:
        raise ReceiptError(
            f"receipt directory {path} is inside the repository; refusing "
            "(a committed receipt is a reusable one)")
    path.mkdir(parents=True, exist_ok=True)
    return path


def receipt_path(root: pathlib.Path, sid: str) -> pathlib.Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", sid or "unknown")[:120]
    return receipt_dir(root) / f"{safe}.json"


def blank(root: pathlib.Path, sid: str) -> dict:
    hashes = canonical_hashes(root)
    return {
        "schema": SCHEMA,
        "kind": KIND,
        "session_id": sid,
        "repo_root": str(root.resolve()),
        "recorded_at_epoch": int(time.time()),
        "manifest_sha256": sha256_file(root / MANIFEST),
        "paths": hashes,
        "canonical_digest": canonical_digest(hashes),
        "canonical_bytes": sum((root / rel).stat().st_size for rel in hashes),
        # Filled in by the sibling gates; carried here so ONE per-session artifact
        # holds everything the wall needs and there is only one thing to expire.
        "declared_phase": None,
        "declared_phase_note": "",
        "prior_art": [],
    }


def record(root: pathlib.Path, sid: str) -> dict:
    """Record a fresh receipt, PRESERVING the session's declarations.

    Re-reading changed documents must not silently wipe the phase the session
    declared or the prior-art searches it recorded -- those are statements about
    the session, not about the files. But a phase declaration is re-validated by
    check_roadmap_order against the NEW roadmap on every use, so carrying it over
    cannot launder a phase that has since stopped being the open one.
    """
    receipt = blank(root, sid)
    previous = load(root, sid)
    if previous:
        receipt["declared_phase"] = previous.get("declared_phase")
        receipt["declared_phase_note"] = previous.get("declared_phase_note", "")
        receipt["prior_art"] = previous.get("prior_art", [])
    write_receipt(root, sid, receipt)
    return receipt


def write_receipt(root: pathlib.Path, sid: str, receipt: dict) -> None:
    receipt_path(root, sid).write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(root: pathlib.Path, sid: str) -> dict | None:
    try:
        return json.loads(receipt_path(root, sid).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ReceiptError):
        return None


def verify(root: pathlib.Path, sid: str) -> tuple[bool, str]:
    """(ok, reason). Content-bound only -- no clock.

    A receipt is valid exactly as long as the canonical bytes it names are the
    bytes on disk. There is deliberately no expiry interval: an interval would
    both permit acting on documents that changed inside it and demand a pointless
    re-read of documents that did not.
    """
    receipt = load(root, sid)
    if receipt is None:
        return False, "no full-read receipt for this session"
    if receipt.get("schema") != SCHEMA or receipt.get("kind") != KIND:
        return False, "full-read receipt has an unrecognised schema/kind"
    if receipt.get("repo_root") != str(root.resolve()):
        return False, "full-read receipt was recorded against a different repository root"
    try:
        current_manifest = sha256_file(root / MANIFEST)
        current = canonical_hashes(root)
    except (ReceiptError, OSError) as exc:
        return False, f"cannot re-hash the canonical set: {exc}"
    if receipt.get("manifest_sha256") != current_manifest:
        return False, (f"{MANIFEST} changed after the full-read receipt: the canonical set "
                       "itself was redefined")
    recorded = receipt.get("paths")
    if not isinstance(recorded, dict):
        return False, "full-read receipt carries no per-file hashes"
    added = sorted(set(current) - set(recorded))
    if added:
        return False, f"canonical files not covered by the receipt: {added}"
    dropped = sorted(set(recorded) - set(current))
    if dropped:
        return False, f"canonical files in the receipt are no longer in the manifest: {dropped}"
    changed = sorted(rel for rel in current if current[rel] != recorded.get(rel))
    if changed:
        return False, f"canonical files changed after the full-read receipt: {changed}"
    if receipt.get("canonical_digest") != canonical_digest(current):
        return False, "full-read receipt digest does not match its own hashes (tampered)"
    return True, (f"full-read receipt valid for {len(current)} canonical files "
                  f"(digest {receipt['canonical_digest'][:12]})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--root", default=str(pathlib.Path(__file__).resolve().parents[1]))
    parser.add_argument("--session", default=None)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--record", action="store_true")
    action.add_argument("--verify", action="store_true")
    action.add_argument("--show", action="store_true")
    args = parser.parse_args(argv)
    root = pathlib.Path(args.root).resolve()
    sid = session_id(args.session)
    try:
        if args.record:
            receipt = record(root, sid)
            print(f"GREEN: recorded full-read receipt for session {sid}: "
                  f"{len(receipt['paths'])} canonical files, {receipt['canonical_bytes']} bytes, "
                  f"digest {receipt['canonical_digest'][:12]}")
            return 0
        if args.show:
            receipt = load(root, sid)
            print(json.dumps(receipt, indent=2, sort_keys=True) if receipt else "RED: no receipt")
            return 0 if receipt else 1
        ok, reason = verify(root, sid)
    except ReceiptError as exc:
        print(f"RED: {exc}")
        return 1
    print(("GREEN: " if ok else "RED: ") + reason)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
