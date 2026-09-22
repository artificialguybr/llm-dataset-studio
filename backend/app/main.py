"""API completa: datasets, imports/jobs, text items, issues, duplicates,
labels, decisions, versions, semantic search, clusters, export.

Text-domain port: replaces all image-item/thumbnail/caption endpoints with
text-item, caption (generated text), conversation/turn, and preference-pair
endpoints.
"""
import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import PlainTextResponse, JSONResponse
from typing import Literal

from pydantic import BaseModel, Field, PositiveFloat
from sqlmodel import Session, func, or_, select

from . import jobs as jobrunner
from .services import versions_service
from .config import get_settings, public_provider_settings, update_provider_settings
from .analyzers import quality
from .db import engine, get_session, init_db
from .exporters.exporter import export
from .models import (Dataset, DatasetVersion, DuplicateGroup, DuplicateMember,
                     ExportRecord, TextItem, TextIssue, TextLabel, Job,
                     TextTurn, Conversation, PreferencePair, TextReviewDecision,
                     SFTRecord, AgentTrace, Caption)
from .services import (ai_service, dedup_service, embeddings_service, importers,
                       ingest, normalization_service, decontamination_service,
                       redact_service, sampling_service, quality_service,
                       versions_service)
from .services.paths import item_text
from . import model_catalog, plugin_runtime
from . import providers  # noqa: F401 — registra os builtin plugins
from . import seed as seed_module

app = FastAPI(title="LLM Dataset Studio", version="0.1.0")

app.on_event("startup")(init_db)


@app.on_event("startup")
def _reconcile_stuck_jobs():
    """Jobs 'running' de um processo anterior morrem com o servidor; sem isso
    ficam presos para sempre na UI."""
    with Session(engine) as session:
        stmt = (select(Job)
                .where(Job.status.in_(("queued", "running"))))
        stuck = session.exec(stmt).all()
        for j in stuck:
            j.status = "failed"
            j.error_summary = "server restarted while job was in flight"
            j.finished_at = datetime.now(UTC)
            session.add(j)
        session.commit()


# ---------- security helpers ----------

ALLOWED_SCHEMES = ("http", "https", "file", "hf")


def _safe_path(p: Path, s) -> bool:
    """Text file: must stay under data_dir, or be an allowed source file."""
    rp = p.resolve()
    try:
        under = rp.is_relative_to(s.data_dir.resolve())
    except (TypeError, ValueError):
        under = False
    if under:
        return True
    forbidden = ("/etc", "/System", "/private/etc", "/usr/bin", "/bin", "/sbin",
                 "Library/Keychains")
    return rp.is_file() and not any(rp.is_relative_to(Path(f)) for f in forbidden)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


# ---------- schemas ----------

class DatasetIn(BaseModel):
    name: str
    description: str = ""
    folder: Optional[str] = None
    license: str = "unknown"
    license_evidence_uri: str = ""


class ImportRequest(BaseModel):
    paths: list[str] = []
    zips: list[str] = []
    jsonls: list[str] = []  # new: JSONL/Parquet imports
    hf_dataset: str = ""  # HuggingFace dataset id, e.g. "lmsys/chatbot_arena_preferences"


class TextLabelIn(BaseModel):
    label_type: str = "classification"
    category: str
    value: dict[str, Any] = {}
    source_type: str = "human"
    confidence: Optional[float] = None
    span_start: Optional[int] = None
    span_end: Optional[int] = None
    supersedes_id: Optional[str] = None


class TextLabelPatch(BaseModel):
    category: Optional[str] = None


class DecisionIn(BaseModel):
    decision: Literal["keep", "review", "quarantine", "reject", "restore", "pending"]
    reason: str = ""
    reviewer: str = "local"


class VersionIn(BaseModel):
    description: str = ""


class TagIn(BaseModel):
    tags: list[str]


class ExportIn(BaseModel):
    fmt: Literal["jsonl", "parquet", "hf", "manifest", "report"] = "jsonl"
    version_id: Optional[str] = None


class IssueAckIn(BaseModel):
    status: Literal["acknowledged", "dismissed"] = "acknowledged"
    reviewer: str = "local"


class TurnIn(BaseModel):
    role: str = "user"
    content: str = ""
    tokens: int = 0
    token_estimator: str = ""
    tool_calls: list[dict[str, Any]] = []
    tool_call_id: Optional[str] = None
    parent_turn_id: Optional[str] = None
    agent_trace: bool = False


class PreferenceIn(BaseModel):
    prompt_text: str = ""
    chosen_text: str = ""
    rejected_text: str = ""
    chosen_turn_id: Optional[str] = None
    rejected_turn_id: Optional[str] = None
    strategy: str = "manual"


class PreferenceDecisionIn(BaseModel):
    decision: Literal["a", "b", "tie", "skip"]
    reviewer: str = "local"



class SFTRecordIn(BaseModel):
    messages: list[dict[str, str]] = Field(default_factory=list)
    system_prompt: str = ""
    tokens: int = 0
    schema_type: str = "sft"
    source_type: str = "human"
    source_id: str = ""
    license: str = "unknown"


class AgentTraceIn(BaseModel):
    trace_type: str = "agent"
    trace_id: str = ""
    trace_json: dict[str, Any] = Field(default_factory=dict)
    tokens: int = 0
    model: str = ""
    duration_ms: Optional[int] = None
    success: Optional[bool] = None
    error: str = ""


# ---------- datasets ----------

@app.post("/api/datasets", status_code=201)
def create_dataset(body: DatasetIn, session: Session = Depends(get_session)):
    ds = Dataset(**{k: v for k, v in body.model_dump().items() if v is not None and k not in ("folder",)})
    if body.folder:
        p = Path(body.folder).resolve()
        p.mkdir(parents=True, exist_ok=True)
        ds.source_uri = f"local:{p}"
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


@app.get("/api/datasets")
def list_datasets(session: Session = Depends(get_session)):
    dss = session.exec(select(Dataset)).all()
    out = []
    for ds in dss:
        rows = session.exec(select(TextItem.decision_status, func.count())
                            .where(TextItem.dataset_id == ds.id)
                            .group_by(TextItem.decision_status)).all()
        counts = {"total": 0, "keep": 0, "review": 0, "quarantine": 0, "reject": 0, "restore": 0}
        for status, n in rows:
            counts["total"] += n
            if status in counts:
                counts[status] = n
        issue_open = session.exec(select(func.count()).select_from(TextIssue).where(
            TextIssue.dataset_id == ds.id, TextIssue.status == "open")).one()
        running = [j.id for j in session.exec(select(Job.id).where(
            Job.dataset_id == ds.id, Job.status.in_(("queued", "running")))).all()]
        out.append({**ds.model_dump(), "item_counts": counts,
                   "open_issues": issue_open, "running_jobs": running})
    return out


