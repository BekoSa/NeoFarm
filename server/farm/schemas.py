"""Pydantic schemas for the public API."""

from __future__ import annotations

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field


class FlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    flag: str
    status: str
    sploit: str | None
    team: str | None
    target_ip: str | None
    response: str | None
    captured_at: datetime
    submitted_at: datetime | None


class FlagSubmitItem(BaseModel):
    """Either pre-extracted flags, or raw stdout (we'll regex it)."""

    flag: str | None = None
    output: str | None = None
    sploit: str | None = None
    team: str | None = None
    target_ip: str | None = None


class FlagSubmitRequest(BaseModel):
    items: list[FlagSubmitItem] = Field(default_factory=list)


class FlagSubmitResponse(BaseModel):
    new: int
    duplicate: int
    invalid: int


class FlagRequeueRequest(BaseModel):
    """Bulk requeue filter — e.g. every ERROR/REJECTED flag after fixing
    the jury credentials. Only flags still within `flag_lifetime` move."""

    status: str
    sploit: str | None = None
    team: str | None = None
    q: str | None = None


class FlagRequeueResponse(BaseModel):
    requeued: int


class ManualFlagsRequest(BaseModel):
    text: str = Field(..., description="Free-form text containing flags to submit.")
    sploit: str | None = "manual"
    team: str | None = None


class ExploitOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    host: str | None
    enabled: bool
    last_seen: datetime | None
    notes: str | None
    created_at: datetime


class ExploitRegister(BaseModel):
    """Client heartbeat. `enabled` is left alone unless explicitly sent, so
    a restarted client doesn't re-enable a sploit switched off in the UI."""

    name: str
    host: str | None = None
    notes: str | None = None
    enabled: bool | None = None


class ExploitUpdate(BaseModel):
    """Partial update from the UI; omitted fields are kept."""

    name: str | None = None
    host: str | None = None
    notes: str | None = None
    enabled: bool | None = None


class RunReport(BaseModel):
    sploit: str
    team: str | None = None
    target_ip: str | None = None
    host: str | None = None
    flags_found: int = 0
    duration_ms: int | None = None
    exit_code: int | None = None
    stdout_tail: str | None = None
    stderr_tail: str | None = None


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sploit: str
    team: str | None
    target_ip: str | None
    host: str | None
    flags_found: int
    duration_ms: int | None
    exit_code: int | None
    stdout_tail: str | None
    stderr_tail: str | None
    started_at: datetime


class TeamOut(BaseModel):
    alias: str
    ip: str


class StatsBucket(BaseModel):
    label: str
    accepted: int = 0
    rejected: int = 0
    queued: int = 0
    expired: int = 0
    duplicate: int = 0
    error: int = 0


class StatsOut(BaseModel):
    totals: StatsBucket
    by_sploit: list[StatsBucket]
    by_team: list[StatsBucket]
    last_minute: StatsBucket
    last_hour: StatsBucket
    # Running total of duplicate captures dropped at ingest (not stored as
    # rows, so this comes from a counter, not the flags table).
    deduplicated: int = 0
