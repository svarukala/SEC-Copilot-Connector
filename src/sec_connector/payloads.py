"""Canonical external-item serialization shared by transport and sync state."""

import hashlib
import json


def serialize_item(payload: dict) -> bytes:
    return json.dumps(
        {key: value for key, value in payload.items() if key != "id"},
        ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False,
    ).encode("utf-8")


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(serialize_item(payload)).hexdigest()
