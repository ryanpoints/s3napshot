from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from s3napshot.models.profile import Profile
from s3napshot.services.config import (
    add_profile,
    get_fernet,
    load_profiles,
    remove_profile,
    save_profiles,
)


def _make_profile(name: str = "default") -> Profile:
    return Profile(
        name=name,
        endpoint_url="https://s3.amazonaws.com",
        bucket_name="my-bucket",
        access_key_id="AKIAIOSFODNN7EXAMPLE",
        secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
    )


@pytest.fixture()
def key() -> bytes:
    return Fernet.generate_key()


@pytest.fixture()
def fernet(key: bytes) -> Fernet:
    return get_fernet(key)


def test_get_fernet_with_explicit_key(key: bytes):
    f = get_fernet(key)
    assert f is not None
    # Verify it can encrypt/decrypt
    ct = f.encrypt(b"hello")
    assert f.decrypt(ct) == b"hello"


def test_save_and_load_round_trip(tmp_path: Path, fernet: Fernet):
    profiles_file = tmp_path / "profiles.enc"
    profile = _make_profile()
    profiles = {profile.name: profile}

    save_profiles(profiles, profiles_file, fernet)
    loaded = load_profiles(profiles_file, fernet)

    assert "default" in loaded
    p = loaded["default"]
    assert p.name == "default"
    assert p.endpoint_url == "https://s3.amazonaws.com"
    assert p.bucket_name == "my-bucket"
    assert p.access_key_id == "AKIAIOSFODNN7EXAMPLE"
    assert p.secret_access_key == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    assert p.region == "us-east-1"


def test_encrypted_file_does_not_contain_plaintext_secrets(tmp_path: Path, fernet: Fernet):
    profiles_file = tmp_path / "profiles.enc"
    profile = _make_profile()
    save_profiles({"default": profile}, profiles_file, fernet)

    raw = profiles_file.read_bytes()
    assert b"wJalrXUtnFEMI" not in raw
    assert b"AKIAIOSFODNN7EXAMPLE" not in raw


def test_load_profiles_missing_file(tmp_path: Path, fernet: Fernet):
    result = load_profiles(tmp_path / "nonexistent.enc", fernet)
    assert result == {}


def test_load_profiles_wrong_key(tmp_path: Path):
    key1 = Fernet.generate_key()
    key2 = Fernet.generate_key()
    f1 = get_fernet(key1)
    f2 = get_fernet(key2)

    profiles_file = tmp_path / "profiles.enc"
    save_profiles({"default": _make_profile()}, profiles_file, f1)

    with pytest.raises(ValueError, match="Failed to decrypt"):
        load_profiles(profiles_file, f2)


def test_add_profile_success():
    profile = _make_profile()
    result = add_profile({}, profile)
    assert "default" in result


def test_add_profile_duplicate_raises():
    profile = _make_profile()
    profiles = add_profile({}, profile)
    with pytest.raises(ValueError, match="already exists"):
        add_profile(profiles, _make_profile())


def test_add_profile_overwrite_succeeds():
    profile = _make_profile()
    profiles = add_profile({}, profile)
    updated = Profile(
        name="default",
        endpoint_url="https://new.endpoint.com",
        bucket_name="new-bucket",
        access_key_id="NEW_KEY",
        secret_access_key="NEW_SECRET",
    )
    result = add_profile(profiles, updated, overwrite=True)
    assert result["default"].endpoint_url == "https://new.endpoint.com"


def test_remove_profile_success():
    profile = _make_profile()
    profiles = {"default": profile}
    result = remove_profile(profiles, "default")
    assert "default" not in result


def test_remove_profile_unknown_raises():
    with pytest.raises(KeyError, match="not found"):
        remove_profile({}, "nonexistent")


def test_save_profiles_creates_parent_dirs(tmp_path: Path, fernet: Fernet):
    nested = tmp_path / "a" / "b" / "profiles.enc"
    save_profiles({"default": _make_profile()}, nested, fernet)
    assert nested.exists()


def test_profile_safe_display_masks_secrets():
    p = _make_profile()
    d = p.safe_display()
    assert d["secret_access_key"] == "********"
    assert "****" in d["access_key_id"]
    assert "wJalrXUtnFEMI" not in str(d)
