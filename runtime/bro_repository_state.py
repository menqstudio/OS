from __future__ import annotations

import hashlib
import json
import os
import pathlib
import subprocess
from dataclasses import dataclass
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]


class RepositoryStateError(ValueError):
    pass


@dataclass(frozen=True)
class RepositoryState:
    root: