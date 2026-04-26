"""Protocol plugin system.

Drop a `*.py` file into this directory that defines exactly one subclass
of :class:`BaseProtocol` and the file's stem becomes a usable protocol id
(set it as `protocol:` in `config.yml`). No registry edits, no imports.

The loader scans this package's directory once at process start and caches
the result.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import logging
import pkgutil
import threading
from pathlib import Path

from .base import BaseProtocol, SubmissionResult

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, type[BaseProtocol]] | None = None


def _discover() -> dict[str, type[BaseProtocol]]:
    here = Path(__file__).parent
    found: dict[str, type[BaseProtocol]] = {}
    for info in pkgutil.iter_modules([str(here)]):
        if info.name.startswith("_") or info.name == "base":
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as exc:  # pragma: no cover - bad plugin shouldn't kill us
            log.exception("failed to import protocol %s: %s", info.name, exc)
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(cls, BaseProtocol)
                and cls is not BaseProtocol
                and cls.__module__ == mod.__name__
            ):
                found[info.name] = cls
                break
    return found


def available_protocols() -> dict[str, type[BaseProtocol]]:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = _discover()
                log.info(
                    "loaded protocols: %s", sorted(_cache.keys())
                )
    return _cache


def build_protocol(name: str, **kwargs) -> BaseProtocol:
    protocols = available_protocols()
    if name not in protocols:
        raise KeyError(
            f"unknown protocol '{name}'; available: {sorted(protocols.keys())}"
        )
    return protocols[name](**kwargs)


__all__ = [
    "BaseProtocol",
    "SubmissionResult",
    "available_protocols",
    "build_protocol",
]
