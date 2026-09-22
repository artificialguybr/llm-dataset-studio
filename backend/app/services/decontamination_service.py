"""Decontamination contra benchmarks e eval sets (Fase: anti-leakage).

Compara n-grams (padrão: 10 palavras) dos itens do dataset com os n-grams de
um benchmark/eval set fornecido em cfg['benchmark'] (caminho local de
.jsonl/.json/.parquet/.txt/.csv) ou cfg['ngrams'] (lista de strings).
Itens contaminados viram TextIssue(issue_type='contamination',
detector_name='decontam-ngram'). Idempotente: issues antigas do detector
são substituídas a cada rodada.
"""
import json
import re
from pathlib import Path
from typing import Any
from sqlmodel import Session, select

from ..analyzers import quality
from ..jobs import is_cancelled, update_progress
from ..models import Job, TextIssue, TextItem
from ..services.quality_service import _read_text

DEFAULT_N = 10
DEFAULT_THRESHOLD = 0.05  # fração mínima de n-grams do item presentes no benchmark

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def _ngrams(text: str, n: int) -> set[tuple[str, ...]]:
    words = [w.lower() for w in _WORD_RE.findall(text)]
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def _extract_text(rec: Any) -> str:
    """Pega o campo de texto mais provável de um registro de benchmark."""
    if isinstance(rec, str):
        return rec
    if isinstance(rec, dict):
        for k in ("text", "content", "response", "answer", "chosen",
                  "prompt", "question", "input"):
            if rec.get(k):
                return str(rec[k])
        return json.dumps(rec, ensure_ascii=False)
    return str(rec)


def _benchmark_ngrams(source: Any, n: int) -> set[tuple[str, ...]]:
    """Extrai n-grams de um benchmark: lista direta, path .jsonl/.json/.txt/.csv/.parquet."""
    grams: set[tuple[str, ...]] = set()
    if isinstance(source, list):
        for t in source:
            grams |= _ngrams(str(t), n)
        return grams
    p = Path(str(source))
    if not p.is_file():
        raise FileNotFoundError(f"benchmark file not found: {p}")
    texts: list[str] = []
    if p.suffix == ".jsonl":
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            texts.append(_extract_text(json.loads(line)))
    elif p.suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if isinstance(data, list):
            texts = [str(r) for r in data]
        else:
            texts = [json.dumps(data)]
    elif p.suffix == ".parquet":
        from ..services.importers import _read_parquet
        for rec in _read_parquet(p):
            texts.append(_extract_text(rec))
    else:  # .txt / .csv / qualquer coisa: uma linha = um texto
        texts = p.read_text(encoding="utf-8", errors="replace").splitlines()
    for t in texts:
        grams |= _ngrams(t, n)
    if not grams:
        raise ValueError(f"no benchmark n-grams extracted from {p}")
    return grams


def run_decontamination(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    cfg = job.config_json or {}
    n = int(cfg.get("n") or DEFAULT_N)
    threshold = float(cfg.get("threshold") or DEFAULT_THRESHOLD)
    if cfg.get("ngrams"):
        bench = _benchmark_ngrams(cfg["ngrams"], n)
    else:
        src = cfg.get("benchmark") or cfg.get("benchmark_path")
        if not src:
            raise ValueError("decontaminate needs cfg['benchmark'] (file) or cfg['ngrams'] (list)")
        bench = _benchmark_ngrams(src, n)

    # idempotência: remove issues anteriores deste detector
    for issue in session.exec(select(TextIssue).where(
            TextIssue.dataset_id == dataset_id)).all():
        if issue.detector_name == "decontam-ngram":
            session.delete(issue)
    session.commit()

    items = session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id,
        TextItem.ingest_status == "done")).all()
    processed = flagged = failed = 0
    pending = 0
    total = max(len(items), 1)
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            text = _read_text(it)
            if text is None:
                failed += 1
                continue
            grams = _ngrams(text, n)
            if grams:
                overlap = len(grams & bench) / len(grams)
                if overlap >= threshold:
                    matches = [" ".join(g) for g in list(grams & bench)[:3]]
                    session.add(TextIssue(
                        text_id=it.id, dataset_id=dataset_id,
                        issue_type="contamination",
                        score=overlap, threshold=threshold,
                        detector_name="decontam-ngram",
                        detector_version=quality.DETECTOR_VERSION,
                        evidence_json={
                            "n": n,
                            "overlap_ngrams": len(grams & bench),
                            "total_ngrams": len(grams),
                            "samples": matches,
                        }))
                    flagged += 1
            processed += 1
        except Exception:  # noqa: BLE001 — item falha não derruba job
            failed += 1
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, total)
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, total)
