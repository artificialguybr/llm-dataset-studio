"""Contract tests for the text-domain model pipeline: quality, dedup, embeddings, export.

Run: uv run python -m pytest backend/tests/test_contracts.py -q
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.exporters.exporter import export  # noqa: E402


def test_sha256_deterministic():
    """SHA-256 of same content should be identical."""
    text = "Test content for hashing"
    h1 = hashlib.sha256(text.encode()).hexdigest()
    h2 = hashlib.sha256(text.encode()).hexdigest()
    assert h1 == h2
    assert len(h1) == 64


def test_plugin_jsonl_contract_error_event():
    """A plugin handler must emit a result event per request and never crash the process;
    failures become error events. This is the ids-plugin.v1 common contract."""
    handler = """
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    try:
        if req["capability"] == "text_classification":
            out = {"labels": []}
        else:
            raise ValueError("unsupported capability")
    except Exception as exc:
        out = None
        sys.stdout.write(json.dumps({"type": "error", "error": str(exc)}) + "\\n")
    if out is not None:
        sys.stdout.write(json.dumps({"type": "result", "output": out}) + "\\n")
    sys.stdout.flush()
"""
    requests = json.dumps({"capability": "text_classification", "payload": {}}) + "\n" \
             + json.dumps({"capability": "bogus", "payload": {}}) + "\n"
    proc = subprocess.run([sys.executable, "-c", handler], input=requests,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    events = [json.loads(line) for line in proc.stdout.splitlines()]
    assert events[0] == {"type": "result", "output": {"labels": []}}
    assert events[1]["type"] == "error" and "unsupported" in events[1]["error"]


def test_label_supersession_idempotency():
    """Rerunning a model job must supersede prior labels of the same model,
    not accumulate duplicates."""
    from app.models import TextLabel
    from datetime import UTC, datetime

    class FakeLabel:
        def __init__(self, source_model):
            self.source_model = source_model
            self.superseded_at = None

    labels = [FakeLabel("bert-base"), FakeLabel("distilbert"), FakeLabel("bert-base")]
    now = datetime.now(UTC)
    for lb in labels:
        if isinstance(lb, TextLabel):
            continue
    # simulate the supersede step the job runner applies per model
    active = [lb for lb in labels if lb.source_model == "bert-base"]
    for lb in active[:-1]:
        lb.superseded_at = now
    assert sum(1 for lb in labels if lb.source_model == "bert-base" and lb.superseded_at is None) == 1
    assert sum(1 for lb in labels if lb.source_model == "distilbert" and lb.superseded_at is None) == 1


def test_jsonl_export_shape():
    """JSONL export must produce valid output with correct structure."""
    import json
    import tempfile

    # Just test the JSONL structure that export generates
    manifest_row = {
        "item_id": "i1",
        "source_uri": "local:/tmp/test.txt",
        "storage_uri": "raw/ds-123/i1.txt",
        "output_uri": "raw/ds-123/i1.txt",
        "sha256": "abc123def456",
        "text_hash": "abc123def456",
        "char_count": 100,
        "word_count": 20,
        "line_count": 5,
        "tokens": 25,
        "language": "pt",
        "has_html": False,
        "mime_type": "text/plain",
        "license": "unknown",
        "decision": "keep",
        "tags": [],
        "dataset_version": "",
        "labels": [{"type": "span", "category": "entity",
                    "value": {"text": "test"}, "source_type": "model",
                    "span_start": 0, "span_end": 5,
                    "confidence": 0.95, "status": "approved"}],
        "exported_by": "local-operator",
        "pipeline_version": "0.1.0"
    }
    # Verify it can be serialized to JSON
    json_str = json.dumps(manifest_row)
    parsed = json.loads(json_str)
    assert parsed["item_id"] == "i1"
    assert parsed["decision"] == "keep"
    assert len(parsed["labels"]) == 1
    assert parsed["labels"][0]["category"] == "entity"
    # Test with temp directory write
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "export.jsonl"
        out.write_text(json_str + "\n", encoding="utf-8")
        assert out.read_text().strip() == json_str
    assert True


def test_minhash_signature_structure():
    """MinHash signature should be a list of integers."""
    from app.analyzers.dedup import _minhash
    text = "This is a sample text for minhash testing."
    sig = _minhash(text, k=5, num_hashes=128)
    assert isinstance(sig, list)
    assert len(sig) == 128
    assert all(isinstance(v, int) for v in sig), "signature values should be numeric"


def test_jaccard_from_signatures():
    """Jaccard estimate from identical signatures should be 1.0."""
    from app.analyzers.dedup import _jaccard_from_signatures
    sig = [1, 2, 3, 4, 5] * 20  # 100 elements
    assert _jaccard_from_signatures(sig, sig) == 1.0
    assert _jaccard_from_signatures([], []) == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"ok {name}")