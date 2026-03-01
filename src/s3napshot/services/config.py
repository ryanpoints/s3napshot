from __future__ import annotations

import base64
import json
import os
import stat
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet

from s3napshot.models.profile import Profile

CONFIG_DIR = Path.home() / ".config" / "s3napshot"
KEY_FILE = CONFIG_DIR / ".key"
PROFILES_FILE = CONFIG_DIR / "profiles.enc"
KEYRING_SERVICE = "s3napshot"
KEYRING_USERNAME = "fernet_key"


def _load_or_create_key() -> bytes:
    # Try keyring first
    try:
        import keyring

        stored = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if stored:
            return base64.urlsafe_b64decode(stored.encode())
        key = Fernet.generate_key()
        keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, base64.urlsafe_b64encode(key).decode())
        return key
    except Exception:
        pass

    # File fallback
    if KEY_FILE.exists():
        return KEY_FILE.read_bytes().strip()

    key = Fernet.generate_key()
    CONFIG_DIR.mkdir(parents=True, mode=0o700, exist_ok=True)
    KEY_FILE.write_bytes(key)
    KEY_FILE.chmod(0o600)
    return key


def get_fernet(key: bytes | None = None) -> Fernet:
    if key is None:
        key = _load_or_create_key()
    return Fernet(key)


def load_profiles(path: Path, fernet: Fernet) -> dict[str, Profile]:
    if not path.exists():
        return {}
    try:
        encrypted = path.read_bytes()
        plaintext = fernet.decrypt(encrypted)
        data: dict[str, Any] = json.loads(plaintext)
    except Exception as exc:
        raise ValueError(f"Failed to decrypt profiles file: {exc}") from exc
    return {name: Profile.from_dict(name, fields) for name, fields in data.items()}


def save_profiles(profiles: dict[str, Profile], path: Path, fernet: Fernet) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    data = {name: p.to_dict() for name, p in profiles.items()}
    plaintext = json.dumps(data).encode()
    encrypted = fernet.encrypt(plaintext)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(encrypted)
    tmp.replace(path)


def add_profile(
    profiles: dict[str, Profile],
    profile: Profile,
    *,
    overwrite: bool = False,
) -> dict[str, Profile]:
    if profile.name in profiles and not overwrite:
        raise ValueError(f"Profile '{profile.name}' already exists. Use --overwrite to replace it.")
    return {**profiles, profile.name: profile}


def remove_profile(profiles: dict[str, Profile], name: str) -> dict[str, Profile]:
    if name not in profiles:
        raise KeyError(f"Profile '{name}' not found.")
    return {k: v for k, v in profiles.items() if k != name}
