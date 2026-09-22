#!/usr/bin/env python3
"""Deterministic text PII adapter for the ids-plugin.v1 protocol."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b"),
    "phone": re.compile(r"(?<!\d)(?:\+?\d[\d ()-]{7,}\d)(?!\d)"),
    "card": re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)"),
    "secret": re.compile(r"\b(?:api[_ -]?key|secret|token|password)\s*[:=]\s*\S+", re.I),
}


def _text(payload: dict[str, Any]) -> str:
    value = str(payload.get("text", ""))
    if not value and payload.get("text_path"):
        value = Path(str(payload["text_path"])).read_text(encoding="utf-8")
    return value


def handle(payload: dict[str, Any]) -> dict[str, Any]:
    text = _text(payload)
    hits = [(kind, match) for kind, pattern in PATTERNS.items() for match in pattern.finditer(text)]
    kinds = sorted({kind for kind, _ in hits})
    evidence = ", ".join(f"{kind}@{match.start()}" for kind, match in hits[:10])
    return {"pii": bool(hits), "types": kinds, "evidence": evidence}


for line in sys.stdin:
    try:
        request = json.loads(line)
        if request.get("protocol") != "ids-plugin.v1":
            raise ValueError("plugin protocol must be ids-plugin.v1")
        payload = request.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("payload must be an object")
        print(json.dumps({"type": "result", "output": handle(payload)}), flush=True)
    except Exception as exc:
        print(json.dumps({"type": "error", "error": str(exc)}), flush=True)
