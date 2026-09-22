"""Importadores de datasets de texto: JSONL, Parquet, TXT, CSV, Hugging Face.

Não usa Datumaro — parsers diretos, testados contra os formatos que o próprio app exporta.
Regra: importar labels/metadata com source_type='imported'.
"""
import csv
import gzip
import hashlib
import json
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..analyzers.quality import DETECTOR_VERSION
from ..config import get_settings
from ..jobs import update_progress
from .ingest import _compute_stats, _normalize_text, _read_text_file
from ..models import Dataset, Job, TextItem, TextIssue, TextLabel


# Extensões suportadas para arquivos de texto
TEXT_EXTENSIONS = {".txt", ".jsonl", ".json", ".csv", ".tsv", ".md", ".jsonl.gz", ".parquet"}


def _read_jsonl_lines(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Lê arquivo JSONL (ou .jsonl.gz) linha a linha."""
    lines = []
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                lines.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return lines


def _read_parquet(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Lê arquivo Parquet via pyarrow/pandas."""
    try:
        import pyarrow.parquet as pq
        table = pq.read_table(path)
        if limit:
            table = table.slice(0, limit)
        return table.to_pylist()
    except ImportError:
        # Fallback para pandas se pyarrow não estiver disponível
        try:
            import pandas as pd
            df = pd.read_parquet(path)
            if limit:
                df = df.head(limit)
            return df.to_dict(orient="records")
        except ImportError:
            raise RuntimeError("pyarrow or pandas required for parquet import")


def _read_csv_lines(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Lê CSV/TSV."""
    lines = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        # Detecta delimitador
        sample = f.read(1024)
        f.seek(0)
        sniffer = csv.Sniffer()
        delimiter = sniffer.sniff(sample).delimiter
        reader = csv.DictReader(f, delimiter=delimiter)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            lines.append(row)
    return lines


def _read_txt_lines(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    """Lê arquivo de texto simples — cada linha = um item."""
    lines = []
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            line = line.strip()
            if line:
                lines.append({"text": line})
    return lines


def _infer_text_field(record: dict[str, Any]) -> str | None:
    """Infere qual campo contém o texto principal."""
    # Prioriza campos comuns de texto
    for key in ("text", "content", "message", "prompt", "completion", "response", "answer", "output"):
        if key in record and isinstance(record[key], str) and record[key].strip():
            return record[key]
    # Fallback: primeiro campo string não vazio
    for key, value in record.items():
        if isinstance(value, str) and value.strip():
            return value
    return None


def _infer_role_field(record: dict[str, Any]) -> str:
    """Infere role para conversas."""
    for key in ("role", "speaker", "from", "author"):
        if key in record and isinstance(record[key], str):
            role = record[key].lower()
            if role in ("user", "human", "question"):
                return "user"
            if role in ("assistant", "model", "bot", "answer"):
                return "assistant"
            if role in ("system", "sys"):
                return "system"
            if role in ("tool", "function"):
                return "tool"
    return "user"


def _register_text_item(
    session: Session,
    dataset_id: str,
    source_kind: str,
    source_uri: str,
    original_filename: str,
    relative_path: str,
    text: str,
    metadata: dict[str, Any] | None = None,
) -> TextItem:
    """Registra um TextItem com o texto e metadata."""
    s = get_settings()
    ds = session.get(Dataset, dataset_id)

    stats = _compute_stats(text)

    content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    tokens = len(text) // 4  # estimativa rough

    item = TextItem(
        dataset_id=dataset_id,
        source_uri=f"{source_kind}:{source_uri}",
        original_filename=original_filename,
        relative_path=relative_path,
        byte_size=len(text.encode("utf-8")),
        mime_type="text/plain",
        content_hash_sha256=content_hash,
        text_hash_sha256=content_hash,
        tokens=tokens,
        token_estimator="character",
        language=stats.get("language", ""),
        char_count=stats.get("char_count", 0),
        word_count=stats.get("word_count", 0),
        line_count=stats.get("line_count", 0),
        max_line_length=stats.get("max_line_length", 0),
        min_line_length=stats.get("min_line_length", 0),
        has_html=stats.get("has_html", False),
        license=ds.license if ds else "unknown",
        license_evidence_uri=ds.license_evidence_uri if ds else "",
        ingest_status="done",
    )

    # Detecta issues de normalização
    import unicodedata
    if text and unicodedata.normalize("NFC", text) != text:
        item.has_unicode_normalization_issues = True
    if text and any(c in "\t\r" for c in text[:100]):
        item.has_whitespace_issues = True

    # Salva texto normalizado
    dest_dir = s.raw_dir / dataset_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{item.id}.txt"
    dest.write_text(text, encoding="utf-8")
    item.storage_uri = str(dest.relative_to(s.data_dir))

    # Metadata extra em exif_json
    if metadata:
        item.exif_json = metadata

    session.add(item)
    session.flush()

    # Detecta issues básicos
    issues = []
    if stats.get("char_count", 0) < 10:
        issues.append(("too_short", 1.0, 10.0))
    if tokens > 4000:
        issues.append(("too_long", 1.0, 4000.0))

    for issue_type, score, threshold in issues:
        session.add(TextIssue(
            text_id=item.id, dataset_id=dataset_id, issue_type=issue_type,
            score=score, threshold=threshold, detector_name="ingest-detectors",
            detector_version=DETECTOR_VERSION, evidence_json={"stat": issue_type},
        ))

    return item


def run_import_jsonl(session: Session, job: Job) -> None:
    """Importa JSONL: cada linha = um TextItem. Campo 'text'/'content'/'message' vira o texto."""
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    dataset_id = job.dataset_id

    files = list(folder.rglob("*.jsonl")) + list(folder.rglob("*.jsonl.gz")) + list(folder.rglob("*.json"))
    total = len(files)
    processed = failed = 0

    for f in files:
        try:
            records = _read_jsonl_lines(f)
            for rel_idx, rec in enumerate(records):
                text = _infer_text_field(rec)
                if not text:
                    continue
                metadata = {k: v for k, v in rec.items() if k not in ("text", "content", "message", "prompt", "completion", "response", "answer", "output")}
                _register_text_item(
                    session, dataset_id, "imported", str(f),
                    f.name, f"{f.stem}_{rel_idx}", text, metadata
                )
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_parquet(session: Session, job: Job) -> None:
    """Importa Parquet: cada linha = um TextItem."""
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    dataset_id = job.dataset_id

    files = list(folder.rglob("*.parquet"))
    total = len(files)
    processed = failed = 0

    for f in files:
        try:
            records = _read_parquet(f)
            for rel_idx, rec in enumerate(records):
                text = _infer_text_field(rec)
                if not text:
                    continue
                metadata = {k: v for k, v in rec.items() if k not in ("text", "content", "message", "prompt", "completion", "response", "answer", "output")}
                _register_text_item(
                    session, dataset_id, "imported", str(f),
                    f.name, f"{f.stem}_{rel_idx}", text, metadata
                )
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_csv(session: Session, job: Job) -> None:
    """Importa CSV/TSV: cada linha = um TextItem."""
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    dataset_id = job.dataset_id

    files = list(folder.rglob("*.csv")) + list(folder.rglob("*.tsv"))
    total = len(files)
    processed = failed = 0

    for f in files:
        try:
            records = _read_csv_lines(f)
            for rel_idx, rec in enumerate(records):
                text = _infer_text_field(rec)
                if not text:
                    continue
                metadata = {k: v for k, v in rec.items() if k not in ("text", "content", "message", "prompt", "completion", "response", "answer", "output")}
                _register_text_item(
                    session, dataset_id, "imported", str(f),
                    f.name, f"{f.stem}_{rel_idx}", text, metadata
                )
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_txt(session: Session, job: Job) -> None:
    """Importa TXT/MD: cada linha = um TextItem."""
    cfg = job.config_json
    folder = Path(cfg["folder"]).resolve()
    dataset_id = job.dataset_id

    files = list(folder.rglob("*.txt")) + list(folder.rglob("*.md"))
    total = len(files)
    processed = failed = 0

    for f in files:
        try:
            records = _read_txt_lines(f)
            for rel_idx, rec in enumerate(records):
                text = rec.get("text", "")
                if not text:
                    continue
                _register_text_item(
                    session, dataset_id, "imported", str(f),
                    f.name, f"{f.stem}_{rel_idx}", text
                )
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_import_hf(session: Session, job: Job) -> None:
    """Importa Hugging Face dataset: carrega via datasets library."""
    cfg = job.config_json
    dataset_id = job.dataset_id
    hf_id = cfg.get("hf_dataset", "")
    split = cfg.get("split", "train")
    text_column = cfg.get("text_column", "text")
    max_samples = cfg.get("max_samples")

    if not hf_id:
        raise ValueError("hf_dataset required")

    try:
        from datasets import load_dataset
    except ImportError:
        raise RuntimeError("datasets library required for HF import — install with `uv sync --extra hf`")

    ds = load_dataset(hf_id, split=split, streaming=True)
    if max_samples:
        ds = ds.take(max_samples)

    total = max_samples or 10000  # estimativa para progress
    processed = failed = 0
    batch = []

    for i, rec in enumerate(ds):
        if isinstance(rec, dict):
            text = rec.get(text_column) or _infer_text_field(rec)
        else:
            text = str(rec)

        if not text:
            continue

        metadata = {k: v for k, v in rec.items() if k != text_column} if isinstance(rec, dict) else {}
        batch.append((f"{hf_id}/{split}/{i}", text, metadata))

        if len(batch) >= 100:
            for src_uri, txt, meta in batch:
                try:
                    _register_text_item(session, dataset_id, "huggingface", src_uri,
                                        f"{hf_id.split('/')[-1]}_{split}", src_uri, txt, meta)
                    processed += 1
                except Exception:  # noqa: BLE001
                    failed += 1
            batch = []
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))

    # Flush remaining
    for src_uri, txt, meta in batch:
        try:
            _register_text_item(session, dataset_id, "huggingface", src_uri,
                                f"{hf_id.split('/')[-1]}_{split}", src_uri, txt, meta)
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1

    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))


def is_conversation_record(rec: dict[str, Any]) -> bool:
    """True se o registro JSON usa um formato de treino conhecido."""
    if any(k in rec for k in ("conversations", "messages", "instruction")):
        return True
    if all(k in rec for k in ("prompt", "chosen", "rejected")):
        return True  # TRL DPO
    if "prompt" in rec and "completion" in rec:
        return True  # TRL prompt-completion SFT
    return any(k in rec for k in ("trace_type", "trace", "steps", "tool_calls", "trajectory"))


def run_import_conversations(session: Session, job: Job) -> None:
    """Importa conversas/records (SFT/DPO/traces) como records estruturados."""
    from ..models import (Conversation, TextTurn, SFTRecord, PreferencePair, AgentTrace)
    import hashlib

    cfg = job.config_json
    dataset_id = job.dataset_id
    explicit = [Path(f) for f in cfg.get("files", [])]
    if explicit:
        files = explicit
    else:
        folder = Path(cfg["folder"]).resolve()
        files = list(folder.rglob("*.jsonl")) + list(folder.rglob("*.json")) + list(folder.rglob("*.jsonl.gz"))
    total = len(files)

    # dedupe por conteúdo: pula registros idênticos já importados
    pref_seen = {hashlib.sha256(
        (p.prompt_text + p.chosen_text + p.rejected_text).encode()).hexdigest()
        for p in session.exec(select(PreferencePair).where(
            PreferencePair.dataset_id == dataset_id)).all()}
    sft_seen = {hashlib.sha256(
        json.dumps(r.messages, sort_keys=True).encode()).hexdigest()
        for r in session.exec(select(SFTRecord).where(
            SFTRecord.dataset_id == dataset_id)).all()}
    trace_seen = {hashlib.sha256(
        json.dumps(t.trace_json, sort_keys=True).encode()).hexdigest()
        for t in session.exec(select(AgentTrace).where(
            AgentTrace.dataset_id == dataset_id)).all()}
    processed = failed = 0

    for f in files:
        try:
            records = _read_jsonl_lines(f) if f.suffix in (".jsonl", ".gz") else json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                records = [records]

            for rec in records:
                # ShareGPT format: {"conversations": [{"from": "human", "value": "..."}, ...]}
                # Alpaca format: {"instruction": "...", "input": "...", "output": "..."}
                # OpenAI format: {"messages": [{"role": "user", "content": "..."}, ...]}

                conv = Conversation(
                    dataset_id=dataset_id,
                    title=rec.get("title", "")[:200] if rec.get("title") else "",
                    source_uri=f"imported:{f}",
                    conversation_type=rec.get("type", "sft"),
                    language=rec.get("language", ""),
                    license=rec.get("license", "unknown"),
                )

                turns_data = []
                if "conversations" in rec:  # ShareGPT
                    for turn in rec["conversations"]:
                        role = _infer_role_field(turn)
                        content = turn.get("value") or turn.get("content") or ""
                        turns_data.append({"role": role, "content": content})
                elif "messages" in rec:  # OpenAI
                    for turn in rec["messages"]:
                        role = turn.get("role", "user")
                        content = turn.get("content", "")
                        turns_data.append({"role": role, "content": content})
                elif "instruction" in rec:  # Alpaca
                    prompt = rec.get("instruction", "")
                    if rec.get("input"):
                        prompt += "\n" + rec["input"]
                    turns_data.append({"role": "user", "content": prompt})
                    if rec.get("output"):
                        turns_data.append({"role": "assistant", "content": rec["output"]})

                # TRL DPO: {"prompt": "...", "chosen": "...", "rejected": "..."}
                # (prompt/chosen/rejected may be strings or message lists)
                if not turns_data and all(k in rec for k in ("prompt", "chosen", "rejected")):
                    from ..models import PreferencePair
                    def _pref_text(v):
                        if isinstance(v, str):
                            return v
                        return "\n".join(
                            f"{m.get('role', 'user')}: {m.get('content', '')}"
                            for m in v if isinstance(m, dict))
                    _p, _c, _r = (_pref_text(rec["prompt"]), _pref_text(rec["chosen"]),
                                   _pref_text(rec["rejected"]))
                    _key = hashlib.sha256((_p + _c + _r).encode()).hexdigest()
                    if _key in pref_seen:
                        continue
                    pref_seen.add(_key)
                    session.add(PreferencePair(
                        dataset_id=dataset_id,
                        prompt_text=_p, chosen_text=_c, rejected_text=_r,
                        strategy=rec.get("strategy", "dpo"),
                        license=rec.get("license", "unknown"),
                    ))
                    processed += 1
                    continue
                # TRL prompt-completion SFT: {"prompt": "...", "completion": "..."}
                if not turns_data and "prompt" in rec and "completion" in rec:
                    from ..models import SFTRecord
                    _msgs = [{"role": "user", "content": str(rec["prompt"])},
                             {"role": "assistant", "content": str(rec["completion"])}]
                    _key = hashlib.sha256(json.dumps(_msgs, sort_keys=True).encode()).hexdigest()
                    if _key in sft_seen:
                        continue
                    sft_seen.add(_key)
                    session.add(SFTRecord(
                        dataset_id=dataset_id,
                        messages=_msgs,
                        system_prompt=str(rec.get("system", "")),
                        tokens=(len(str(rec["prompt"])) + len(str(rec["completion"]))) // 4,
                        schema_type="sft",
                        source_type="imported",
                        license=rec.get("license", "unknown"),
                    ))
                    processed += 1
                    continue
                # Agent/reasoning traces: {"trace_type"|"trace"|"steps"|"tool_calls"}
                if not turns_data and any(k in rec for k in ("trace_type", "trace", "steps", "tool_calls", "trajectory")):
                    from ..models import AgentTrace
                    _key = hashlib.sha256(json.dumps(rec, sort_keys=True).encode()).hexdigest()
                    if _key in trace_seen:
                        continue
                    trace_seen.add(_key)
                    session.add(AgentTrace(
                        dataset_id=dataset_id,
                        trace_type=str(rec.get("trace_type", "agent")),
                        trace_id=str(rec.get("trace_id", "")),
                        trace_json=rec,
                        tokens=sum(len(str(v)) // 4 for v in rec.values()),
                        model=str(rec.get("model", "")),
                        duration_ms=rec.get("duration_ms"),
                        success=rec.get("success"),
                        error=str(rec.get("error", "")),
                    ))
                    processed += 1
                    continue

                if not turns_data:
                    continue

                session.add(conv)
                session.flush()

                for idx, turn_data in enumerate(turns_data):
                    content = turn_data.get("content", "")
                    content_hash = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()
                    tokens = len(content) // 4

                    turn = TextTurn(
                        conversation_id=conv.id,
                        dataset_id=dataset_id,
                        role=turn_data.get("role", "user"),
                        content=content,
                        content_hash_sha256=content_hash,
                        tokens=tokens,
                        token_estimator="character",
                        turn_index=idx,
                        tool_calls=turn_data.get("tool_calls", []),
                        tool_call_id=turn_data.get("tool_call_id"),
                        agent_trace=turn_data.get("agent_trace", False),
                    )
                    session.add(turn)

                conv.turn_count = len(turns_data)
                conv.total_tokens = sum(t.tokens for t in session.exec(
                    select(TextTurn).where(TextTurn.conversation_id == conv.id)).all()
                ) if False else sum(len(t["content"]) // 4 for t in turns_data)
                session.add(conv)

            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))


def run_retry_errors(session: Session, job: Job) -> None:
    """Reprocessa apenas itens com ingest_status=error deste dataset."""
    cfg = job.config_json
    dataset_id = job.dataset_id
    items = session.exec(
        select(TextItem).where(TextItem.dataset_id == dataset_id, TextItem.ingest_status == "error")
    ).all()
    total = len(items)
    processed = failed = 0

    for it in items:
        try:
            src = it.source_uri.split(":", 1)[1] if ":" in it.source_uri else it.source_uri
            src_path = Path(src)
            if src_path.suffix.lower() in {".jsonl", ".jsonl.gz", ".json"}:
                records = _read_jsonl_lines(src_path)
            elif src_path.suffix.lower() == ".parquet":
                records = _read_parquet(src_path)
            elif src_path.suffix.lower() in {".csv", ".tsv"}:
                records = _read_csv_lines(src_path)
            elif src_path.suffix.lower() in {".txt", ".md"}:
                records = _read_txt_lines(src_path)
            else:
                raise ValueError(f"Unsupported format for retry: {src_path.suffix}")

            for rel_idx, rec in enumerate(records):
                text = _infer_text_field(rec)
                if not text:
                    continue
                metadata = {k: v for k, v in rec.items() if k not in ("text", "content", "message")}
                _register_text_item(
                    session, dataset_id, "retried", str(src_path),
                    src_path.name, f"{src_path.stem}_{rel_idx}", text, metadata
                )
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))
