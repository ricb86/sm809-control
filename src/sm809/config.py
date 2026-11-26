"""Operacoes de alto nivel: luz, botoes, macros e perfis."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from . import protocol as proto
from .device import Mouse
from .runtime import data_home

# --------------------------------------------------------------------------- luz


@dataclass(frozen=True)
class LedState:
    color: tuple[int, int, int]
    mode: int
    p1: int
    p2: int

    @property
    def mode_name(self) -> str:
        for name, code in proto.EFFECTS.items():
            if code == self.mode:
                return name
        return f"unknown-{self.mode:02x}"


class Lighting:
    def __init__(self, mouse: Mouse):
        self.mouse = mouse

    def get(self) -> LedState:
        color = self.mouse.read(proto.CMD_COLOR | proto.READ)[0][:3]
        mode, p1, p2 = self.mouse.read(proto.CMD_EFFECT | proto.READ)[0][:3]
        return LedState(tuple(color), mode, p1, p2)

    def set_color(self, red: int, green: int, blue: int) -> None:
        self.mouse.write(proto.CMD_COLOR, red, green, blue)

    def set_effect(self, effect: str | int, p1: int | None = None, p2: int | None = None) -> None:
        mode = effect if isinstance(effect, int) else proto.EFFECTS[effect]
        if p1 is None or p2 is None:
            d1, d2 = proto.DEFAULT_EFFECT_PARAMS.get(mode, (0x00, 0x00))
            p1 = d1 if p1 is None else p1
            p2 = d2 if p2 is None else p2
        self.mouse.write(proto.CMD_EFFECT, mode, p1, p2)

    def set(self, color: tuple[int, int, int] | None = None, effect: str | int | None = None,
            p1: int | None = None, p2: int | None = None) -> LedState:
        if color:
            self.set_color(*color)
        if effect is not None:
            self.set_effect(effect, p1, p2)
        return self.get()

    def get_palette(self, page: int = 0) -> list[tuple[int, int, int]]:
        if not hasattr(self.mouse, "read_block") or self.mouse.__class__.__name__ == "UsbMouse":
            raise NotImplementedError("paleta nao e legivel no firmware 3.x")
        raw = self.mouse.read_block(proto.CMD_CYCLE_PALETTE, page, 32)
        return [tuple(raw[i : i + 3]) for i in range(0, 24, 3)]

    def set_palette(self, colors: list[tuple[int, int, int]], page: int = 0) -> None:
        raw = b"".join(bytes(c)[:3].ljust(3, b"\x00") for c in colors[:8]).ljust(32, b"\x00")
        self.mouse.write_block(proto.CMD_CYCLE_PALETTE, page, 0x18, raw)


# --------------------------------------------------------------------------- botoes

BUTTON_CACHE = data_home() / "buttons"
MACRO_CACHE = data_home() / "macros"

_MOUSE_CODES = {"left": 0xF0, "right": 0xF1, "middle": 0xF2, "back": 0xF3, "forward": 0xF4}
_MOUSE_CODES_INV = {v: k for k, v in _MOUSE_CODES.items()}
_SCROLL_CODES = {"up": 0x01, "down": 0x02, "right": 0x03, "left": 0x04}
_DPI_CODES = {"up": 0x01, "down": 0x02, "cycle": 0x03}
_PROFILE_CODES = {"previous": 0x00, "down": 0x02, "up": 0x01, "cycle": 0x03}
_RATE_CODES = {"125": 0x00, "250": 0x01, "500": 0x02, "1000": 0x03}
_HID_KEYS_INV = {}  # preenchido abaixo
_HID_KEYS = {
    "a": 0x04, "b": 0x05, "c": 0x06, "d": 0x07, "e": 0x08, "f": 0x09,
    "g": 0x0A, "h": 0x0B, "i": 0x0C, "j": 0x0D, "k": 0x0E, "l": 0x0F,
    "m": 0x10, "n": 0x11, "o": 0x12, "p": 0x13, "q": 0x14, "r": 0x15,
    "s": 0x16, "t": 0x17, "u": 0x18, "v": 0x19, "w": 0x1A, "x": 0x1B,
    "y": 0x1C, "z": 0x1D, "enter": 0x28, "esc": 0x29, "space": 0x2C,
    "ctrl": 0xE0, "shift": 0xE1, "alt": 0xE2, "win": 0xE3,
}
_HID_KEYS_INV.update({v: k for k, v in _HID_KEYS.items()})

BUTTON_DATA_NAMES = {
    b"\x01\x00\xf0\x00": "left", b"\x01\x00\xf1\x00": "right",
    b"\x01\x00\xf2\x00": "middle", b"\x01\x00\xf3\x00": "back",
    b"\x01\x00\xf4\x00": "forward", b"\x00\x00\x00\x00": "disabled",
    b"\x03\x00\xcd\x00": "play-pause", b"\x03\x00\xb5\x00": "next-track",
    b"\x03\x00\xb6\x00": "prev-track", b"\x03\x00\xe2\x00": "mute",
    b"\x03\x00\xe9\x00": "volume-up", b"\x03\x00\xea\x00": "volume-down",
    b"\x07\x00\x01\x00": "dpi-up", b"\x07\x00\x02\x00": "dpi-down",
    b"\x07\x00\x03\x00": "dpi-cycle", b"\x04\x00\x01\x00": "scroll-up",
    b"\x04\x00\x02\x00": "scroll-down", b"\x0b\x00\x00\x00": "disabled",
}


def parse_button_action(action: str) -> bytes:
    """Converte uma acao legivel nos 4 bytes de `holtek8_button_data`."""
    a = action.strip().lower()
    if a in _MOUSE_CODES:
        return bytes((0x01, 0x00, _MOUSE_CODES[a], 0x00))
    if a.startswith("scroll-"):
        key = a[7:]
        if key not in _SCROLL_CODES:
            raise ValueError(f"scroll invalido: {key}")
        return bytes((0x04, 0x00, _SCROLL_CODES[key], 0x00))
    if a.startswith("dpi-"):
        key = a[4:]
        if key not in _DPI_CODES:
            raise ValueError(f"DPI invalido: {key}")
        return bytes((0x07, 0x00, _DPI_CODES[key], 0x00))
    if a in ("disabled", "none", "off"):
        return b"\x00\x00\x00\x00"
    if a.startswith("profile-"):
        key = a[8:]
        if key not in _PROFILE_CODES:
            raise ValueError(f"perfil invalido: {key}")
        return bytes((0x08, 0x00, _PROFILE_CODES[key], 0x00))
    if a.startswith("rate-"):
        key = a[5:]
        if key not in _RATE_CODES:
            raise ValueError("taxas validas: 125, 250, 500, 1000")
        return bytes((0x05, 0x00, _RATE_CODES[key], 0x00))
    if a.startswith("key-"):
        key = a[4:]
        code = _HID_KEYS.get(key)
        if code is None:
            try:
                code = int(key, 16)
            except ValueError as exc:
                raise ValueError(f"tecla desconhecida: {key}") from exc
        return bytes((0x00, 0x00, code, 0x00))
    if a.startswith("macro-"):
        parts = a.split("-")
        try:
            index = int(parts[1])
            mode = int(parts[2]) if len(parts) > 2 else 0
        except (IndexError, ValueError) as exc:
            raise ValueError("use macro-<1..9>[-<0..2>]") from exc
        if not 1 <= index <= 9 or not 0 <= mode <= 2:
            raise ValueError("macro: indice 1..9, modo 0..2")
        return bytes((0x09, mode, index, 0x00))
    if a.startswith("multiclick-"):
        parts = a.split("-")
        if len(parts) != 3 or parts[1] not in _MOUSE_CODES:
            raise ValueError("use multiclick-<left|right|...>-<vezes>")
        try:
            count = int(parts[2])
        except ValueError as exc:
            raise ValueError("contagem invalida") from exc
        return bytes((0x0A, _MOUSE_CODES[parts[1]], 50, count))
    raise ValueError(
        "acao desconhecida. Exemplos: left, right, dpi-up, scroll-down, "
        "macro-1, key-a, rate-1000, multiclick-left-3, disabled"
    )


@dataclass
class Button:
    slot: int
    data: tuple[int, int, int, int]

    @property
    def type(self) -> int:
        return self.data[0]

    @property
    def code(self) -> int:
        return self.data[2]

    @property
    def action(self) -> str:
        raw = bytes(self.data)
        if raw in BUTTON_DATA_NAMES:
            return BUTTON_DATA_NAMES[raw]
        if self.type == 0x00 and self.data[1] == 0x00:
            key = _HID_KEYS_INV.get(self.code)
            if key:
                return f"key-{key}"
        if self.type == 0x09:
            return f"macro-{self.code}-{self.data[1]}"
        if self.type == 0x0A:
            button = _MOUSE_CODES_INV.get(self.data[1], f"{self.data[1]:02x}")
            return f"multiclick-{button}-{self.data[3]}"
        return f"type-{self.type:02x}-data-{bytes(self.data[1:]).hex()}"

    @classmethod
    def from_bytes(cls, slot: int, raw: bytes) -> "Button":
        return cls(slot, tuple(raw[:4]))  # type: ignore[arg-type]

    @classmethod
    def from_action(cls, slot: int, action: str) -> "Button":
        return cls(slot, tuple(parse_button_action(action)))  # type: ignore[arg-type]

    def to_bytes(self) -> bytes:
        return bytes(self.data)


class Buttons:
    """Mapa de 16 botoes por perfil (4 perfis no SM809)."""

    def __init__(self, mouse: Mouse, page: int = 0):
        self.mouse = mouse
        self.page = page
        self.is_usb = mouse.__class__.__name__ == "UsbMouse"

    def _cache(self) -> Path:
        return BUTTON_CACHE / f"profile-{self.page + 1}.json"

    def read(self) -> list[Button]:
        if self.is_usb:
            # O firmware 3.x nao devolve tabelas: usamos o cache local ou o
            # mapa de fabrica extraido do Data.ini oficial.
            path = self._cache()
            if path.exists():
                data = json.loads(path.read_text())
                return [Button(item["slot"], tuple(item["data"])) for item in data]
            from .defaults import DEFAULT_BUTTONS
            idx = self.page if 0 <= self.page < len(DEFAULT_BUTTONS) else 0
            return [Button(i + 1, tuple(raw)) for i, raw in enumerate(DEFAULT_BUTTONS[idx])]
        raw = self.mouse.read_block(proto.CMD_BUTTON_MAP, self.page or 1, 64)
        return [Button.from_bytes(i + 1, raw[4 * i:4 * i + 4]) for i in range(16)]

    def write(self, buttons: list[Button]) -> None:
        if len(buttons) != 16:
            raise ValueError("mapa deve ter 16 botoes")
        raw = b"".join(b.to_bytes() for b in buttons)
        page = self.page if self.is_usb else (self.page or 1)
        self.mouse.write_block(proto.CMD_BUTTON_MAP, page, 0x40, raw)
        if self.is_usb:
            BUTTON_CACHE.mkdir(parents=True, exist_ok=True)
            self._cache().write_text(json.dumps(
                [{"slot": b.slot, "data": list(b.data)} for b in buttons], indent=2,
            ) + "\n")

    def set(self, slot: int, action: str) -> None:
        if not 1 <= slot <= 16:
            raise ValueError("botao deve estar entre 1 e 16")
        buttons = self.read()
        buttons[slot - 1] = Button.from_action(slot, action)
        self.write(buttons)


# --------------------------------------------------------------------------- macros

@dataclass(frozen=True)
class MacroEvent:
    key: int
    press: bool = True
    delay: int = 1
    command: int | None = None
    argument: int = 0
    wait: int = 0  # unidades de 2 ms, apenas para command=0x01 (WAIT)

    def to_bytes(self) -> bytes:
        if self.command is not None:
            return bytes((self.argument, self.command))
        return bytes(((self.delay & 0x7F) | (0x00 if self.press else 0x80), self.key))


class Macros:
    """Macros de 128 bytes por pagina (API A do Holtek 8-bit)."""

    def __init__(self, mouse: Mouse):
        self.mouse = mouse
        self.is_usb = mouse.__class__.__name__ == "UsbMouse"

    def _cache(self, page: int) -> Path:
        return MACRO_CACHE / f"page-{page}.json"

    def read(self, page: int) -> list[MacroEvent]:
        if self.is_usb:
            path = self._cache(page)
            if not path.exists():
                return []
            data = json.loads(path.read_text())
            return [MacroEvent(**e) for e in data.get("events", [])]
        raw = self.mouse.read_block(proto.CMD_MACRO_DATA, page, 128)
        return self._decode(raw)

    @staticmethod
    def _decode(raw: bytes) -> list[MacroEvent]:
        events: list[MacroEvent] = []
        i = 2
        while i + 1 < len(raw):
            a, b = raw[i], raw[i + 1]
            if a == 0 and b == 0:
                break
            if b == 0x01:  # WAIT: proximos 2 bytes big-endian, 2 ms por unidade
                if i + 4 > len(raw):
                    break
                events.append(MacroEvent(0, command=b, wait=int.from_bytes(raw[i + 2:i + 4], "big")))
                i += 4
                continue
            if b in (0xFA, 0xFE):
                events.append(MacroEvent(0, command=b, argument=a))
                i += 2
                continue
            events.append(MacroEvent(b, press=not bool(a & 0x80), delay=a & 0x7F))
            i += 2
        return events

    def encode(self, events: list[MacroEvent], repeat: int = 1) -> bytes:
        raw = bytearray(repeat.to_bytes(2, "big"))
        for ev in events:
            raw += ev.to_bytes()
            if ev.command == 0x01:
                raw += ev.wait.to_bytes(2, "big")
        if len(raw) > 128:
            raise ValueError("macro excede 128 bytes; use outra pagina")
        return bytes(raw.ljust(128, b"\x00")[:128])

    def write(self, page: int, events: list[MacroEvent], repeat: int = 1) -> None:
        if not 1 <= page <= 9:
            raise ValueError("pagina de macro deve estar entre 1 e 9 (API A)")
        raw = self.encode(events, repeat)
        self.mouse.write_block(proto.CMD_MACRO_DATA, page, 0x80, raw)
        if self.is_usb:
            MACRO_CACHE.mkdir(parents=True, exist_ok=True)
            self._cache(page).write_text(json.dumps({
                "repeat": repeat,
                "events": [asdict(e) for e in events],
            }, indent=2, ensure_ascii=False) + "\n")


# --------------------------------------------------------------------------- perfil

@dataclass
class Profile:
    name: str
    led: LedState | None = None
    buttons: list[Button] | None = None
    macros: dict[int, list[MacroEvent]] | None = None

    def to_json(self) -> dict:
        d = {"name": self.name}
        if self.led:
            d["led"] = {"color": list(self.led.color), "mode": self.led.mode,
                        "p1": self.led.p1, "p2": self.led.p2}
        if self.buttons:
            d["buttons"] = [{"slot": b.slot, "data": list(b.data)} for b in self.buttons]
        if self.macros:
            d["macros"] = {str(k): [asdict(e) for e in v] for k, v in self.macros.items()}
        return d


class Profiles:
    """Perfis salvos localmente em JSON, aplicados ao mouse sob demanda."""

    def __init__(self, mouse: Mouse, directory: str | Path, button_page: int = 0):
        self.mouse = mouse
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lighting = Lighting(mouse)
        self.buttons = Buttons(mouse, button_page)
        self.macros = Macros(mouse)

    def path(self, name: str) -> Path:
        safe = "".join(c for c in name if c.isalnum() or c in "-_") or "profile"
        return self.directory / f"{safe}.json"

    def save(self, name: str) -> Path:
        saved_macros = {}
        for page in range(1, 10):
            events = self.macros.read(page)
            if events:
                saved_macros[page] = events
        profile = Profile(
            name=name,
            led=self.lighting.get(),
            buttons=self.buttons.read(),
            macros=saved_macros or None,
        )
        path = self.path(name)
        path.write_text(json.dumps(profile.to_json(), indent=2, ensure_ascii=False) + "\n")
        return path

    def apply(self, name: str) -> None:
        data = json.loads(self.path(name).read_text())
        led = data.get("led")
        if led:
            self.lighting.set_color(*led["color"])
            self.lighting.set_effect(led["mode"], led["p1"], led["p2"])
        buttons = data.get("buttons")
        if buttons:
            self.buttons.write([
                Button(b["slot"], tuple(b["data"])) for b in buttons  # type: ignore[arg-type]
            ])
        for page, events in data.get("macros", {}).items():
            self.macros.write(int(page), [MacroEvent(**e) for e in events])

    def list(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json"))
