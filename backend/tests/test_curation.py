"""Contract tests for curation features: normalization, decontamination,
sampling, mixing. Run: uv run --with pytest pytest backend/tests/test_curation.py -q
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app.db import init_db
from app.main import app
from app.analyzers import quality

init_db()
client = TestClient(app)


def _mk_dataset(name: str) -> str:
    r = client.post("/api/datasets", json={"name": name, "description": "curation test"})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _import_texts(ds_id: str, texts: list[str], kind: str = "txt") -> None:
    """Importa textos via endpoint de imports com pasta temporária."""
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for i, t in enumerate(texts):
            (Path(td) / f"t{i}.txt").write_text(t, encoding="utf-8")
        r = client.post(f"/api/datasets/{ds_id}/imports",
                       json={"paths": [td], "zips": [], "jsonls": []})
        assert r.status_code == 202, r.text
        job_id = r.json()["job_id"]
        for _ in range(100):
            jr = client.get(f"/api/jobs/{job_id}")
            if jr.json()["status"] in ("completed", "failed"):
                assert jr.json()["status"] == "completed", jr.text
                return
            import time
            time.sleep(0.1)


def test_normalize_text_pipeline():
    """normalize_text limpa HTML, unicode, whitespace e boilerplate."""
    dirty = ("<p>Hello&nbsp;&amp;world</p>\r\n\n\n\n"
             "click here to subscribe\r\n"
             "line one\nline one\nline one\n")
    out, report = quality.normalize_text(dirty)
    assert "Hello &world" in out, out
    assert "<p>" not in out and "&nbsp;" not in out
    assert chr(13) not in out
    assert "click here" not in out  # boilerplate removido
    assert "line one" in out
    assert out.count("line one") == 1  # repetições consecutivas colapsadas
    assert report["html"] and report["boilerplate"] and report["whitespace"]
    # idempotente
    out2, report2 = quality.normalize_text(out)
    assert out2 == out
    assert not any(report2.values())


def test_normalize_job_rewrites_content():
    ds = _mk_dataset("norm-ds")
    _import_texts(ds, ["<b>bold&nbsp;text</b>  with   spaces"])
    r = client.post(f"/api/datasets/{ds}/jobs/normalize", json={})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        jr = client.get(f"/api/jobs/{job_id}").json()
        if jr["status"] == "completed":
            break
        assert jr["status"] != "failed", jr
        import time
        time.sleep(0.1)
    assert jr["status"] == "completed", jr
    items = client.get(f"/api/datasets/{ds}/items?limit=50").json()
    assert len(items) == 1
    text = client.get(f"/api/items/{items[0]['id']}/text").text
    assert "&nbsp;" not in text and "<b>" not in text


def test_decontamination_flags_overlap():
    ds = _mk_dataset("decon-ds")
    _import_texts(ds, [
        "the quick brown fox jumps over the lazy dog near the river bank today",
        "completely unrelated text about cooking recipes and pasta dishes",
    ])
    bench_texts = [
        "The quick brown fox jumps over the lazy dog near the river bank today",
    ]
    r = client.post(f"/api/datasets/{ds}/jobs/decontaminate",
                    json={"ngrams": bench_texts, "n": 5, "threshold": 0.2})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    for _ in range(100):
        jr = client.get(f"/api/jobs/{job_id}").json()
        if jr["status"] == "completed":
            break
        assert jr["status"] != "failed", jr
        import time
        time.sleep(0.1)
    issues = client.get(f"/api/datasets/{ds}/issues?issue_type=contamination").json()
    assert len(issues) == 1, issues  # só o item contaminado
    assert issues[0]["text_id"] != ""


def test_decontamination_requires_benchmark():
    """Sem benchmark o job é aceito mas falha com erro visível no error_summary."""
    import time
    ds = _mk_dataset("decon-empty")
    r = client.post(f"/api/datasets/{ds}/jobs/decontaminate", json={})
    assert r.status_code == 202
    job_id = r.json()["job_id"]
    for _ in range(100):
        jr = client.get(f"/api/jobs/{job_id}").json()
        if jr["status"] in ("completed", "failed"):
            break
        time.sleep(0.1)
    assert jr["status"] == "failed"
    assert "benchmark" in jr["error_summary"]


def test_sample_random_is_reproducible():
    ds = _mk_dataset("sample-ds")
    _import_texts(ds, [f"sample text number {i}" for i in range(20)])
    r1 = client.post(f"/api/datasets/{ds}/sample", json={"size": 5, "method": "random", "seed": 42}).json()
    r2 = client.post(f"/api/datasets/{ds}/sample", json={"size": 5, "method": "random", "seed": 42}).json()
    assert r1["sampled_items"] == 5
    items1 = {i["original_filename"] for i in client.get(f"/api/datasets/{r1['id']}/items?limit=50").json()}
    items2 = {i["original_filename"] for i in client.get(f"/api/datasets/{r2['id']}/items?limit=50").json()}
    assert items1 == items2  # mesmo seed → mesma amostra


def test_sample_diverse_and_important():
    ds = _mk_dataset("sample-div")
    _import_texts(ds, [f"unique text {i} " + "word " * (i + 1) for i in range(10)])
    rd = client.post(f"/api/datasets/{ds}/sample", json={"size": 4, "method": "diverse"}).json()
    assert rd["sampled_items"] == 4
    imp = client.post(f"/api/datasets/{ds}/sample", json={"size": 3, "method": "important"}).json()
    assert imp["sampled_items"] == 3


def test_mix_with_weights():
    ds1 = _mk_dataset("mix-a")
    ds2 = _mk_dataset("mix-b")
    _import_texts(ds1, [f"from A {i}" for i in range(10)])
    _import_texts(ds2, [f"from B {i}" for i in range(10)])
    r = client.post("/api/datasets/mix", json={
        "sources": [{"dataset_id": ds1, "weight": 3.0},
                    {"dataset_id": ds2, "weight": 1.0}],
        "name": "mixed-3to1", "size": 8,
    })
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["recipe_json"]["kind"] == "mix"
    items = client.get(f"/api/datasets/{out['id']}/items?limit=50").json()
    assert len(items) == 8
    from_a = sum(1 for i in items if i["original_filename"].startswith("t") or True)  # filenames are tN.txt; check content
    texts = [client.get(f"/api/items/{i['id']}/text").text for i in items]
    n_a = sum(1 for t in texts if "from A" in t)
    n_b = sum(1 for t in texts if "from B" in t)
    assert n_a == 6 and n_b == 2, (n_a, n_b)  # peso 3:1 sobre 8 itens


def test_delete_dataset_cascades():
    ds = _mk_dataset("delete-cascade-ds")
    _import_texts(ds, ["alpha text", "beta text", "gamma text"])
    r = client.post(f"/api/datasets/{ds}/jobs/quality", json={})
    assert r.status_code == 202
    import time
    for _ in range(100):
        jr = client.get(f"/api/jobs/{r.json()['job_id']}")
        if jr.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    d = client.delete(f"/api/datasets/{ds}")
    assert d.status_code == 204, d.text
    assert client.get(f"/api/datasets/{ds}").status_code == 404
    assert client.get(f"/api/datasets/{ds}/items").json() == []


def test_delete_dataset_with_duplicates():
    ds = _mk_dataset("delete-dup-ds")
    _import_texts(ds, ["same text", "same text", "other text"])
    r = client.post(f"/api/datasets/{ds}/jobs/dedup_exact", json={})
    assert r.status_code == 202, r.text
    import time
    for _ in range(100):
        jr = client.get(f"/api/jobs/{r.json()['job_id']}")
        if jr.json()["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    d = client.delete(f"/api/datasets/{ds}")
    assert d.status_code == 204, d.text


def test_training_format_import_and_export_roundtrip():
    ds = _mk_dataset("roundtrip-ds")
    import json as _json
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        dpo = [{"prompt": "What is 2+2?", "chosen": "4", "rejected": "5",
                "strategy": "dpo"},
               {"prompt": "Capital of France?", "chosen": "Paris", "rejected": "Lyon"}]
        sft = [{"prompt": "Say hi.", "completion": "Hi there!"}]
        trace = [{"trace_type": "tool_call", "model": "demo-agent",
                 "steps": [{"tool": "search", "q": "x"}], "success": True}]
        (Path(td) / "dpo.jsonl").write_text(
            "\n".join(_json.dumps(r) for r in dpo), encoding="utf-8")
        (Path(td) / "sft.jsonl").write_text(
            "\n".join(_json.dumps(r) for r in sft), encoding="utf-8")
        (Path(td) / "trace.jsonl").write_text(
            "\n".join(_json.dumps(r) for r in trace), encoding="utf-8")
        r = client.post(f"/api/datasets/{ds}/imports",
                       json={"paths": [td], "zips": [], "jsonls": []})
        assert r.status_code == 202, r.text
        import time
        for _ in range(100):
            jr = client.get(f"/api/jobs/{r.json()['job_id']}")
            if jr.json()["status"] in ("completed", "failed"):
                assert jr.json()["status"] == "completed", jr.text
                break
            time.sleep(0.05)
        # structured records landed
        pairs = client.get(f"/api/datasets/{ds}/preference-pairs").json()
        assert len(pairs) == 2, pairs
        recs = client.get(f"/api/datasets/{ds}/sft-records").json()
        assert len(recs) == 1, recs
        traces = client.get(f"/api/datasets/{ds}/traces").json()
        assert len(traces) == 1, traces
        # re-import must not duplicate (content dedupe)
        r2 = client.post(f"/api/datasets/{ds}/imports",
                        json={"paths": [td], "zips": [], "jsonls": []})
        for _ in range(100):
            jr = client.get(f"/api/jobs/{r2.json()['job_id']}")
            if jr.json()["status"] in ("completed", "failed"):
                break
            time.sleep(0.05)
        assert len(client.get(f"/api/datasets/{ds}/preference-pairs").json()) == 2
        # export carries the training files
        ex = client.post(f"/api/datasets/{ds}/export", json={"fmt": "jsonl"}).json()
        out = Path(ex["path"])
        assert (out / "dpo.jsonl").is_file()
        assert (out / "sft.jsonl").is_file()
        assert (out / "traces.jsonl").is_file()
        rows = [_json.loads(l) for l in (out / "dpo.jsonl").read_text().splitlines()]
        assert rows[0]["chosen"] == "4" and rows[0]["rejected"] == "5"
        assert ex["report"]["training_records"]["dpo"] == 2
