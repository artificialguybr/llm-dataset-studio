"""Pré-anotação por IA e PII — domínio TEXTO.

Providers: pergunta ao modelo ativo (OpenAI, plugins) sobre o TEXTO.
Sugestões salvam como TextLabel source_type=model, status=pending — humano aprova.
PII textual: regex + modelo, vira TextIssue.
"""
from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from ..jobs import is_cancelled, update_progress
from ..models import TextItem, TextIssue, TextLabel, Job, TextReviewDecision
from .. import model_catalog, plugin_runtime
from ..providers.base import active
from ..providers.cloud import call_text
from ..services.quality_service import _read_text

# Prompts para texto (substituem os de imagem)
PROMPT_PREANN = (
    'Classify this text. Respond ONLY minified JSON: '
    '{"labels":[{"category":"topic|sentiment|intent|entity|other",'
    '"span_start":0,"span_end":10,"confidence":0.9}]}. '
    "Spans are character offsets in the original text."
)
PROMPT_PII = (
    "Does this text contain personally identifiable information (emails, phones, "
    "SSNs, credit cards, addresses, names, IDs)? "
    'Respond ONLY minified JSON: {"pii":bool,"types":[str],"evidence":str}.'
)
PROMPT_LABEL_ISSUES = (
    "Given a text and a proposed label, flag potential label errors. "
    'Respond ONLY minified JSON: {"issues":[{"category":"wrong_label|ambiguous|conflict",'
    '"explanation":str,"confidence":float}]}.'
)


def _llm_call(text: str, prompt: str, provider: str, capability: str) -> dict:
    """Chama o LLM ativo (OpenAI-compatível) para texto."""
    return call_text(provider, text, prompt, capability)


def run_label_issues(session: Session, job: Job) -> None:
    """Cleanlab opcional: precisa de pred_probs externas + labels existentes."""
    p = active("label_issues")
    ok, msg = p.available() if p else (False, "no provider registered")
    if not ok:
        raise RuntimeError(f"label-issues provider unavailable — {msg}")
    import numpy as np
    from ..models import TextLabel
    dataset_id = job.dataset_id
    items = session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id,
        TextItem.ingest_status == "done")).all()
    cfg = job.config_json
    probs = np.load(cfg["pred_probs_path"]) if cfg.get("pred_probs_path") else None
    labels = np.array([int(next(iter(
        [int(l.category) for l in session.exec(select(TextLabel).where(
            TextLabel.text_id == it.id, TextLabel.status == "approved")).all()] or [-1])))
        for it in items])
    if probs is None or probs.ndim != 2 or probs.shape[0] != len(items):
        raise RuntimeError("job config requires pred_probs_path (n_items x n_classes matrix)")
    from cleanlab.filter import find_label_issues
    ordered_types = cfg.get("classes", [])
    issues_idx = find_label_issues(labels=labels, pred_probs=probs,
                                    return_indices_ranked_by_score=True)
    for rank, idx in enumerate(issues_idx):
        it = items[int(idx)]
        session.add(TextIssue(
            text_id=it.id, dataset_id=dataset_id, issue_type="possible_label_error",
            score=float(rank) / max(1, len(issues_idx)), threshold=0.0,
            detector_name=p.name, detector_version=p.version,
            evidence_json={"rank": int(rank)}))
    session.commit()
    update_progress(job.id, len(issues_idx), 0, max(len(items), 1))


def _external_plugin(job: Job, capability: str, builtins: set[str], required: bool = False) -> tuple[str, str] | None:
    model_id = str(job.config_json.get("model_id") or model_catalog.active_model(capability) or "")
    if not model_id or model_id in builtins:
        if required:
            raise RuntimeError(f"no installed model is active for {capability}")
        return None
    spec = model_catalog.get_model(model_id)
    if spec.capability != capability:
        raise RuntimeError(f"model {model_id} does not provide {capability}")
    if not model_catalog.plugin_installed(spec.plugin_id):
        raise RuntimeError(f"plugin for {model_id} is not installed")
    return model_id, spec.plugin_id


