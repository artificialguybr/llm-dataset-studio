"""Embeddings de texto: sentence-transformers plugável; cache por (sha256, model, version).

Regra: nunca assumir que embeddings de modelos diferentes são comparáveis.
Se sentence-transformers não estiver instalado, provider fica 'unavailable'
e a busca semântica responde 501 — sem resultado falso.
"""
import json
from pathlib import Path
from typing import Any, Optional

from ..config import get_settings

DETECTOR_VERSION = "st-1"

try:
    import numpy as np
    from sentence_transformers import SentenceTransformer
    _AVAILABLE = True
except ImportError:
    _AVAILABLE = False

_model_cache: dict[tuple, Any] = {}       # (model_name, device) -> SentenceTransformer
_model_last_used: dict[tuple, float] = {}
_vector_cache: dict[tuple, Any] = {}       # (sha256, model, ver) -> vec — com teto
_VECTOR_CACHE_MAX = 20000                   # ~384-dim float32: ~30 MB; além disso, disco
_UNLOAD_AFTER_S = 600                     # 10 min idle -> unload + empty_cache


def _get_np():
    import numpy as np
    return np


def is_available() -> bool:
    return _AVAILABLE


def _device() -> str:
    import torch
    from ..config import get_settings
    d = get_settings().embeddings_device
    if d:
        return d
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _load_model(model_name: str):
    import time
    key = (model_name, _device())
    now = time.monotonic()
    _model_last_used[key] = now
    if key not in _model_cache:
        _model_cache[key] = SentenceTransformer(model_name, device=key[1])
    _unload_idle(now)
    return _model_cache[key]


def _unload_idle(now: float) -> None:
    """Despeja modelos parados há mais de _UNLOAD_AFTER_S — RAM/VRAM voltam pro sistema."""
    stale = [k for k, t in _model_last_used.items()
             if now - t > _UNLOAD_AFTER_S and k in _model_cache]
    for k in stale:
        _model_cache.pop(k, None)
        _model_last_used.pop(k, None)
    import torch
    if stale and torch.cuda.is_available():
        torch.cuda.empty_cache()


def _vector_path(text_id: str, model_name: str) -> Path:
    s = get_settings()
    d = s.embeddings_dir / model_name.replace("/", "_")
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{text_id}.npy"


def embed_text(text: str, model_name: str = "sentence-transformers/all-MiniLM-L6-v2",
               content_hash: str = "") -> Optional[Any]:
    """Embed de texto. Cache por (hash de conteúdo, modelo)."""
    np = _get_np()
    if not _AVAILABLE:
        return None
    model = _load_model(model_name)
    cache_key = (content_hash, model_name, DETECTOR_VERSION)
    if cache_key not in _vector_cache:
        if len(_vector_cache) >= _VECTOR_CACHE_MAX:
            _vector_cache.pop(next(iter(_vector_cache)))
        vec = model.encode(text, convert_to_numpy=True, normalize_embeddings=True).astype("float32")
        _vector_cache[cache_key] = vec
        np.save(_vector_path(content_hash or "unknown", model_name), vec)
    return _vector_cache[cache_key]


def embed_texts(texts: list[str], model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> list[Any]:
    """Batch embed multiple texts."""
    np = _get_np()
    if not _AVAILABLE:
        return [None] * len(texts)
    model = _load_model(model_name)
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True).astype("float32")
    return list(vecs)


def load_vectors(text_ids: list[str], model_name: str = "sentence-transformers/all-MiniLM-L6-v2") -> dict[str, Any]:
    """Carrega vetores persistidos; retorna {text_id: vector}."""
    np = _get_np()
    out: dict[str, Any] = {}
    for tid in text_ids:
        p = _vector_path(tid, model_name)
        if p.exists():
            out[tid] = np.load(p)
    return out