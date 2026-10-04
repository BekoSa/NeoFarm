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

A stronger (but riskier) pattern lives in the body ends. Across 3930 accepted
flags the body ALWAYS started with "6" and ended with "a"; among the
signature-rejected flags that held for only 0.3%. Requiring body_prefix "6"
and body_suffix "a" would therefore drop ~99.7% of forgeries with zero false
positives *on this snapshot*. It is OFF by default on purpose: those markers
are inferred, not documented. If "6" is a fixed format nibble they are safe,
but if it is the high nibble of a timestamp/round counter it will roll over
mid-game and then this rule drops EVERY real flag. Enable only once you are
sure the markers are constant, and watch the accepted rate right after.

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
        body_prefix: ""       # require the body to start with this (e.g. "6") —
                              # see the warning above before enabling
        body_suffix: ""       # require the body to end with this (e.g. "a")
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
        # Optional fixed format markers at the ends of the body. Observed in
        # this farm's data: every one of 3930 accepted flags began with "6"
        # and ended with "a", while that pattern held for only 0.3% of the
        # signature-rejected ones. Off by default — see the module docstring
        # for the risk of enabling it mid-game.
        self._body_prefix = str(kwargs.get("body_prefix", ""))
        self._body_suffix = str(kwargs.get("body_suffix", ""))

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

        if self._body_prefix and not body.startswith(self._body_prefix):
            return ValidationResult.reject(f"body does not start with {self._body_prefix!r}")

        if self._body_suffix and not body.endswith(self._body_suffix):
            return ValidationResult.reject(f"body does not end with {self._body_suffix!r}")

        return ValidationResult.accept()
