"""Contract tests for LLM-domain endpoints: conversations, preference pairs, SFT, traces.

Run: uv run python -m pytest backend/tests/test_llm_contracts.py -q
"""
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from app.main import app


from app.db import init_db

# TestClient without a context manager never fires startup events, so create tables explicitly.
init_db()
client = TestClient(app)


def test_health():
    """Health endpoint returns ok."""
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_conversations_list_no_dataset_id():
    """GET /api/conversations without dataset_id returns 422."""
    r = client.get("/api/conversations")
    # The endpoint expects a required query param; FastAPI returns 422 for missing required field
    assert r.status_code == 422


def test_conversations_list_invalid_dataset():
    """GET /api/conversations with nonexistent dataset_id returns 404."""
    r = client.get("/api/conversations?dataset_id=does-not-exist")
    assert r.status_code == 404


def test_conversations_create_and_list():
    """Create a conversation then list it back."""
    r = client.post("/api/datasets", json={"name": "test-ds", "description": "contract test"})
    assert r.status_code == 201
    ds_id = r.json()["id"]

    r = client.post("/api/conversations", json={"dataset_id": ds_id, "title": "hello conv", "conversation_type": "sft"})
    assert r.status_code == 201
    conv_id = r.json()["id"]

    r = client.get(f"/api/conversations?dataset_id={ds_id}")
    assert r.status_code == 200
    convs = r.json()
    assert len(convs) >= 1
    assert any(c["id"] == conv_id for c in convs)


def test_conversation_detail():
    """GET /api/conversations/{conv_id} returns conversation and turns."""
    r = client.post("/api/datasets", json={"name": "detail-ds", "description": "detail test"})
    assert r.status_code == 201
    ds_id = r.json()["id"]

    r = client.post("/api/conversations", json={"dataset_id": ds_id, "title": "detail conv"})
    assert r.status_code == 201
    conv_id = r.json()["id"]

    r = client.get(f"/api/conversations/{conv_id}")
    assert r.status_code == 200
    data = r.json()
    assert "conversation" in data
    assert "turns" in data


def test_conversation_turns():
    """POST /api/conversations/{conv_id}/turns adds a turn and returns it."""
    r = client.post("/api/datasets", json={"name": "turns-ds", "description": "turns test"})
    assert r.status_code == 201
    ds_id = r.json()["id"]

    r = client.post("/api/conversations", json={"dataset_id": ds_id, "title": "turns conv"})
    assert r.status_code == 201
    conv_id = r.json()["id"]

    r = client.post(f"/api/conversations/{conv_id}/turns", json={"role": "user", "content": "Hello assistant", "tokens": 5})
    assert r.status_code == 201
    turn = r.json()
    assert turn["role"] == "user"
    assert turn["content"] == "Hello assistant"
    assert turn["turn_index"] == 0


def test_preference_pairs_create_and_list():
    """Create a preference pair then list it back."""
    r = client.post("/api/datasets", json={"name": "pref-ds", "description": "pref test"})
    assert r.status_code == 201
    ds_id = r.json()["id"]

    r = client.post(f"/api/datasets/{ds_id}/preference-pairs", json={
        "prompt_text": "What is love?",
        "chosen_text": "Love is patient",
        "rejected_text": "Love is fading",
        "strategy": "manual"
    })
    assert r.status_code == 201
    pair_id = r.json()["id"]

    r = client.get(f"/api/datasets/{ds_id}/preference-pairs")
    assert r.status_code == 200
    pairs = r.json()
    assert len(pairs) >= 1
    assert any(p["id"] == pair_id for p in pairs)


def test_preference_pairs_invalid_dataset():
    """POST to a nonexistent dataset returns 404."""
    r = client.post("/api/datasets/does-not-exist/preference-pairs", json={
        "prompt_text": "prompt",
        "chosen_text": "chosen",
        "rejected_text": "rejected"
    })
    assert r.status_code == 404


def test_sft_records_create_and_list():
    """Create an SFT record then list it back."""
    r = client.post("/api/datasets", json={"name": "sft-ds", "description": "sft test"})
    assert r.status_code == 201
    ds_id = r.json()["id"]

    r = client.post(f"/api/datasets/{ds_id}/sft-records", json={
        "messages": [{"role": "user", "content": "Hello"}],
        "schema_type": "sft",
        "source_type": "human"
    })
    assert r.status_code == 201
    record_id = r.json()["id"]

    r = client.get(f"/api/datasets/{ds_id}/sft-records")
    assert r.status_code == 200
    records = r.json()
    assert len(records) >= 1
    assert any(rec["id"] == record_id for rec in records)


def test_sft_records_invalid_dataset():
    """POST to a nonexistent dataset returns 404."""
    r = client.post("/api/datasets/does-not-exist/sft-records", json={
        "messages": [],
        "schema_type": "sft"
    })
    assert r.status_code == 404


def test_traces_create_and_list():
    """Create an agent trace then list it back."""
    r = client.post("/api/datasets", json={"name": "trace-ds", "description": "trace test"})
    assert r.status_code == 201
    ds_id = r.json()["id"]

    r = client.post(f"/api/datasets/{ds_id}/traces", json={
        "trace_type": "agent",
        "trace_id": "trace-123",
        "trace_json": {},
        "tokens": 100,
        "model": "test-model"
    })
    assert r.status_code == 201
    trace_id = r.json()["id"]

    r = client.get(f"/api/datasets/{ds_id}/traces")
    assert r.status_code == 200
    traces = r.json()
    assert len(traces) >= 1
    assert any(t["id"] == trace_id for t in traces)


def test_traces_invalid_dataset():
    """POST to a nonexistent dataset returns 404."""
    r = client.post("/api/datasets/does-not-exist/traces", json={
        "trace_type": "agent",
        "trace_id": "x",
        "trace_json": {}
    })
    assert r.status_code == 404


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
