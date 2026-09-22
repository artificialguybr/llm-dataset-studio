"""Ingestão de textos: varre pastas/ZIPs, cria TextItems, hashes, stats, quality issues.

Idempotente: importação reexecutada pula arquivos já inventariados (por source_uri).
Falha por item não derruba o job; item fica ingest_status=error com mensagem.

Suporta: .txt, .jsonl, .parquet, .jsonl.gz, .csv → cada linha = um TextItem.
HuggingFace datasets são importados via import_hf (job separado).
"""
import hashlib
import gzip
import json
import os
import shutil
import zipfile
from datetime import timezone
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..analyzers import quality
from ..analyzers.dedup import sha256_file
from ..config import get_settings
from ..jobs import is_cancelled, update_progress
from ..models import Dataset, TextItem, TextIssue, Job

# Map of supported text extensions to mime types
TEXT_EXTENSIONS = {".txt", ".jsonl", ".json", ".csv", ".tsv", ".md", ".jsonl.gz", ".parquet"}


def _tokens_chardet(text: str) -> int:
    """Estimate token count: ~4 chars per token (rough heuristic)."""
    return len(text) // 4 if text else 0


def _normalize_text(text: str) -> str:
    """Normalize Unicode (NFC), strip HTML tags, collapse whitespace."""
    import re
    import unicodedata
    text = unicodedata.normalize("NFC", text)
    # Simple HTML tag strip
    text = re.sub(r"<[^>]+>", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _infer_language(text: str) -> str:
    """Very rough language detection: checks for common words in English vs Portuguese/Spanish."""
    import re
    words = set(re.findall(r"\b[a-zA-Z]+\b", text.lower()))
    # Minimal check: if more 'the' style words, English; else best guess
    en_words = {"the", "and", "is", "of", "to", "in", "a", "it", "that", "with", "for"}
    pt_words = {"o", "a", "e", "de", "que", "se", "para", "com", "não", "uma", "em"}
    es_words = {"el", "la", "de", "que", "y", "en", "un", "una", "los", "las"}
    en_count = len(words & en_words)
    pt_count = len(words & pt_words)
    es_count = len(words & es_words)
    if en_count >= pt_count and en_count >= es_count:
        return "en"
    if pt_count >= es_count:
        return "pt"
    return "es"


def _compute_stats(text: str) -> dict[str, Any]:
    """Compute text statistics."""
    lines = text.splitlines()
    line_lengths = [len(l) for l in lines] if lines else [0]
    return {
        "char_count": len(text),
        "word_count": len(text.split()),
        "line_count": len(lines),
        "max_line_length": max(line_lengths) if line_lengths else 0,
        "min_line_length": min(line_lengths) if line_lengths else 0,
        "has_html": "<" in text and ">" in text,
        "language": _infer_language(text),
    }


def _read_text_file(path: Path, limit_bytes: int = 10 * 1024 * 1024) -> str:
    """Read a text file, handling encoding and large files."""
    raw = path.read_bytes()[:limit_bytes]
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc, errors="strict")
        except (UnicodeDecodeError, ValueError):
            continue
    return raw.decode("utf-8", errors="replace")


def _register(session: Session, dataset_id: str, src: Path, relative: str,
              source_kind: str, content: str | None = None) -> TextItem:
    """Register a single text item in the dataset."""
    s = get_settings()
    ds = session.get(Dataset, dataset_id)
    if content is None:
        content = _read_text_file(src)
    stats = _compute_stats(content)
    item = TextItem(
        dataset_id=dataset_id,
        source_uri=f"{source_kind}:{src.resolve()}",
        original_filename=src.name,
        relative_path=relative,
        byte_size=src.stat().st_size,
        mime_type="text/plain",
        content_hash_sha256=sha256_file(src) if src.exists() else "",
        text_hash_sha256=hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest(),
        tokens=_tokens_chardet(content),
        token_estimator="character",
        language=stats["language"],
        char_count=stats["char_count"],
        word_count=stats["word_count"],
        line_count=stats["line_count"],
        max_line_length=stats["max_line_length"],
        min_line_length=stats["min_line_length"],
        has_html=stats["has_html"],
        license=ds.license if ds else "unknown",
        license_evidence_uri=ds.license_evidence_uri if ds else "",
        ingest_status="done",
    )

    # Detect Unicode normalization issues (if already in NFC, no issue)
    import unicodedata
    if content and unicodedata.normalize("NFC", content) != content:
        item.has_unicode_normalization_issues = True
    if content and any(c.isspace() for c in content[:100] if c in "\t\r"):
        item.has_whitespace_issues = True

    # Store the normalized text in storage_uri as a file
    dest_dir = s.raw_dir / dataset_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{item.id}.txt"
    dest.write_text(content, encoding="utf-8")
    item.storage_uri = str(dest.relative_to(s.data_dir))

    # Detect basic issues
    issues = []
    if stats["char_count"] < 10:
        issues.append(("too_short", 1.0, 10.0))
    if _tokens_chardet(content) > 4000:
        issues.append(("too_long", 1.0, 4000.0))

    session.add(item)
    session.flush()
    from ..analyzers.quality import DETECTOR_VERSION
    for issue_type, score, threshold in issues:
        session.add(TextIssue(
            text_id=item.id, dataset_id=dataset_id, issue_type=issue_type,
            score=score, threshold=threshold, detector_name="ingest-detectors",
            detector_version=DETECTOR_VERSION, evidence_json={"stat": issue_type},
        ))
    return item


