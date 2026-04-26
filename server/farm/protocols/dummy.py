"""Dummy protocol — accepts everything. For local testing without a jury."""

from __future__ import annotations

import random

from .base import BaseProtocol, FlagVerdict, SubmissionResult


class DummyProtocol(BaseProtocol):
    display_name = "Dummy (local testing)"

    def __init__(self, accept_rate: float = 1.0, **kwargs) -> None:
        super().__init__(accept_rate=accept_rate, **kwargs)
        self.accept_rate = float(accept_rate)

    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        out: list[SubmissionResult] = []
        for f in flags:
            if random.random() < self.accept_rate:
                out.append(
                    SubmissionResult(flag=f, verdict=FlagVerdict.ACCEPTED, response="dummy: ok")
                )
            else:
                out.append(
                    SubmissionResult(
                        flag=f, verdict=FlagVerdict.REJECTED, response="dummy: rejected"
                    )
                )
        return out
