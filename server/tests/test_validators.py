from __future__ import annotations

import pytest

from farm.validators import available_validators, build_validator
from farm.validators.base import BaseValidator, ValidationResult

SAMPLE = "ALT_69cdd49a050c053c703d55b19a"  # real shape: ALT_ + 26 lowercase hex


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
        "flag_69cdd49a050c053c703d55b19a",  # wrong prefix
        "ALT_69cdd49a",                     # body too short
        "ALT_" + "a" * 40,                  # body too long
        "ALT_eDc3c5bdbdbb5dab6382a150b8",   # uppercase hex not in 0-9a-f
        "ALT_69cdd49a050c053c703d55b1z!",   # illegal chars in body
    ],
)
def test_altayctf_rejects_malformed(flag: str) -> None:
    res = build_validator("altayctf").validate(flag)
    assert not res.ok and res.reason


def test_altayctf_rejects_degenerate_body_by_entropy() -> None:
    # The real forgery "ALT_0000...0" is perfect hex of the right length,
    # caught only by the distinct-chars floor.
    v = build_validator("altayctf", min_distinct=6)
    assert not v.validate("ALT_" + "0" * 26).ok
    assert v.validate(SAMPLE).ok  # real flag has plenty of distinct chars


def test_altayctf_blacklist_and_length_range() -> None:
    v = build_validator("altayctf", body_len=[8, 64], blacklist=["deadbeef"])
    assert v.validate("ALT_abc12345").ok              # within 8..64
    assert not v.validate("ALT_abc").ok               # below range
    assert not v.validate("ALT_xxdeadbeefxx").ok      # blacklisted substring


def test_altayctf_length_check_can_be_disabled() -> None:
    v = build_validator("altayctf", body_len=None)
    assert v.validate("ALT_a").ok and v.validate("ALT_" + "abcdef0123" * 20).ok


def test_result_helpers() -> None:
    assert ValidationResult.accept().ok
    r = ValidationResult.reject("nope")
    assert not r.ok and r.reason == "nope"
