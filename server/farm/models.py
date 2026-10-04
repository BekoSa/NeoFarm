"""Database models.

The data model is intentionally tiny — three tables are enough:

* `flags`     — every flag we see, with submission state.
* `exploits`  — sploits registered by clients (so the UI can show them).
* `runs`     — recent exploit runs (per round / per team) with stdout snippets.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class FlagStatus(StrEnum):
    QUEUED = "QUEUED"          # captured, not submitted yet
    PENDING = "PENDING"        # picked up by submitter, awaiting jury reply
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    DUPLICATE = "DUPLICATE"    # we already had it
    ERROR = "ERROR"            # legacy: jury errors are now retried until expiry


class Flag(Base):
    __tablename__ = "flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flag: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    status: Mapped[FlagStatus] = mapped_column(
        String(16), default=FlagStatus.QUEUED, index=True
    )
    sploit: Mapped[str | None] = mapped_column(String(128), index=True)
    team: Mapped[str | None] = mapped_column(String(64), index=True)
    target_ip: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[str | None] = mapped_column(Text)
    # Jury submission attempts so far; the submitter serves fresh flags
    # (fewest attempts) before retrying ones the jury failed to answer.
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_flags_status_captured", "status", "captured_at"),
        Index("ix_flags_status_submitted", "status", "submitted_at"),
        Index("ix_flags_status_attempts_captured", "status", "attempts", "captured_at"),
    )


class Exploit(Base):
    __tablename__ = "exploits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    host: Mapped[str | None] = mapped_column(String(128))   # which client runs it
    enabled: Mapped[bool] = mapped_column(default=True)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    runs: Mapped[list["Run"]] = relationship(back_populates="exploit")


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exploit_id: Mapped[int | None] = mapped_column(
        ForeignKey("exploits.id", ondelete="SET NULL"), index=True
    )
    sploit: Mapped[str] = mapped_column(String(128), index=True)
    team: Mapped[str | None] = mapped_column(String(64), index=True)
    target_ip: Mapped[str | None] = mapped_column(String(64))
    host: Mapped[str | None] = mapped_column(String(128))   # which client
    flags_found: Mapped[int] = mapped_column(default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    stdout_tail: Mapped[str | None] = mapped_column(Text)
    stderr_tail: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )

    exploit: Mapped[Exploit | None] = relationship(back_populates="runs")


class Node(Base):
    """A teammate's machine running the ``farm-cli node`` agent.

    The agent registers itself (stable ``node_id``), heartbeats every few
    seconds, and in return receives the exploit tasks the operator assigned
    to it from the UI. It then drives those exploits in round loops exactly
    like ``farm-cli run`` — flags and run reports flow through the normal
    pipeline — while the farm tracks each node's liveness and what it runs.
    """

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Stable id generated once by the agent; survives restarts / renames.
    node_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(128))
    hostname: Mapped[str | None] = mapped_column(String(128))
    ip: Mapped[str | None] = mapped_column(String(64))
    labels: Mapped[str | None] = mapped_column(String(256))  # free-form tags
    agent_version: Mapped[str | None] = mapped_column(String(32))
    # Operator switch: when off, the node stops every task (break / repair).
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # Last status word the agent reported (informational).
    status: Mapped[str | None] = mapped_column(String(32))
    # JSON array the agent reports: what it is currently running.
    running: Mapped[str | None] = mapped_column(Text)
    last_seen: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    tasks: Mapped[list["NodeTask"]] = relationship(
        back_populates="node", cascade="all, delete-orphan"
    )


class NodeTask(Base):
    """One exploit the operator pushed onto a node.

    The script body travels with the task so the node is self-contained: on
    each heartbeat the agent compares ``rev`` and only rewrites/restarts the
    exploit when it actually changed.
    """

    __tablename__ = "node_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    node_id: Mapped[int] = mapped_column(
        ForeignKey("nodes.id", ondelete="CASCADE"), index=True
    )
    sploit: Mapped[str] = mapped_column(String(128))
    script_name: Mapped[str] = mapped_column(String(128))
    script: Mapped[str] = mapped_column(Text)
    args: Mapped[str | None] = mapped_column(String(512))
    enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )
    # Bumped whenever script/args change, so the agent knows to re-sync.
    rev: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    node: Mapped[Node] = relationship(back_populates="tasks")

    __table_args__ = (
        UniqueConstraint("node_id", "sploit", name="uq_node_tasks_node_sploit"),
    )
