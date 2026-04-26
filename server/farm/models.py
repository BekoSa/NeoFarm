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
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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
    ERROR = "ERROR"            # transport-level failure


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

    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_flags_status_captured", "status", "captured_at"),
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
