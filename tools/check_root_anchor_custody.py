#!/usr/bin/env python3
"""The production trust anchors' private halves are not in this tree. Checked, not asserted.

Every guarantee in this repository that ends in `trusted_verified` rests on one fact: the private half
of the root public key compiled into `tcb.rs` exists only on the Owner's offline media. `tcb.rs` says so
in a comment. A comment is not evidence, and the failure mode is not hypothetical — a seed pasted into a
fixture, a test helper, a runbook snippet or a JSON sample would hand the whole trust chain to anyone
with a clone, and nothing in the tree would notice.

So the arithmetic is done: every 32-byte hex literal in every tracked text file is treated as an Ed25519
seed, its public half derived, and compared against each declared anchor.

FIVE RULES, and the fourth is the one that makes the other four mean anything:

  1. Each `tcb.rs` declares both anchors -- a production one and a demonstration one.
  2. The two anchors in a file are DIFFERENT keys. If they were the same, rule 3 would be checking the
     fixture anchor and passing while the production private sat in the open.
  3. No literal in the tree derives a PRODUCTION anchor.
  4. At least one literal DOES derive each DEMONSTRATION anchor. This is the CONTRAST. A sweep that
     silently matched nothing -- a changed literal format, a broken regex, a file-walk that reads no
     files -- would satisfy rule 3 vacuously and report the strongest possible result while measuring
     nothing. The demonstration seed is known to be in the tree by design, so it is the control: if the
     sweep cannot find the seed that IS there, it has not established anything about the one that
     must not be.
  5. Every `tcb.rs` pins the SAME production anchor. Two different production roots across the Linux
     broker and the Windows kit would mean the Owner's single offline root can provision one of them
     and never the other, and the one it cannot provision would be undeployable without anyone saying so.

FAIL-CLOSED: without `cryptography` this gate cannot do the arithmetic, and it exits non-zero saying so
rather than passing. A check that reports success when it could not run is the defect this repository is
named for finding.

Usage:  python tools/check_root_anchor_custody.py [repo-root]
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else pathlib.Path(
    __file__).resolve().parents[1]

#: Where an anchor is declared. Every file matching this must declare both constants.
TCB_FILES = (
    "apps/desktop/src-tauri/broker/src/tcb.rs",
    "apps/desktop/src-tauri/win-live/src/tcb.rs",
)

PRODUCTION_CONST = "ROOT_PUBLIC_KEY_HEX"
DEMONSTRATION_CONST = "DEMO_ROOT_PUBLIC_KEY_HEX"

#: 64 lowercase hex, delimited so a 128-hex blob is not read as two seeds.
HEX32 = re.compile(r"(?<![0-9a-fA-F])([0-9a-f]{64})(?![0-9a-fA-F])")

#: Text the sweep reads. A binary is not where a seed gets pasted by accident, and decoding every
#: tracked byte would make this gate slow enough to be switched off.
SWEPT_EXT = {
    ".rs", ".py", ".ts", ".tsx", ".js", ".json", ".md", ".yml", ".yaml", ".toml", ".sql",
    ".sh", ".ps1", ".txt", ".cfg", ".ini", ".env", ".html", ".css", ".lock",
}


def tracked_files(root: pathlib.Path) -> list[str] | str:
    """Every tracked path, from git. A string return is the reason this could not be established."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
    except (subprocess.SubprocessError, OSError) as exc:
        return f"git ls-files failed ({exc}); the sweep cannot be told what is in this tree"
    names = [n for n in out.stdout.decode("utf-8", "replace").split("\0") if n]
    if not names:
        return "git ls-files returned nothing; a sweep over no files proves nothing"
    return names


def declared_anchor(text: str, const: str) -> str | None:
    """The hex value of `pub const <const>: &str = "..."` , across one or two lines."""
    m = re.search(
        r"pub\s+const\s+" + re.escape(const) + r"\s*:\s*&str\s*=\s*\n?\s*\"([0-9a-f]{64})\"", text)
    return m.group(1) if m else None


