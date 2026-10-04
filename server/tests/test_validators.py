from __future__ import annotations

import pytest

from farm.validators import available_validators, build_validator
from farm.validators.base import BaseValidator, ValidationResult

SAMPLE = "alt_eDc3c5bdbdbb5dab6382a150b8"  # prefix + 26 alphanumerics


def test_plugins_discovered_but_base_is_not() -> None:
    names = available_validators()
    assert {"passthrough", "altayctf"} <= names.keys()
    assert "base" not in names and "_base" not in names
    assert all(issubclass(c, BaseValidator) for c in names.values())


def test_unknown_validator_raises() -> None:
    with pytest.raises(KeyError):
        build_validator("nope")


def test_passthrough_accepts_anything() -> None:
    v = build_validator("passthrough")
    for flag in [SAMPLE, "garbage", "", "alt_short"]:
        assert v.validate(flag).ok


def test_altayctf_accepts_the_real_shape() -> None:
    assert build_validator("altayctf").validate(SAMPLE).ok


@pytest.mark.parametrize(
    "flag",
    [
        "flag_eDc3c5bdbdbb5dab6382a150b8",  # wrong prefix
        "alt_short",                        # body too short
        "alt_" + "a" * 40,                  # body too long
        "alt_eDc3c5bdbdbb5dab6382a150b!",   # illegal char in body
        "alt_eDc3-c5bdbdbb5dab6382a150",    # dash not in alphabet
    ],
)
def test_altayctf_rejects_malformed(flag: str) -> None:
    res = build_validator("altayctf").validate(flag)
    assert not res.ok and res.reason


def test_altayctf_blacklist_and_length_range() -> None:
    v = build_validator("altayctf", body_len=[8, 64], blacklist=["DEADBEEF"])
    assert v.validate("alt_abc12345").ok              # within 8..64
    assert not v.validate("alt_abc").ok               # below range
    assert not v.validate("alt_xxDEADBEEFxx").ok      # blacklisted substring


def test_altayctf_length_check_can_be_disabled() -> None:
    v = build_validator("altayctf", body_len=None)
    assert v.validate("alt_a").ok and v.validate("alt_" + "z" * 200).ok


def test_result_helpers() -> None:
    assert ValidationResult.accept().ok
    r = ValidationResult.reject("nope")
    assert not r.ok and r.reason == "nope"
