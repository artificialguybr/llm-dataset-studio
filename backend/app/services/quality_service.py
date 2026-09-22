"""Análise de qualidade para textos: detectores sobre todos os itens do dataset.

Idempotente: reexecução com mesma config gera mesmos scores; issues antigas
do mesmo detector são substituídas (delete+reinsert por text_id+detector).
"""
from typing import Any

from sqlmodel import Session, select

from ..analyzers import quality
from ..config import get_settings
from ..jobs import update_progress
from ..models import TextIssue, TextItem, Job

# (issue_type, score_fn, threshold_key, comparator)
# comparator: 'below' => issue se score < threshold; 'above' => issue se score > threshold
QUALITY_RULES = [
    ("too_short", lambda t: float(len(t)), "min_length", "below"),
    ("too_long", lambda t: float(len(t)), "max_length", "above"),
    ("repetition", lambda t: quality.repetition_score(t), "repetition_threshold", "above"),
    ("spam_score", lambda t: quality.spam_score(t), "spam_threshold", "above"),
    ("code_ratio", lambda t: quality.code_ratio(t), "code_threshold", "above"),
    ("toxicity", lambda t: quality.toxicity_score(t), "toxicity_threshold", "above"),
    ("pii_score", lambda t: quality.pii_score(t), "pii_threshold", "above"),
]


def _thresholds(session: Session, dataset_id: str) -> dict:
    from ..models import Dataset
    ds = session.get(Dataset, dataset_id)
    overrides = ds.thresholds_json if ds and ds.thresholds_json else {}
    s = get_settings()
    return {k: overrides.get(k, getattr(s, k)) for k in (
        "min_length", "max_length", "repetition_threshold", "spam_threshold",
        "code_threshold", "toxicity_threshold", "pii_threshold",
    )}


def run_quality(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    th = _thresholds(session, dataset_id)
    items = session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id,
        TextItem.ingest_status == "done")).all()

    # limpa issues ABERTAS anteriores dos mesmos tipos p/ idempotência —
    # inclui 'ingest-detectors' para não duplicar achados do import
    detectors = {"quality-rules", "ingest-detectors"}
    rule_types = {rule[0] for rule in QUALITY_RULES}
    for issue in session.exec(select(TextIssue).where(
            TextIssue.dataset_id == dataset_id)).all():
        if issue.detector_name in detectors and issue.issue_type in rule_types and issue.status == "open":
            session.delete(issue)
    session.commit()

    processed = failed = 0
    total = len(items)
    pending = 0
    from ..jobs import is_cancelled
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            text = _read_text(it)
            if text is None:
                failed += 1
                continue
            issues = []
            for issue_type, fn, th_key, cmp in QUALITY_RULES:
                score = fn(text)
                t = th[th_key]
                hit = score < t if cmp == "below" else score > t
                if hit:
                    issues.append((issue_type, score, t))
            for issue_type, score, t in issues:
                session.add(TextIssue(
                    text_id=it.id, dataset_id=dataset_id, issue_type=issue_type,
                    score=score, threshold=t, detector_name="quality-rules",
                    detector_version=quality.DETECTOR_VERSION,
                    evidence_json={"rule": issue_type},
                ))
            processed += 1
        except Exception:  # noqa: BLE001 — item falha não derruba job
            failed += 1
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))


def _read_text(it: TextItem) -> str | None:
    """Read the text content for an item."""
    s = get_settings()
    path = s.data_dir / it.storage_uri if it.storage_uri else None
    if path and path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return None
