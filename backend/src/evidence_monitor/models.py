"""SQLAlchemy ORM models for Evidence Currency Monitor."""

import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


class Base(DeclarativeBase):
    pass


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String, primary_key=True)  # OpenAlex id
    doi: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    publication_date: Mapped[str | None] = mapped_column(String, nullable=True)
    publication_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    journal: Mapped[str | None] = mapped_column(String, nullable=True)
    publisher: Mapped[str | None] = mapped_column(String, nullable=True)
    authors_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    cited_by_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    type: Mapped[str | None] = mapped_column(String, nullable=True)
    language: Mapped[str | None] = mapped_column(String, nullable=True)
    openalex_is_retracted: Mapped[bool] = mapped_column(Boolean, default=False)
    fetched_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (UniqueConstraint("citing_id", "cited_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    citing_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    cited_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    first_seen_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )


class IntegrityNotice(Base):
    __tablename__ = "integrity_notices"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    kind: Mapped[str] = mapped_column(String)  # retraction/correction/concern/withdrawal
    notice_doi: Mapped[str | None] = mapped_column(String, nullable=True)
    notice_date: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String)  # "crossref" or "openalex"
    checked_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )


class IngestRun(Base):
    __tablename__ = "ingest_runs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    started_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    finished_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    query: Mapped[str | None] = mapped_column(Text, nullable=True)
    papers_new: Mapped[int] = mapped_column(Integer, default=0)
    papers_updated: Mapped[int] = mapped_column(Integer, default=0)
    citations_new: Mapped[int] = mapped_column(Integer, default=0)
    notices_found: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="running")


class Claim(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    claim_text: Mapped[str] = mapped_column(Text)
    source_sentence: Mapped[str] = mapped_column(Text)
    direction: Mapped[str | None] = mapped_column(String, nullable=True)
    effect_reported: Mapped[str | None] = mapped_column(String, nullable=True)
    population: Mapped[str | None] = mapped_column(Text, nullable=True)
    country_or_setting: Mapped[str | None] = mapped_column(String, nullable=True)
    design: Mapped[str | None] = mapped_column(String, nullable=True)
    outcome_measure: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sample_size_text: Mapped[str | None] = mapped_column(String, nullable=True)
    follow_up: Mapped[str | None] = mapped_column(String, nullable=True)
    is_primary_claim: Mapped[bool] = mapped_column(Boolean, default=True)
    extraction_confidence: Mapped[str | None] = mapped_column(String, nullable=True)
    confidence_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    fields_missing_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    extracted_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )
    model: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)


class ExtractionRun(Base):
    __tablename__ = "extraction_runs"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    status: Mapped[str] = mapped_column(String)  # ok / empty / failed
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[float | None] = mapped_column(Float, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(timezone=True), default=_now
    )


# ---------------------------------------------------------------------------
# Phase 3: comparison pipeline
# ---------------------------------------------------------------------------

class ClaimEmbedding(Base):
    __tablename__ = "claim_embeddings"

    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"), primary_key=True)
    model: Mapped[str] = mapped_column(String)
    embedding_json: Mapped[str] = mapped_column(Text)  # JSON list of floats
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ClaimPair(Base):
    __tablename__ = "claim_pairs"
    __table_args__ = (UniqueConstraint("anchor_claim_id", "new_claim_id"),)

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    anchor_claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"))
    new_claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"))
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    same_question: Mapped[str | None] = mapped_column(String, nullable=True)  # yes/partly/no
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class FieldComparison(Base):
    __tablename__ = "field_comparisons"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    claim_pair_id: Mapped[str] = mapped_column(String, ForeignKey("claim_pairs.id"))
    field_name: Mapped[str] = mapped_column(String)
    anchor_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(String)  # similar / differs / unknown


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    anchor_claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"))
    new_claim_id: Mapped[str | None] = mapped_column(String, ForeignKey("claims.id"), nullable=True)
    notice_id: Mapped[str | None] = mapped_column(String, ForeignKey("integrity_notices.id"), nullable=True)
    label: Mapped[str] = mapped_column(String)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String, nullable=True)  # high/medium/low
    confidence_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    skeptic_verdict: Mapped[str | None] = mapped_column(String, nullable=True)
    alternative_label: Mapped[str | None] = mapped_column(String, nullable=True)
    skeptic_argument: Mapped[str | None] = mapped_column(Text, nullable=True)
    needs_human_attention: Mapped[bool] = mapped_column(Boolean, default=False)
    priority_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String, default="ready_for_review")
    state: Mapped[str] = mapped_column(String, default="ready_for_review")  # ready_for_review|decided
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Phase 4A: agent orchestration
# ---------------------------------------------------------------------------

