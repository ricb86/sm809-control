"""Camada de acesso ao mouse SM809 via hidraw (sem dependencias externas)."""

from __future__ import annotations

import fcntl
import glob
import os
import time
from pathlib import Path

from . import protocol as proto

VID = 0x04D9
PID = 0xA09F
KEY_CACHE = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "sm809" / "key"
KEY_CHARS = b"0123456789ABCDEF"
DATA_LEN = {0x90: 32, 0x91: 32, 0x92: 64, 0x93: 128, 0x13: 128}


def _hidioc(nr: int, size: int) -> int:
    """Constante de ioctl HID do Linux (_IOC(read|write, 'H', nr, size))."""
    return (3 << 30) | (size << 16) | (ord("H") << 8) | nr


HIDIOCSFEATURE9 = _hidioc(0x06, proto.FEATURE_SIZE)
HIDIOCGFEATURE9 = _hidioc(0x07, proto.FEATURE_SIZE)


class MouseNotFound(Exception):
    pass


class KeyNotFound(Exception):
    pass


class DeviceError(Exception):
    pass


def find_config_hidraw() -> str | None:
    """Encontra o hidraw da interface de configuracao (usage page FF00)."""
    for sysfs in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            uevent = Path(sysfs, "device", "uevent").read_text()
            descriptor = Path(sysfs, "device", "report_descriptor").read_bytes()
        except OSError:
            continue
        if f"HID_ID=0003:{VID:08X}:{PID:08X}" in uevent and descriptor[:3] == b"\x06\x00\xff":
            return "/dev/" + Path(sysfs).name
    return None


def _descramble_q(wire: bytes) -> bytes:
    """Remove offsets e rotacao, devolvendo os bytes ja permutados/XORados."""
    q = bytes((wire[i] - proto.ADD[i]) & 0xFF for i in range(8))
    v = int.from_bytes(q, "big")
    v = ((v >> 3) | (v << 61)) & ((1 << 64) - 1)
    return v.to_bytes(8, "big")


def key_from_idle(wire: bytes) -> bytes | None:
    """Logo apos plugar, o buffer contem scramble(00*8, key)."""
    q = _descramble_q(wire)
    key = q[1:7]
    if q[0] == 0 and q[7] == 0 and all(c in KEY_CHARS for c in key):
        return key
    return None


def key_candidates(wire: bytes) -> list[bytes]:
    """Depois do primeiro uso so 2 caracteres da chave ficam desconhecidos."""
    q = _descramble_q(wire)
    if q[0] != 0 or not all(c in KEY_CHARS for c in (q[1], q[2], q[3], q[5])):
        return []
    return [bytes((q[1], q[2], q[3], c3, q[5], c5)) for c3 in KEY_CHARS for c5 in KEY_CHARS]


