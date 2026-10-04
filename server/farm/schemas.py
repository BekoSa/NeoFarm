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


class NodeTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sploit: str
    script_name: str
    script: str
    args: str | None
    enabled: bool
    rev: int
    created_at: datetime
    updated_at: datetime


class NodeTaskCreate(BaseModel):
    sploit: str = Field(..., min_length=1, max_length=128)
    script: str = Field(..., description="The exploit source the node writes and runs.")
    script_name: str | None = Field(
        None, description="Filename to write (defaults to <sploit>.py)."
    )
    args: str | None = None
    enabled: bool = True


class NodeTaskUpdate(BaseModel):
    script: str | None = None
    script_name: str | None = None
    args: str | None = None
    enabled: bool | None = None


class NodeHeartbeat(BaseModel):
    """Agent -> farm, every few seconds."""

    node_id: str = Field(..., min_length=1, max_length=64)
    name: str | None = None
    hostname: str | None = None
    ip: str | None = None
    labels: str | None = None
    agent_version: str | None = None
    status: str | None = None
    # What the agent is running right now, e.g. [{"sploit": "...", "since": ...}].
    running: list[dict] = Field(default_factory=list)


class NodeHeartbeatResponse(BaseModel):
    """Farm -> agent: the node switch, farm state, and the assigned tasks."""

    enabled: bool
    paused: bool
    round_length: int
    flag_format: str
    tasks: list[NodeTaskOut]


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    node_id: str
    name: str | None
    hostname: str | None
    ip: str | None
    labels: str | None
    agent_version: str | None
    enabled: bool
    status: str | None
    # Parsed from the stored JSON by the API layer.
    running: list[dict] = Field(default_factory=list)
    task_count: int = 0
    last_seen: datetime | None
    created_at: datetime


class NodeUpdate(BaseModel):
    name: str | None = None
    labels: str | None = None
    enabled: bool | None = None


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