def main() -> int:
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        print("RED: cryptography is not importable, so this gate cannot derive a public key from a")
        print("     seed. It refuses rather than reporting a custody property it did not measure.")
        return 2

    problems: list[str] = []

    # ---- rules 1, 2, 5: what each tcb.rs declares -------------------------------------------------
    production: dict[str, str] = {}
    demonstration: dict[str, str] = {}
    for rel in TCB_FILES:
        path = ROOT / rel
        if not path.is_file():
            problems.append(f"{rel}: absent, but this gate exists because it declares a trust anchor")
            continue
        text = path.read_text(encoding="utf-8")
        prod = declared_anchor(text, PRODUCTION_CONST)
        demo = declared_anchor(text, DEMONSTRATION_CONST)
        if prod is None:
            problems.append(f"{rel}: no `pub const {PRODUCTION_CONST}` with a 64-hex value")
        if demo is None:
            problems.append(f"{rel}: no `pub const {DEMONSTRATION_CONST}` with a 64-hex value")
        if prod and demo:
            if prod == demo:
                problems.append(
                    f"{rel}: the production and demonstration anchors are the SAME key ({prod[:12]}...) "
                    f"— then a demonstration private IS a production private, and rule 3 below would "
                    f"be checking the fixture")
            production[rel] = prod
            demonstration[rel] = demo

    distinct = set(production.values())
    if len(distinct) > 1:
        problems.append(
            "the tcb files pin DIFFERENT production anchors — "
            + "; ".join(f"{r} -> {v[:12]}..." for r, v in sorted(production.items()))
            + ". The Owner holds one offline root, so one of these is undeployable")

    if not production:
        for line in ["RED: root anchor custody could not be established", ""]:
            print(line)
        for p in problems:
            print(f"  - {p}")
        return 1

    # ---- the sweep --------------------------------------------------------------------------------
    names = tracked_files(ROOT)
    if isinstance(names, str):
        print("RED: root anchor custody could not be established\n")
        print(f"  - {names}")
        return 1

    wanted = {v: ("production", r) for r, v in production.items()}
    for r, v in demonstration.items():
        wanted.setdefault(v, ("demonstration", r))

    seen: dict[str, tuple[str, int]] = {}   # public hex -> (file, line) of the first seed found
    swept = literals = 0
    for name in names:
        path = ROOT / name
        if path.suffix.lower() not in SWEPT_EXT or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        swept += 1
        for n, line in enumerate(text.splitlines(), 1):
            for literal in HEX32.findall(line):
                literals += 1
                try:
                    pub = Ed25519PrivateKey.from_private_bytes(
                        bytes.fromhex(literal)).public_key().public_bytes_raw().hex()
                except (ValueError, TypeError):
                    continue
                if pub in wanted and pub not in seen:
                    seen[pub] = (name, n)

    # ---- rule 3: no production private anywhere ---------------------------------------------------
    for rel, pub in sorted(production.items()):
        if pub in seen:
            where, n = seen[pub]
            problems.append(
                f"{where}:{n} holds a seed whose public half IS the PRODUCTION anchor pinned by {rel}. "
                f"The private root is in this repository; every `trusted_verified` it can produce is "
                f"forgeable by anyone with a clone. Rotate the root and re-pin, do not delete the line")

    # ---- rule 4: the contrast -- the demonstration seed must be found -----------------------------
    for rel, pub in sorted(demonstration.items()):
        if pub not in seen:
            problems.append(
                f"{rel}: the DEMONSTRATION anchor's seed was NOT found by the sweep, and it is in this "
                f"tree by design. So the sweep did not establish the production property either — it "
                f"read {swept} files and {literals} literals and matched nothing it was supposed to")

    if problems:
        print("RED: root anchor custody could not be established\n")
        for p in problems:
            print(f"  - {p}")
        print("\nThe production anchor's private half belongs on the Owner's offline media and nowhere")
        print("else. This gate does the arithmetic instead of trusting the comment that says so.")
        return 1

    print(f"GREEN: root anchor custody holds — {len(distinct)} production anchor "
          f"({next(iter(distinct))[:12]}...) pinned by {len(production)} tcb file(s), its private half "
          f"derivable from no literal in this tree; {len(demonstration)} demonstration anchor(s) found "
          f"by the same sweep, which is what proves the sweep works. "
          f"{literals:,} 32-byte literals across {swept:,} text files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