class Mouse:
    """Conexao com a interface de configuracao do mouse."""

    def __init__(self, key: bytes | str | None = None, path: str | None = None):
        self.path = path or find_config_hidraw()
        if not self.path:
            raise MouseNotFound("mouse SM809 nao encontrado (mouse conectado?)")
        self.fd = os.open(self.path, os.O_RDWR | os.O_NONBLOCK)
        try:
            self.key = self._resolve_key(key)
        except Exception:
            os.close(self.fd)
            raise
        self.verbose = False

    def __enter__(self) -> "Mouse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "fd", None) is not None:
            os.close(self.fd)
            self.fd = None

    # ------------------------------- chave -------------------------------
    def _get_feature(self) -> bytes:
        buf = bytearray(proto.FEATURE_SIZE)
        fcntl.ioctl(self.fd, HIDIOCGFEATURE9, buf)
        return bytes(buf[1:])

    def _set_feature(self, packet: bytes) -> None:
        if self.verbose:
            print(f"  TX {packet.hex(' ')}  ->  {proto.scramble(packet, self.key).hex(' ')}")
        buf = bytearray(proto.as_feature(packet, self.key))
        fcntl.ioctl(self.fd, HIDIOCSFEATURE9, buf)

    def _probe(self, key: bytes) -> bool:
        """0x83 e o comando usado pela referencia: o mouse so responde com a chave certa."""
        cmd = 0x83
        self._set_feature(proto.build(cmd))
        time.sleep(0.01)
        reply = proto.unscramble(self._get_feature(), key)
        return reply[0] == cmd

    def _resolve_key(self, key: bytes | str | None) -> bytes:
        if key is not None:
            key = key.encode("ascii") if isinstance(key, str) else bytes(key)
            if len(key) != proto.KEY_LEN:
                raise ValueError("chave deve ter 6 caracteres ASCII")
            if not self._probe(key):
                raise KeyNotFound(f"chave {key.decode(errors='replace')!r} nao aceita pelo mouse")
            return key

        cached = None
        try:
            cached = KEY_CACHE.read_bytes().strip()
        except OSError:
            pass
        idle = self._get_feature()
        candidates = []
        for k in (cached, key_from_idle(idle)):
            if k and k not in candidates:
                candidates.append(k)
        candidates.extend(k for k in key_candidates(idle) if k not in candidates)

        for k in candidates:
            if not self._probe(k):
                continue
            try:
                KEY_CACHE.parent.mkdir(parents=True, exist_ok=True)
                KEY_CACHE.write_bytes(k)
            except OSError:
                pass
            return k
        raise KeyNotFound("nao foi possivel descobrir a chave; reconecte o mouse e tente de novo")

    # --------------------------- operacoes basicas ------------------------
    def _drain_input(self, max_packets: int = 64) -> None:
        for _ in range(max_packets):
            try:
                if not os.read(self.fd, 64):
                    return
            except BlockingIOError:
                return

    def read_input(self, want: int, timeout: float = 0.5) -> bytes:
        data = b""
        deadline = time.time() + timeout
        while len(data) < want and time.time() < deadline:
            try:
                chunk = os.read(self.fd, 64)
                if chunk:
                    data += chunk
                    continue
            except BlockingIOError:
                pass
            time.sleep(0.005)
        return data[:want]

    def read(self, cmd: int, arg: int = 0) -> tuple[bytes, bytes]:
        """Le um grupo. cmd deve ter o bit 0x80 (ex.: 0x8C para ler 0x0C)."""
        if cmd == 0x89:
            raise DeviceError("ler grupo 0x09 trava a interface do mouse; operacao recusada")
        self._drain_input()
        self._set_feature(proto.build(cmd, bytes((arg,))))
        time.sleep(0.03)
        reply = proto.unscramble(self._get_feature(), self.key)
        if reply[0] != cmd:
            raise DeviceError(f"resposta inesperada para {cmd:02x}: {reply.hex(' ')}")
        want = DATA_LEN.get(cmd & 0x7F, 0)
        data = self.read_input(want) if want else b""
        return reply[1:7], data

    def write(self, cmd: int, *args: int) -> bytes:
        """Escreve um valor simples e espera o ACK."""
        self._set_feature(proto.build(cmd, bytes(args)))
        time.sleep(0.03)
        reply = proto.unscramble(self._get_feature(), self.key)
        if reply[0] != cmd:
            raise DeviceError(f"ACK inesperado para {cmd:02x}: {reply.hex(' ')}")
        return reply[1:7]

    def write_block(self, cmd: int, page: int, length: int, data: bytes) -> bytes:
        """Escreve um bloco de dados (feature report + output reports de 32 bytes)."""
        self._set_feature(proto.build(cmd, bytes((page, length))))
        for i in range(0, len(data), 32):
            os.write(self.fd, b"\x00" + data[i : i + 32].ljust(32, b"\x00"))
            time.sleep(0.02)
        time.sleep(0.1)
        return self.read(cmd | proto.READ, page)[1][:length]

    def read_block(self, cmd: int, page: int, length: int) -> bytes:
        return self.read(cmd | proto.READ, page)[1][:length]
