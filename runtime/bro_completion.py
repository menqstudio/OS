from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time
from typing import Any

from bro_authority import AuthorityError, validate_verifier_assignment
from bro_contracts import canonical_json_sha256, validate_task_contract
from bro_repository_state import resolve_state
from bro_security import SecurityError, verify_signed_document

ROOT = pathlib.Path