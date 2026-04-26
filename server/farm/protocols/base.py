"""Base classes for jury protocols.

Implementing a new jury system is a matter of adding one file under
``server/farm/protocols/`` that subclasses :class:`BaseProtocol`. The class
will be discovered automatically by stem name; configure per-protocol
options under ``protocols.<name>:`` in ``config.yml``.

The contract is intentionally narrow:

* :meth:`submit` accepts a list of flag strings and returns the per-flag
  outcome. Order MUST match the input.
* The protocol is constructed once per submitter cycle, so it's fine to
  open short-lived clients in __init__/aenter; long-lived state belongs in
  the class.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


class FlagVerdict:
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


@dataclass(slots=True)
class SubmissionResult:
    """Per-flag outcome from the jury."""

    flag: str
    verdict: str          # FlagVerdict.*
    response: str = ""    # human-readable jury reply (verbatim)


class BaseProtocol(abc.ABC):
    """Subclass to add support for a new jury system.

    Implementations may be either sync or expose an async ``submit`` —
    the framework awaits whatever is returned. Keep it async if the
    protocol does network IO (it almost certainly should).
    """

    #: Human-readable name shown in the UI. Defaults to the class name.
    display_name: str = ""

    def __init__(self, **kwargs) -> None:  # noqa: D401 - intentional generic kwargs
        # Subclasses pull what they need; we keep the rest as-is for the UI
        # diagnostics.
        self.options = kwargs

    @abc.abstractmethod
    async def submit(self, flags: list[str]) -> list[SubmissionResult]:
        """Send flags to the jury and return one verdict per input flag."""
        raise NotImplementedError
