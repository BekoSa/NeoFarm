"""Structural validator for AltayCTF flags.

A real jury flag looks like ``alt_eDc3c5bdbdbb5dab6382a150b8``: the prefix
``alt_`` followed by a fixed-length alphanumeric body. This validator
drops flags that do not fit that shape — tighter than a permissive
``flag_format`` regex — plus anything matching a configurable blacklist.

It canNOT detect a forgery that copies the format exactly: the jury's
``Invalid Signature`` verdict comes from a secret-keyed MAC we cannot
check locally (see ``validators/base.py``). It only removes malformed junk
before it reaches the queue, so it is a cheap first line, not a guarantee.

Config (all optional, shown with defaults)::

    flag_validator: altayctf
    validators:
      altayctf:
        prefix: "alt_"
        body_len: 26          # exact length of the part after the prefix,
                              # or [min, max]; null disables the length check
        alphabet: "A-Za-z0-9" # character class allowed in the body
        blacklist: []         # reject a flag containing any of these substrings
"""

from __future__ import annotations

import re

from .base import BaseValidator, ValidationResult


class AltayCtfValidator(BaseValidator):
    display_name = "AltayCTF (structural)"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefix = str(kwargs.get("prefix", "alt_"))

        body_len = kwargs.get("body_len", 26)
        if body_len is None:
            self._min_len, self._max_len = None, None
        elif isinstance(body_len, (list, tuple)) and len(body_len) == 2:
            self._min_len, self._max_len = int(body_len[0]), int(body_len[1])
        else:
            self._min_len = self._max_len = int(body_len)

        alphabet = str(kwargs.get("alphabet", "A-Za-z0-9"))
        self._body_re = re.compile(f"^[{alphabet}]+$")
        self._blacklist = [str(s) for s in (kwargs.get("blacklist") or [])]

    def validate(self, flag: str) -> ValidationResult:
        for bad in self._blacklist:
            if bad and bad in flag:
                return ValidationResult.reject(f"blacklisted substring {bad!r}")

        if not flag.startswith(self._prefix):
            return ValidationResult.reject(f"missing prefix {self._prefix!r}")

        body = flag[len(self._prefix):]
        if self._min_len is not None and not (self._min_len <= len(body) <= self._max_len):
            want = (
                str(self._min_len)
                if self._min_len == self._max_len
                else f"{self._min_len}..{self._max_len}"
            )
            return ValidationResult.reject(f"body length {len(body)} != {want}")

        if not self._body_re.match(body):
            return ValidationResult.reject("body has characters outside the alphabet")

        return ValidationResult.accept()
