"""Default validator: accept every well-formed flag.

This keeps the farm's behaviour unchanged — flags are already filtered by
``flag_format`` upstream, so there is nothing more to check. It is the
default ``flag_validator`` and the fallback when a configured validator id
is unknown.
"""

from __future__ import annotations

from .base import BaseValidator, ValidationResult


class PassthroughValidator(BaseValidator):
    display_name = "Passthrough (accept all)"

    def validate(self, flag: str) -> ValidationResult:
        return ValidationResult.accept()