def _job_items(session: Session, job: Job) -> list[TextItem]:
    query = select(TextItem).where(
        TextItem.dataset_id == job.dataset_id,
        TextItem.ingest_status == "done")
    raw_ids = job.config_json.get("item_ids")
    if isinstance(raw_ids, list):
        ids = {str(value) for value in raw_ids if str(value)}
        if not ids:
            return []
        query = query.where(TextItem.id.in_(ids))
    return session.exec(query).all()


def _plugin_payload(model_id: str, item: TextItem, prompt: str = "") -> dict:
    return {"text_path": str(item.storage_uri), "model_id": model_id,
            "model_path": model_catalog.installed_path(model_id), "prompt": prompt}


def run_preannotate(session: Session, job: Job) -> None:
    external = _external_plugin(job, "preannotation", {"openai-text"})
    model_id, plugin_id = external or (None, None)
    p = active("preannotation")
    ok, msg = p.available() if p else (False, "no provider registered")
    if not external and not ok:
        raise RuntimeError(f"preannotation provider unavailable — {msg}")
    source_id = model_id or (p.name if p else "plugin")
    items = _job_items(session, job)
    total = len(items)
    processed = failed = pending = 0
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            text = _read_text(it)
            if not text:
                failed += 1
                continue
            out = plugin_runtime.invoke(plugin_id, "preannotation", _plugin_payload(model_id, it, PROMPT_PREANN)) if external else _llm_call(text, PROMPT_PREANN, p.name, "preannotation")
            labels = []
            for lb in out.get("labels", []):
                labels.append(TextLabel(
                    text_id=it.id, label_type="span",
                    category=str(lb.get("category", "entity")).strip() or "entity",
                    value_json={"text": text[lb.get("span_start", 0):lb.get("span_end", len(text))]},
                    span_start=lb.get("span_start"), span_end=lb.get("span_end"),
                    source_type="model", source_id=source_id,
                    confidence=_confidence(lb.get("confidence")), status="pending"))
            _save_model_labels(session, job, it, "preannotation", source_id, labels)
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))


def run_pii_scan(session: Session, job: Job) -> None:
    external = _external_plugin(job, "pii", {"openai-text-pii"})
    model_id, plugin_id = external or (None, None)
    p = active("pii")
    ok, msg = p.available() if p else (False, "no provider registered")
    if not external and not ok:
        raise RuntimeError(f"PII provider unavailable — {msg}")
    source_id = model_id or (p.name if p else "plugin")
    dataset_id = job.dataset_id
    items = _job_items(session, job)
    # idempotente: issues possible_pii antigas (do mesmo source) são substituídas
    source_ids = {it.id for it in items}
    if source_ids:
        for old in session.exec(select(TextIssue).where(
                TextIssue.dataset_id == dataset_id,
                TextIssue.issue_type == "possible_pii",
                TextIssue.text_id.in_(source_ids))).all():
            if (old.detector_name or "") == source_id or old.status == "resolved":
                session.delete(old)
        session.commit()
    total = len(items)
    processed = failed = pending = 0
    for it in items:
        if is_cancelled(job.id):
            break
        try:
            text = _read_text(it)
            if not text:
                failed += 1
                continue
            out = plugin_runtime.invoke(plugin_id, "pii", {"text": text, "model_id": model_id, "model_path": model_catalog.installed_path(model_id), "prompt": PROMPT_PII}) if external else _llm_call(text, PROMPT_PII, p.name, "pii")
            if out.get("pii"):
                session.add(TextIssue(
                    text_id=it.id, dataset_id=dataset_id, issue_type="possible_pii",
                    score=1.0, threshold=0.0, detector_name=source_id,
                    detector_version=p.version if p else "plugin",
                    evidence_json={"types": out.get("types", []),
                                   "evidence": str(out.get("evidence", ""))[:500]}))
            processed += 1
        except Exception:  # noqa: BLE001
            failed += 1
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))


def _confidence(raw: object) -> float | None:
    if raw is None:
        return None
    value = float(raw)
    if not 0 <= value <= 1:
        raise ValueError("plugin returned an invalid confidence")
    return value