class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String, ForeignKey("cases.id"), unique=True)
    action: Mapped[str] = mapped_column(String)  # no_action|expert_review|author_contact|flag_for_update
    reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str] = mapped_column(String)
    decided_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    flagged_paper_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str | None] = mapped_column(String, ForeignKey("cases.id"), nullable=True)
    need_id: Mapped[str | None] = mapped_column(String, nullable=True)  # UC2 need reference
    run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    actor: Mapped[str] = mapped_column(String)  # system|editor|copilot
    event: Mapped[str] = mapped_column(String)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class RevisionItem(Base):
    __tablename__ = "revision_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String, ForeignKey("cases.id"))
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    where_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    started_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    finished_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cases_created: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String, default="running")  # running|done|error
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AffectedItem(Base):
    __tablename__ = "affected_items"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    case_id: Mapped[str] = mapped_column(String, ForeignKey("cases.id"))
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    score_components_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict
    relation: Mapped[str | None] = mapped_column(String, nullable=True)  # anchor/direct_citer/indirect


# ---------------------------------------------------------------------------
# Phase 6: Use Case 2 — Evidence-to-Impact Agent
# ---------------------------------------------------------------------------

class Need(Base):
    __tablename__ = "needs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    title: Mapped[str] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String)
    source_url: Mapped[str | None] = mapped_column(String, nullable=True)
    need_text: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(String)
    deadline: Mapped[str | None] = mapped_column(String, nullable=True)
    topic_keywords_json: Mapped[str] = mapped_column(Text)       # JSON list[str]
    population_of_interest: Mapped[str] = mapped_column(Text)
    setting_of_interest: Mapped[str] = mapped_column(Text)
    is_example: Mapped[bool] = mapped_column(Boolean, default=False)
    state: Mapped[str] = mapped_column(String, default="new")    # new|running|awaiting_approval|approved|submitted|outcome_recorded
    thread_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class NeedMatch(Base):
    __tablename__ = "need_matches"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    need_id: Mapped[str] = mapped_column(String, ForeignKey("needs.id"))
    claim_id: Mapped[str] = mapped_column(String, ForeignKey("claims.id"))
    paper_id: Mapped[str] = mapped_column(String, ForeignKey("papers.id"))
    fit_score: Mapped[float] = mapped_column(Float)
    fit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    included: Mapped[bool] = mapped_column(Boolean, default=True)  # editor-overridable


class CurrencyCheck(Base):
    __tablename__ = "currency_checks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    need_match_id: Mapped[str] = mapped_column(String, ForeignKey("need_matches.id"))
    # current|current_with_note|challenged|under_review|retracted
    status: Mapped[str] = mapped_column(String)
    source_case_id: Mapped[str | None] = mapped_column(String, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ContextFit(Base):
    __tablename__ = "context_fits"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    need_match_id: Mapped[str] = mapped_column(String, ForeignKey("need_matches.id"))
    level: Mapped[str] = mapped_column(String)   # good|partial|poor|unknown
    field_notes_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict


class Brief(Base):
    __tablename__ = "briefs"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    need_id: Mapped[str] = mapped_column(String, ForeignKey("needs.id"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    text: Mapped[str] = mapped_column(Text)
    claim_ids_json: Mapped[str] = mapped_column(Text)  # JSON list[str]
    # draft|approved|submitted|outcome_recorded
    status: Mapped[str] = mapped_column(String, default="draft")
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    approved_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


class BriefCheck(Base):
    __tablename__ = "brief_checks"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    brief_id: Mapped[str] = mapped_column(String, ForeignKey("briefs.id"))
    check_name: Mapped[str] = mapped_column(String)
    passed: Mapped[bool] = mapped_column(Boolean)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)


class SubmissionRecord(Base):
    __tablename__ = "submission_records"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    brief_id: Mapped[str] = mapped_column(String, ForeignKey("briefs.id"))
    submitted_by: Mapped[str] = mapped_column(String)
    submitted_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    channel_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class Outcome(Base):
    __tablename__ = "outcomes"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    brief_id: Mapped[str] = mapped_column(String, ForeignKey("briefs.id"))
    outcome: Mapped[str] = mapped_column(String)  # cited|acknowledged|no_visible_use
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
    impact_summary: Mapped[str | None] = mapped_column(Text, nullable=True)


class CoverageGap(Base):
    __tablename__ = "coverage_gaps"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    need_id: Mapped[str] = mapped_column(String, ForeignKey("needs.id"))
    reason: Mapped[str] = mapped_column(Text)
    idea_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, default="open")  # open|sent_to_editors
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)


# ---------------------------------------------------------------------------
# Agent Run Events (for AgentRunView animation)
# ---------------------------------------------------------------------------

class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    run_id: Mapped[str] = mapped_column(String, index=True)
    seq: Mapped[int] = mapped_column(Integer)
    node: Mapped[str] = mapped_column(String)
    # started | progress | finished | paused | failed
    status: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    counters_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON dict
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime(timezone=True), default=_now)
