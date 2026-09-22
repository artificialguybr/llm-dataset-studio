"""Shared path helpers for item URIs.

source_uri schemes: 'local:', 'imported:', 'retried:', 'file:' prefix a filesystem
path. A bare path (including a Windows drive 'C:\\...') is used as-is.
"""
from pathlib import Path
from ..models import TextItem


_SCHEMES = ("local:", "imported:", "retried:", "file:")


def item_path(it: TextItem) -> Path:
    uri = it.source_uri
    for scheme in _SCHEMES:
        if uri.startswith(scheme):
            uri = uri[len(scheme):]
            break
    path = Path(uri)
    if not path.is_file() and ":/" in uri:
        # Repair legacy imports that concatenated an absolute path after a colon.
        candidate = Path("/" + uri.rsplit(":/", 1)[-1].lstrip("/"))
        if candidate.is_file():
            path = candidate
    return path.resolve()


def item_text(it: TextItem) -> str | None:
    """Read the text content for an item."""
    from ..config import get_settings
    s = get_settings()
    path = s.data_dir / it.storage_uri if it.storage_uri else None
    if path and path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return None