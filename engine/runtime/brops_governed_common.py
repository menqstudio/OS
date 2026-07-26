"""Shared primitives for the additive Wave 3b-1B governed-turn protocol family.

This module deliberately does not modify the frozen Wave 3a / 3b-1A contracts.  It
contains only the v1B object-JCS configuration formula, bounded diagnostics and
strict wire helpers used by the challenge authority, sidecar and supervisor.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
from typing import Any, Mapping

from bro_signature import canonical_bytes

PENDING_TTL_MS = 30_000
CHALLENGE_TTL_MS = 30_000
AUTHORITY_REPLAY_WINDOW_MS = 30_000
ISSUED_RETENTION_MS = CHALLENGE_TTL_MS + AUTHORITY_REPLAY_WINDOW_MS
MAX_AUTHORITY_ATTEMPTS = 3
MAX_CONCURRENT_GOVERNED_TURNS = 2
MAX_ISSUED_ROWS_PER_INSTALL = 8
MAX_ISSUED_BYTES_PER_INSTALL = 8 * 8_192
PENDING_SWEEP_INTERVAL_MS = 60_000
AUTHORITY_CHANNEL_FRAME_BYTES = 8_192
AUTHORITY_REQUEST_FRAME_BYTES = 4_096
AUTHORITY_ATTEMPT_TIMEOUT_MS = 2_000
AUTHORITY_RETRY_BACKOFF_MS = 1_000
MAX_DIAGNOSTIC_BYTES = 256
MAX_SYSTEM_BYTES = 262_144
MAX_MESSAGE_BYTES = 1_048_576
MAX_CONVERSATION_BYTES = 8_388_608
MAX_GENERATION_CONFIG_BYTES = 65_536
MAX_OUTPUT_BYTES = 8_388_608
STAGING_CHUNK_BYTES = 184_320
MAX_STAGING_CHUNKS = 46
OUTPUT_STREAM_TTL_MS = 360_000
OUTPUT_STREAM_RETENTION_MS = 360_000
# §4.10(f) per-install output-stream quota. A completing turn's stream is ALWAYS created;
# on breach the supervisor FIFO-evicts oldest present rows (by created_at_ms) until both the
# row-count and byte bounds hold. 64 rows x MAX_OUTPUT_BYTES (8 MiB) == 512 MiB byte ceiling.
MAX_OUTPUT_STREAM_ROWS_PER_INSTALL = 64
MAX_OUTPUT_STREAM_BYTES_PER_INSTALL = 512 * 1024 * 1024
LEASE_DURATION_MS = 210_000
EXECUTION_TIMEOUT_MS = 120_000
MIN_LAUNCH_REMAINING_MS = 180_000
MAX_FUTURE_SKEW_MS = 60_000

DEFAULT_GENERATION_CONFIG = {
    "engine_id": "brops.governed-engine.sidecar.v1",
    "model": "claude-sonnet-5",
    "max_output_tokens": "4096",
    "temperature": "0.00",
    "top_p": "1.00",
}
PINNED_GENERATION_CONFIG_SHA256 = (
    "732b58634d0a83e9b7fdf1ca69db78df145bd9dd79ac8922fed3e79cf5faab22"
)

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_ENGINE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_MODEL = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_DECIMAL_INT = re.compile(r"^[1-9][0-9]{0,6}$")
_TEMP = re.compile(r"^[0-2]\.[0-9]{2}$")
_TOP_P = re.compile(r"^[01]\.[0-9]{2}$")
_B64URL = re.compile(r"^[A-Za-z0-9_-]*$")

GENERATION_CONFIG_KEYS = frozenset(DEFAULT_GENERATION_CONFIG)


class GovernedProtocolError(ValueError):
    """Strict validation failure.  Callers must fail closed."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def b64url_decode(value: str, *, max_bytes: int | None = None) -> bytes:
    if not isinstance(value, str) or not _B64URL.fullmatch(value):
        raise GovernedProtocolError("malformed base64url")
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except Exception as exc:  # noqa: BLE001
        raise GovernedProtocolError("malformed base64url") from exc
    if b64url_encode(raw) != value:
        raise GovernedProtocolError("noncanonical base64url")
    if max_bytes is not None and len(raw) > max_bytes:
        raise GovernedProtocolError("decoded value exceeds bound")
    return raw


