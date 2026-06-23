"""Secrets live in the OS keychain (Windows Credential Manager / macOS Keychain /
Linux Secret Service) via `keyring`, not in app.db. The DB only records whether a
secret is set, never its value.
"""

from __future__ import annotations

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "savepoint-ai"
TAVILY = "tavily_api_key"


def get_tavily_key() -> str:
    try:
        return keyring.get_password(SERVICE, TAVILY) or ""
    except KeyringError:
        return ""


def set_tavily_key(value: str) -> None:
    value = (value or "").strip()
    if value:
        keyring.set_password(SERVICE, TAVILY, value)
    else:
        try:
            keyring.delete_password(SERVICE, TAVILY)
        except PasswordDeleteError:
            pass  # nothing stored — fine