def _looks_like_training_data(path: Path) -> bool:
    """True se o arquivo JSON/JSONL usa formatos de treino (SFT/DPO/traces)."""
    from .importers import is_conversation_record
    try:
        with (gzip.open if path.suffix == ".gz" else open)(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                if isinstance(rec, list):
                    rec = rec[0] if rec and isinstance(rec[0], dict) else {}
                if isinstance(rec, dict) and is_conversation_record(rec):
                    return True
                return False
    except Exception:  # noqa: BLE001 — arquivo inválido vira TextItem normal
        return False
    return False


def run_ingest(session: Session, job: Job) -> None:
    """Import text files from paths and zips; training-format files become structured records."""
    cfg = job.config_json
    dataset_id = job.dataset_id
    s = get_settings()

    processed = failed = pending = 0

    paths: list[Path] = ([Path(p) for p in cfg.get("paths", [])]
                         + [Path(p) for p in cfg.get("jsonls", [])])
    zips: list[Path] = [Path(p) for p in cfg.get("zips", [])]
    extract_roots: list[Path] = []

    for zp in zips:
        dest = s.derived_dir / dataset_id / f"zip-{zp.stem}"
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp) as zf:
            limit = 1 << 30  # 1 GiB total
            total = 0
            for info in zf.infolist():
                total += info.file_size
                if total > limit:
                    raise ValueError(f"zip {zp.name} exceeds the {limit}-byte limit")
                member = Path(info.filename)
                if member.is_absolute() or ".." in member.parts:
                    raise ValueError(f"malicious zip member: {info.filename}")
                target = dest / member
                if not target.exists():
                    zf.extract(info, target.parent)
            extract_roots.append(dest)

    all_files: list[tuple[Path, str, str]] = []  # (path, relative, source_kind)
    for root in paths + extract_roots:
        root = root.resolve()
        if root.is_file() and root.suffix.lower() in TEXT_EXTENSIONS:
            all_files.append((root, root.name, "local"))
        else:
            for f in sorted(root.rglob("*")):
                if f.is_file() and f.suffix.lower() in TEXT_EXTENSIONS:
                    all_files.append((f, str(f.relative_to(root)), str(root)))

    existing = {it.source_uri for it in session.exec(
        select(TextItem).where(TextItem.dataset_id == dataset_id)).all()}
    todo = [t for t in all_files if f"{t[2]}:{t[0]}" not in existing]

    # Conversation/training-format files go to the structured importer
    # instead of becoming one plain TextItem per file.
    from .importers import is_conversation_record, run_import_conversations
    conv_files: list[tuple[Path, str]] = []
    text_files: list[tuple[Path, str, str]] = []
    for src, rel, kind in todo:
        if src.suffix.lower() in (".jsonl", ".json", ".jsonl.gz") and _looks_like_training_data(src):
            conv_files.append((src, rel))
        else:
            text_files.append((src, rel, kind))
    if conv_files:
        conv_job = Job(dataset_id=dataset_id, type="ingest",
                      config_json={"files": [str(f) for f, _r in conv_files]})
        run_import_conversations(session, conv_job)
    todo = text_files
    total = len(todo) + len(conv_files)

    for src, rel, kind in todo:
        if is_cancelled(job.id):
            break
        try:
            _register(session, dataset_id, src, rel, kind)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            it = TextItem(dataset_id=dataset_id, source_uri=f"{kind}:{src}",
                          original_filename=src.name, relative_path=rel,
                          ingest_status="error",
                          ingest_error=f"{type(exc).__name__}: {exc}"[:500])
            session.add(it)
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed + failed, failed, max(total, 1))
            pending = 0

    session.commit()
    update_progress(job.id, processed + failed, failed, max(total, 1))

    # Cleanup extracted zip dirs (only if all items registered)
    for root in extract_roots:
        members = [f for f in sorted(root.rglob("*")) if f.is_file()]
        raw_ok = bool(members)
        by_src = {i.source_uri: i for i in session.exec(select(TextItem).where(
            TextItem.dataset_id == dataset_id)).all()}
        for f in members:
            it = by_src.get(f"imported:{f}")
            if it is None or it.ingest_status != "done":
                raw_ok = False
                break
        if raw_ok:
            shutil.rmtree(root, ignore_errors=True)