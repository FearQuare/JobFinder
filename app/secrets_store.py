"""Credentials storage.

API keys go to the operating system keychain (macOS Keychain) through `keyring`.
If no keychain backend is available, they fall back to a file in the data folder
readable only by the current user. Nothing here is ever sent anywhere except the
service the key belongs to.
"""
from __future__ import annotations

import json
import os
from typing import Optional

from . import config

SERVICE = "JobFinder"
KNOWN_KEYS = ("anthropic_api_key", "openai_api_key", "adzuna_app_id", "adzuna_app_key")


def _keyring():
    if os.environ.get("JOBFINDER_NO_KEYRING"):
        return None
    try:
        import keyring
        from keyring.backends import fail

        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def _read_file() -> dict:
    try:
        return json.loads(config.SECRETS_FALLBACK_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return {}


def _write_file(data: dict) -> None:
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = config.SECRETS_FALLBACK_PATH
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh)


def get_secret(name: str) -> Optional[str]:
    kr = _keyring()
    if kr is not None:
        try:
            value = kr.get_password(SERVICE, name)
            if value:
                return value
        except Exception:
            pass
    return _read_file().get(name) or None


def set_secret(name: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        delete_secret(name)
        return
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, name, value)
            return
        except Exception:
            pass
    data = _read_file()
    data[name] = value
    _write_file(data)


def delete_secret(name: str) -> None:
    kr = _keyring()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, name)
        except Exception:
            pass
    data = _read_file()
    if name in data:
        data.pop(name)
        _write_file(data)


def storage_backend() -> str:
    return "macOS Keychain / system keyring" if _keyring() is not None else f"file ({config.SECRETS_FALLBACK_PATH})"


def mask(value: Optional[str]) -> str:
    if not value:
        return ""
    return value[:4] + "…" + value[-4:] if len(value) > 10 else "••••"
