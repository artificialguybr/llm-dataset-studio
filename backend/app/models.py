"""Data models for LLM Dataset Studio — text/corpus/SFT/DPO/traces.

Replaces the image-domain models from images-dataset-studio.
Keeps the same SQLModel/SQLite/UUID conventions (table names,
timestamps, status enums) so migrations are additive, not destructive.
"""
import uuid
from datetime import UTC, datetime
from typing import Any, Optional

from sqlmodel import JSON, Column, Field, SQLModel


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Core dataset
# ---------------------------------------------------------------------------

class Dataset(SQLModel, table=True):
    __tablename__ = "datasets"
    id: str = Field(default_factory=new_id, primary_key=True)
    name: str = Field(index=True)
    description: str = ""
    owner: str = "local"
    source_type: str = "local"           # local | zip | imported | cloud | huggingface
    source_uri: str = ""
    license: str = "unknown"
    license_evidence_uri: str = ""
    license_policy: str = "permissive"  # permissive | strict
    thresholds_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    recipe_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # mix/sample recipe + lineage
    current_version_id: Optional[str] = Field(default=None, foreign_key="dataset_versions.id")
    status: str = "active"              # active | archived
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Text items (replaces ImageItem)
# ---------------------------------------------------------------------------

class TextItem(SQLModel, table=True):
    __tablename__ = "text_items"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    source_uri: str                      # original path/uri, never rewritten
    storage_uri: str = ""                # where bytes live inside data/
    original_filename: str = Field(index=True)
    relative_path: str = ""
    mime_type: str = "text/plain"
    byte_size: int = 0
    content_hash_sha256: str = Field(default="", index=True)
    text_hash_sha256: str = ""           # hash of *content* (not metadata)
    tokens: int = 0                      # token count (estimator/model)
    token_estimator: str = ""            # e.g. "tiktoken-gpt4", "character"
    language: str = ""                   # iso-639-1 inferred
    char_count: int = 0
    word_count: int = 0
    line_count: int = 0
    max_line_length: int = 0
    min_line_length: int = 0
    has_html: bool = False
    has_unicode_normalization_issues: bool = False
    has_whitespace_issues: bool = False
    exif_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # reuse for arbitrary metadata
    tags_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    license: str = "unknown"
    license_evidence_uri: str = ""
    ingest_status: str = "pending"        # pending | done | error
    ingest_error: str = ""
    decision_status: str = "keep"        # keep | review | quarantine | reject | restore
    quarantine_reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Issues (replaces ImageIssue)
# ---------------------------------------------------------------------------

class TextIssue(SQLModel, table=True):
    __tablename__ = "text_issues"
    id: str = Field(default_factory=new_id, primary_key=True)
    text_id: str = Field(foreign_key="text_items.id", index=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    issue_type: str = Field(index=True)
    score: float = 0.0
    threshold: float = 0.0
    detector_name: str = ""
    detector_version: str = ""
    evidence_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = "open"                  # open | acknowledged | dismissed
    created_at: datetime = Field(default_factory=utcnow)
    reviewed_at: Optional[datetime] = None
    reviewed_by: Optional[str] = None


# ---------------------------------------------------------------------------
# Labels (expands Label label_type for text)
# ---------------------------------------------------------------------------

class TextLabel(SQLModel, table=True):
    __tablename__ = "text_labels"
    id: str = Field(default_factory=new_id, primary_key=True)
    text_id: str = Field(foreign_key="text_items.id", index=True)
    label_type: str = "classification"
    category: str = Field(index=True)
    geometry_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))  # kept for compat
    value_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    span_start: Optional[int] = None      # character offset in text
    span_end: Optional[int] = None
    source_type: str = "human"            # human | model | imported | rule | unknown
    source_id: str = ""
    confidence: Optional[float] = None
    status: str = "approved"              # approved | pending | rejected
    created_at: datetime = Field(default_factory=utcnow)
    created_by: str = "local"
    superseded_at: Optional[datetime] = None
    supersedes_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Conversations & turns (text-specific)
# ---------------------------------------------------------------------------

