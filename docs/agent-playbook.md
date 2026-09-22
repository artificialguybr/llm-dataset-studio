# Agent playbook

LLM Dataset Studio is designed to be operated by a human, an MCP client, or an internal agent that follows an explicit review loop.

## Safe operating loop

1. **Inspect** the dataset and its current counts.
2. **Search or filter** the unified Explorer envelope.
3. **Read** the selected record and its issues/evidence.
4. **Propose** a decision or transformation.
5. **Wait for explicit approval** before changing decisions, redacting data, or starting a destructive-looking job.
6. **Run** the job or decision through the API/MCP tool.
7. **Verify** the returned status and export only the intended version.

Agents should never claim a provider result, semantic search result, annotation, or export that the API did not return.

## MCP tools

The stdio server exposes these agent-facing operations:

| Purpose | Tool |
|---|---|
| Connectivity | `health` |
| Dataset discovery | `list_datasets`, `get_dataset`, `create_dataset` |
| Unified search | `explore_records` |
| Text inspection | `list_items`, `get_item` |
| Decisions | `set_text_decision`, `set_conversation_decision`, `set_preference_decision` |
| Processing | `start_dataset_job`, `get_job` |
| Delivery | `export_dataset` |

`explore_records` returns a common envelope with `kind` values `text`, `conversation`, `sft`, `preference`, and `trace`. Use `record_filter=has_tool_calls` or `record_filter=missing_final` for trace-oriented review without changing the main workspace model.

## Example review prompts

### Quality triage

> Inspect `sample-corpus`. Find records with open PII, toxicity, or repetition issues. Show the record id, evidence, and a proposed decision. Do not mutate anything until I approve the list.

### DPO review

> Use `explore_records` with `record_filter=preference`. For each pair, summarize the prompt and compare response A and B. Ask me before calling `set_preference_decision`.

### Trace review

> Search with `record_filter=missing_final`. Inspect the trace payloads and report which runs lack a final answer. Do not reject or quarantine records automatically.

### Export check

> Confirm the dataset counts, open issues, and pending decisions. Then prepare the requested export format. Do not overwrite source files.

## REST equivalents

The MCP server is a thin adapter over the local REST API. Useful endpoints include:

```text
GET   /api/datasets
GET   /api/datasets/{dataset_id}/explorer
GET   /api/items/{item_id}
PATCH /api/items/{item_id}/decision
PATCH /api/explorer/{conversation_id}/decision
PATCH /api/preference-pairs/{pair_id}/decision
POST  /api/datasets/{dataset_id}/jobs/{job_type}
POST  /api/datasets/{dataset_id}/export
```

All decision endpoints are local and auditable. The app remains single-user and does not provide authentication or multi-user permissions.
