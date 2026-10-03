from __future__ import annotations

from datetime import UTC, datetime

from farm.models import FlagStatus
from farm.protocols.base import FlagVerdict
from farm.workers.submitter import plan_updates

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def by_id(outcome):
    return {row["flag_id"]: row for row in outcome.rows}


def test_verdicts_map_to_statuses() -> None:
    out = plan_updates(
        [(1, "A"), (2, "B")],
        {"A": (FlagVerdict.ACCEPTED, "ok"), "B": (FlagVerdict.REJECTED, "too old")},
        NOW,
    )
    rows = by_id(out)
    assert rows[1]["status_value"] == FlagStatus.ACCEPTED.value
    assert rows[2]["status_value"] == FlagStatus.REJECTED.value
    assert rows[1]["submitted_at_value"] == NOW
    assert (out.accepted, out.rejected, out.retry) == (1, 1, 0)


def test_errors_are_requeued_not_burned() -> None:
    # A 4xx from a wrong team token/id must not be final: once the config
    # is fixed, these flags still have to reach the jury.
    out = plan_updates(
        [(1, "A"), (2, "B")],
        {"A": (FlagVerdict.ERROR, "HTTP 400: bad team id")},  # B: no verdict at all
        NOW,
    )
    rows = by_id(out)
    assert {r["status_value"] for r in rows.values()} == {FlagStatus.QUEUED.value}
    assert rows[1]["submitted_at_value"] is None
    assert rows[2]["response_value"] == "no verdict from protocol"
    assert out.retry == 2
    assert out.sample_error == "HTTP 400: bad team id"


def test_long_responses_are_truncated() -> None:
    out = plan_updates([(1, "A")], {"A": (FlagVerdict.REJECTED, "x" * 10_000)}, NOW)
    assert len(out.rows[0]["response_value"]) == 4000
