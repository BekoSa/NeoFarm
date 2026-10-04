"""Flag validator plugin system.

Mirrors ``farm.protocols``: drop a ``*.py`` file in this directory that
defines exactly one :class:`BaseValidator` subclass and the file's stem
becomes a usable validator id (set it as ``flag_validator:`` in
``config.yml``). Files whose names start with ``_`` and ``base`` are
skipped. The directory is scanned once at process start and cached.
"""

from __future__ import annotations

import importlib
import inspect
import logging
import pkgutil
import threading
from pathlib import Path

from .base import BaseValidator, ValidationResult

log = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: dict[str, type[BaseValidator]] | None = None


def _discover() -> dict[str, type[BaseValidator]]:
    here = Path(__file__).parent
    found: dict[str, type[BaseValidator]] = {}
    for info in pkgutil.iter_modules([str(here)]):
        if info.name.startswith("_") or info.name == "base":
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{info.name}")
        except Exception as exc:  # pragma: no cover - a bad plugin shouldn't kill us
            log.exception("failed to import validator %s: %s", info.name, exc)
            continue
        for _, cls in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(cls, BaseValidator)
                and cls is not BaseValidator
                and cls.__module__ == mod.__name__
            ):
                found[info.name] = cls
                break
    return found


def available_validators() -> dict[str, type[BaseValidator]]:
    global _cache
    if _cache is None:
        with _lock:
            if _cache is None:
                _cache = _discover()
                log.info("loaded validators: %s", sorted(_cache.keys()))
    return _cache


def build_validator(name: str, **kwargs) -> BaseValidator:
    validators = available_validators()
    if name not in validators:
        raise KeyError(
            f"unknown validator '{name}'; available: {sorted(validators.keys())}"
        )
    return validators[name](**kwargs)


__all__ = [
    "BaseValidator",
    "ValidationResult",
    "available_validators",
    "build_validator",
]
