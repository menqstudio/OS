#!/usr/bin/env python3
"""No Owner-held key, and no ceremony to make one. The Owner's decision, held by a gate.

On 2026-08-09 (#78) the Owner decided: *"install it, and everything is already done. No keys to carry,
no USB, no annual renewal, nothing ever asked again, on any OS."* The install mints trust; no person
holds a root. The decision lived in a pull request body and one section of a long page, and from
2026-09-20 to 2026-09-30 an offline-root ceremony was rebuilt for the broker's TCB root anyway — tools,
a runbook, kit flags — and the Owner was told, again, that the next step was his. T-130 removed it.
This gate is why it stays removed: a memory note or a sentence in a document is what failed last time.

THREE RULES.

  1. The removed artifacts do not exist: the two ceremony runbooks, the offline signer and the root
     generator.
  2. No tracked text file outside the history below names them, or names the flags and environment
     variables that existed only to carry an offline root's material into a kit.
  3. No such file asserts, in prose, that a PERSON holds the root: the phrases below, matched without
     regard to case. Rule 2 alone missed ten of these in 2026-10 (`preflight.rs`, two engine modules,
     the Phase-10 inventory) because it matched tool names, not claims.

     And without regard to LAYOUT. Until T-145 a phrase was matched against the file's bytes, so a
     claim that wrapped at the end of a comment line, or carried one bold word, was a different
     string from the phrase that named it: `the root private is` / `// held offline entirely` and
     `held **offline**` both read GREEN. A phrase is now matched against the file as PROSE --
     comment leaders, emphasis marks and line breaks removed (`prose`).

HISTORY IS EXEMPT, and only history: `docs/archive/`, the audit reports under `apps/desktop/AUDIT/`
(rewriting audit evidence would be falsifying it), the released CHANGELOG, this gate with its test, and
the engine test that asserts the provisioner refuses those flags.

A CONTROL, so a green means something: the sweep must read at least one file it knows contains a
forbidden token — its own test file, which is exempt by path and therefore proves the walk reached it
and the matcher fired. A walk that read nothing would otherwise pass vacuously.

Usage:  python tools/check_no_owner_key_ceremony.py [repo-root]
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(
    __file__).resolve().parents[1]

#: Rule 1 — paths that must not exist.
REMOVED_PATHS = (
    "docs/DEBIAN_CUSTODY_CEREMONY.md",
    "apps/desktop/src-tauri/win-live/CUSTODY_CEREMONY.md",
    "engine/ci/live/sign_manifest.py",
    "apps/desktop/src-tauri/win-live/src/bin/win_gen_root.rs",
)

#: Rule 2 — tokens that existed only to mint, carry or apply an Person-held root. Concrete names, not
#: prose: a gate on the word "offline" would fire on every honest sentence explaining why it is gone.
FORBIDDEN_TOKENS = (
    "DEBIAN_CUSTODY_CEREMONY",
    "CUSTODY_CEREMONY.md",
    "sign_manifest.py",
    "win_gen_root",
    "root.private.seed",
    "--emit-manifest",
    "--emit-registry",
    "--registry-sig-in",
    "--manifest-sig-in",
    "--root-anchor-pub-hex",
    "BROPS_MANIFEST_SIG_IN",
    "BROPS_REGISTRY_SIG_IN",
    "BROPS_ROOT_ANCHOR_PUB_HEX",
    # The removable-media path the deleted Steps 1-5 kept the operator root on. A runbook line that
    # still cited it (T-145) was pointing at a file no step creates.
    "/media/usb/bro-root",
)

#: Rule 3 — prose that asserts a person holds, mints or exports the root. Lowercased before matching.
#: Narrow on purpose: each is a CLAIM, not a topic, so the honest sentence explaining why the
#: ceremony is gone ("nobody holds an offline root") does not trip it.
FORBIDDEN_PHRASES = (
    "owner's offline",
    "offline-root-custodian",
    "owner-provided key",
    "owner mints a key",
    "only the owner can make",
    "the owner must export",
    # T-145. The whole-repository read found the claim alive in thirty-odd places the six phrases
    # above could not see. Each one below is the wording of a sentence that was actually in the
    # tree, and `test_check_no_owner_key_ceremony.SURVIVORS` keeps that sentence beside it.
    # -- a root or key a person keeps off the machine
    "your offline root",
    "held offline by the operator",
    "root private is held offline",
    "private key is held offline",
    "is offline, not on this box",
    "trusted_verified without the offline root",
    "offline operator",
    "offline issuer",
    "owner-held recovery",
    "the owner holds",
    # -- a step that waits on a person's key or signature
    "only the owner can mint",
    "only the owner can provide",
    "is the owner's step",
    "owner's out-of-band",
    "the owner's ceremony",
    "is the owner's signature",
    "owner mints the artifact",
    "owner must mint",
    "owner has to mint",
    "signed offline by the owner",
    "the owner has run steps",
    "mint, offline",
    "anchoring a ledger by hand",
)

#: Exempt by path prefix: history, and the two files that must name what they forbid.
EXEMPT_PREFIXES = (
    "docs/archive/",
    "apps/desktop/AUDIT/",
    "apps/desktop/CHANGELOG.md",
    "tools/check_no_owner_key_ceremony.py",
    "tools/test_check_no_owner_key_ceremony.py",
    # Names the flags and variables to assert the provisioner REFUSES them and the kits never read
    # them — the runtime half of this gate.
    "engine/tests/test_live_provisioning_anchor.py",
)

#: The control: a file that is exempt AND must contain a forbidden token.
CONTROL = "tools/test_check_no_owner_key_ceremony.py"

#: Includes "" — a file with NO suffix. Maintainer scripts (`deb/postinst`) and git hooks have none,
#: and until T-135 the sweep skipped them: an installer script was the one place a ceremony
#: instruction could have returned unseen.
#:
#: ONE set, read by `check_root_anchor_custody.py` too. Until T-145 that gate kept its own list, and
#: the two had drifted: this one had "" and the seed sweep did not, the seed sweep had `.cfg`/`.ini`/
#: `.env`/`.lock` and this one did not, and neither read `.mjs` or `.xml`. A file one sweep cannot
#: see is where the thing the other sweep forbids would sit.
TEXT_EXT = frozenset({
    "",
    ".rs", ".py", ".ts", ".tsx", ".js", ".mjs", ".json", ".md", ".yml", ".yaml", ".toml", ".sql",
    ".sh", ".ps1", ".txt", ".html", ".css", ".xml", ".cfg", ".ini", ".env", ".lock",
})

#: What opens a comment or a quote at the start of a line. Removed by `prose`, so a claim wrapped
#: across two comment lines is one sentence again.
_LINE_LEADER = re.compile(r"(?m)^[ \t]*(?://[/!]?|#+|>+|--)[ \t]*")


def prose(text: str) -> str:
    """`text` as the sentence a reader sees: lowercased, comment leaders and emphasis marks dropped,
    every run of whitespace — line breaks included — one space."""
    text = _LINE_LEADER.sub("", text.lower())
    return " ".join(text.replace("*", "").replace("`", "").split())


def tracked_files(root: pathlib.Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True)
    if out.returncode != 0:
        return []
    return [p for p in out.stdout.decode("utf-8", "replace").split("\0") if p]


def check(root: pathlib.Path) -> tuple[list[str], bool]:
    problems = []
    for rel in REMOVED_PATHS:
        if (root / rel).exists():
            problems.append(f"{rel} exists — it was removed in T-130 and must stay removed")
    control_seen = False
    for rel in tracked_files(root):
        if pathlib.PurePosixPath(rel).suffix not in TEXT_EXT:
            continue
        path = root / rel
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # Tokens against the bytes as written; phrases against the same bytes as prose. A phrase
        # that matched the raw text still matches: `prose` only removes what a phrase never contains
        # (the gate's test holds every phrase to `prose(p) == p`).
        flat = prose(text)
        hits = [t for t in FORBIDDEN_TOKENS if t in text] + [
            f'"{p}"' for p in FORBIDDEN_PHRASES if p in flat]
        if rel == CONTROL and hits:
            control_seen = True
        if hits and not rel.startswith(EXEMPT_PREFIXES):
            problems.append(f"{rel} names {', '.join(hits)}")
    return problems, control_seen


def main(root: pathlib.Path | None = None) -> int:
    problems, control_seen = check(ROOT if root is None else root)
    if not control_seen:
        print("RED: the sweep never matched its control "
              f"({CONTROL}); it cannot have checked anything else either")
        return 1
    if problems:
        print("RED: an Owner-held-key ceremony is coming back. The Owner decided on 2026-08-09 (#78)")
        print("that the install mints trust and no person carries a key; see OWNER_ACTION_REQUIRED §0.")
        for p in problems:
            print(f"  - {p}")
        return 1
    print(f"GREEN: no Owner-key ceremony in the tree; {len(REMOVED_PATHS)} removed paths absent, "
          f"{len(FORBIDDEN_TOKENS)} tokens and {len(FORBIDDEN_PHRASES)} phrases absent outside "
          "history; control matched")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
