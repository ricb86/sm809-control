"""Back-end usbfs para firmwares 3.x (a interface 2 nao tem endpoint IN).

Baseado em `docs/references/driver-holtek-a09f-pr1915.c`.
"""

from __future__ import annotations

import ctypes
import fcntl
import glob
import os
import time
from pathlib import Path

from . import protocol as proto

USB_CLASS_HID = 0x21
REQ_SET_REPORT = 0x09
REQ_GET_REPORT = 0x01
FEATURE_REPORT_0 = 0x0300
INTERFACE = 2
ENDPOINT_OUT = 0x03
BLOCK_SIZE = 32
TIMEOUT_MS = 1000
REPLY_RETRIES = 10
COMMAND_DELAY = 0.03


class _CtrlTransfer(ctypes.Structure):
    _fields_ = [
        ("bRequestType", ctypes.c_uint8),
        ("bRequest", ctypes.c_uint8),
        ("wValue", ctypes.c_uint16),
        ("wIndex", ctypes.c_uint16),
        ("wLength", ctypes.c_uint16),
        ("timeout", ctypes.c_uint32),
        ("data", ctypes.c_void_p),
    ]


class _BulkTransfer(ctypes.Structure):
    _fields_ = [
        ("ep", ctypes.c_uint),
        ("len", ctypes.c_uint),
        ("timeout", ctypes.c_uint),
        ("data", ctypes.c_void_p),
    ]


def _ioc(direction: int, typ: int, nr: int, size: int) -> int:
    return (direction << 30) | (typ << 8) | nr | (size << 16)


USBDEVFS_CONTROL = _ioc(3, ord("U"), 0, ctypes.sizeof(_CtrlTransfer))
USBDEVFS_BULK = _ioc(3, ord("U"), 2, ctypes.sizeof(_BulkTransfer))
USBDEVFS_CLAIMINTERFACE = _ioc(2, ord("U"), 15, ctypes.sizeof(ctypes.c_uint))
USBDEVFS_RELEASEINTERFACE = _ioc(2, ord("U"), 16, ctypes.sizeof(ctypes.c_uint))

# Em 3.x, ler estas tabelas faz o mouse ignorar comandos ate reset USB
# (0x09 trava a interface ate reconectar).
FORBIDDEN_READS = {0x09, 0x10, 0x11, 0x12}
SAFE_READS = {0x00, 0x01, 0x0B, 0x0C, 0x0D}


def find_usbfs_device(vid: int = 0x04D9, pid: int = 0xA09F) -> str | None:
    """Descobre /dev/bus/usb/BBB/DDD pelo sysfs (mesmo dentro de Flatpak)."""
    for dev in sorted(glob.glob("/sys/bus/usb/devices/*")):
        try:
            if int(Path(dev, "idVendor").read_text(), 16) != vid:
                continue
            if int(Path(dev, "idProduct").read_text(), 16) != pid:
                continue
            bus = int(Path(dev, "busnum").read_text())
            num = int(Path(dev, "devnum").read_text())
        except (OSError, ValueError):
            continue
        path = f"/dev/bus/usb/{bus:03d}/{num:03d}"
        if os.path.exists(path):
            return path
    return None


