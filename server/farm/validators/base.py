"""Base classes for local flag validators.

A validator is a *local*, pre-queue sanity check on a flag the farm has
already extracted with ``flag_format``. Its job is to drop flags that are
worth rejecting *without* spending a jury submission on them — e.g. junk
that other teams plant in their own service output hoping our exploits
scrape and submit it, clogging the queue and the jury rate limit.

Hard truth about signatures: a real jury flag is usually ``prefix + MAC``
where the MAC is computed with the jury's **secret** key. Without that key
the signature cannot be verified locally — that is the whole point of it.
So a validator can enforce *structure* (prefix, length, alphabet, a
key-free checksum if the format has one) and *blacklists*, but it cannot
tell a perfectly-formatted forgery from a real flag. Keep expectations
honest and never reject something you are not sure about: a wrongly
dropped flag is a lost point, while a forgery that slips through only
costs one jury reject (which is final and not retried).

Adding a validator is exactly like adding a protocol: drop one ``*.py``
file in this directory defining a single :class:`BaseValidator` subclass;
the file stem becomes its id (set it as ``flag_validator:`` in
``config.yml``). Per-validator options go under ``validators.<id>:``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(slots=True)
class ValidationResult:
    """Outcome of a local check for one flag."""

    ok: bool
    reason: str = ""  # why it was dropped (shown in logs/stats), empty when ok

    @classmethod
    def accept(cls) -> "ValidationResult":
        return cls(True)

    @classmethod
    def reject(cls, reason: str) -> "ValidationResult":
        return cls(False, reason)


class BaseValidator(abc.ABC):
    """Subclass to add a local flag check for a particular CTF/jury.

    Instances are built once per ingestion request from
    ``validators.<id>:`` kwargs, so ``__init__`` may precompile regexes or
    load tables. :meth:`validate` must be cheap and side-effect free — it
    runs once per captured flag.
    """

    #: Human-readable name for the UI; defaults to the class name.
    display_name: str = ""

    def __init__(self, **kwargs) -> None:
        # Subclasses pull what they need; the rest is kept for diagnostics.
        self.options = kwargs

    @abc.abstractmethod
    def validate(self, flag: str) -> ValidationResult:
        """Return whether `flag` is worth submitting to the jury."""
        raise NotImplementedError

    def validate_many(self, flags: list[str]) -> list[ValidationResult]:
        """Validate a batch; override if a bulk check is cheaper."""
        return [self.validate(flag) for flag in flags]
