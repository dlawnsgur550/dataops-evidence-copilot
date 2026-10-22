"""Safe metadata and redacted review snapshots. Never retain malformed model text."""
from __future__ import annotations

import json
import re

from .artifact_store import redact


def sanitized(value):
    if isinstance(value, dict):
        return {k: sanitized(v) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitized(v) for v in value]
    if not isinstance(value, str):
        return value
    text = redact(value)
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", text)
    return re.sub(r"/Users/[^\s\"']+", "[LOCAL_PATH]", text)


def validation_locations(exc, allowed_fields):
    # Extra-field locations can themselves contain provider data/secrets.
    rows = []
    for error in exc.errors(include_input=False, include_context=False)[:8]:
        loc = [x if isinstance(x, int) or x in allowed_fields else "[FIELD]" for x in error['loc']]
        rows.append({'location': loc, 'type': error['type']})
    return rows