def _supersede_model_labels(session: Session, item_id: str, model_id: str) -> None:
    for old in session.exec(select(TextLabel).where(
            TextLabel.text_id == item_id, TextLabel.source_type == "model",
            TextLabel.source_id == model_id, TextLabel.superseded_at.is_(None))).all():
        old.superseded_at = datetime.now(UTC)
        session.add(old)


def _automation_state(capability: str) -> tuple[bool, float, bool, bool]:
    config = model_catalog.read_settings().get("automation", {}).get(capability, {})
    return (
        bool(config.get("enabled", False)),
        max(0.0, min(1.0, float(config.get("confidence", 0.95)))),
        bool(config.get("preview", True)),
        bool(config.get("auto_quarantine", False)),
    )


def _save_model_labels(session: Session, job: Job, item: TextItem, capability: str, model_id: str, labels: list[TextLabel]) -> None:
    _supersede_model_labels(session, item.id, model_id)
    enabled, threshold, preview, auto_quarantine = _automation_state(capability)
    apply = enabled and not preview
    confident = [label for label in labels if label.confidence is not None and label.confidence >= threshold]
    for label in labels:
        if apply and label in confident:
            label.status = "approved"
        session.add(label)
        if apply and label in confident:
            session.add(TextReviewDecision(
                target_type="label", target_id=label.id,
                decision="approve", reason=f"automation:{job.id}",
                comment=f"{capability} confidence {label.confidence:.2f}"))
    if apply and auto_quarantine and confident:
        previous = item.decision_status
        item.decision_status = "quarantine"
        item.quarantine_reason = f"automation:{capability} ({model_id})"
        session.add(item)
        session.add(TextReviewDecision(
            target_type="item", target_id=item.id,
            decision="quarantine", reason=f"automation:{job.id}",
            comment=f"previous_decision:{previous}"))


def _run_plugin_labels(session: Session, job: Job, capability: str, output_key: str, parser) -> None:
    model_id, plugin_id, items = _plugin_items(session, job, capability)
    total = len(items)
    processed = failed = pending = 0
    errors: list[str] = []
    for item in items:
        if is_cancelled(job.id):
            break
        try:
            output = plugin_runtime.invoke(plugin_id, capability, _plugin_payload(model_id, item))
            records = output.get(output_key)
            if not isinstance(records, list):
                raise ValueError(f"plugin output must contain a {output_key} list")
            _save_model_labels(session, job, item, capability, model_id, parser(records, item, model_id))
            processed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{item.original_filename}: {type(exc).__name__}: {exc}")
        pending += 1
        if pending >= 50:
            session.commit()
            update_progress(job.id, processed, failed, max(total, 1))
            pending = 0
    session.commit()
    update_progress(job.id, processed, failed, max(total, 1))
    if errors:
        job.error_summary = "; ".join(errors)[:1000]
        session.add(job)
        session.commit()


def _parse_ner(records: list, item: TextItem, model_id: str) -> list[TextLabel]:
    labels = []
    text = _read_text(item) or ""
    for record in records:
        if not isinstance(record, dict) or not str(record.get("text", "")).strip():
            raise ValueError("plugin returned invalid NER text")
        labels.append(TextLabel(
            text_id=item.id, label_type="span", category="entity",
            value_json={"text": str(record["text"]).strip()},
            span_start=record.get("span_start"), span_end=record.get("span_end"),
            source_type="model", source_id=model_id,
            confidence=_confidence(record.get("confidence")), status="pending"))
    return labels


def _parse_classification(records: list, item: TextItem, model_id: str) -> list[TextLabel]:
    labels = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("plugin returned invalid classification")
        labels.append(TextLabel(
            text_id=item.id, label_type="classification",
            category=str(record.get("category", "label")).strip() or "label",
            value_json={"text": str(record.get("text", "")).strip()},
            source_type="model", source_id=model_id,
            confidence=_confidence(record.get("confidence")), status="pending"))
    return labels


def run_ner(session: Session, job: Job) -> None:
    _run_plugin_labels(session, job, "ner", "entities", _parse_ner)


