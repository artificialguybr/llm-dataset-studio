"""Sampling, diversidade e mistura de fontes com pesos e recipes.

- sample(): cria dataset derivado com N itens escolhidos por método
  (random com seed, diverse via MinHash farthest-first, important = prioriza
  itens com issues / review). Linha de_origem fica em source_uri.
- mix_sources(): mistura N datasets com pesos (proporções), repetível por
  seed; a recipe (fontes+pesos+params) é gravada em Dataset.recipe_json.
Originais nunca são movidos: itens derivados apontam para os mesmos bytes.
"""
import hashlib
import random
from datetime import UTC, datetime
from sqlmodel import Session, select

from ..analyzers.dedup import _jaccard_from_signatures, _minhash
from ..models import Dataset, Job, TextItem, TextLabel
from .derive_service import _register_from_item


def _copy_labels(session: Session, src: TextItem, dst: TextItem) -> None:
    for lb in session.exec(select(TextLabel).where(
            TextLabel.text_id == src.id)).all():
        session.add(TextLabel(text_id=dst.id, label_type=lb.label_type,
                             category=lb.category,
                             geometry_json=lb.geometry_json,
                             value_json=lb.value_json,
                             source_type=lb.source_type, status=lb.status))


def _items_of(session: Session, ds_id: str) -> list[TextItem]:
    return session.exec(select(TextItem).where(
        TextItem.dataset_id == ds_id,
        TextItem.ingest_status == "done")).all()


def _pick_random(items: list[TextItem], size: int, seed: int) -> list[TextItem]:
    rng = random.Random(seed)
    pool = list(items)
    rng.shuffle(pool)
    return pool[:size]


def _pick_diverse(items: list[TextItem], size: int) -> list[TextItem]:
    """Farthest-first traversal: começa pelo mais longo, sempre pega o item
    mais distante (Jaccard/MinHash) do que já foi escolhido."""
    if size >= len(items):
        return list(items)
    sigs = {it.id: _minhash(_read(it) or it.original_filename) for it in items}
    by_len = sorted(items, key=lambda i: i.char_count or 0, reverse=True)
    chosen = [by_len[0]]
    rest = by_len[1:]
    while len(chosen) < size and rest:
        best, best_dist = None, -1.0
        for cand in rest:
            d = min(_jaccard_from_signatures(sigs[c.id], sigs[c.id])
                   for c in chosen)
            # distância = 1 - similaridade
            if 1.0 - d > best_dist:
                best, best_dist = cand, 1.0 - d
        chosen.append(best)
        rest.remove(best)
    return chosen


def _pick_important(session: Session, ds_id: str,
                    items: list[TextItem], size: int) -> list[TextItem]:
    """Prioriza: itens com issues abertas > em revisão > maiores (tokens)."""
    open_issues: dict[str, int] = {}
    from ..models import TextIssue
    for iss in session.exec(select(TextIssue).where(
            TextIssue.dataset_id == ds_id, TextIssue.status == "open")).all():
        open_issues[iss.text_id] = open_issues.get(iss.text_id, 0) + 1

    def rank(it: TextItem) -> tuple:
        return (-open_issues.get(it.id, 0),
                1 if it.decision_status == "review" else 0,
                -(it.tokens or 0))

    return sorted(items, key=rank)[:size]


def _read(it: TextItem) -> str | None:
    from .quality_service import _read_text
    return _read_text(it)


def sample(session: Session, ds_id: str, size: int, method: str = "random",
          seed: int = 0, name: str = "") -> dict:
    """methods: random | diverse | important. Sempre reproduzível com seed."""
    items = _items_of(session, ds_id)
    if not items:
        raise ValueError("dataset has no done items to sample")
    size = max(0, min(size, len(items)))
    if method == "diverse":
        picked = _pick_diverse(items, size)
    elif method == "important":
        picked = _pick_important(session, ds_id, items, size)
    else:
        picked = _pick_random(items, size, seed)
    ds = Dataset(name=name or f"sample-{method}-{ds_id[:8]}",
                description=f"{size} items sampled ({method}, seed={seed})",
                source_type="sampled",
                source_uri=f"sample:{ds_id}:{method}:{seed}:{size}")
    ds.recipe_json = {"kind": "sample", "source": ds_id, "method": method,
                      "seed": seed, "size": size}
    session.add(ds)
    session.commit()
    for it in picked:
        ni = _register_from_item(session, ds.id, it)
        _copy_labels(session, it, ni)
    ds.updated_at = datetime.now(UTC)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    out = ds.model_dump()
    out["sampled_items"] = len(picked)
    return out


def mix_sources(session: Session, sources: list[dict], name: str,
               size: int = 0, seed: int = 0,
               recipe: dict | None = None) -> dict:
    """Mistura datasets com pesos: cada fonte contribui proporcionalmente ao
    seu peso. size=0 → total = soma ponderada dos tamanhos das fontes.
    Item duplicado (mesmo content hash entre fontes) entra uma vez só."""
    if not sources:
        raise ValueError("mix needs at least one source")
    weights = {s["dataset_id"]: float(s.get("weight") or 1.0) for s in sources}
    pools = {}
    for sid in weights:
        pool = _items_of(session, sid)
        if not pool:
            raise ValueError(f"dataset {sid} has no done items")
        pools[sid] = pool
    total_w = sum(weights.values()) or 1.0
    if size <= 0:
        total_items = sum(len(p) for p in pools.values())
        size = 0
        for sid in weights:
            size += min(len(pools[sid]),
                          int(round(weights[sid] / total_w * total_items)))
    quotas: dict[str, int] = {}
    acc = 0
    sids = list(weights)
    for i, sid in enumerate(sids):
        if i == len(sids) - 1:
            q = size - acc
        else:
            q = int(size * weights[sid] / total_w)
            acc += q
        quotas[sid] = max(0, min(q, len(pools[sid])))
    rng = random.Random(seed)
    ds = Dataset(name=name,
                 description=f"mix of {len(sources)} sources (seed={seed})",
                 source_type="mixed",
                 source_uri="mixed:" + ",".join(
                     f"{sid}:{weights[sid]:g}" for sid in sids))
    rc = {"kind": "mix", "sources": sources, "size": size, "seed": seed}
    if recipe:
        rc.update(recipe)
    ds.recipe_json = rc
    session.add(ds)
    session.commit()
    seen_hash: set[str] = set()
    collisions = 0
    for sid in sids:
        pool = sorted(pools[sid], key=lambda i: i.id)
        rng.shuffle(pool)
        for it in pool[:quotas[sid]]:
            if it.content_hash_sha256 and it.content_hash_sha256 in seen_hash:
                collisions += 1
                continue
            if it.content_hash_sha256:
                seen_hash.add(it.content_hash_sha256)
            ni = _register_from_item(session, ds.id, it)
            _copy_labels(session, it, ni)
    session.commit()
    ds.updated_at = datetime.now(UTC)
    session.add(ds)
    session.commit()
    session.refresh(ds)
    out = ds.model_dump()
    out["content_collisions"] = collisions
    return out