def require_exact_keys(obj: Mapping[str, Any], keys: set[str] | frozenset[str], where: str) -> None:
    if not isinstance(obj, Mapping) or set(obj) != set(keys):
        raise GovernedProtocolError(f"{where} has wrong key set")


def require_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 128:
        raise GovernedProtocolError(f"{field} is invalid")
    return value


def require_hex64(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        raise GovernedProtocolError(f"{field} is not lowercase 64-hex")
    return value


def require_ms(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1_000_000_000_000:
        raise GovernedProtocolError(f"{field} is not canonical epoch-ms")
    return value


def validate_generation_config(value: Mapping[str, Any]) -> dict[str, str]:
    require_exact_keys(value, GENERATION_CONFIG_KEYS, "generation_config")
    out: dict[str, str] = {}
    for key in GENERATION_CONFIG_KEYS:
        item = value.get(key)
        if not isinstance(item, str):
            raise GovernedProtocolError(f"generation_config.{key} must be a string")
        out[key] = item
    if not _ENGINE_ID.fullmatch(out["engine_id"]):
        raise GovernedProtocolError("generation_config.engine_id invalid")
    if not _MODEL.fullmatch(out["model"]):
        raise GovernedProtocolError("generation_config.model invalid")
    if not _DECIMAL_INT.fullmatch(out["max_output_tokens"]):
        raise GovernedProtocolError("generation_config.max_output_tokens invalid")
    if not 1 <= int(out["max_output_tokens"]) <= 1_048_576:
        raise GovernedProtocolError("generation_config.max_output_tokens out of range")
    if not _TEMP.fullmatch(out["temperature"]):
        raise GovernedProtocolError("generation_config.temperature invalid")
    temp_hundredths = int(out["temperature"][0]) * 100 + int(out["temperature"][2:])
    if not 0 <= temp_hundredths <= 200:
        raise GovernedProtocolError("generation_config.temperature out of range")
    if not _TOP_P.fullmatch(out["top_p"]):
        raise GovernedProtocolError("generation_config.top_p invalid")
    top_hundredths = int(out["top_p"][0]) * 100 + int(out["top_p"][2:])
    if not 0 <= top_hundredths <= 100:
        raise GovernedProtocolError("generation_config.top_p out of range")
    encoded = canonical_bytes(out)
    if len(encoded) > MAX_GENERATION_CONFIG_BYTES:
        raise GovernedProtocolError("generation_config exceeds bound")
    return out


def governed_generation_config_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_bytes(validate_generation_config(value))


def generation_config_sha256(value: Mapping[str, Any]) -> str:
    return sha256_hex(governed_generation_config_bytes(value))


def model_profile_id(config_sha256: str) -> str:
    require_hex64(config_sha256, "generation_config_sha256")
    return "cfg-sha256:" + config_sha256


def history_bytes(history: Any) -> bytes:
    if not isinstance(history, list) or len(history) > 1_000:
        raise GovernedProtocolError("history invalid")
    normalized: list[dict[str, str]] = []
    for item in history:
        require_exact_keys(item, {"role", "content"}, "history item")
        role = item.get("role")
        content = item.get("content")
        if role not in {"user", "assistant", "system"} or not isinstance(content, str):
            raise GovernedProtocolError("history item invalid")
        if len(content.encode("utf-8")) > MAX_MESSAGE_BYTES:
            raise GovernedProtocolError("history message exceeds bound")
        normalized.append({"content": content, "role": role})
    encoded = canonical_bytes(normalized)
    if len(encoded) > MAX_CONVERSATION_BYTES:
        raise GovernedProtocolError("history exceeds bound")
    return encoded


def system_bytes(system: Any) -> bytes:
    if not isinstance(system, str):
        raise GovernedProtocolError("system must be a string")
    encoded = system.encode("utf-8")
    if len(encoded) > MAX_SYSTEM_BYTES:
        raise GovernedProtocolError("system exceeds bound")
    return encoded


def request_payload(*, workspace_id: str, install_id: str, request_nonce: str,
                    system_sha256: str, history_sha256: str,
                    generation_config_sha256: str, requested_at_ms: int) -> dict[str, str]:
    # Mirrors the merged brops.request.v1 flat-string formula.  requested_at is a
    # decimal-ms string because the frozen receipt protocol represents it as text.
    return {
        "protocol": "brops.request.v1",
        "workspace_id": require_id(workspace_id, "workspace_id"),
        "install_id": require_id(install_id, "install_id"),
        "request_nonce": require_id(request_nonce, "request_nonce"),
        "system_sha256": require_hex64(system_sha256, "system_sha256"),
        "history_sha256": require_hex64(history_sha256, "history_sha256"),
        "generation_config_sha256": require_hex64(
            generation_config_sha256, "generation_config_sha256"
        ),
        "requested_at": str(require_ms(requested_at_ms, "requested_at_ms")),
    }


def request_sha256(**kwargs: Any) -> str:
    return sha256_hex(canonical_bytes(request_payload(**kwargs)))


# §4.10(h) LOCKED: the diagnostic `stage` is exactly the five sidecar-driven hop
# stages of the one-shot submit subprocess.  Every value maps to
# governed_internal_refusal:{stage}:{reason} on the desktop.  There is NO
# "authority"/"supervisor"/"transport" stage — Carrier 2 (authority) is backend-direct,
# and transport/local failures use transport_failure() (rule-4 catch-all) instead.
DIAGNOSTIC_STAGES = (
    "governed-turn-open",
    "staging-open",
    "staging-chunk",
    "staging-final",
    "evidence-request",
)

# A sidecar transport/local failure is emitted under a DISTINCT top-level protocol so the
# desktop §4.10(h) rule-4 catch-all classifies it as governed_transport_failure — never an
# internal refusal, never a signed verdict.
TRANSPORT_FAILURE_PROTOCOL = "bridge.governed-turn-transport-failure.v1"


def transport_failure(detail: str) -> dict[str, str]:
    """Signature-free sidecar transport/local-failure frame, capped to MAX_DIAGNOSTIC_BYTES."""
    text = str(detail).replace("\x00", "")
    while text:
        obj = {"protocol": TRANSPORT_FAILURE_PROTOCOL, "detail": text}
        if len(canonical_bytes(obj)) <= MAX_DIAGNOSTIC_BYTES:
            return obj
        text = text[:-1]
    return {"protocol": TRANSPORT_FAILURE_PROTOCOL, "detail": "transport"}


def bounded_diagnostic(stage: str, upstream_reason: str) -> dict[str, str]:
    """Return the exact signature-free §4.10(h) internal-refusal diagnostic, ≤256 UTF-8 bytes.

    `stage` MUST be one of the five DIAGNOSTIC_STAGES (the closed routing discriminator of
    the §4.10(h) table).  A caller passing any other value is degraded to a transport_failure
    frame (fail-safe: the desktop still records exactly one Block, attributed to transport).
    The reason is truncated safely so serialization always stays within MAX_DIAGNOSTIC_BYTES.
    """
    if stage not in DIAGNOSTIC_STAGES:
        return transport_failure(str(upstream_reason))
    reason = str(upstream_reason).replace("\x00", "")
    while reason:
        obj = {
            "protocol": "bridge.governed-turn-diagnostic.v1",
            "stage": stage,
            "upstream_reason": reason,
        }
        if len(canonical_bytes(obj)) <= MAX_DIAGNOSTIC_BYTES:
            return obj
        reason = reason[:-1]
    return {
        "protocol": "bridge.governed-turn-diagnostic.v1",
        "stage": stage,
        "upstream_reason": "blocked",
    }


# Guard the frozen default hash at import time.  A drift is a build failure, not a
# value silently reinterpreted by an allow-list.
if generation_config_sha256(DEFAULT_GENERATION_CONFIG) != PINNED_GENERATION_CONFIG_SHA256:
    raise RuntimeError("pinned governed generation config hash drift")
