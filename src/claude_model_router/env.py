"""
Environment variable management for Windows.
"""
import ctypes
import os
import sys
from typing import Optional

import winreg

SYSTEM_ENV_SUBKEY = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
USER_ENV_SUBKEY = r"Environment"


def broadcast_env_change() -> None:
    """Broadcast environment variable change to all Windows processes."""
    HWND_BROADCAST = 0xFFFF
    WM_SETTINGCHANGE = 0x001A
    SMTO_ABORTIFHUNG = 0x0002
    ctypes.windll.user32.SendMessageTimeoutW(
        HWND_BROADCAST,
        WM_SETTINGCHANGE,
        0,
        "Environment",
        SMTO_ABORTIFHUNG,
        5000,
        None,
    )


def set_env_in_registry(root: int, subkey: str, name: str, value: str) -> None:
    """Set an environment variable in the Windows registry."""
    with winreg.OpenKey(root, subkey, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def set_env_system(name: str, value: str) -> bool:
    """Set a system-wide environment variable (requires admin)."""
    try:
        set_env_in_registry(winreg.HKEY_LOCAL_MACHINE, SYSTEM_ENV_SUBKEY, name, value)
        return True
    except PermissionError:
        return False


def set_env_user(name: str, value: str) -> None:
    """Set a user environment variable."""
    set_env_in_registry(winreg.HKEY_CURRENT_USER, USER_ENV_SUBKEY, name, value)


def delete_env_user(name: str) -> bool:
    """Delete a user environment variable."""
    try:
        access = winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_ENV_SUBKEY, 0, access) as key:
            try:
                winreg.QueryValueEx(key, name)
            except FileNotFoundError:
                return False
            winreg.DeleteValue(key, name)
            return True
    except (FileNotFoundError, PermissionError):
        return False


def read_env_value(root: int, subkey: str, name: str) -> Optional[str]:
    """Read an environment variable from the registry."""
    try:
        with winreg.OpenKey(root, subkey, 0, winreg.KEY_QUERY_VALUE) as key:
            value, _ = winreg.QueryValueEx(key, name)
        if value is None:
            return None
        return str(value)
    except (FileNotFoundError, PermissionError, OSError):
        return None


def refresh_env_from_registry(config_keys: list) -> None:
    """Refresh environment variables from registry."""
    for key in config_keys:
        value = read_env_value(winreg.HKEY_LOCAL_MACHINE, SYSTEM_ENV_SUBKEY, key)
        if value is None:
            value = read_env_value(winreg.HKEY_CURRENT_USER, USER_ENV_SUBKEY, key)
        if value is not None:
            os.environ[key] = value


def mask_secret(value: str) -> str:
    """Mask a secret value for display."""
    if not value:
        return "(not set)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def format_config_value(name: str, value: Optional[str]) -> str:
    """Format a configuration value for display."""
    if not value:
        return "(not set)"
    if name in {"ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"}:
        return mask_secret(value)
    return value


def print_config_details(config_keys: list, title: str) -> None:
    """Print configuration details with masked secrets."""
    print(title)
    for key in config_keys:
        value = os.environ.get(key)
        formatted = format_config_value(key, value)
        print(f"  {key}={formatted}")