@app.get("/api/datasets/{ds_id}")
def get_dataset(ds_id: str, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    stmt = (select(TextItem.decision_status, func.count())
             .where(TextItem.dataset_id == ds.id)
             .group_by(TextItem.decision_status))
    rows = session.exec(stmt).all()
    counts = {"total": 0, "keep": 0, "review": 0, "quarantine": 0, "reject": 0, "restore": 0}
    for status, n in rows:
        counts["total"] += n
        if status in counts:
            counts[status] = n
    stmt_i = (select(func.count()).select_from(TextIssue)
              .where(TextIssue.dataset_id == ds.id, TextIssue.status == "open"))
    issue_open = session.exec(stmt_i).one()
    return {**ds.model_dump(), "item_counts": counts, "open_issues": issue_open}


@app.get("/api/datasets/{ds_id}/stats")
def dataset_stats(ds_id: str, session: Session = Depends(get_session)):
    """Aggregate corpus shape and token statistics without fetching every item."""
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    row = session.exec(select(
        func.count(TextItem.id),
        func.coalesce(func.sum(TextItem.tokens), 0),
        func.coalesce(func.sum(TextItem.char_count), 0),
        func.coalesce(func.sum(TextItem.word_count), 0),
        func.coalesce(func.avg(TextItem.tokens), 0),
        func.coalesce(func.avg(TextItem.char_count), 0),
        func.coalesce(func.avg(TextItem.word_count), 0),
        func.coalesce(func.min(TextItem.tokens), 0),
        func.coalesce(func.max(TextItem.tokens), 0),
        func.count(func.distinct(TextItem.source_uri)),
    ).where(TextItem.dataset_id == ds_id)).one()
    languages = session.exec(select(TextItem.language, func.count(TextItem.id))
                             .where(TextItem.dataset_id == ds_id)
                             .group_by(TextItem.language)
                             .order_by(func.count(TextItem.id).desc())).all()
    mime_types = session.exec(select(TextItem.mime_type, func.count(TextItem.id))
                              .where(TextItem.dataset_id == ds_id)
                              .group_by(TextItem.mime_type)
                              .order_by(func.count(TextItem.id).desc())).all()
    return {
        "documents": int(row[0] or 0), "total_tokens": int(row[1] or 0),
        "total_characters": int(row[2] or 0), "total_words": int(row[3] or 0),
        "average_tokens": round(float(row[4] or 0), 1),
        "average_characters": round(float(row[5] or 0), 1),
        "average_words": round(float(row[6] or 0), 1),
        "min_tokens": int(row[7] or 0), "max_tokens": int(row[8] or 0),
        "sources": int(row[9] or 0),
        "languages": [{"value": v or "unknown", "count": int(n)} for v, n in languages],
        "mime_types": [{"value": v or "unknown", "count": int(n)} for v, n in mime_types],
    }


@app.delete("/api/datasets/{ds_id}", status_code=204)
def delete_dataset(ds_id: str, session: Session = Depends(get_session)):
    """Remove o dataset e todos os seus registros derivados.

    Ordem respeita FKs: filhos primeiro, dataset por último. Arquivos em
    data_dir são preservados — só o índice some.
    """
    from sqlmodel import delete as sql_delete
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    item_ids = list(session.exec(
        select(TextItem.id).where(TextItem.dataset_id == ds_id)).all())
    group_ids = list(session.exec(
        select(DuplicateGroup.id).where(DuplicateGroup.dataset_id == ds_id)).all())
    if item_ids:
        session.exec(sql_delete(TextReviewDecision).where(
            TextReviewDecision.target_id.in_(item_ids)))  # type: ignore[arg-type]
        session.exec(sql_delete(Caption).where(Caption.text_id.in_(item_ids)))  # type: ignore[arg-type]
        session.exec(sql_delete(TextLabel).where(TextLabel.text_id.in_(item_ids)))  # type: ignore[arg-type]
        session.exec(sql_delete(TextIssue).where(TextIssue.text_id.in_(item_ids)))  # type: ignore[arg-type]
    if group_ids:
        session.exec(sql_delete(DuplicateMember).where(
            DuplicateMember.group_id.in_(group_ids)))  # type: ignore[arg-type]
    for model in (Conversation, TextTurn, PreferencePair, SFTRecord,
                  AgentTrace, DuplicateGroup, DatasetVersion, Job, ExportRecord):
        session.exec(sql_delete(model).where(model.dataset_id == ds_id))  # type: ignore[attr-defined]
    session.exec(sql_delete(TextItem).where(TextItem.dataset_id == ds_id))
    session.exec(sql_delete(Dataset).where(Dataset.id == ds_id))
    session.commit()
    return Response(status_code=204)


@app.patch("/api/datasets/{ds_id}")
def patch_dataset(ds_id: str, body: dict, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    for k in ("name", "description", "license", "license_evidence_uri", "license_policy", "thresholds_json"):
        v = body.get(k)
        if k in body and v is not None:
            setattr(ds, k, v)
    if ds.license_policy not in ("permissive", "strict"):
        raise HTTPException(400, "license_policy must be permissive|strict")
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


# ---------- sample corpus (first-run demo) ----------

def _wait_for_job(session: Session, job_id: str, timeout_s: float = 30.0) -> Job:
    deadline = datetime.now(tz=UTC).timestamp() + timeout_s
    while datetime.now(tz=UTC).timestamp() < deadline:
        job = session.get(Job, job_id)
        if job and job.status in ("completed", "failed", "cancelled"):
            if job.status != "completed":
                raise HTTPException(500, f"seed job {job.type} failed: {job.error_summary}")
            return job
        import time
        time.sleep(0.1)
        session.expire_all()
    raise HTTPException(500, f"seed job {job_id} timed out")


@app.post("/api/seed-demo", status_code=201)
def seed_demo(session: Session = Depends(get_session)):
    """Create the sample corpus and run the built-in analysis jobs.

    English texts covering every detector (PII, duplicates, toxicity, spam,
    code, size, repetition) so a fresh install is explorable immediately.
    """
    existing = session.exec(select(Dataset).where(Dataset.name == "sample-corpus")).first()
    if existing is not None:
        raise HTTPException(409, "sample dataset already loaded")
    ds = Dataset(name="sample-corpus",
                description="Built-in demo corpus — every detector has something to find.",
                license="CC-BY-4.0")
    session.add(ds)
    session.commit()
    session.refresh(ds)
    seed_dir = get_settings().raw_dir / "seed"
    seed_dir.mkdir(parents=True, exist_ok=True)
    for fname, text in seed_module.SEED_FILES:
        (seed_dir / fname).write_text(text, encoding="utf-8")
    (seed_dir / "17-too-long.txt").write_text(seed_module.long_unique_text(), encoding="utf-8")
    job = Job(type="ingest", dataset_id=ds.id)
    ingest_job = jobrunner.spawn_job(job, ingest.run_ingest,
                                   {"paths": [str(seed_dir)], "zips": [], "jsonls": []})
    _wait_for_job(session, ingest_job)
    for job_type, fn in (("quality", quality_service.run_quality),
                         ("dedup_exact", dedup_service.run_exact_dedup),
                         ("dedup_semantic", dedup_service.run_minhash_dedup)):
        j = Job(type=job_type, dataset_id=ds.id)
        jid = jobrunner.spawn_job(j, fn, {})
        _wait_for_job(session, jid)
    session.refresh(ds)
    n_items = session.exec(select(func.count()).select_from(TextItem).where(
        TextItem.dataset_id == ds.id)).one()
    n_issues = session.exec(select(func.count()).select_from(TextIssue).where(
        TextIssue.dataset_id == ds.id, TextIssue.status == "open")).one()
    return {"dataset_id": ds.id, "name": ds.name,
            "items": n_items, "issues": n_issues}



# ---------- imports & jobs ----------

@app.post("/api/datasets/{ds_id}/imports", status_code=202)
def start_import(ds_id: str, body: ImportRequest, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    for p in body.paths + body.zips + body.jsonls:
        if not Path(p).exists():
            raise HTTPException(400, f"path not found: {p}")
    job = Job(type="ingest", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ingest.run_ingest, body.model_dump())
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/datasets/{ds_id}/jobs/{job_type}", status_code=202)
def start_job(ds_id: str, job_type: str, body: dict | None = None, session: Session = Depends(get_session)):
    body = body or {}
    cfg = {k: (str(v) if k == "folder" else v) for k, v in body.items()
           if k in ("folder", "urls", "urls_file", "urls_json", "model_id", "automation",
                    "confidence", "preview", "prompt", "prefix", "suffix",
                    "separator", "template", "item_ids", "hf_dataset",
                    "benchmark", "ngrams", "n", "threshold")}
    model_capabilities = {
        "embeddings": "embedding", "preannotate": "preannotation",
        "pii_scan": "pii", "caption": "captioning",
    }
    requested_model = body.get("model_id") or model_catalog.active_model(model_capabilities.get(job_type, ""))
    if requested_model:
        selected = next((m for m in model_catalog.list_catalog() if m["id"] == requested_model), None)
        if selected is None:
            raise HTTPException(404, "model not found")
        if not selected["installed"]:
            raise HTTPException(409, "selected model is not installed")
        cfg["model_id"] = requested_model
        cfg["model"] = {key: selected[key] for key in ("id", "name", "capability", "revision", "runtime", "license", "sha256") if key in selected}
    fn = {
        "quality": quality_service.run_quality,
        "dedup_exact": dedup_service.run_exact_dedup,
        "dedup_semantic": dedup_service.run_minhash_dedup,
        "embeddings": embeddings_service.run_embeddings,
        "import_hf": importers.run_import_hf,
        "retry_errors": importers.run_retry_errors,
        "normalize": normalization_service.run_normalize,
        "decontaminate": decontamination_service.run_decontamination,
        "redact_pii": redact_service.redact_pii,
        "pii_scan": ai_service.run_pii_scan,
        "caption": ai_service.run_caption,
        "preannotate": ai_service.run_preannotate,
        "label_issues": ai_service.run_label_issues,
    }.get(job_type)
    if fn is None:
        raise HTTPException(400, f"unknown job type: {job_type}")
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type=job_type, dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, fn, cfg)
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    if not jobrunner.cancel_job(job_id):
        raise HTTPException(409, "job not running")
    return {"job_id": job_id, "status": "cancelled"}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, session: Session = Depends(get_session)):
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job


@app.get("/api/datasets/{ds_id}/jobs")
def list_jobs(ds_id: str, session: Session = Depends(get_session)):
    return session.exec(select(Job).where(Job.dataset_id == ds_id)).all()


# ---------- items ----------

def _preview_for(it, size: int = 512) -> str:
    """Primeiros bytes do arquivo do item, para listas."""
    if it is None or not it.storage_uri:
        return ""
    try:
        path = get_settings().data_dir / it.storage_uri
        if path.is_file():
            return path.open("rb").read(size).decode("utf-8", errors="replace").strip()
    except OSError:
        pass
    return ""


@app.get("/api/datasets/{ds_id}/items")
def list_items(ds_id: str, q: str = "", status: str = "", issue: str = "",
               tag: str = "", license: str = "",
               label: str = "", order: str = "", queue: str = "",
               limit: int = 1000, offset: int = 0,
               session: Session = Depends(get_session)):
    from .services.filters import count_items, page_items
    f = {"q": q, "status": status, "issue": issue, "tag": tag,
         "license": license, "label": label, "order": order, "queue": queue}
    total = count_items(session, ds_id, f)
    items = page_items(session, ds_id, f, max(1, min(limit, 5000)), max(0, offset))
    s_cfg = get_settings()
    rows = []
    for it in items:
        d = it.model_dump()
        d["preview"] = _preview_for(it)
        rows.append(d)
    return JSONResponse(content=jsonable_encoder(rows),
                        headers={"X-Total-Count": str(total)})


def _explorer_status(status: str, kind: str) -> str:
    if kind == "preference":
        return {"approved": "keep", "rejected": "reject", "pending": "review"}.get(status, status)
    return status or "pending"


def _explorer_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(_explorer_text(v) for v in value)
    if isinstance(value, dict):
        return " ".join(_explorer_text(v) for v in value.values())
    return str(value or "")


@app.get("/api/datasets/{ds_id}/explorer")
def explorer_records(ds_id: str, q: str = "", status: str = "", issue: str = "",
                     record_filter: str = "", order: str = "recent",
                     limit: int = 100, offset: int = 0,
                     session: Session = Depends(get_session)):
    """Return one stable record envelope for text, chat, SFT, DPO and traces."""
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    issue_ids = set(session.exec(select(TextIssue.text_id).where(
        TextIssue.dataset_id == ds_id, TextIssue.issue_type == issue,
        TextIssue.status == "open")).all()) if issue else set()
    records: list[dict[str, Any]] = []

    for item in session.exec(select(TextItem).where(TextItem.dataset_id == ds_id)).all():
        if issue and item.id not in issue_ids:
            continue
        preview = _preview_for(item, 240)
        records.append({
            "id": item.id, "kind": "text", "title": item.original_filename,
            "preview": preview, "status": item.decision_status or "pending",
            "tokens": item.tokens, "language": item.language, "created_at": item.created_at.isoformat(),
            "payload": {"mime_type": item.mime_type, "char_count": item.char_count,
                        "word_count": item.word_count, "relative_path": item.relative_path},
        })

    conversations = session.exec(select(Conversation).where(Conversation.dataset_id == ds_id)).all()
    turns = session.exec(select(TextTurn).where(TextTurn.dataset_id == ds_id)
                         .order_by(TextTurn.conversation_id, TextTurn.turn_index)).all()
    turns_by_conv: dict[str, list[dict[str, Any]]] = {}
    for turn in turns:
        turns_by_conv.setdefault(turn.conversation_id, []).append({
            "id": turn.id, "role": turn.role, "content": turn.content,
            "tokens": turn.tokens, "tool_calls": turn.tool_calls, "agent_trace": turn.agent_trace,
        })
    for conv in conversations:
        conv_turns = turns_by_conv.get(conv.id, [])
        has_tools = any(t["tool_calls"] or t["agent_trace"] for t in conv_turns)
        missing_final = bool(conv_turns) and conv_turns[-1]["role"] not in ("assistant", "tool")
        if record_filter == "has_tool_calls" and not has_tools:
            continue
        if record_filter == "missing_final" and not missing_final:
            continue
        records.append({
            "id": conv.id, "kind": "conversation", "title": conv.title or f"conversation-{conv.id[:8]}",
            "preview": conv_turns[0]["content"] if conv_turns else "",
            "status": conv.decision_status or "pending", "tokens": conv.total_tokens,
            "language": conv.language, "created_at": conv.created_at.isoformat(),
            "payload": {"conversation_type": conv.conversation_type, "turns": conv_turns,
                        "turn_count": conv.turn_count, "has_tool_calls": has_tools},
        })

    for pair in session.exec(select(PreferencePair).where(PreferencePair.dataset_id == ds_id)).all():
        records.append({
            "id": pair.id, "kind": "preference", "title": f"preference-{pair.id[:8]}",
            "preview": pair.prompt_text[:240], "status": _explorer_status(pair.status, "preference"),
            "tokens": sum(len(x) // 4 for x in (pair.prompt_text, pair.chosen_text, pair.rejected_text)),
            "language": "", "created_at": pair.created_at.isoformat(),
            "payload": {"prompt": pair.prompt_text, "chosen": pair.chosen_text,
                        "rejected": pair.rejected_text, "strategy": pair.strategy},
        })

    for record in session.exec(select(SFTRecord).where(SFTRecord.dataset_id == ds_id)).all():
        if record.conversation_id:
            continue
        records.append({
            "id": record.id, "kind": "sft", "title": f"sft-{record.id[:8]}",
            "preview": _explorer_text(record.messages)[:240],
            "status": record.status or "pending", "tokens": record.tokens,
            "language": "", "created_at": record.created_at.isoformat(),
            "payload": {"messages": record.messages, "system_prompt": record.system_prompt,
                        "schema_type": record.schema_type},
        })

    for trace in session.exec(select(AgentTrace).where(AgentTrace.dataset_id == ds_id)).all():
        trace_text = _explorer_text(trace.trace_json)
        has_tools = any(k in trace_text.lower() for k in ("tool_call", "tool_calls", "function"))
        missing_final = trace.success is False or bool(trace.error) or "final" not in trace_text.lower()
        if record_filter == "has_tool_calls" and not has_tools:
            continue
        if record_filter == "missing_final" and not missing_final:
            continue
        records.append({
            "id": trace.id, "kind": "trace", "title": trace.trace_id or f"trace-{trace.id[:8]}",
            "preview": trace_text[:240],
            "status": "keep" if trace.success else "review", "tokens": trace.tokens,
            "language": "", "created_at": trace.created_at.isoformat(),
            "payload": {"trace_type": trace.trace_type, "trace": trace.trace_json,
                        "model": trace.model, "success": trace.success, "error": trace.error},
        })

    if record_filter in {"text", "conversation", "preference", "sft"}:
        records = [r for r in records if r["kind"] == record_filter]
    elif record_filter in {"has_tool_calls", "missing_final"}:
        records = [r for r in records if r["kind"] in {"conversation", "trace"}]

    query = q.strip().lower()
    if query:
        records = [r for r in records if query in f"{r['title']} {r['preview']} {_explorer_text(r['payload'])}".lower()]
    if status:
        records = [r for r in records if r["status"] == status]
    if order == "tokens":
        records.sort(key=lambda r: (r["tokens"], r["title"].lower()))
    elif order == "name":
        records.sort(key=lambda r: r["title"].lower())
    elif order == "pending_first":
        priority = {"review": 0, "quarantine": 1, "pending": 2, "keep": 3, "reject": 4}
        records.sort(key=lambda r: (priority.get(r["status"], 5), r["title"].lower()))
    else:
        records.sort(key=lambda r: r["created_at"], reverse=True)
    total = len(records)
    return {"records": records[offset:offset + max(1, min(limit, 500))], "total": total}


@app.get("/api/items/{item_id}")
def get_item(item_id: str, session: Session = Depends(get_session)):
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    issues = session.exec(select(TextIssue).where(TextIssue.text_id == item_id)).all()
    labels = session.exec(select(TextLabel).where(TextLabel.text_id == item_id)).all()
    caption = None
    s_cfg = get_settings()
    text_content = ""
    if it.storage_uri:
        path = s_cfg.data_dir / it.storage_uri
        if path.is_file():
            text_content = path.read_text("utf-8", errors="replace")[:200_000]
    return {"item": {**it.model_dump(), "text_content": text_content},
            "issues": issues, "labels": labels, "caption": caption}


@app.get("/api/items/{item_id}/text")
def get_item_text(item_id: str, if_none_match: str | None = Header(None),
                  session: Session = Depends(get_session)):
    """Return the text content of an item."""
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    s = get_settings()
    p = s.data_dir / it.storage_uri if it.storage_uri else None
    if not p or not p.exists():
        if not _safe_path(Path(it.source_uri.split(":", 1)[1]), s):
            raise HTTPException(403, "path inacessível")
        p = Path(it.source_uri.split(":", 1)[1])
    etag = f'"{item_id}:{it.text_hash_sha256}"'
    if if_none_match == etag:
        return Response(status_code=304, headers={"ETag": etag})
    return PlainTextResponse(p.read_text(encoding="utf-8", errors="replace"),
                             headers={"ETag": etag, "Cache-Control": "private, max-age=86400"})


@app.patch("/api/items/{item_id}/decision")
def set_decision(item_id: str, body: DecisionIn, session: Session = Depends(get_session)):
    it = versions_service.set_decision(session, item_id, body.decision, body.reason, body.reviewer)
    return it


@app.patch("/api/explorer/{record_id}/decision")
def set_explorer_decision(record_id: str, body: DecisionIn, session: Session = Depends(get_session)):
    """Persist the common review decision for structured conversation records."""
    conversation = session.get(Conversation, record_id)
    if conversation is None:
        raise HTTPException(404, "conversation record not found")
    conversation.decision_status = body.decision
    conversation.updated_at = datetime.now(UTC)
    session.add(conversation)
    session.commit()
    session.refresh(conversation)
    return conversation


@app.patch("/api/items/{item_id}/tags")
def set_tags(item_id: str, body: TagIn, session: Session = Depends(get_session)):
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    it.tags_json = body.tags
    session.add(it)
    session.commit()
    session.refresh(it)
    return it.model_dump()


@app.get("/api/items/{item_id}/stats")
def get_stats(item_id: str, session: Session = Depends(get_session)):
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    return {
        "char_count": it.char_count, "word_count": it.word_count, "line_count": it.line_count,
        "tokens": it.tokens, "language": it.language, "has_html": it.has_html,
        "has_unicode_normalization_issues": it.has_unicode_normalization_issues,
        "has_whitespace_issues": it.has_whitespace_issues,
    }


# ---------- issues ----------

@app.get("/api/datasets/{ds_id}/issues")
def list_issues(ds_id: str, issue_type: str = "", status: str = "open",
                order_by_score: bool = True, limit: int = 500,
                session: Session = Depends(get_session)):
    stmt = select(TextIssue).where(TextIssue.dataset_id == ds_id)
    if status:
        stmt = stmt.where(TextIssue.status == status)
    if issue_type:
        stmt = stmt.where(TextIssue.issue_type == issue_type)
    issues = session.exec(stmt.limit(limit)).all()
    if order_by_score:
        issues.sort(key=lambda i: -i.score)
    _ids = list({i.text_id for i in issues})
    _by = {}
    if _ids:
        for it in session.exec(select(TextItem).where(TextItem.id.in_(_ids))).all():
            _by[it.id] = it
    return [{**iss.model_dump(),
             "original_filename": _by[iss.text_id].original_filename if iss.text_id in _by else None,
             "char_count": _by[iss.text_id].char_count if iss.text_id in _by else None,
             "word_count": _by[iss.text_id].word_count if iss.text_id in _by else None,
             "tokens": _by[iss.text_id].tokens if iss.text_id in _by else None,
             "language": _by[iss.text_id].language if iss.text_id in _by else None,
             "ingest_status": _by[iss.text_id].ingest_status if iss.text_id in _by else None,
             "preview": _preview_for(_by.get(iss.text_id))}
            for iss in issues]


@app.patch("/api/issues/{issue_id}/ack")
def ack_issue(issue_id: str, body: IssueAckIn, session: Session = Depends(get_session)):
    iss = session.get(TextIssue, issue_id)
    if iss is None:
        raise HTTPException(404, "issue not found")
    iss.status = body.status
    iss.reviewed_by = body.reviewer
    iss.reviewed_at = datetime.now(UTC)
    session.add(iss)
    session.commit()
    return iss


# ---------- labels ----------

@app.post("/api/items/{item_id}/labels", status_code=201)
def add_label(item_id: str, body: TextLabelIn, session: Session = Depends(get_session)):
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    lb = TextLabel(text_id=item_id, label_type=body.label_type, category=body.category,
                   value_json=body.value, span_start=body.span_start, span_end=body.span_end,
                   source_type=body.source_type, confidence=body.confidence,
                   supersedes_id=body.supersedes_id,
                   status="approved" if body.source_type == "human" else "pending")
    if body.supersedes_id:
        old = session.get(TextLabel, body.supersedes_id)
        if old:
            old.superseded_at = datetime.now(UTC)
            session.add(old)
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


@app.patch("/api/labels/{label_id}")
def patch_label(label_id: str, body: TextLabelPatch, session: Session = Depends(get_session)):
    lb = session.get(TextLabel, label_id)
    if lb is None:
        raise HTTPException(404, "label not found")
    if body.category is not None:
        category = body.category.strip()
        if not category:
            raise HTTPException(400, "category cannot be empty")
        lb.category = category
    session.add(lb)
    session.commit()
    session.refresh(lb)
    return lb


@app.patch("/api/labels/{label_id}/review")
def review_label(label_id: str, body: dict, session: Session = Depends(get_session)):
    lb = session.get(TextLabel, label_id)
    if lb is None:
        raise HTTPException(404, "label not found")
    new_status = body.get("status")
    if new_status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be approved|rejected")
    lb.status = new_status
    session.add(lb)
    session.add(TextReviewDecision(target_type="label", target_id=label_id,
                                   reviewer_id=body.get("reviewer", "local"),
                                   decision=new_status, comment=body.get("comment", "")))
    session.commit()
    return lb


# ---------- versions ----------

@app.post("/api/datasets/{ds_id}/versions", status_code=201)
def create_version(ds_id: str, body: VersionIn, session: Session = Depends(get_session)):
    return versions_service.create_version(session, ds_id, body.description)


@app.get("/api/datasets/{ds_id}/versions")
def list_versions(ds_id: str, session: Session = Depends(get_session)):
    return session.exec(select(DatasetVersion).where(
        DatasetVersion.dataset_id == ds_id)).all()


@app.get("/api/datasets/{ds_id}/versions/diff")
def version_diff(ds_id: str, old: str, new: str, session: Session = Depends(get_session)):
    return versions_service.diff_versions(session, ds_id, old, new)


@app.post("/api/datasets/{ds_id}/versions/{version_id}/restore")
def restore_version(ds_id: str, version_id: str, session: Session = Depends(get_session)):
    v = session.get(DatasetVersion, version_id)
    if v is None or v.dataset_id != ds_id:
        raise HTTPException(404, "version not found")
    keep_ids = {e["item_id"] for e in v.snapshot_json}
    for it in session.exec(select(TextItem).where(TextItem.dataset_id == ds_id)).all():
        want = "keep" if it.id in keep_ids else "quarantine"
        if it.decision_status in ("keep", "restore", "quarantine"):
            it.decision_status = want
            session.add(it)
    ds = session.get(Dataset, ds_id)
    assert ds is not None
    ds.current_version_id = version_id
    session.add(ds)
    session.add(TextReviewDecision(
        target_type="dataset", target_id=ds_id,
        reviewer_id="local-operator", decision="restore",
        comment=f"restore da versão {version_id[:8]} ({v.description[:40]})"))
    session.commit()
    return {"restored_version": version_id}


# ---------- semantic search & clusters ----------

@app.get("/api/datasets/{ds_id}/clusters")
def get_clusters(ds_id: str, k: int = 8, session: Session = Depends(get_session)):
    try:
        return embeddings_service.clusters(session, ds_id, k)
    except RuntimeError as exc:
        raise HTTPException(501, str(exc)) from exc


@app.get("/api/datasets/{ds_id}/search")
def semantic_search(ds_id: str, q: str = "", limit: int = 50, status: str = "",
                    license: str = "", tag: str = "", issue: str = "",
                    session: Session = Depends(get_session)):
    """Busca semântica por texto (embeddings) com filtros de metadata."""
    if not q:
        raise HTTPException(400, "provide q (text query)")
    filters = {k: v for k, v in {"status": status, "license": license,
                                  "tag": tag, "issue": issue}.items() if v}
    try:
        results = embeddings_service.semantic_search(session, ds_id, q, "text", None, limit, filters or None)
        s_cfg = get_settings()
        rows = []
        for row in results:
            it = row["item"]
            d = it.model_dump()
            d["preview"] = _preview_for(it)
            d["score"] = row["score"]
            rows.append(d)
        return JSONResponse(content=jsonable_encoder(rows))
    except RuntimeError as exc:
        raise HTTPException(501, str(exc)) from exc


# ---------- derive / merge / split ----------

class DeriveIn(BaseModel):
    name: str
    description: str = ""
    filters: dict[str, Any] = {}


class MergeIn(BaseModel):
    dataset_ids: list[str]
    name: str


class SplitIn(BaseModel):
    ratios: list[PositiveFloat] = Field(min_length=1)
    seed: int = 0


@app.post("/api/datasets/{ds_id}/derive", status_code=201)
def derive_dataset(ds_id: str, body: DeriveIn, session: Session = Depends(get_session)):
    from .services import derive_service
    return derive_service.derive(session, ds_id, body.name, body.description, body.filters)


@app.post("/api/datasets/merge", status_code=201)
def merge_datasets(body: MergeIn, session: Session = Depends(get_session)):
    from .services import derive_service
    return derive_service.merge(session, body.dataset_ids, body.name)


@app.post("/api/datasets/{ds_id}/split", status_code=201)
def split_dataset(ds_id: str, body: SplitIn, session: Session = Depends(get_session)):
    from .services import derive_service
    return derive_service.split(session, ds_id, body.ratios, body.seed)

# ---------- sampling & mixing (amostragem, diversidade, recipes) ----------
class SampleIn(BaseModel):
    size: int = Field(gt=0)
    method: str = "random"   # random | diverse | important
    seed: int = 0
    name: str = ""

class MixSourceIn(BaseModel):
    dataset_id: str
    weight: float = 1.0

class MixIn(BaseModel):
    sources: list[MixSourceIn] = Field(min_length=1)
    name: str
    size: int = 0
    seed: int = 0
    recipe: dict | None = None

@app.post("/api/datasets/{ds_id}/sample", status_code=201)
def sample_dataset(ds_id: str, body: SampleIn, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    return sampling_service.sample(session, ds_id, body.size, body.method,
                                  body.seed, body.name)

@app.post("/api/datasets/mix", status_code=201)
def mix_with_weights(body: MixIn, session: Session = Depends(get_session)):
    return sampling_service.mix_sources(
        session, [s.model_dump() for s in body.sources], body.name,
        body.size, body.seed, body.recipe)


# ---------- license per item ----------

@app.patch("/api/items/{item_id}/license")
def set_item_license(item_id: str, body: dict, session: Session = Depends(get_session)):
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    it.license = str(body.get("license", "unknown"))
    it.license_evidence_uri = str(body.get("license_evidence_uri", ""))
    session.add(it)
    session.commit()
    session.refresh(it)
    return it.model_dump()


# ---------- generated text (replaces captions) ----------

class GenTextIn(BaseModel):
    text: str
    status: str = "approved"


@app.get("/api/items/{item_id}/caption")
def get_caption(item_id: str, session: Session = Depends(get_session)):
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    cap = session.exec(select(Caption).where(
        Caption.text_id == item_id,
        Caption.superseded_at.is_(None)).order_by(Caption.created_at.desc())).first()
    return cap if cap else {}


@app.patch("/api/items/{item_id}/caption")
def set_caption(item_id: str, body: GenTextIn, session: Session = Depends(get_session)):
    it = session.get(TextItem, item_id)
    if it is None:
        raise HTTPException(404, "item not found")
    for old in session.exec(select(Caption).where(
            Caption.text_id == item_id,
            Caption.superseded_at.is_(None))).all():
        old.superseded_at = datetime.now(UTC)
        session.add(old)
    cap = Caption(text_id=item_id, text=body.text.strip(),
                   source_type="human", status=body.status)
    session.add(cap)
    session.commit()
    session.refresh(cap)
    return cap


@app.patch("/api/captions/{caption_id}/review")
def review_caption(caption_id: str, body: dict, session: Session = Depends(get_session)):
    cap = session.get(Caption, caption_id)
    if cap is None:
        raise HTTPException(404, "caption not found")
    status = str(body.get("status", ""))
    if status not in ("approved", "pending", "rejected"):
        raise HTTPException(400, "status must be approved | pending | rejected")
    cap.status = status
    session.add(cap)
    session.commit()
    session.refresh(cap)
    return cap


# ---------- conversations & turns ----------

@app.get("/api/conversations")
def list_conversations(dataset_id: str, session: Session = Depends(get_session)):
    """List conversations for a dataset (the dataset detail endpoint does not inline them)."""
    if not dataset_id:
        raise HTTPException(400, "dataset_id is required")
    ds = session.get(Dataset, dataset_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    return session.exec(select(Conversation).where(
        Conversation.dataset_id == dataset_id)).all()


@app.post("/api/conversations", status_code=201)
def create_conversation(body: dict, session: Session = Depends(get_session)):
    conv = Conversation(
        dataset_id=body["dataset_id"],
        title=body.get("title", ""),
        source_uri=body.get("source_uri", ""),
        conversation_type=body.get("conversation_type", "sft"),
        language=body.get("language", ""),
        tags_json=body.get("tags", []),
        license=body.get("license", "unknown"),
    )
    session.add(conv)
    session.commit()
    session.refresh(conv)
    return conv


@app.get("/api/conversations/{conv_id}")
def get_conversation(conv_id: str, session: Session = Depends(get_session)):
    conv = session.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    turns = session.exec(select(TextTurn).where(
        TextTurn.conversation_id == conv_id).order_by(TextTurn.turn_index)).all()
    return {"conversation": conv, "turns": turns}


@app.post("/api/conversations/{conv_id}/turns", status_code=201)
def add_turn(conv_id: str, body: TurnIn, session: Session = Depends(get_session)):
    conv = session.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(404, "conversation not found")
    import hashlib
    content_hash = hashlib.sha256(body.content.encode("utf-8", errors="replace")).hexdigest()
    turn = TextTurn(
        conversation_id=conv_id,
        dataset_id=conv.dataset_id,
        role=body.role,
        content=body.content,
        content_hash_sha256=content_hash,
        tokens=body.tokens,
        token_estimator=body.token_estimator,
        turn_index=conv.turn_count,
        tool_calls=body.tool_calls,
        tool_call_id=body.tool_call_id,
        agent_trace=body.agent_trace,
        parent_turn_id=body.parent_turn_id,
    )
    session.add(turn)
    conv.turn_count = conv.turn_count + 1
    conv.total_tokens = conv.total_tokens + body.tokens
    session.add(conv)
    session.commit()
    session.refresh(turn)
    return turn


# ---------- preference pairs ----------

@app.post("/api/datasets/{ds_id}/preference-pairs", status_code=201)
def create_preference_pair(ds_id: str, body: PreferenceIn, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    pair = PreferencePair(
        dataset_id=ds_id,
        prompt_text=body.prompt_text,
        chosen_text=body.chosen_text,
        rejected_text=body.rejected_text,
        chosen_turn_id=body.chosen_turn_id,
        rejected_turn_id=body.rejected_turn_id,
        strategy=body.strategy,
    )
    session.add(pair)
    session.commit()
    session.refresh(pair)
    return pair


@app.get("/api/datasets/{ds_id}/preference-pairs")
def list_preference_pairs(ds_id: str, status: str = "", session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    stmt = select(PreferencePair).where(PreferencePair.dataset_id == ds_id)
    if status:
        stmt = stmt.where(PreferencePair.status == status)
    return session.exec(stmt).all()


@app.patch("/api/preference-pairs/{pair_id}/decision")
def decide_preference(pair_id: str, body: PreferenceDecisionIn, session: Session = Depends(get_session)):
    pair = session.get(PreferencePair, pair_id)
    if pair is None:
        raise HTTPException(404, "preference pair not found")
    pair.reviewer = body.reviewer
    if body.decision == "b":
        pair.chosen_text, pair.rejected_text = pair.rejected_text, pair.chosen_text
        pair.status = "approved"
    elif body.decision == "a":
        pair.status = "approved"
    elif body.decision == "tie":
        pair.status = "rejected"
        pair.strategy = "manual_tie"
    else:
        pair.status = "pending"
    session.add(pair)
    session.commit()
    session.refresh(pair)
    return pair


# ---------- SFT records ----------

@app.post("/api/datasets/{ds_id}/sft-records", status_code=201)
def create_sft_record(ds_id: str, body: SFTRecordIn, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    record = SFTRecord(
        dataset_id=ds_id,
        messages=body.messages,
        system_prompt=body.system_prompt,
        tokens=body.tokens,
        schema_type=body.schema_type,
        source_type=body.source_type,
        source_id=body.source_id,
        license=body.license,
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@app.get("/api/datasets/{ds_id}/sft-records")
def list_sft_records(ds_id: str, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    return session.exec(select(SFTRecord).where(SFTRecord.dataset_id == ds_id)).all()


# ---------- agent traces ----------

@app.post("/api/datasets/{ds_id}/traces", status_code=201)
def create_trace(ds_id: str, body: AgentTraceIn, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    trace = AgentTrace(
        dataset_id=ds_id,
        trace_type=body.trace_type,
        trace_id=body.trace_id,
        trace_json=body.trace_json,
        tokens=body.tokens,
        model=body.model,
        duration_ms=body.duration_ms,
        success=body.success,
        error=body.error,
    )
    session.add(trace)
    session.commit()
    session.refresh(trace)
    return trace


@app.get("/api/datasets/{ds_id}/traces")
def list_traces(ds_id: str, session: Session = Depends(get_session)):
    ds = session.get(Dataset, ds_id)
    if ds is None:
        raise HTTPException(404, "dataset not found")
    return session.exec(select(AgentTrace).where(AgentTrace.dataset_id == ds_id)).all()


# ---------- providers ----------

@app.get("/api/providers")
def providers_status():
    from .providers.base import status
    return status()


@app.get("/api/provider-settings")
def provider_settings():
    return public_provider_settings()


@app.patch("/api/provider-settings")
def patch_provider_settings(body: dict):
    return update_provider_settings(body)


# ---------- model/plugin catalog ----------

@app.get("/api/model-catalog")
def model_catalog_status():
    state = model_catalog.read_settings()
    return {"models": model_catalog.list_catalog(), "plugins": model_catalog.plugins(),
            "automation": state.get("automation", {})}


@app.post("/api/models/{model_id}/install", status_code=202)
def install_model(model_id: str, body: dict | None = None):
    body = body or {}
    try:
        return model_catalog.install_model(
            model_id, str(body.get("source", "")), str(body.get("sha256", "")),
            license_ack=bool(body.get("license_ack", False)))
    except KeyError as exc:
        raise HTTPException(404, "model not found") from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/models/{model_id}/uninstall")
def uninstall_model(model_id: str):
    try:
        return model_catalog.uninstall_model(model_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.patch("/api/models/{model_id}/active")
def activate_model(model_id: str, body: dict):
    try:
        return model_catalog.set_active(str(body.get("capability", "")), model_id)
    except KeyError as exc:
        raise HTTPException(404, "model not found") from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@app.patch("/api/model-automation/{capability}")
def update_model_automation(capability: str, body: dict):
    return model_catalog.set_automation(
        capability, bool(body.get("enabled", False)),
        float(body.get("confidence", 0.95)),
        bool(body.get("preview", True)),
        bool(body.get("auto_quarantine", False)))


@app.post("/api/plugins/install", status_code=201)
def install_plugin(body: dict):
    try:
        return model_catalog.install_plugin(str(body.get("path", "")))
    except (ValueError, OSError, zipfile.BadZipFile) as exc:
        raise HTTPException(400, str(exc)) from exc


@app.post("/api/plugins/{plugin_id}/uninstall")
def uninstall_plugin(plugin_id: str):
    try:
        return model_catalog.uninstall_plugin(plugin_id)
    except KeyError as exc:
        raise HTTPException(404, "plugin not found") from exc


@app.post("/api/plugins/{plugin_id}/invoke")
def invoke_plugin(plugin_id: str, body: dict):
    try:
        return plugin_runtime.invoke(plugin_id, str(body.get("capability", "")),
                                     body.get("payload", {}), int(body.get("timeout", 600)))
    except plugin_runtime.PluginError as exc:
        raise HTTPException(409, str(exc)) from exc


# ---------- AI-powered jobs ----------

@app.post("/api/datasets/{ds_id}/preannotate", status_code=202)
def preannotate(ds_id: str, body: dict | None = None, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type="preannotate", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ai_service.run_preannotate, body or {})
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/datasets/{ds_id}/label-issues", status_code=202)
def label_issues(ds_id: str, body: dict | None = None, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type="label_issues", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ai_service.run_label_issues, body or {})
    return {"job_id": job_id, "status": "queued"}


@app.post("/api/datasets/{ds_id}/pii-scan", status_code=202)
def pii_scan(ds_id: str, body: dict | None = None, session: Session = Depends(get_session)):
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    job = Job(type="pii_scan", dataset_id=ds_id)
    job_id = jobrunner.spawn_job(job, ai_service.run_pii_scan, body or {})
    return {"job_id": job_id, "status": "queued"}


# ---------- export ----------

@app.post("/api/datasets/{ds_id}/export")
def export_dataset(ds_id: str, body: ExportIn, session: Session = Depends(get_session)):
    try:
        return export(session, ds_id, body.fmt, body.version_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"export failed: {exc}") from exc


@app.get("/api/datasets/{ds_id}/exports")
def list_exports(ds_id: str, fmt: str = "", session: Session = Depends(get_session)):
    stmt = (select(ExportRecord).where(ExportRecord.dataset_id == ds_id)
             .order_by(ExportRecord.created_at.desc()))
    if fmt:
        stmt = stmt.where(ExportRecord.fmt == fmt)
    recs = session.exec(stmt).all()
    return [{"id": r.id, "fmt": r.fmt, "version_id": r.version_id or "",
             "path": r.path, "item_count": r.item_count,
             "created_at": r.created_at.isoformat()} for r in recs]


# ---------- wave-3: duplicates, derive-from ----------

@app.get("/api/datasets/{ds_id}/duplicates")
def list_duplicates(ds_id: str, session: Session = Depends(get_session)):
    """Grupos de duplicatas com membros (item + is_canonical + score de similaridade)."""
    from .models import DuplicateGroup, DuplicateMember
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    groups = session.exec(select(DuplicateGroup).where(
        DuplicateGroup.dataset_id == ds_id)).all()
    out = []
    for g in groups:
        members = session.exec(select(DuplicateMember).where(
            DuplicateMember.group_id == g.id)).all()
        rows = []
        for m in members:
            it = session.get(TextItem, m.text_id)
            if it is None:
                continue
            rows.append({"text_id": m.text_id, "is_canonical": m.is_canonical,
                         "similarity": m.similarity,
                         "original_filename": it.original_filename,
                         "decision_status": it.decision_status,
                         "preview": _preview_for(it, 120)})
        out.append({"group": {"id": g.id, "method": g.method,
                               "threshold": g.threshold}, "members": rows})
    return out


@app.patch("/api/duplicates/groups/{group_id}/canonical/{item_id}")
def swap_canonical(group_id: str, item_id: str, session: Session = Depends(get_session)):
    try:
        return dedup_service.swap_canonical(session, group_id, item_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc


class DeriveFromIn(BaseModel):
    name: str
    item_ids: list[str] = []
    group_id: str = ""
    cluster_index: int = -1
    outliers: bool = False
    k: int = 8


@app.post("/api/datasets/{ds_id}/derive-from", status_code=201)
def derive_from(ds_id: str, body: DeriveFromIn, session: Session = Depends(get_session)):
    from .models import DuplicateMember
    if session.get(Dataset, ds_id) is None:
        raise HTTPException(404, "dataset not found")
    ids = body.item_ids
    note = ""
    if body.group_id:
        ids = [m.text_id for m in session.exec(select(DuplicateMember).where(
            DuplicateMember.group_id == body.group_id)).all()]
        note = f"dup-group {body.group_id[:8]}"
    elif body.outliers or body.cluster_index >= 0:
        cl = embeddings_service.clusters(session, ds_id, body.k)
        if body.outliers:
            ids = [o["text_id"] for o in cl.get("outliers", [])]
            note = "outliers"
        elif body.cluster_index < len(cl.get("clusters", [])):
            ids = [m for m in cl["clusters"][body.cluster_index]["members"]]
            note = f"cluster {body.cluster_index}"
    if not ids:
        raise HTTPException(400, "nenhum item para derivar (especifique item_ids, group_id, cluster_index ou outliers)")
    out = dedup_service.derive_from_items(session, body.name, ds_id, ids, note)
    out["note"] = note
    return out


@app.get("/api/datasets/{ds_id}/items-by-label")
def items_by_label(ds_id: str, category: str = "", label_type: str = "",
                   session: Session = Depends(get_session)):
    stmt = select(TextLabel.text_id, TextLabel.category, TextLabel.label_type, TextLabel.status).where(
        TextLabel.status == "approved")
    rows = session.exec(stmt).all()
    by_cat: dict[str, list[str]] = {}
    for tid, cat, ltype, _st in rows:
        item = session.get(TextItem, tid)
        if item is None or item.dataset_id != ds_id:
            continue
        if category and cat != category:
            continue
        if label_type and ltype != label_type:
            continue
        by_cat.setdefault(cat, []).append(tid)
    return {"categories": {c: sorted(v) for c, v in by_cat.items()},
            "total": sum(len(v) for v in by_cat.values())}


# ---------- single-process deployment: serve the built frontend ----------
from fastapi.staticfiles import StaticFiles  # noqa: E402

_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _dist.is_dir():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
