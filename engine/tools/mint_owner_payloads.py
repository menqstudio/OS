#!/usr/bin/env python3
"""Write the unsigned payloads for the three Owner artifacts, ready to hand to `broctl sign`.

This exists because the alternative is typing JSON with hand-computed Unix timestamps at a
terminal on an offline machine, which is where a wrong `expires_at_epoch` gets pasted and nobody
notices until a session refuses.

**It cannot sign anything, deliberately.** Signing needs the offline operator-root private key, and
a tool that offered to do both would invite running it on the box that serves — which is the one
place the key must never be. The output of this is an input to `broctl sign`, nothing more.

    python3 engine/tools/mint_owner_payloads.py \
        --key-id gev-operator-root-1 \
        --session-id s-2026-08-08-a \
        --task-id t-example.1 --head-sequence 5 \
        --hours 8 --out /media/usb/payloads

Then, per file:

    python3 engine/tools/broctl.py sign --key <offline private> \
        --artifact <type> --in <payload>.json --out <artifact>.signed.json

See `docs/OWNER_CEREMONY.md` for what each artifact does and `docs/DEBIAN_DEPLOYMENT.md` for the
machine setup it belongs to.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time

#: Beyond this an expiry stops being a session and becomes a standing grant. The conductor token is
#: judged against the WALL clock precisely so a caller who could move the system clock cannot
#: revive an expired one; a long window gives that protection nothing to protect.
MAX_REASONABLE_HOURS = 24


def build(args: argparse.Namespace) -> dict[str, dict]:
    expires = int(time.time()) + args.hours * 3600
    return {
        # O-3. Rotated per harness session: it authorises any command the conductor could already
        # reach, for as long as it is valid, so its value is the window and the window should be
        # short.
        "conductor-session": {
            "artifact_type": "conductor-session",
            "key_id": args.key_id,
            "session_id": args.session_id,
            "agent_id": "bro-000",
            "role": "bro",
            "expires_at_epoch": expires,
        },
        # O-5. One per task, and `head_sequence` must be the chain's REAL head — an anchor naming a
        # sequence the chain never reached is a rollback with a signature on it.
        "evidence-floor-anchor": {
            "artifact_type": "evidence-floor-anchor",
            "key_id": args.key_id,
            "task_id": args.task_id,
            "head_sequence": args.head_sequence,
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--key-id", required=True, help="the operator-root key id that will sign these")
    p.add_argument("--session-id", required=True, help="a fresh id for this harness session")
    p.add_argument("--task-id", required=True, help="the task the evidence floor anchor is for")
    p.add_argument("--head-sequence", type=int, required=True,
                   help="the chain's real head sequence for that task")
    p.add_argument("--hours", type=int, default=8, help="conductor session validity (default 8)")
    p.add_argument("--out", type=pathlib.Path, required=True, help="directory to write into")
    args = p.parse_args()

    if args.hours < 1:
        print("RED: --hours must be at least 1", file=sys.stderr)
        return 1
    if args.hours > MAX_REASONABLE_HOURS:
        # Refused rather than warned. A warning at a terminal during a ceremony is a line that
        # scrolls past, and the mistake it describes is invisible afterwards.
        print(f"RED: --hours {args.hours} exceeds {MAX_REASONABLE_HOURS}. A conductor session "
              "authorises any command the conductor could already reach for its whole life; past a "
              "day that is a standing grant wearing a session's name. Mint a new one instead.",
              file=sys.stderr)
        return 1
    if args.head_sequence < 1:
        print("RED: --head-sequence must be at least 1 (1 is a chain's first anchor)",
              file=sys.stderr)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    for artifact, payload in build(args).items():
        path = args.out / f"{artifact}.payload.json"
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    expires = build(args)["conductor-session"]["expires_at_epoch"]
    print(f"\nconductor session expires at {expires} "
          f"({time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(expires))} local)")
    print("\nNothing here is signed. Next, on the machine holding the offline root:")
    for artifact in build(args):
        print(f"  python3 engine/tools/broctl.py sign --key <offline private> \\\n"
              f"      --artifact {artifact} \\\n"
              f"      --in {args.out / f'{artifact}.payload.json'} \\\n"
              f"      --out {args.out / f'{artifact}.signed.json'}")
    print("\nThe control-room-command artifact (O-4) is NOT minted here: it binds one specific "
          "command_id/task_id/command, so it is written at the moment that command is issued "
          "rather than ahead of time. That is what makes it per-command rather than a session.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
