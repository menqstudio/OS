#!/usr/bin/env python3
"""Every repeated fact equals its one source — `sync_facts.py --check`, as a gate.

`tools/sync_facts.py` keeps the facts declared in `config/doc-facts.json` equal across the
documents that repeat them. Its `--write` mode is a tool; its `--check` mode is a verdict, and a
verdict nothing runs is a habit. The argument-free gate loop and `check_push_ready.py` run every
`tools/check_*.py`, so this file is how they run it without knowing it exists.

The finding behind it (eleventh audit round, 2026-10-09): the standing round was changed by hand
in nine files, and `config/current_state.json` still said NINTH in two fields, two rounds stale.

Run:  python3 tools/check_facts.py          RED?  python3 tools/sync_facts.py --write
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import sync_facts  # noqa: E402

if __name__ == "__main__":
    sys.exit(sync_facts.main(["--check", *sys.argv[1:]]))
