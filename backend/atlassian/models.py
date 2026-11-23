"""Data contracts for Requirements Intelligence (Phase 0). Design: docs/REQUIREMENTS_INTELLIGENCE.md.

The rules the rest of the feature relies on are enforced here, so no later code can bypass them:

  Connection         Jira Cloud / Confluence Cloud only (https://<site>.atlassian.net); the token is NEVER stored
                     in the model, only the name of the secret that holds it; read-only unless writes are enabled
  SourceRef          every requirement cites where it came from: site, issue key / page id, version, link, hash
  AcceptanceCriterion  text taken from a source must appear in its cited quote (nothing invented); an AI proposal
                     stays 'needs_review' until a person accepts it; an unautomatable criterion says why
  TraceLink          requirement -> criterion -> test case -> run; 'passed' / 'failed' / 'flaky' need a run id
                     AND evidence; the source version the test was designed from is kept
  OutboundWrite      every NEW write to Jira needs an approval id before it is approved or sent, and carries an
                     idempotency key so a retry never creates a second comment / issue / link
  ai_use_allowed     whether requirement text may be sent to an AI under the privacy mode and its classification
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from enum import Enum
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = 1

CLOUD_HOST = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}\.atlassian\.net$")
ISSUE_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,19}-[1-9][0-9]{0,9}$")
PAGE_ID = re.compile(r"^[0-9]{1,20}$")
SECRET_REF = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")  # the NAME of an env var / secret, e.g. JIRA_API_TOKEN
# values that look like a credential rather than a name (Atlassian API tokens start with ATATT, PATs are long)
LOOKS_LIKE_SECRET = re.compile(r"(ATATT|ATCTT)[A-Za-z0-9_\-=]{8,}|[A-Za-z0-9_\-]{40,}")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=False)


def _no_secret(value: str, field: str) -> str:
    if LOOKS_LIKE_SECRET.search(value or ""):
        raise ValueError(f"{field} looks like a credential; store the token as a secret and give its name")
    return value


def normalize_text(text: str) -> str:
    """For comparing a criterion with its quote: same characters, case and spacing ignored."""
    text = unicodedata.normalize("NFKC", text or "").replace("’", "'").replace("“", '"').replace(
        "”", '"')
    return re.sub(r"\s+", " ", text).strip().lower()


def content_hash(text: str) -> str:
    """sha256 of the normalized content: the same text in a later sync -> the same hash (no change)."""
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- enums

class Product(str, Enum):
    jira = "jira"
    confluence = "confluence"


class SourceKind(str, Enum):
    jira_issue = "jira_issue"
    confluence_page = "confluence_page"
    confluence_attachment = "confluence_attachment"


class Classification(str, Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"


class Extraction(str, Enum):
    rules = "rules"            # copied from the source by deterministic rules (Gherkin, AC field, AC section)
    human = "human"            # typed or edited by a person in review
    ai_proposed = "ai_proposed"  # suggested by an AI: never trusted until a person accepts it


class ReviewStatus(str, Enum):
    needs_review = "needs_review"
    accepted = "accepted"
    rejected = "rejected"


class TestResult(str, Enum):
    not_run = "not_run"
    passed = "passed"
    failed = "failed"
    flaky = "flaky"
    skipped = "skipped"
    blocked = "blocked"
    inconclusive = "inconclusive"
    not_automated = "not_automated"


EXECUTED = {TestResult.passed, TestResult.failed, TestResult.flaky}


class WriteOperation(str, Enum):
    create_issue = "create_issue"
    add_comment = "add_comment"
    add_remote_link = "add_remote_link"
    link_issues = "link_issues"
    add_attachment = "add_attachment"


class WriteStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    rejected = "rejected"
    sent = "sent"
    failed = "failed"


class SyncStatus(str, Enum):
    idle = "idle"
    running = "running"
    complete = "complete"
    partial = "partial"   # some items failed; the cursor still points at the last good page
    failed = "failed"


# ---------------------------------------------------------------- connection

class Connection(_Model):
    """One Atlassian Cloud site for one tenant. Holds where and how - never the token itself."""
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    tenant_id: str = Field(min_length=1, max_length=64)
    product: Product
    site_url: str
    email: str = Field(min_length=3, max_length=254)
    token_ref: str  # the NAME of the secret (e.g. JIRA_API_TOKEN), resolved only at request time
    read_only: bool = True
    allow_writes: bool = False  # even when True, every write still needs an approval (OutboundWrite)
    classification: Classification = Classification.internal
    allow_cloud_ai_for_confidential: bool = False

    @field_validator("site_url")
    @classmethod
    def cloud_only(cls, v: str) -> str:
        p = urlparse(v)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or not CLOUD_HOST.match(host) or p.port not in (None, 443) or p.username:
            raise ValueError("site_url must be https://<your-site>.atlassian.net (Atlassian Cloud only)")
        if p.path not in ("", "/", "/wiki", "/wiki/") or p.query or p.fragment:
            raise ValueError("site_url must be the site address only")
        return f"https://{host}"

    @field_validator("token_ref")
    @classmethod
    def name_not_value(cls, v: str) -> str:
        _no_secret(v, "token_ref")
        if not SECRET_REF.match(v):
            raise ValueError("token_ref must be the NAME of a secret such as JIRA_API_TOKEN, not the token")
        return v

    @field_validator("email")
    @classmethod
    def plain_email(cls, v: str) -> str:
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v):
            raise ValueError("email is not an email address")
        return v

    @model_validator(mode="after")
    def writes_need_switch(self):
        if self.allow_writes and self.read_only:
            raise ValueError("allow_writes needs read_only=False")
        return self

    @property
    def host(self) -> str:
        return urlparse(self.site_url).hostname or ""


# ---------------------------------------------------------------- sources and citations

class SourceRef(_Model):
    """Exactly where a requirement came from, at which version."""
    tenant_id: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=64)
    kind: SourceKind
    source_id: str = Field(min_length=1, max_length=64)  # PROJ-12 | Confluence page / attachment id
    version: int = Field(ge=1)  # Confluence version number; Jira: our own counter, +1 when content_hash changes
    updated: datetime  # the source's own last-modified time (Jira 'updated', Confluence version.createdAt)
    url: str
    title: str = Field(default="", max_length=500)
    content_hash: str
    retrieved_at: datetime
    parent_id: str = ""  # an attachment's page, a sub-task's story

    @field_validator("content_hash")
    @classmethod
    def sha256_hex(cls, v: str) -> str:
        if not HEX64.match(v):
            raise ValueError("content_hash must be a sha256 hex digest (content_hash())")
        return v

    @model_validator(mode="after")
    def id_and_link_match(self):
        if self.kind == SourceKind.jira_issue and not ISSUE_KEY.match(self.source_id):
            raise ValueError("a Jira source_id is an issue key such as PROJ-12")
        if self.kind != SourceKind.jira_issue and not PAGE_ID.match(self.source_id):
            raise ValueError("a Confluence source_id is a numeric id")
        p = urlparse(self.url)
        if p.scheme != "https" or not CLOUD_HOST.match((p.hostname or "").lower()):
            raise ValueError("url must be an https link on <site>.atlassian.net")
        return self

    @property
    def key(self) -> str:
        """Stable identity of the source, without its version."""
        return f"{self.connection_id}:{self.kind.value}:{self.source_id}"


class Citation(_Model):
    """A quote from one version of one source: the proof behind a criterion or an expected outcome."""
    source: SourceRef
    locator: str = Field(min_length=1, max_length=200)  # 'description', 'customfield_10045', 'h2: Login rules'
    quote: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- requirements

class AcceptanceCriterion(_Model):
    id: str = Field(pattern=r"^[A-Za-z0-9:_-]+#AC-[1-9][0-9]{0,3}$")  # PROJ-12#AC-1
    requirement_id: str
    text: str = Field(min_length=3, max_length=2000)
    given: str = ""
    when: str = ""
    then: str = ""
    expected_outcome: str = ""  # only what the source says; empty when the source gives none
    citations: list[Citation] = Field(min_length=1)
    extraction: Extraction
    review: ReviewStatus = ReviewStatus.needs_review
    reviewer: str = ""
    automatable: bool = True
    not_automatable_reason: str = ""
    platforms: list[Literal["web", "android"]] = Field(default_factory=lambda: ["web"])

    @model_validator(mode="after")
    def grounded(self):
        if not self.id.startswith(self.requirement_id + "#"):
            raise ValueError("criterion id must start with its requirement id")
        quotes = " ".join(normalize_text(c.quote) for c in self.citations)
        if self.extraction == Extraction.rules:
            # taken from the source: the criterion and its expected outcome must be IN the quote
            for name in ("text", "expected_outcome", "given", "when", "then"):
                value = normalize_text(getattr(self, name))
                if value and value not in quotes:
                    raise ValueError(f"{name} is not in the cited source text (nothing may be invented)")
        if self.extraction == Extraction.ai_proposed and self.expected_outcome:
            out = normalize_text(self.expected_outcome)
            if out not in quotes:
                raise ValueError("an AI-proposed expected outcome must be quoted from the source")
        if self.review == ReviewStatus.accepted and self.extraction != Extraction.rules and not self.reviewer:
            raise ValueError("an AI-proposed or edited criterion is accepted only by a named reviewer")
        if not self.automatable and not self.not_automatable_reason.strip():
            raise ValueError("an unautomatable criterion must say why")
        if self.automatable and self.not_automatable_reason:
            raise ValueError("not_automatable_reason is only for unautomatable criteria")
        return self

    @property
    def usable(self) -> bool:
        """May become a test: accepted, or taken from the source by rules and not rejected."""
        return self.review == ReviewStatus.accepted or (
            self.extraction == Extraction.rules and self.review != ReviewStatus.rejected)


class Requirement(_Model):
    id: str = Field(min_length=1, max_length=80)  # PROJ-12, or conf:<page id>
    tenant_id: str = Field(min_length=1, max_length=64)
    kind: Literal["story", "bug", "task", "epic", "spec"] = "story"
    title: str = Field(min_length=1, max_length=500)
    sources: list[SourceRef] = Field(min_length=1)  # the issue first, then linked Confluence pages
    criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    classification: Classification = Classification.internal
    labels: list[str] = Field(default_factory=list)
    status: str = ""  # the Jira status as shown there, e.g. 'In Progress'

    @model_validator(mode="after")
    def consistent(self):
        tenants = {s.tenant_id for s in self.sources}
        if tenants != {self.tenant_id}:
            raise ValueError("every source of a requirement belongs to the requirement's tenant")
        known = {s.key for s in self.sources}
        ids = set()
        for c in self.criteria:
            if c.requirement_id != self.id:
                raise ValueError(f"{c.id} belongs to another requirement")
            if c.id in ids:
                raise ValueError(f"duplicate criterion id {c.id}")
            ids.add(c.id)
            for cit in c.citations:
                if cit.source.key not in known:
                    raise ValueError(f"{c.id} cites a source that is not one of this requirement's sources")
        return self


class Conflict(_Model):
    """Two sources disagree (e.g. the story says 8 characters, the spec says 12). Never resolved by the AI."""
    id: str = Field(min_length=1, max_length=80)
    tenant_id: str = Field(min_length=1, max_length=64)
    requirement_ids: list[str] = Field(min_length=1)
    summary: str = Field(min_length=5, max_length=1000)
    citations: list[Citation] = Field(min_length=2)
    detected_by: Literal["rules", "ai"]
    status: Literal["open", "resolved", "not_a_conflict"] = "open"
    resolution: str = ""
    resolved_by: str = ""

    @model_validator(mode="after")
    def resolved_by_person(self):
        if len({c.source.key + c.locator for c in self.citations}) < 2:
            raise ValueError("a conflict cites two different places")
        if self.status != "open" and not (self.resolved_by and self.resolution):
            raise ValueError("only a named person resolves a conflict, with the resolution")
        return self


# ---------------------------------------------------------------- traceability

class TraceLink(_Model):
    """requirement -> criterion -> test case -> one run's result. One row per (criterion, test, run)."""
    tenant_id: str = Field(min_length=1, max_length=64)
    requirement_id: str
    criterion_id: str
    source_key: str
    source_version: int = Field(ge=1)  # the version the test was designed from (stale when the source moved on)
    tc_id: str = Field(min_length=1, max_length=80)
    platform: Literal["web", "android"]
    run_id: str = ""
    result: TestResult = TestResult.not_run
    evidence: list[str] = Field(default_factory=list)  # run-relative paths: screenshot, trace, video, log
    reason: str = ""
    defect_keys: list[str] = Field(default_factory=list)  # Jira bugs linked to this failure
    recorded_at: datetime | None = None

    @field_validator("evidence")
    @classmethod
    def run_relative(cls, v: list[str]) -> list[str]:
        for path in v:
            if path.startswith(("/", "\\")) or ".." in re.split(r"[\\/]", path) or re.match(r"^[A-Za-z]:", path):
                raise ValueError("evidence paths are relative to the run folder")
        return v

    @field_validator("defect_keys")
    @classmethod
    def issue_keys(cls, v: list[str]) -> list[str]:
        for key in v:
            if not ISSUE_KEY.match(key):
                raise ValueError(f"{key!r} is not a Jira issue key")
        return v

    @model_validator(mode="after")
    def evidence_first(self):
        if not self.criterion_id.startswith(self.requirement_id + "#"):
            raise ValueError("criterion_id must belong to requirement_id")
        if self.result in EXECUTED and not (self.run_id and self.evidence):
            raise ValueError(f"'{self.result.value}' needs the run id and execution evidence")
        if self.result in (TestResult.not_automated, TestResult.blocked, TestResult.skipped,
                           TestResult.inconclusive) and not self.reason.strip():
            raise ValueError(f"'{self.result.value}' needs a reason")
        if self.result == TestResult.not_run and (self.run_id or self.evidence):
            raise ValueError("a test that was not run has no run evidence")
        return self

    def is_stale(self, current_version: int) -> bool:
        return current_version > self.source_version


