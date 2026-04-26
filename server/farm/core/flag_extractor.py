"""Extract flags from arbitrary exploit stdout."""

from __future__ import annotations

import re
from functools import lru_cache


@lru_cache(maxsize=8)
def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


def extract_flags(text: str, pattern: str) -> list[str]:
    """Return a deduplicated list of flags found in `text`.

    Order is preserved so that `seen first` wins over later occurrences,
    which keeps logs readable.
    """
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for match in _compile(pattern).finditer(text):
        flag = match.group(0)
        if flag not in seen:
            seen.add(flag)
            found.append(flag)
    return found


def is_well_formed(flag: str, pattern: str) -> bool:
    return bool(_compile(pattern).fullmatch(flag))
