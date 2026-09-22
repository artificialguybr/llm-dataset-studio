"""Normalização de texto: Unicode (NFKC), HTML, whitespace e boilerplate.

Reescreve o CONTEÚDO em uma nova cópia (raw/<ds>/<id>.norm.txt) e aponta o
item para ela — o arquivo original (source_uri) nunca é tocado. Idempotente:
reexecutar sobre texto já normalizado não muda nada (hash igual → skip).
"""
import hashlib
from sqlmodel import Session, select

from ..analyzers import quality
from ..config import get_settings
from ..jobs import is_cancelled, update_progress
from ..models import Job, TextItem


def run_normalize(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    s = get_settings()
    items = session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id,
        TextItem.ingest_status == "done")).all()
    processed = failed = changed = 0
    pending = 0
    total = max(len(items), 1)
    transforms: dict[str, int] = {}
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            path = s.data_dir / it.storage_uri if it.storage_uri else None
            if not path or not path.exists():
                failed += 1
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            new_text, report = quality.normalize_text(text)
            if new_text != text:
                dest_dir = s.raw_dir / dataset_id
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f"{it.id}.norm.txt"
                dest.write_text(new_text, encoding="utf-8")
                it.storage_uri = str(dest.relative_to(s.data_dir))
                stats = quality._compute_stats(new_text)
                it.byte_size = len(new_text.encode("utf-8"))
                h = hashlib.sha256(
                    new_text.encode("utf-8", errors="replace")).hexdigest()
                it.content_hash_sha256 = h
                it.text_hash_sha256 = h
                it.char_count = stats.get("char_count", 0)
                it.word_count = stats.get("word_count", 0)
                it.line_count = stats.get("line_count", 0)
                it.max_line_length = stats.get("max_line_length", 0)
                it.min_line_length = stats.get("min_line_length", 0)
                it.has_html = False
                it.has_unicode_normalization_issues = False
                it.has_whitespace_issues = False
                session.add(it)
                changed += 1
                for k, v in report.items():
                    if v:
                        transforms[k] = transforms.get(k, 0) + 1
            processed += 1
        except Exception:  # noqa: BLE001 — item falha não derruba job
            failed += 1
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, total)
            pending = 0
    session.commit()
    job.config_json = {**job.config_json, "changed_items": changed,
                       "transforms": transforms} if job.config_json is not None else {}
    session.add(job)
    session.commit()
    update_progress(job.id, processed, failed, total)
