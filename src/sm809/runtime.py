"""Pontos comuns de execução: descoberta do mouse e diretório de dados do usuário."""

from __future__ import annotations

import os
from pathlib import Path

from .device import Mouse
from .usbfs import UsbMouse, find_usbfs_device

APP_NAME = "sm809-control"


def data_home() -> Path:
    """Diretório gravável para perfis, backups e caches.

    Pode ser sobrescrito com SM809_HOME (útil para desenvolvimento).
    """
    raw = os.environ.get("SM809_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".local/share/sm809"


def open_mouse(key: str | None = None, verbose: bool = False) -> Mouse | UsbMouse:
    """Escolhe usbfs (3.x) ou hidraw (2.x) automaticamente."""
    usb = find_usbfs_device()
    dev = UsbMouse(key=key, path=usb) if usb else Mouse(key=key)
    dev.verbose = verbose
    return dev