class Conversation(SQLModel, table=True):
    __tablename__ = "conversations"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    title: str = ""
    source_uri: str = ""
    conversation_type: str = "sft"         # sft | dpo | eval | benchmark | trace | agent
    turn_count: int = 0
    total_tokens: int = 0
    language: str = ""
    tags_json: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    license: str = "unknown"
    ingest_status: str = "pending"
    decision_status: str = "keep"
    quarantine_reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class TextTurn(SQLModel, table=True):
    __tablename__ = "text_turns"
    id: str = Field(default_factory=new_id, primary_key=True)
    conversation_id: str = Field(foreign_key="conversations.id", index=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    text_item_id: Optional[str] = Field(default=None, foreign_key="text_items.id")
    role: str = "user"                     # system | user | assistant | tool | function | custom
    content: str = ""
    content_hash_sha256: str = ""
    tokens: int = 0
    token_estimator: str = ""
    turn_index: int = 0
    tool_calls: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    tool_call_id: Optional[str] = None
    agent_trace: Optional[bool] = False
    parent_turn_id: Optional[str] = None   # for DPO: pointer to paired turn
    license: str = "unknown"
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# SFT / DPO / preference pairs
# ---------------------------------------------------------------------------

class PreferencePair(SQLModel, table=True):
    __tablename__ = "preference_pairs"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    conversation_id: Optional[str] = None
    turn_id: Optional[str] = None
    chosen_turn_id: Optional[str] = Field(default=None, foreign_key="text_turns.id")
    rejected_turn_id: Optional[str] = Field(default=None, foreign_key="text_turns.id")
    prompt_text: str = ""
    chosen_text: str = ""
    rejected_text: str = ""
    strategy: str = "manual"               # manual | rank | sft | dpo | synthetic
    reviewer: str = "local"
    status: str = "approved"               # approved | pending | rejected
    superseded_at: Optional[datetime] = None
    supersedes_id: Optional[str] = None
    created_at: datetime = Field(default_factory=utcnow)


class SFTRecord(SQLModel, table=True):
    __tablename__ = "sft_records"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    conversation_id: Optional[str] = None
    text_item_id: Optional[str] = None
    turn_id: Optional[str] = None
    messages: list[dict[str, str]] = Field(default_factory=list, sa_column=Column(JSON))
    system_prompt: str = ""
    tokens: int = 0
    token_estimator: str = ""
    schema_type: str = "sft"               # sft | dpo | trace | eval | rag
    source_type: str = "human"             # human | model | imported | rule | synthetic
    source_id: str = ""
    license: str = "unknown"
    status: str = "approved"
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Agent traces & reasoning
# ---------------------------------------------------------------------------

class AgentTrace(SQLModel, table=True):
    __tablename__ = "agent_traces"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    trace_type: str = "agent"              # agent | reasoning | verifier | tool_call
    trace_id: str = ""
    trace_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    tokens: int = 0
    model: str = ""
    duration_ms: Optional[int] = None
    success: Optional[bool] = None
    error: str = ""
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Review / human adjudication
# ---------------------------------------------------------------------------

class TextReviewDecision(SQLModel, table=True):
    __tablename__ = "text_review_decisions"
    id: str = Field(default_factory=new_id, primary_key=True)
    target_type: str = "item"
    target_id: str = Field(index=True)
    reviewer_id: str = "local"
    decision: str = "keep"
    category: str = ""
    comment: str = ""
    evidence_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


# ---------------------------------------------------------------------------
# Duplicate infra (changed image_id -> text_id)
# ---------------------------------------------------------------------------

class DuplicateGroup(SQLModel, table=True):
    __tablename__ = "duplicate_groups"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    method: str = "sha256"
    threshold: float = 0.0
    model_name: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class DuplicateMember(SQLModel, table=True):
    __tablename__ = "duplicate_members"
    id: str = Field(default_factory=new_id, primary_key=True)
    group_id: str = Field(foreign_key="duplicate_groups.id", index=True)
    text_id: str = Field(foreign_key="text_items.id", index=True)
    similarity: float = 1.0
    is_canonical: bool = False
    evidence_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    decision: str = "pending"


# ---------------------------------------------------------------------------
# Backwards-compatible aliases (deprecated — migrate to the new names)
# ---------------------------------------------------------------------------

# Legacy name for the text-label model. The old Label had image_id; the new
# TextLabel has text_id. Callers that still import `Label` get the new model
# with the new FK — no silent breakage, just a deprecation path.
Label = TextLabel

# Legacy name for a per-item generated text. In the image era this was a
# caption for an image; in the text era it is an assistant turn / generated
# response attached to a TextItem.
class Caption(SQLModel, table=True):
    __tablename__ = "captions"
    id: str = Field(default_factory=new_id, primary_key=True)
    text_id: str = Field(foreign_key="text_items.id", index=True)
    text: str = ""
    prompt: str = ""
    prefix: str = ""
    suffix: str = ""
    template: str = "{caption}"
    source_type: str = "model"          # model | human | imported
    source_id: str = ""
    confidence: Optional[float] = None
    status: str = "pending"             # pending | approved | rejected
    superseded_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=utcnow)


# Legacy name for the review-decision model.
ReviewDecision = TextReviewDecision

class DatasetVersion(SQLModel, table=True):
    __tablename__ = "dataset_versions"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    parent_version_id: Optional[str] = None
    manifest_uri: str = ""
    item_count: int = 0
    checksum: str = ""
    description: str = ""
    snapshot_json: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=utcnow)


class ExportRecord(SQLModel, table=True):
    __tablename__ = "export_records"
    id: str = Field(default_factory=new_id, primary_key=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    fmt: str = "jsonl"                     # jsonl | parquet | hf | manifest | report
    version_id: str = ""
    path: str = ""
    item_count: int = 0
    created_at: datetime = Field(default_factory=utcnow)


class Job(SQLModel, table=True):
    __tablename__ = "jobs"
    id: str = Field(default_factory=new_id, primary_key=True)
    type: str = Field(index=True)
    dataset_id: str = Field(foreign_key="datasets.id", index=True)
    status: str = "queued"
    progress: float = 0.0
    total: int = 0
    processed: int = 0
    failed: int = 0
    config_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    error_summary: str = ""
    created_at: datetime = Field(default_factory=utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None