def run_classification(session: Session, job: Job) -> None:
    _run_plugin_labels(session, job, "classification", "labels", _parse_classification)


def _caption_text(raw: object, config: dict) -> str:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("caption plugin returned empty text")
    separator = str(config.get("separator", ", ")) or ", "
    prefix = str(config.get("prefix", "")).strip()
    suffix = str(config.get("suffix", "")).strip()
    if prefix:
        text = f"{prefix}{separator}{text}"
    if suffix:
        text = f"{text}{separator}{suffix}"
    template = str(config.get("template", "{caption}"))
    if "{caption}" not in template:
        raise ValueError("caption template must contain {caption}")
    return template.replace("{caption}", text).strip()


def _save_caption(session: Session, job: Job, item: TextItem, model_id: str, text: str,
                  confidence: float | None, config: dict) -> None:
    for old in session.exec(select(TextLabel).where(
            TextLabel.text_id == item.id, TextLabel.label_type == "generated",
            TextLabel.source_type == "model", TextLabel.source_id == model_id,
            TextLabel.superseded_at.is_(None))).all():
        old.superseded_at = datetime.now(UTC)
        session.add(old)
    enabled, threshold, preview, _ = _automation_state("captioning")
    caption = TextLabel(
        text_id=item.id, label_type="generated", category="assistant",
        value_json={"text": text}, span_start=None, span_end=None,
        source_type="model", source_id=model_id, confidence=confidence,
        status="approved" if enabled and not preview and (confidence or 0) >= threshold else "pending")
    session.add(caption)
    if caption.status == "approved":
        session.add(TextReviewDecision(target_type="label", target_id=caption.id,
                                       decision="approve", reason=f"automation:{job.id}",
                                       comment=f"caption confidence {confidence or 0:.2f}"))


def _run_cloud_caption(session: Session, job: Job, provider: str) -> None:
    config = job.config_json
    items = _job_items(session, job)
    total = len(items)
    processed = failed = 0
    errors: list[str] = []
    prompt = str(config.get("prompt", "Generate a helpful response for this text."))
    for item in items:
        if is_cancelled(job.id):
            break
        try:
            text = _read_text(item)
            if not text:
                failed += 1
                continue
            output = _llm_call(text, prompt, provider, "captioning")
            text_out = _caption_text(output.get("caption") or output.get("text"), config)
            _save_caption(session, job, item, provider, text_out, _confidence(output.get("confidence")), config)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{item.original_filename}: {type(exc).__name__}: {exc}")
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))
    if errors:
        job.error_summary = "; ".join(errors)[:1000]
        session.add(job)
        session.commit()


def run_caption(session: Session, job: Job) -> None:
    if _external_plugin(job, "captioning", set()):
        _run_plugin_caption(session, job)
        return
    provider = active("captioning")
    if provider and provider.name in {"openai"}:
        ok, msg = provider.available()
        if not ok:
            raise RuntimeError(f"captioning provider unavailable — {msg}")
        _run_cloud_caption(session, job, provider.name)
        return
    _run_plugin_caption(session, job)


def _run_plugin_caption(session: Session, job: Job) -> None:
    model_id, plugin_id, items = _plugin_items(session, job, "captioning")
    config = job.config_json
    total = len(items)
    processed = failed = 0
    errors: list[str] = []
    for item in items:
        if is_cancelled(job.id):
            break
        try:
            payload = _plugin_payload(model_id, item, str(config.get("prompt", "")))
            payload.update({key: config.get(key, default) for key, default in (
                ("prefix", ""), ("suffix", ""), ("separator", ", "), ("template", "{caption}"))})
            output = plugin_runtime.invoke(plugin_id, "captioning", payload)
            text = _caption_text(output.get("caption"), config)
            _save_caption(session, job, item, model_id, text, _confidence(output.get("confidence")), config)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            errors.append(f"{item.original_filename}: {type(exc).__name__}: {exc}")
        session.commit()
        update_progress(job.id, processed, failed, max(total, 1))
    if errors:
        job.error_summary = "; ".join(errors)[:1000]
        session.add(job)
        session.commit()