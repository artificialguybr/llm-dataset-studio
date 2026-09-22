import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_unified_explorer_and_preference_review():
    dataset = client.post('/api/datasets', json={'name': 'explorer-test'}).json()['id']
    created = client.post(f'/api/datasets/{dataset}/preference-pairs', json={
        'prompt_text': 'Which answer is clearer?',
        'chosen_text': 'The concise answer.',
        'rejected_text': 'An unclear answer.',
    })
    assert created.status_code == 201, created.text
    pair_id = created.json()['id']

    conversation = client.post('/api/conversations', json={
        'dataset_id': dataset, 'title': 'A short dialogue', 'conversation_type': 'sft',
    }).json()
    turn = client.post(f"/api/conversations/{conversation['id']}/turns", json={
        'role': 'user', 'content': 'Hello there', 'tokens': 3,
    })
    assert turn.status_code == 201, turn.text

    records = client.get(f'/api/datasets/{dataset}/explorer').json()
    assert records['total'] == 2
    assert {record['kind'] for record in records['records']} == {'preference', 'conversation'}
    assert client.get(f'/api/datasets/{dataset}/explorer?record_filter=preference').json()['total'] == 1
    assert client.get(f'/api/datasets/{dataset}/explorer?record_filter=conversation').json()['total'] == 1

    decision = client.patch(f'/api/preference-pairs/{pair_id}/decision', json={'decision': 'b'})
    assert decision.status_code == 200, decision.text
    assert decision.json()['chosen_text'] == 'An unclear answer.'
    assert decision.json()['status'] == 'approved'
