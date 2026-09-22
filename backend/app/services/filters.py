"""Filtros compartilhados entre list_items e derive — uma só fonte de verdade.

Tudo no SQL (subqueries + LIMIT/OFFSET), nada de carregar dataset inteiro
em Python para filtrar em memória. Usa TextItem/TextIssue/TextLabel.
"""
from sqlalchemy import case, func
from sqlmodel import Session, or_, select

from ..models import TextIssue, TextItem, TextLabel


def _on_stmt(base_stmt, f: dict):
    """Aplica os filtros sobre um stmt que já pode ter WHERE (dataset, status…)."""
    stmt = base_stmt
    if f.get("q"):
        stmt = stmt.where(or_(TextItem.original_filename.contains(f["q"]),
                             TextItem.relative_path.contains(f["q"])))
    if f.get("status"):
        stmt = stmt.where(TextItem.decision_status == f["status"])
    if f.get("min_length"):
        stmt = stmt.where(TextItem.char_count >= int(f["min_length"]))
    if f.get("tag"):
        stmt = stmt.where(TextItem.tags_json.contains(f["tag"]))
    if f.get("license"):
        # "unknown" é um filtro de primeira classe (§9.2)
        stmt = stmt.where(TextItem.license == f["license"])
    if f.get("queue"):
        # fila de limpeza (QuickClean): tudo que ainda pede decisão,
        # mais corruptos mesmo se marcados keep.
        stmt = stmt.where(or_(TextItem.decision_status != "keep",
                             TextItem.ingest_status == "error"))
    if f.get("issue"):
        stmt = stmt.where(TextItem.id.in_(
            select(TextIssue.text_id).where(TextIssue.issue_type == f["issue"])))
    order = (f.get("order") or "").strip()
    if order == "pending_first":
        # fila de limpeza/anotação: indecisos primeiro, depois os demais
        # por decisão; dentro de cada decisão, itens com erro de ingest
        # antes dos sadios (corruptos precisam de triagem cedo).
        stmt = stmt.order_by(
            case((TextItem.decision_status == "pending", 0),
                 (TextItem.decision_status == "review", 1),
                 (TextItem.decision_status == "quarantine", 2),
                 (TextItem.decision_status == "reject", 3), else_=4),
            case((TextItem.ingest_status == "error", 0), else_=1),
            TextItem.created_at, TextItem.id)
    return stmt


def apply_filters(session: Session, base_stmt, f: dict) -> list[TextItem]:
    """Compat: chamadores existentes (derive, semantic search) esperam lista."""
    return session.exec(_on_stmt(base_stmt, f)).all()


def count_items(session: Session, ds_id: str, f: dict) -> int:
    stmt = _on_stmt(select(func.count()).select_from(TextItem).where(
        TextItem.dataset_id == ds_id), f)
    return session.exec(stmt).one()


def page_items(session: Session, ds_id: str, f: dict, limit: int, offset: int) -> list[TextItem]:
    """Página real: LIMIT/OFFSET no SQL, sem teto silencioso de 1000."""
    stmt = _on_stmt(select(TextItem).where(TextItem.dataset_id == ds_id), f) \
        .offset(offset).limit(limit)
    return session.exec(stmt).all()