# ---------------------------------------------------------------- synchronization

class SyncCursor(_Model):
    """Where an incremental sync stands, so a stopped or failed sync resumes instead of starting over."""
    tenant_id: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=64)
    scope: str = Field(min_length=1, max_length=2000)  # 'jql:project = PROJ AND type = Story' | 'space:ENG'
    high_water: datetime | None = None  # newest 'updated' fully stored; the next sync asks for updated >= this
    next_page_token: str = Field(default="", max_length=4000)  # Jira /search/jql nextPageToken, Confluence cursor
    status: SyncStatus = SyncStatus.idle
    fetched: int = Field(default=0, ge=0)
    failed_items: list[str] = Field(default_factory=list)
    last_error: str = Field(default="", max_length=500)

    @field_validator("last_error")
    @classmethod
    def no_secret_in_error(cls, v: str) -> str:
        return LOOKS_LIKE_SECRET.sub("[redacted]", v)

    @model_validator(mode="after")
    def page_token_only_while_running(self):
        if self.next_page_token and self.status == SyncStatus.complete:
            raise ValueError("a complete sync has no next page")
        return self


def idempotency_key(tenant_id: str, operation: WriteOperation, target: str, payload: dict) -> str:
    """The same write (tenant, operation, target, content) -> the same key, so a retry is recognized."""
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    raw = f"{tenant_id}|{operation.value}|{target}|{body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class OutboundWrite(_Model):
    """One proposed NEW write to Jira (comment, issue, link). Approved by a person before it is sent.
    (Qpilot's older opt-in defect creation, integrations.create_jira_issues, is unchanged and not modelled here.)"""
    tenant_id: str = Field(min_length=1, max_length=64)
    connection_id: str = Field(min_length=1, max_length=64)
    operation: WriteOperation
    target: str = Field(min_length=1, max_length=80)  # an issue key, or a project key for create_issue
    payload: dict
    idempotency_key: str
    status: WriteStatus = WriteStatus.proposed
    approval_id: str = ""  # backend/approvals.py row id
    approved_by: str = ""
    remote_id: str = ""  # what Jira answered (comment id, new issue key, link id)
    attempts: int = Field(default=0, ge=0)
    last_error: str = Field(default="", max_length=500)

    @field_validator("last_error")
    @classmethod
    def no_secret_in_error(cls, v: str) -> str:
        return LOOKS_LIKE_SECRET.sub("[redacted]", v)

    @model_validator(mode="after")
    def approved_first(self):
        if self.idempotency_key != idempotency_key(self.tenant_id, self.operation, self.target, self.payload):
            raise ValueError("idempotency_key does not match the write (use idempotency_key())")
        if self.status in (WriteStatus.approved, WriteStatus.sent, WriteStatus.failed) and not (
                self.approval_id and self.approved_by):
            raise ValueError("a write is approved by a named person (approval_id) before it is sent")
        if self.status == WriteStatus.sent and not self.remote_id:
            raise ValueError("a sent write records what Jira answered")
        if self.operation != WriteOperation.create_issue and not ISSUE_KEY.match(self.target):
            raise ValueError("the target of this write is an issue key")
        if self.operation == WriteOperation.create_issue and not re.match(r"^[A-Z][A-Z0-9_]{0,19}$", self.target):
            raise ValueError("create_issue targets a project key")
        _no_secret(json.dumps(self.payload, default=str), "payload")
        return self


# ---------------------------------------------------------------- privacy

def ai_use_allowed(classification: Classification, *, privacy_mode: str, cloud_consent: bool,
                   provider_is_local: bool, connection: Connection | None = None) -> tuple[bool, str]:
    """May this requirement's text go to the AI? Builds on backend/privacy.py (local / cloud mode).

    local mode       only a local model (Ollama on this PC)
    cloud mode       needs consent; 'confidential' only when the connection explicitly allows it
    """
    if provider_is_local:
        return True, "local model: the text stays on this computer"
    if privacy_mode != "cloud":
        return False, "privacy mode is 'local only': requirement text is not sent to a cloud AI"
    if not cloud_consent:
        return False, "cloud AI needs your consent in the privacy settings"
    if classification == Classification.confidential and not (
            connection and connection.allow_cloud_ai_for_confidential):
        return False, "confidential requirements are not sent to a cloud AI unless the connection allows it"
    return True, "cloud AI allowed by the privacy settings"
