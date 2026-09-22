"""Exportações para o domínio de texto: JSONL, Parquet, Hugging Face, manifest e relatório.

Formatos suportados: jsonl, parquet, hf, manifest, report.
Tudo no data_dir export/, organizado por dataset_id + timestamp.
"""
import csv
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlmodel import Session, select

from ..config import get_settings
from ..models import (Dataset, DatasetVersion, ExportRecord, TextItem, TextIssue,
                       TextLabel, SFTRecord, PreferencePair, AgentTrace)


def _active_items(session: Session, dataset_id: str) -> list[TextItem]:
    return session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id,
        TextItem.decision_status.in_(("keep", "restore")))).all()


def _active_issues(session: Session, dataset_id: str) -> list[TextIssue]:
    return session.exec(select(TextIssue).where(
        TextIssue.dataset_id == dataset_id)).all()


def _item_labels(session: Session, text_id: str) -> list[TextLabel]:
    return session.exec(select(TextLabel).where(
        TextLabel.text_id == text_id, TextLabel.status == "approved")).all()


def export(session: Session, dataset_id: str, fmt: str = "jsonl",
          version_id: str | None = None) -> dict[str, Any]:
    s = get_settings()
    ds = session.get(Dataset, dataset_id)
    assert ds is not None
    version = session.get(DatasetVersion, version_id) if version_id else None
    # sem version_id: exporta o estado VIVO (keep|restore atuais);
    # version_id explícito: pacote reflete o snapshot do checkpoint.

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    out_dir = s.exports_dir / dataset_id[:8] / f"{fmt}-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Fase 9.2.6/§10: policy exige licença válida => bloqueia itens com licença 'unknown'
    policy = (ds.license_policy or "permissive").lower()
    items = _active_items(session, dataset_id)
    if policy == "strict":
        bad = [it for it in items if (it.license or "unknown") == "unknown"]
        if bad:
            raise RuntimeError(
                f"strict license policy blocks export: {len(bad)} items have no defined license. "
                f"Set licenses or PATCH dataset.license_policy='permissive'.")

    # Export versionado (§12): quando checkpoint explícito é pedido, reflete o snapshot
    snap_labels: dict[str, list[dict[str, Any]]] = {}
    snap_decision: dict[str, str] = {}
    if version_id and version and version.snapshot_json:
        wanted = [e["item_id"] for e in version.snapshot_json]
        by_id = {it.id: it for it in items}
        items = [by_id[i] for i in wanted if i in by_id]
        for e in version.snapshot_json:
            snap_labels[e["item_id"]] = e.get("labels", [])
            snap_decision[e["item_id"]] = e.get("decision", "")

    counts = {"keep": 0, "quarantine": 0, "reject": 0, "review": 0}
    all_items = session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id)).all()
    for it in all_items:
        if it.decision_status in counts:
            counts[it.decision_status] += 1

    def _item_decision(it: TextItem) -> str:
        return snap_decision.get(it.id) or it.decision_status

    manifest_rows: list[dict[str, Any]] = []
    for it in items:
        labels = snap_labels.get(it.id) if snap_labels else _item_labels(session, it.id)
        manifest_rows.append({
            "item_id": it.id, "source_uri": it.source_uri,
            "storage_uri": it.storage_uri, "output_uri": it.storage_uri,
            "sha256": it.content_hash_sha256, "text_hash": it.text_hash_sha256,
            "char_count": it.char_count, "word_count": it.word_count,
            "line_count": it.line_count, "tokens": it.tokens,
            "language": it.language, "has_html": it.has_html,
            "mime_type": it.mime_type, "license": it.license,
            "decision": _item_decision(it),
            "tags": it.tags_json,
            "dataset_version": version.id if version else "",
            "labels": [{"type": lb.label_type, "category": lb.category,
                         "value": lb.value_json, "source_type": lb.source_type,
                         "span_start": lb.span_start, "span_end": lb.span_end,
                         "confidence": lb.confidence, "status": lb.status}
                       for lb in labels],
        })

    for r in manifest_rows:
        r["exported_by"] = "local-operator"
        r["pipeline_version"] = "0.1.0"

    # JSONL (formato nativo)
    jsonl_path = out_dir / "export.jsonl"
    jsonl_path.write_text("\n".join(json.dumps(r) for r in manifest_rows),
                           encoding="utf-8")

    # Manifest (metadados + decisões)
    manifest_path = out_dir / "manifest.jsonl"
    manifest_path.write_text("\n".join(json.dumps(r) for r in manifest_rows),
                              encoding="utf-8")
    # manifest.csv
    if manifest_rows:
        with (out_dir / "manifest.csv").open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(manifest_rows[0].keys()))
            w.writeheader()
            w.writerows(manifest_rows)

    # Parquet (pyarrow é dependência core — export sempre funcional)
    if fmt in ("parquet", "jsonl", "manifest", "hf"):
        import pyarrow as pa
        import pyarrow.parquet as pq
        if manifest_rows:
            scalar = ("item_id", "source_uri", "storage_uri", "output_uri",
                      "sha256", "text_hash", "language", "mime_type", "license",
                      "decision", "dataset_version", "exported_by", "pipeline_version")
            cols = {
                k: [json.dumps(r.get(k)) if k not in scalar else r.get(k)
                    for r in manifest_rows]
                for k in manifest_rows[0].keys()}
            table = pa.table(cols)
            pq.write_table(table, out_dir / "manifest.parquet")

    # ---- training-ready record exports (TRL / OpenAI contracts) ----
    # sft.jsonl: OpenAI/TRL conversational SFT — {"messages":[{role,content}]}
    sft_rows = [{
        "id": r.id, "messages": r.messages, "system_prompt": r.system_prompt,
        "schema_type": r.schema_type, "source_type": r.source_type,
        "license": r.license, "tokens": r.tokens,
    } for r in session.exec(select(SFTRecord).where(
        SFTRecord.dataset_id == dataset_id, SFTRecord.status == "approved")).all()]
    # dpo.jsonl: TRL preference — {"prompt","chosen","rejected"}
    dpo_rows = [{
        "id": p.id, "prompt": p.prompt_text, "chosen": p.chosen_text,
        "rejected": p.rejected_text, "strategy": p.strategy, "status": p.status,
    } for p in session.exec(select(PreferencePair).where(
        PreferencePair.dataset_id == dataset_id, PreferencePair.status == "approved")).all()]
    # traces.jsonl: agent/reasoning traces — trace_json carries the payload
    trace_rows = [{
        "id": t.id, "trace_type": t.trace_type, "trace_id": t.trace_id,
        "model": t.model, "tokens": t.tokens, "duration_ms": t.duration_ms,
        "success": t.success, "error": t.error, "trace": t.trace_json,
    } for t in session.exec(select(AgentTrace).where(
        AgentTrace.dataset_id == dataset_id)).all()]
    record_files: dict[str, list[dict[str, Any]]] = {
        "sft": sft_rows, "dpo": dpo_rows, "traces": trace_rows,
    }
    for name, rows in record_files.items():
        if rows:
            (out_dir / f"{name}.jsonl").write_text(
                "\n".join(json.dumps(r) for r in rows), encoding="utf-8")
            if fmt in ("parquet", "jsonl", "manifest", "hf"):
                import pyarrow as pa
                import pyarrow.parquet as pq
                table = pa.Table.from_pylist(rows)
                pq.write_table(table, out_dir / f"{name}.parquet")

    # Hugging Face format (HF-style folder com dataset_info + parquet + README)
    if fmt == "hf":
        hf_dir = out_dir / "hf_export"
        hf_dir.mkdir(exist_ok=True)
        # dataset_info.json — every present parquet becomes a config
        data_files = [("default", "manifest.parquet")] + [
            (n, f"{n}.parquet") for n in ("sft", "dpo", "traces")
            if (out_dir / f"{n}.parquet").exists()]
        info = {
            "dataset_name": ds.name,
            "description": ds.description,
            "license": ds.license,
            "size_categories": "n<1K" if len(manifest_rows) < 1000 else
                               "n<10K" if len(manifest_rows) < 10000 else "n>=10K",
            "format": "parquet",
            "configs": [{"config_name": n, "data_files": [f]} for n, f in data_files],
        }
        (hf_dir / "dataset_info.json").write_text(json.dumps(info, indent=2),
                                                    encoding="utf-8")
        # copia os parquet presentes para hf_dir
        for _n, f in data_files:
            shutil.copy2(out_dir / f, hf_dir / f)
        # README.md estilo HF
        readme = f"""---
dataset_name: {ds.name}
description: {ds.description}
license: {ds.license}
---

# {ds.name}

{ds.description}

Config: default
Format: parquet
License: {ds.license}
"""
        (hf_dir / "README.md").write_text(readme, encoding="utf-8")

    # relatório de limpeza / inspeção
    issues = _active_issues(session, dataset_id)
    by_type: dict[str, int] = {}
    for iss in issues:
        by_type[iss.issue_type] = by_type.get(iss.issue_type, 0) + 1
    report = {
        "dataset": {"id": dataset_id, "name": ds.name, "version": version.id if version else None},
        "exported_items": len(manifest_rows),
        "decisions": counts,
        "issues_by_type": by_type,
        "training_records": {"sft": len(sft_rows), "dpo": len(dpo_rows),
                                "traces": len(trace_rows)},
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (out_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # ledger de export em DB + retenção: 5 mais recentes por dataset+fmt.
    rec = ExportRecord(dataset_id=dataset_id, fmt=fmt,
                     version_id=version.id if version else "",
                     path=str(out_dir), item_count=len(manifest_rows))
    session.add(rec)
    session.commit()
    old_recs = session.exec(select(ExportRecord).where(
        ExportRecord.dataset_id == dataset_id, ExportRecord.fmt == fmt)
        .order_by(ExportRecord.created_at.desc())).all()  # type: ignore[attr-defined]
    keep_list: list[str] = []
    for r in old_recs:
        if len(keep_list) < 5 and (Path(r.path).is_dir()
                                or Path(str(r.path) + '.zip').exists()):
            keep_list.append(r.id)
        elif r.id != rec.id:
            shutil.rmtree(r.path, ignore_errors=True)
            Path(str(r.path) + ".zip").unlink(missing_ok=True)
            session.delete(r)
    session.commit()
    keep_paths: set[str] = set()
    for i, rid in enumerate(keep_list):
        r = session.get(ExportRecord, rid)
        zp = str(r.path) + ".zip"
        if Path(zp).exists():
            keep_paths.add(zp)
        if i == 0:
            keep_paths.add(r.path)  # dir aberto apenas no mais recente
        else:
            shutil.rmtree(r.path, ignore_errors=True)  # zip basta para os antigos
    for p in (s.exports_dir / dataset_id[:8]).glob(f"{fmt}-*"):
        if str(p) not in keep_paths:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            else:
                p.unlink(missing_ok=True)
    return {"path": str(out_dir), "items": len(manifest_rows),
            "report": report, "export_id": rec.id}