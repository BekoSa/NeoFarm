"""Structural validator for AltayCTF flags.

Measured against this farm's own database (3461 accepted vs 10721 flags the
jury rejected with ``Invalid Signature``), a real flag is always
``ALT_`` + exactly 26 lower-case hex chars, e.g.
``ALT_69cdd49a050c053c703d55b19a`` (13 bytes). This validator enforces that
shape plus an optional minimum-distinct-characters floor and a blacklist.

Honest effectiveness (see validators/base.py): 99% of the invalid-signature
flags were themselves perfect ``ALT_`` + 26-hex strings with high entropy —
structurally identical to real flags. The jury signature is a secret-keyed
MAC we cannot reproduce, so those cannot be caught locally. The structural
rules only drop the ~0.5% of broken/lazy forgeries (non-hex chars, or
degenerate bodies like ``ALT_00000000000000000000000000``), and they do so
with zero false positives on the accepted set (whose bodies never had fewer
than 9 distinct hex chars).

Config (all optional, shown with defaults)::

    flag_validator: altayctf
    validators:
      altayctf:
        prefix: "ALT_"
        body_len: 26          # exact length after the prefix, or [min, max],
                              # or null to disable the length check
        alphabet: "0-9a-f"    # character class allowed in the body
        min_distinct: 0       # reject a body with fewer than N distinct chars
                              # (0 disables it; 6-7 is safe — real min was 9)
        blacklist: []         # reject a flag containing any of these substrings
"""

from __future__ import annotations

import re

from .base import BaseValidator, ValidationResult


class AltayCtfValidator(BaseValidator):
    display_name = "AltayCTF (structural)"

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._prefix = str(kwargs.get("prefix", "ALT_"))

        body_len = kwargs.get("body_len", 26)
        if body_len is None:
            self._min_len, self._max_len = None, None
        elif isinstance(body_len, (list, tuple)) and len(body_len) == 2:
            self._min_len, self._max_len = int(body_len[0]), int(body_len[1])
        else:
            self._min_len = self._max_len = int(body_len)

        alphabet = str(kwargs.get("alphabet", "0-9a-f"))
        self._body_re = re.compile(f"^[{alphabet}]+$")
        self._min_distinct = int(kwargs.get("min_distinct", 0))
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

        if self._min_distinct and len(set(body)) < self._min_distinct:
            return ValidationResult.reject(
                f"body has {len(set(body))} distinct chars < {self._min_distinct} (likely fake)"
            )

        return ValidationResult.accept()
