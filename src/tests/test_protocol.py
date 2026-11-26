"""Testes sem hardware: vetores capturados e codificacao de macros."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sm809 import protocol as proto                      # noqa: E402
from sm809.config import Button, MacroEvent, Macros, parse_button_action  # noqa: E402
from sm809.device import key_from_idle                   # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_checksum(self):
        pkt = proto.build(0x83)
        self.assertEqual(pkt, bytes.fromhex("83 00 00 00 00 00 00 7c"))
        self.assertTrue(proto.valid(pkt))

    def test_scramble_argus_vector(self):
        # Vetor do PROTOCOLO_ARGUS.md / argus_proto.py, chave FB1313
        pkt = proto.build(0x83)
        self.assertEqual(proto.scramble(pkt, b"FB1313").hex(" "),
                         "27 27 d5 ff e4 e5 7e 76")

    def test_scramble_captured_idle_sm809(self):
        # Capturado do mouse SM809 conectado (bcdDevice 0301), chave FB1570
        wire = bytes.fromhex("27 28 f5 ff f0 0d 66 76")
        self.assertEqual(proto.scramble(b"\x00" * 8, b"FB1570"), wire)
        self.assertEqual(key_from_idle(wire), b"FB1570")

    def test_roundtrip(self):
        key = b"FB1570"
        for cmd, data in ((0x0C, b"\x00\x00\xff"), (0x0D, b"\x01\xff\x00"),
                          (0x83, b""), (0x01, b"\x01")):
            pkt = proto.build(cmd, data)
            self.assertEqual(proto.unscramble(proto.scramble(pkt, key), key), pkt)

    def test_feature_wrapper(self):
        pkt = proto.build(0x0C, b"\x00\x00\xff")
        feat = proto.as_feature(pkt, b"FB1570")
        self.assertEqual(len(feat), 9)
        self.assertEqual(feat[0], 0)
        self.assertEqual(proto.feature_payload(feat), proto.scramble(pkt, b"FB1570"))


class FakeMouse:
    def __init__(self, raw):
        self.raw = raw

    def read_block(self, cmd, page, length):
        return self.raw[:length]


class MacroTests(unittest.TestCase):
    def test_wait_decode(self):
        # [repeat_hi, repeat_lo, WAIT arg, 0x01, delay_hi, delay_lo, tecla 'A', 0x04]
        raw = bytes.fromhex("00 01 00 01 00 32 04 04") + b"\x00" * 120
        events = Macros(FakeMouse(raw)).read(1)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].command, 0x01)
        self.assertEqual(events[0].wait, 50)
        self.assertEqual(events[1].key, 0x04)
        self.assertTrue(events[1].press)

    def test_wait_encode(self):
        events = [MacroEvent(0, command=0x01, wait=50), MacroEvent(0x04)]
        macros = Macros(FakeMouse(b""))
        captured = {}
        macros.mouse.write_block = lambda cmd, page, length, data: captured.update(data=data)
        macros.write(1, events)
        self.assertEqual(captured["data"][:10], bytes.fromhex("00 01 00 01 00 32 01 04 00 00"))


class ButtonTests(unittest.TestCase):
    def test_parse_actions(self):
        self.assertEqual(parse_button_action("left"), bytes.fromhex("01 00 f0 00"))
        self.assertEqual(parse_button_action("dpi-up"), bytes.fromhex("07 00 01 00"))
        self.assertEqual(parse_button_action("scroll-down"), bytes.fromhex("04 00 02 00"))
        self.assertEqual(parse_button_action("macro-3-1"), bytes.fromhex("09 01 03 00"))
        self.assertEqual(parse_button_action("multiclick-left-3"), bytes.fromhex("0a f0 32 03"))
        self.assertEqual(parse_button_action("key-a"), bytes.fromhex("00 00 04 00"))

    def test_roundtrip_name(self):
        b = Button.from_action(1, "macro-3-1")
        self.assertEqual(Button.from_bytes(1, b.to_bytes()).action, "macro-3-1")


if __name__ == "__main__":
    unittest.main()
