"""Verdict parsing shared by the AltayCTF protocols.

The leading underscore keeps the plugin loader from treating this module as
a protocol. The jury's exact reply wording isn't published, so replies are
classified by whole words, with negative words taking precedence over
positive ones ("incorrect", "not accepted" must never count as accepted).
Anything unrecognised is an ERROR, which the submitter retries — so a
surprising reply costs a retry, never a flag. Tune the word lists below
once you have seen the real jury answers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .base import FlagVerdict

# Jury-side trouble: worth retrying the same flag later.
_RETRY_PHRASES = (
    "rate limit", "too many", "try again", "try later", "slow down", "internal",
    "unavailable", "not available", "timeout", "timed out", "server error",
    "not started", "game is over", "game over", "paused",
)
# The flag itself is bad / already used — final.
_REJECT_WORDS = frozenset({
    "invalid", "incorrect", "wrong", "bad", "rejected", "reject", "denied",
    "expired", "old", "stale", "duplicate", "duplicated", "already", "own",
    "yours", "unknown", "fake", "not", "no", "nope", "unsuccessful", "fail",
    "failed", "false",
})
_ACCEPT_WORDS = frozenset({
    "accepted", "accept", "correct", "success", "successful", "ok", "okay",
    "captured", "good", "congratulations", "congrats", "true",
})
# Boolean fields that carry the verdict directly.
_BOOL_KEYS = ("accepted", "success", "ok", "valid", "status", "result")
# Text fields that carry a human-readable verdict.
_TEXT_KEYS = ("status", "verdict", "result", "message", "msg", "detail", "error")

_WORD = re.compile(r"[a-z]+")


def classify_text(text: str, flag: str | None = None) -> str:
    """Map a free-form jury reply to a verdict.

    The flag itself is cut out first: its random body may well contain
    letter runs like "ok" that would otherwise read as a verdict.
    """
    if flag:
        text = text.replace(flag, " ")
    low = text.lower()
    if any(phrase in low for phrase in _RETRY_PHRASES):
        return FlagVerdict.ERROR
    words = set(_WORD.findall(low))
    if words & _REJECT_WORDS:
        return FlagVerdict.REJECTED
    if words & _ACCEPT_WORDS:
        return FlagVerdict.ACCEPTED
    return FlagVerdict.ERROR


def classify(item: Any, flag: str | None = None) -> str:
    """Verdict for one decoded reply item: bool, str, or JSON object."""
    if isinstance(item, bool):
        return FlagVerdict.ACCEPTED if item else FlagVerdict.REJECTED
    if isinstance(item, dict):
        for key in _BOOL_KEYS:
            if isinstance(item.get(key), bool):
                return FlagVerdict.ACCEPTED if item[key] else FlagVerdict.REJECTED
        for key in _TEXT_KEYS:
            if isinstance(item.get(key), str) and item[key].strip():
                return classify_text(item[key], flag)
        return FlagVerdict.ERROR
    if isinstance(item, str):
        return classify_text(item, flag)
    return FlagVerdict.ERROR


def describe(item: Any) -> str:
    """Human-readable reply text stored with the flag."""
    if isinstance(item, str):
        return item
    return json.dumps(item, ensure_ascii=False)
