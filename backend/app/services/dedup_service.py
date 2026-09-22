"""Dedup: grupos exatos (SHA-256) e near-duplicates (MinHash para texto).

Texto: content_hash = sha256(text); near-duplicate via MinHash (LSH) em vez de dHash.
Canônico eleito por maior token_count; desempate por lex id.
"""
from typing import Any

from sqlmodel import Session, select

from ..analyzers.dedup import DETECTOR_VERSION
from ..config import get_settings
from ..jobs import update_progress
from ..models import (TextItem, TextIssue, DuplicateGroup, DuplicateMember, Job)


def swap_canonical(session: Session, group_id: str, text_id: str) -> DuplicateGroup:
    g = session.get(DuplicateGroup, group_id)
    if g is None:
        raise ValueError("group not found")
    ms = session.exec(select(DuplicateMember).where(DuplicateMember.group_id == group_id)).all()
    if not any(m.text_id == text_id for m in ms):
        raise ValueError("item does not belong to group")
    for m in ms:
        m.is_canonical = m.text_id == text_id
        session.add(m)
    session.commit()
    session.refresh(g)
    return g.model_dump()


def derive_from_items(session: Session, name: str, source_id: str, text_ids: list[str],
                      note: str = "") -> dict:
    from .derive_service import _register_from_item
    items = session.exec(select(TextItem).where(TextItem.id.in_(text_ids))).all()
    ds = _derive_new_dataset(session, name, source_id, note)
    for it in items:
        if it.decision_status != "keep":
            continue
        _register_from_item(session, ds.id, it)
    session.commit()
    session.refresh(ds)
    return ds.model_dump()


def _derive_new_dataset(session: Session, name: str, source_id: str, note: str) -> Any:
    from ..models import Dataset
    ds = Dataset(name=name, source_type="derived",
                 source_uri=f"derived:{source_id} — {note}")
    session.add(ds)
    session.commit()
    session.refresh(ds)
    return ds


def _canonical(items: list[TextItem]) -> TextItem:
    # maior token count; desempate lex id para estabilidade
    return sorted(items, key=lambda i: (-i.tokens, i.id))[0]


def _replace_groups(session: Session, dataset_id: str, method: str) -> None:
    for g in session.exec(select(DuplicateGroup).where(
            DuplicateGroup.dataset_id == dataset_id,
            DuplicateGroup.method == method)).all():
        for m in session.exec(select(DuplicateMember).where(
                DuplicateMember.group_id == g.id)).all():
            session.delete(m)
        session.delete(g)
    session.commit()


def _make_group(session: Session, dataset_id: str, method: str,
                members: list[TextItem], threshold: float,
                similarities: dict[str, float]) -> None:
    canon = _canonical(members)
    g = DuplicateGroup(dataset_id=dataset_id, method=method,
                      threshold=threshold, model_name="")
    session.add(g)
    session.flush()
    for it in members:
        session.add(DuplicateMember(
            group_id=g.id, text_id=it.id,
            similarity=similarities.get(it.id, 1.0),
            is_canonical=(it.id == canon.id),
            evidence_json={"sha256" if method == "sha256" else "minhash":
                          it.content_hash_sha256 if method == "sha256" else "minhash"},
        ))


def run_exact_dedup(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    _replace_groups(session, dataset_id, "sha256")
    items = session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id,
        TextItem.ingest_status == "done")).all()
    by_hash: dict[str, list[TextItem]] = {}
    for it in items:
        if it.content_hash_sha256:
            by_hash.setdefault(it.content_hash_sha256, []).append(it)
    total = sum(1 for v in by_hash.values() if len(v) > 1)
    processed = 0
    from ..jobs import is_cancelled
    for group_items in by_hash.values():
        if is_cancelled(job.id):
            break
        if len(group_items) > 1:
            _make_group(session, dataset_id, "sha256", group_items, 0.0, {})
            processed += 1
            session.commit()
            update_progress(job.id, processed, 0, max(total, 1))


def run_minhash_dedup(session: Session, job: Job) -> None:
    dataset_id = job.dataset_id
    s = get_settings()
    threshold = float(job.config_json.get("threshold", s.minhash_threshold or 0.5))
    _replace_groups(session, dataset_id, "minhash")
    items = session.exec(select(TextItem).where(
        TextItem.dataset_id == dataset_id,
        TextItem.ingest_status == "done")).all()

    import hashlib

    def _minhash(text: str, k: int = 5, num_hashes: int = 128) -> list[int]:
        shingles = set()
        clean = text.replace("\n", " ").replace("\t", " ")
        for i in range(len(clean) - k + 1):
            shingles.add(clean[i:i + k])
        if not shingles:
            return []
        a = [i * 7919 + 31 for i in range(num_hashes)]
        b = [i * 6271 + 17 for i in range(num_hashes)]
        sig = [float("inf")] * num_hashes
        for sh in shingles:
            h = int(hashlib.sha256(sh.encode()).hexdigest()[:16], 16)
            for i in range(num_hashes):
                val = (a[i] * h + b[i]) % (2 ** 32)
                if val < sig[i]:
                    sig[i] = val
        return sig

    from .quality_service import _read_text
    sigs: dict[str, list[int]] = {}
    for it in items:
        text = _read_text(it)
        if text:
            sigs[it.id] = _minhash(text)

    if not sigs:
        return

    # Build buckets per band
    bands = 16
    sig_len = len(next(iter(sigs.values())))
    band_size = max(1, sig_len // bands)
    buckets: dict[tuple, list[str]] = {}
    for iid, sig in sigs.items():
        for b in range(bands):
            chunk = tuple(sig[b * band_size:(b + 1) * band_size])
            buckets.setdefault(chunk, []).append(iid)

    used: set[str] = set()
    total = len(items)
    groups = 0
    from ..jobs import is_cancelled
    for i, a_id in enumerate(items):
        if is_cancelled(job.id):
            break
        if a_id.id not in sigs or a_id.id in used:
            continue
        a_sig = sigs[a_id.id]
        members = [a_id]
        sims = {a_id.id: 1.0}
        # Jaccard estimate via shared bands
        candidates: set[str] = set()
        for b in range(bands):
            chunk = tuple(a_sig[b * band_size:(b + 1) * band_size])
            for cid in buckets.get(chunk, []):
                candidates.add(cid)
        for cid in candidates:
            if cid == a_id.id or cid in used:
                continue
            b_sig = sigs.get(cid)
            if not b_sig:
                continue
            # Approximate Jaccard by band agreement rate
            shared = sum(1 for x, y in zip(a_sig, b_sig) if x == y)
            jac = shared / len(a_sig) if len(a_sig) == len(b_sig) else 0
            if jac >= threshold:
                b_item = session.get(TextItem, cid)
                if b_item:
                    members.append(b_item)
                    sims[cid] = jac
        if len(members) > 1:
            used.update(m.id for m in members)
            _make_group(session, dataset_id, "minhash", members, threshold, sims)
            groups += 1
            session.commit()
        update_progress(job.id, i + 1, 0, max(total, 1))
    session.commit()


def run_phash_dedup(session: Session, job: Job) -> None:
    """No-op for text datasets (kept for API compat)."""
    pass


def _read_text(it: TextItem) -> str | None:
    s = get_settings()
    path = s.data_dir / it.storage_uri if it.storage_uri else None
    if path and path.exists():
        return path.read_text(encoding="utf-8", errors="replace")
    return None
