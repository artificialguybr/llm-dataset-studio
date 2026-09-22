"""Redação de PII textual (Fase 9.3.6): substitui trechos com PII por [REDACTED],
gera novos arquivos (os originais nunca são tocados) e registra versão nova."""
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..analyzers import quality
from ..config import get_settings
from ..models import Dataset, DatasetVersion, Job, TextItem, TextIssue, TextLabel
from .paths import item_path


# PII patterns to redact (simple regex-based, no external deps)
_PII_PATTERNS = [
    (r"[\w.-]+@[\w.-]+\.\w+", "[REDACTED]"),  # emails
    (r"\(?\d{2}\)?\s?\d{4,5}[-\s]?\d{4}", "[REDACTED]"),  # BR phones
    (r"\b(?:\d[ -]*?){13,16}\b", "[REDACTED]"),  # credit cards
    (r"\b\d{3}[ -]?\d{2}[ -]?\d{4}\b", "[REDACTED]"),  # SSN-like
]


def _redact_text(text: str) -> tuple[str, int]:
    """Substitui PII no texto. Retorna (texto_redigido, n_substituicoes)."""
    import re
    n = 0
    out = text
    for pattern, replacement in _PII_PATTERNS:
        new, count = re.subn(pattern, replacement, out, flags=re.IGNORECASE)
        if count:
            n += count
            out = new
    return out, n


def redact_pii(session: Session, job: Job, radius: int = 12) -> dict:
    """Fase 9.3.6: redige PII textual em itens do dataset.

    Cada item com PII detectado gera um novo arquivo em data/redacted/{ds_id[:8]}/
    com o texto substituído. O original nunca é tocado.
    """
    ds_id = job.dataset_id
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise ValueError("dataset not found")

    s = get_settings()
    red_dir = s.data_dir / "redacted" / ds_id[:8]
    red_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    for it in session.exec(
            select(TextItem).where(
                TextItem.dataset_id == ds_id,
                TextItem.decision_status.in_(["keep", "restore"])
            )
    ).all():
        src = item_path(it)
        if src is None or not src.exists():
            continue
        original = src.read_text(encoding="utf-8", errors="replace")
        redacted, count = _redact_text(original)
        if count == 0:
            continue
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        out = red_dir / f"{it.id[:12]}-{stamp}.txt"
        out.write_text(redacted, encoding="utf-8")
        # Atualiza storage_uri para a cópia redigida; original preservado em source_uri
        it.storage_uri = str(out.relative_to(s.data_dir))
        it.license_evidence_uri = it.license_evidence_uri or it.source_uri
        session.add(it)
        n += 1

    session.commit()
    # Versão nova com o resultado (auditoria) — reusa o serviço existente
    from .versions_service import create_version
    v = create_version(session, ds_id,
                       description=f"PII redaction de {n} itens; originais preservados")
    session.refresh(v)
    return {"redacted": n, "version_id": v.id}


def _dumps(o: Any) -> str:
    import json
    return json.dumps(o, ensure_ascii=False, sort_keys=True)