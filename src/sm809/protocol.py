"""Codificacao/decodificacao dos pacotes HID do SM809 (Holtek 04D9:A09F).

Pacote plaintext: [cmd, d1..d6, chk], chk = 0xFF - soma(cmd..d6).
No fio os bytes sao permutados, XORados com uma chave ASCII de 6 caracteres,
rotacionados 3 bits a esquerda (como inteiro big-endian de 64 bits) e somados
a uma tabela de offsets.
"""

from __future__ import annotations

ADD = (0x25, 0xF6, 0xE4, 0x76, 0x47, 0x54, 0xE6, 0x76)
KEY_LEN = 6
PACKET_SIZE = 8
FEATURE_SIZE = PACKET_SIZE + 1  # report ID 0 + 8 bytes

READ = 0x80

CMD_FIRMWARE = 0x00
CMD_POLLING = 0x01
CMD_PROFILE = 0x02
CMD_COLOR = 0x0C
CMD_EFFECT = 0x0D
CMD_CYCLE_PALETTE = 0x10
CMD_DPI_TABLE = 0x11
CMD_BUTTON_MAP = 0x12
CMD_MACRO_DATA = 0x13

EFFECTS = {
    "off": 0x00,
    "static": 0x01,
    "breathing": 0x02,
    "neon": 0x03,
    "wave": 0x04,
    "key-reaction": 0x05,
    "trailing": 0x06,
    "drag": 0x07,
    "slide": 0x08,
    "yo-yo": 0x09,
    "marbles": 0x0A,
    "flying-star": 0x0B,
}

DEFAULT_EFFECT_PARAMS = {
    0x00: (0x00, 0x00),
    0x01: (0xFF, 0x00),
    0x02: (0x03, 0x00),
    0x03: (0x03, 0xFF),
    0x04: (0x03, 0xFF),
    0x05: (0xFF, 0x00),
    0x06: (0x02, 0x00),
    0x07: (0x02, 0x00),
    0x08: (0xFF, 0x00),
    0x09: (0xFF, 0x10),
    0x0A: (0xFF, 0x01),
    0x0B: (0xFF, 0x00),
}


def checksum(packet: bytes) -> int:
    """Checksum de um pacote de 8 bytes (ignora o proprio checksum)."""
    if len(packet) != PACKET_SIZE:
        raise ValueError("pacote deve ter 8 bytes")
    return (0xFF - sum(packet[: PACKET_SIZE - 1])) & 0xFF


def build(cmd: int, data: bytes = b"", *, fix_checksum: bool = True) -> bytes:
    """Monta um pacote plaintext [cmd, dados (ate 6), chk]."""
    if not 0 <= cmd <= 0xFF:
        raise ValueError("cmd fora de 0..255")
    payload = bytes(data[:6]).ljust(6, b"\x00")
    pkt = bytes((cmd,)) + payload + b"\x00"
    if fix_checksum:
        pkt = pkt[:7] + bytes((checksum(pkt),))
    return pkt


def _rotate_left(v: int, n: int) -> int:
    return ((v << n) | (v >> (64 - n))) & ((1 << 64) - 1)


def _rotate_right(v: int, n: int) -> int:
    return ((v >> n) | (v << (64 - n))) & ((1 << 64) - 1)


def _check_key(key: bytes) -> bytes:
    key = bytes(key)
    if len(key) != KEY_LEN:
        raise ValueError(f"chave deve ter {KEY_LEN} bytes, recebido {len(key)}")
    return key


def scramble(packet: bytes, key: bytes) -> bytes:
    """Ofusca um pacote plaintext com a chave de 6 caracteres."""
    if len(packet) != PACKET_SIZE:
        raise ValueError("pacote deve ter 8 bytes")
    key = _check_key(key)
    p = packet
    q = (
        p[5],
        p[4] ^ key[0],
        p[7] ^ key[1],
        p[6] ^ key[2],
        p[1] ^ key[3],
        p[0] ^ key[4],
        p[3] ^ key[5],
        p[2],
    )
    v = _rotate_left(int.from_bytes(bytes(q), "big"), 3)
    q = v.to_bytes(8, "big")
    return bytes((q[i] + ADD[i]) & 0xFF for i in range(8))


def unscramble(wire: bytes, key: bytes) -> bytes:
    """Desfaz a ofuscacao; devolve o pacote plaintext."""
    if len(wire) != PACKET_SIZE:
        raise ValueError("pacote deve ter 8 bytes")
    key = _check_key(key)
    q = bytearray((wire[i] - ADD[i]) & 0xFF for i in range(8))
    v = _rotate_right(int.from_bytes(bytes(q), "big"), 3).to_bytes(8, "big")
    p = [0] * 8
    p[5] = v[0]
    p[4] = v[1] ^ key[0]
    p[7] = v[2] ^ key[1]
    p[6] = v[3] ^ key[2]
    p[1] = v[4] ^ key[3]
    p[0] = v[5] ^ key[4]
    p[3] = v[6] ^ key[5]
    p[2] = v[7]
    return bytes(p)


def valid(packet: bytes) -> bool:
    """Verifica se o checksum de um pacote plaintext esta correto."""
    return len(packet) == PACKET_SIZE and packet[7] == checksum(packet)


def feature_payload(raw: bytes) -> bytes:
    """Remove o report ID (byte 0) de um feature report de 9 bytes."""
    if len(raw) != FEATURE_SIZE:
        raise ValueError(f"feature report deve ter {FEATURE_SIZE} bytes")
    return raw[1:]


def as_feature(packet: bytes, key: bytes) -> bytes:
    """Monta o buffer de 9 bytes pronto para HIDIOCSFEATURE9."""
    return b"\x00" + scramble(packet, key)
