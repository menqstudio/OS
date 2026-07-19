"""Test helper: supply the external operator-root pin the runtime now requires.

Security remediation blocker 2 pins the operator-root public key OUTSIDE the
trusted-key registry (``BRO_OPERATOR_ROOT_PUBKEY`` for CI,
``BRO_OPERATOR_ROOT_PUBKEY_FILE`` for production), so ``load_trusted_keys`` and the
module verify paths refuse to run without it. Tests build an ephemeral operator key
per fixture; this helper exports that key as the CI pin for the lifetime of the
test, standing in for the offline operator who sets it in production.

Not a test module (no ``test_`` prefix), so unittest discovery ignores it. The env
var name is hardcoded to avoid any import-order dependency on ``bro_signature``.
"""
import os
from unittest.mock import patch

ENV_PIN = "BRO_OPERATOR_ROOT_PUBKEY"


def use_operator_pin(test_case, public_key):
    """Set the operator-root pin for the lifetime of ``test_case`` (auto-cleaned)."""
    patcher = patch.dict(os.environ, {ENV_PIN: public_key})
    patcher.start()
    test_case.addCleanup(patcher.stop)