class UsbMouse:
    """Conexao usbfs com a interface de configuracao 2 do SM809 3.x."""

    def __init__(self, key: bytes | str | None = None, path: str | None = None):
        self.path = path or find_usbfs_device()
        if not self.path:
            raise FileNotFoundError("dispositivo usbfs do SM809 nao encontrado")
        self.fd = os.open(self.path, os.O_RDWR)
        self.claimed = False
        self.key = b""
        self.verbose = False
        try:
            fcntl.ioctl(self.fd, USBDEVFS_CLAIMINTERFACE, ctypes.c_uint(INTERFACE))
            self.claimed = True
            self.key = self._resolve_key(key)
        except Exception:
            self.close()
            raise

    def __enter__(self) -> "UsbMouse":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "fd", None) is not None:
            if self.claimed:
                try:
                    fcntl.ioctl(self.fd, USBDEVFS_RELEASEINTERFACE, ctypes.c_uint(INTERFACE))
                except OSError:
                    pass
                self.claimed = False
            os.close(self.fd)
            self.fd = None

    # ------------------------------ transporte -----------------------------
    def _control(self, out: bool, data: bytes) -> bytes:
        buf = (ctypes.c_ubyte * proto.PACKET_SIZE).from_buffer_copy(bytes(data[:8]).ljust(8, b"\0"))
        transfer = _CtrlTransfer(
            0x21 if out else 0xA1,
            REQ_SET_REPORT if out else REQ_GET_REPORT,
            FEATURE_REPORT_0,
            INTERFACE,
            proto.PACKET_SIZE,
            TIMEOUT_MS,
            ctypes.addressof(buf),
        )
        rc = fcntl.ioctl(self.fd, USBDEVFS_CONTROL, transfer)
        if rc != proto.PACKET_SIZE:
            raise OSError(f"transferencia USB incompleta: {rc} bytes")
        return bytes(buf)

    def _get_report(self) -> bytes:
        return self._control(False, b"\0" * 8)

    def _send(self, packet: bytes, key: bytes | None = None) -> None:
        key = key or self.key
        wire = proto.scramble(packet, key)
        if self.verbose:
            print(f"  TX {packet.hex(' ')} -> {wire.hex(' ')}")
        self._control(True, wire)

    def _reply(self, cmd: int, key: bytes | None = None) -> bytes | None:
        key = key or self.key
        for _ in range(REPLY_RETRIES):
            time.sleep(0.005)
            plain = proto.unscramble(self._get_report(), key)
            if plain[0] == cmd:
                return plain
        return None

    # -------------------------------- chave --------------------------------
    def _check_key(self, key: bytes) -> bool:
        cmd = proto.CMD_FIRMWARE | proto.READ
        self._send(proto.build(cmd), key)
        r = self._reply(cmd, key)
        return bool(r and r[1] == 0x03 and r[2] == 0x01)

    def _resolve_key(self, key: bytes | str | None) -> bytes:
        # GET_REPORT descarta a resposta pendente; o proximo traz o buffer com a chave.
        self._get_report()
        time.sleep(0.02)
        wire = self._get_report()
        q = bytes((wire[i] - proto.ADD[i]) & 0xFF for i in range(8))
        keyed = proto._rotate_right(int.from_bytes(q, "big"), 3).to_bytes(8, "big")

        raw = bytearray(keyed[1:7])
        if keyed[7] == 0x01:  # ack de escrita da tabela DPI (tamanho 8)
            raw[0] ^= 8
        raw[4] = 0  # so se descobre com o comando

        candidates = []
        if key is not None:
            k = key.encode("ascii") if isinstance(key, str) else bytes(key)
            if len(k) != proto.KEY_LEN:
                raise ValueError("chave deve ter 6 caracteres")
            candidates.append(k)
        for hint in (b"FB1570", bytes(raw)):
            if hint not in candidates:
                candidates.append(hint)
        for cmd in range(0x80):
            k = bytearray(raw)
            k[4] = keyed[5] ^ cmd
            k = bytes(k)
            if all(c in b"0123456789ABCDEF" for c in k) and k not in candidates:
                candidates.append(k)

        for k in candidates:
            if self._check_key(k):
                return k
        raise PermissionError("nao foi possivel descobrir a chave do mouse")

    # --------------------------- operacoes basicas -------------------------
    def read(self, cmd: int, arg: int = 0) -> tuple[bytes, bytes]:
        group = cmd & 0x7F
        if group in FORBIDDEN_READS:
            raise ValueError(f"leitura do grupo {group:02x} e perigosa neste firmware; recusada")
        if not cmd & proto.READ or group not in SAFE_READS:
            raise ValueError(f"grupo {group:02x} nao e de leitura segura em 3.x")
        self._send(proto.build(cmd, bytes((arg,))))
        reply = self._reply(cmd)
        if reply is None:
            raise TimeoutError(f"sem resposta para leitura {cmd:02x}")
        return reply[1:7], b""

    def write(self, cmd: int, *args: int) -> bytes:
        self._send(proto.build(cmd, bytes(args)))
        time.sleep(COMMAND_DELAY)
        reply = self._reply(cmd)
        if reply is None:
            raise TimeoutError(f"sem ACK para escrita {cmd:02x}")
        return reply[1:7]

    # ------------------------------ tabelas --------------------------------
    def _bulk_out(self, ep: int, data: bytes) -> None:
        """USBDEVFS_BULK tambem atende endpoints de interrupcao (PR #1915)."""
        buf = (ctypes.c_ubyte * len(data)).from_buffer_copy(data)
        transfer = _BulkTransfer(ep, len(data), TIMEOUT_MS, ctypes.addressof(buf))
        rc = fcntl.ioctl(self.fd, USBDEVFS_BULK, transfer)
        if rc != len(data):
            raise OSError(f"bulk incompleto no ep {ep:#04x}: {rc}/{len(data)}")
        time.sleep(COMMAND_DELAY)

    def write_block(self, cmd: int, page: int, length: int, data: bytes) -> bytes:
        """Escreve uma tabela: SET feature [cmd, page, len] + blocos de 32 bytes."""
        if len(data) != length or length % BLOCK_SIZE:
            raise ValueError(f"tabela deve ter {length} bytes multiplos de {BLOCK_SIZE}")
        self._send(proto.build(cmd, bytes((page, length))))
        time.sleep(COMMAND_DELAY)
        ack = self._reply(cmd)
        if ack is None:
            raise TimeoutError(f"sem ACK para tabela {cmd:02x}")
        for off in range(0, length, BLOCK_SIZE):
            chunk = data[off:off + BLOCK_SIZE]
            self._bulk_out(ENDPOINT_OUT, chunk.ljust(BLOCK_SIZE, b"\x00"))
        return ack[1:7]
