"""Declare the single-principal deployment posture the way a deployment must now declare it.

A test process IS a deployment with no principal separation: it owns the pins, floors and
stores that police it, which every custody rule in ``bro_custody`` refuses by default. Saying
so explicitly is right, and it is what these fixtures have always done.

What changed is HOW it may be said. ``BRO_OPERATOR_ROOT_PIN_SELF_OWNED=acknowledged`` used to
be an ungated read of the ambient environment, while the two sibling anchors in
``bro_signature`` were both gated on the CI system having marked the environment
(``BRO_ENV=ci``). Against the adversary the pin exists to stop — one who can set the verifying
process's environment, which is exactly what the original F-06 attack already needed — the
acknowledgement cost one extra ``export``. It is now honoured only under ``BRO_ENV=ci``, or
through a FILE the deployment wrote, which is the production form.

Fixtures use the FILE form deliberately, rather than adding ``BRO_ENV=ci``: a developer
workstation running the suite is not CI, and a fixture that claims to be would be pinning the
gate open rather than declaring a posture. Every helper here writes a real file and hands the
path to the runtime, so what the tests exercise is the path a real single-principal deployment
takes.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import unittest.mock

if str(pathlib.Path(__file__).resolve().parents[1] / "runtime") not in sys.path:
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "runtime"))

from bro_custody import ENV_PIN_SELF_OWNED_ACK_FILE, PIN_SELF_OWNED_ACK_VALUE  # noqa: E402


def write_declaration(directory) -> str:
    """Write the acknowledgement file into ``directory`` and return its path."""
    path = pathlib.Path(directory) / "self-owned-acknowledgement"
    path.write_text(PIN_SELF_OWNED_ACK_VALUE, encoding="utf-8")
    return str(path)


def env_declaring(directory) -> dict:
    """The environment fragment a single-principal deployment sets."""
    return {ENV_PIN_SELF_OWNED_ACK_FILE: write_declaration(directory)}


def patch(directory) -> unittest.mock._patch_dict:
    """An unstarted ``patch.dict`` declaring the posture through the file form."""
    return unittest.mock.patch.dict(os.environ, env_declaring(directory))


def declare_for_process() -> str:
    """Declare the posture for the whole process, for a module that must do it at import.

    Returns the path so a caller can assert on it. The file lands in a temp directory that
    outlives the call deliberately: the declaration has to still be readable whenever a custody
    rule asks, which is at an arbitrary later point in the run.
    """
    existing = os.environ.get(ENV_PIN_SELF_OWNED_ACK_FILE)
    if existing:
        return existing
    path = write_declaration(tempfile.mkdtemp(prefix="bro-self-owned-ack-"))
    os.environ[ENV_PIN_SELF_OWNED_ACK_FILE] = path
    return path


#: Every name a declaration can arrive through. A test that needs the acknowledgement OFF
#: must clear ALL of them: a suite that declares the posture at import time leaks it into
#: every other suite in a single discovery process, and a `pop` that knows only one name
#: would leave the rules it is measuring silently short-circuited.
NAMES = ("BRO_OPERATOR_ROOT_PIN_SELF_OWNED", ENV_PIN_SELF_OWNED_ACK_FILE)


def suppress() -> unittest.mock._patch_dict:
    """An unstarted ``patch.dict`` under which no acknowledgement is declared."""
    patcher = unittest.mock.patch.dict(os.environ, {}, clear=False)
    original_start = patcher.start

    def start():
        result = original_start()
        for name in NAMES:
            os.environ.pop(name, None)
        return result

    patcher.start = start
    return patcher
