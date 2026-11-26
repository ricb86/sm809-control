#!/usr/bin/env python3
"""Gera o ícone do SM809 em PNG (sem dependências) e mantém a fonte SVG."""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent / "icons"
SS = 3  # supersampling


def _chunk(tag: bytes, data: bytes) -> bytes:
    return (struct.pack(">I", len(data)) + tag + data +
            struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))


def _png(size: int, rows: list[list[tuple[int, int, int, int]]]) -> bytes:
    raw = b"".join(b"\x00" + bytes(v for px in row for v in px) for row in rows)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) +
            _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b""))


def _inside(x: float, y: float, cx: float, cy: float, rx: float, ry: float) -> float:
    d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
    return max(0.0, min(1.0, (1.0 - d) * 40))  # borda suave


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _sample(x: float, y: float) -> tuple[int, int, int, int]:
    # Cabo
    if 4 <= y <= 24 and abs(x - 64) <= 2.2:
        return (36, 58, 104, 255)

    body = _inside(x, y, 64, 70, 34, 46)
    if body <= 0:
        return (0, 0, 0, 0)

    t = max(0.0, min(1.0, (y - 24) / 92))
    color = _lerp((82, 142, 255), (24, 74, 188), t)

    # Contorno e divisão central
    if body < 0.35:
        color = (13, 39, 104)
    elif 30 <= y <= 108 and abs(x - 64) < 1.1:
        color = (18, 52, 135)

    # Botão lateral esquerdo
    if 40 <= y <= 68 and 35 <= x <= 44:
        color = (21, 62, 158)

    # Roda
    if 25 <= y <= 45 and 59 <= x <= 69:
        if 59.8 <= x <= 68.2 and 26 <= y <= 44:
            return (238, 243, 255, 255)
        return (14, 40, 100, 255)

    alpha = round(body * 255)
    return (*color, alpha)


def make_png(size: int) -> bytes:
    rows = []
    scale = 128 / size
    for py in range(size):
        row = []
        for px in range(size):
            total = [0, 0, 0, 0]
            for sy in range(SS):
                for sx in range(SS):
                    x = (px + (sx + 0.5) / SS) * scale
                    y = (py + (sy + 0.5) / SS) * scale
                    r, g, b, a = _sample(x, y)
                    total[0] += r * a
                    total[1] += g * a
                    total[2] += b * a
                    total[3] += a
            n = SS * SS
            alpha = total[3] / n
            if alpha < 1:
                row.append((0, 0, 0, 0))
            else:
                row.append((
                    round(total[0] / total[3]),
                    round(total[1] / total[3]),
                    round(total[2] / total[3]),
                    round(alpha),
                ))
        rows.append(row)
    return _png(size, rows)


SVG = """<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" width="128" height="128">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#528eff"/>
      <stop offset="1" stop-color="#184abe"/>
    </linearGradient>
  </defs>
  <path d="M64 5 L64 21" stroke="#243a68" stroke-width="4" stroke-linecap="round"/>
  <ellipse cx="64" cy="70" rx="34" ry="46" fill="url(#g)" stroke="#0d2768" stroke-width="3"/>
  <path d="M64 34 L64 108" stroke="#12347f" stroke-width="2"/>
  <rect x="59" y="26" width="10" height="19" rx="5" fill="#eef3ff" stroke="#0d2768" stroke-width="2"/>
  <path d="M44 42 Q38 54 42 68" fill="none" stroke="#153e9e" stroke-width="3" stroke-linecap="round"/>
</svg>
"""


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for size in (64, 128):
        path = OUT / f"sm809-{size}.png"
        path.write_bytes(make_png(size))
        print(path)
    svg = OUT / "sm809.svg"
    svg.write_text(SVG)
    print(svg)


if __name__ == "__main__":
    main()
