#!/usr/bin/env python3
"""Local text model adapter for the ids-plugin.v1 protocol."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_CACHE: dict[tuple[str, str], Any] = {}


def _error(message: str) -> None:
    print(json.dumps({"type": "error", "error": message}), flush=True)


def _model_dir(model_path: str) -> str:
    path = Path(model_path).expanduser()
    return str(path if path.is_dir() else path.parent)


def _embedding(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError("install the LLM ML extra: uv sync --extra ml") from exc
    model_id = str(payload.get("model_id", ""))
    model_path = _model_dir(str(payload.get("model_path", "")))
    key = (model_id, model_path)
    model = _CACHE.get(key)
    if model is None:
        model = SentenceTransformer(model_path or model_id)
        _CACHE[key] = model
    text = str(payload.get("text", ""))
    if not text and payload.get("text_path"):
        text = Path(str(payload["text_path"])).read_text(encoding="utf-8")
    vector = model.encode(text, normalize_embeddings=True).tolist()
    return {"embedding": vector}


def _classification(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise RuntimeError("install transformers for the text-local plugin") from exc
    model_id = str(payload.get("model_id", ""))
    model_path = _model_dir(str(payload.get("model_path", "")))
    key = ("classification", model_path or model_id)
    classifier = _CACHE.get(key)
    if classifier is None:
        classifier = pipeline("text-classification", model=model_path or model_id, tokenizer=model_path or model_id)
        _CACHE[key] = classifier
    text = str(payload.get("text", ""))
    if not text and payload.get("text_path"):
        text = Path(str(payload["text_path"])).read_text(encoding="utf-8")
    result = classifier(text[:8192], top_k=3)
    rows = result if isinstance(result, list) else [result]
    labels = [{"category": str(row.get("label", "other")), "confidence": float(row.get("score", 0.0))} for row in rows]
    return {"labels": labels}


def _caption(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        from transformers import pipeline
    except ImportError as exc:
        raise RuntimeError("install transformers for the text-local plugin") from exc
    model_id = str(payload.get("model_id", ""))
    model_path = _model_dir(str(payload.get("model_path", "")))
    key = ("generation", model_path or model_id)
    generator = _CACHE.get(key)
    if generator is None:
        generator = pipeline("text-generation", model=model_path or model_id, tokenizer=model_path or model_id)
        _CACHE[key] = generator
    text = str(payload.get("text", ""))
    if not text and payload.get("text_path"):
        text = Path(str(payload["text_path"])).read_text(encoding="utf-8")
    result = generator(text[:4096], max_new_tokens=128, do_sample=False)
    item = result[0] if isinstance(result, list) and result else {}
    return {"caption": str(item.get("generated_text", "")), "confidence": 0.5}


def handle(request: dict[str, Any]) -> dict[str, Any]:
    capability = str(request.get("capability", ""))
    payload = request.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    if capability == "embedding":
        return _embedding(payload)
    if capability == "preannotation":
        return _classification(payload)
    if capability == "captioning":
        return _caption(payload)
    raise ValueError(f"unsupported text-local capability: {capability}")


for line in sys.stdin:
    try:
        request = json.loads(line)
        if request.get("protocol") != "ids-plugin.v1":
            raise ValueError("plugin protocol must be ids-plugin.v1")
        print(json.dumps({"type": "result", "output": handle(request)}), flush=True)
    except Exception as exc:  # plugin boundary: return an actionable result to the host
        _error(str(exc))
