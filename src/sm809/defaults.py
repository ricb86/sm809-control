"""Mapa de botoes reproduzido do Data.ini oficial do SM809.

Cada entrada sao os 4 bytes de `holtek8_button_data` (type, padding, code, padding).
O 5o campo do Data.ini (habilitado) e gerenciado pelo software Windows e nao
faz parte do pacote USB.
"""

from __future__ import annotations

from pathlib import Path

_base = Path(__file__).resolve()
_candidates = [
    _base.parents[2] / "docs" / "references" / "SM809-Data.ini",  # repositorio
    _base.parents[1] / "docs" / "references" / "SM809-Data.ini",  # .deb
]
INI = next((path for path in _candidates if path.exists()), _candidates[0])


def _parse() -> list[list[bytes]]:
    buttons: dict[int, bytes] = {}
    for line in INI.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        if not key.strip().isdigit():
            continue
        fields = value.strip().split(",")
        buttons[int(key)] = bytes(int(x, 16) for x in fields[:4])
    return [
        [buttons[i] for i in range(start, start + 16)]
        for start in range(1, 65, 16)
    ]


DEFAULT_BUTTONS: list[list[bytes]] = _parse()
