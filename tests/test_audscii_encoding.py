"""Offline wire-encoding checks; no service sockets or CAN are constructed."""
import ast
import importlib.util
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional


REPO = Path(__file__).resolve().parents[1]
if not (REPO / "dis_client").is_dir():
    REPO = Path(__file__).resolve().parent.parent / "RNS-E-Hudiy"
SOURCE = REPO / "dis_client"
spec = importlib.util.spec_from_file_location("encoding_icons", SOURCE / "icons.py")
icons = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icons)


def load_pure_nodes(filename, names, namespace, class_name=None):
    tree = ast.parse((SOURCE / filename).read_text(encoding="utf-8"))
    nodes = tree.body
    if class_name:
        nodes = next(node.body for node in nodes if isinstance(node, ast.ClassDef)
                     and node.name == class_name)
    selected = [node for node in nodes if getattr(node, "name", None) in names]
    if {node.name for node in selected} != set(names):
        raise AssertionError("Missing production functions")
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)
    return namespace


TOP = load_pure_nodes("dis_top_display_service.py",
                      {"_normalize", "_encode_text", "_encode_continuous_text", "TextScroller"},
                      dict(audscii_trans=icons.audscii_trans,
                           audscii_unicode=icons.audscii_unicode,
                           encode_audscii=icons.encode_audscii, _unidecode=None,
                           _BLANK=icons.audscii_trans[32], _CONT_GAP=icons.audscii_trans[31],
                           threading=threading, time=time, Optional=Optional))
CENTER = load_pure_nodes("dis_service.py", {"translate_to_audscii", "get_text_payload"},
                         dict(List=List, encode_audscii=icons.encode_audscii), "DisService")


class AudsciiEncodingTests(unittest.TestCase):
    def test_all_legacy_input_bytes_use_the_translation_table(self):
        self.assertEqual(icons.encode_audscii("".join(map(chr, range(256)))),
                         bytes(icons.audscii_trans))

    def test_captured_fraction_and_symbol_assignments(self):
        self.assertEqual(icons.encode_audscii("£§¼½¾"), bytes.fromhex("aa bf bc bd be"))
        self.assertEqual(icons.encode_audscii("↑↓→←✓▲▼▶απ€‰ŒœŠšŽž"),
                         bytes.fromhex("18 19 1a 1b 11 1e 1f 69 a1 a8 a9 a3 e3 f3 cc fc cd fd"))

    def test_unknown_unicode_does_not_alias_to_controls_or_ascii(self):
        self.assertEqual(icons.encode_audscii("\u0100\u0141\U0001f641"), b"   ")
        self.assertEqual(icons.encode_audscii("Aé"),
                         bytes([icons.audscii_trans[65], icons.audscii_trans[233]]))

    def test_logging_controls_use_captured_native_glyphs(self):
        self.assertEqual(icons.encode_audscii('▶□⚑⊕'), bytes.fromhex('69 ab df 15'))

    def test_null_pause_and_scroll_tokens_remain_unchanged(self):
        self.assertEqual(icons.encode_audscii("\x00\x1c\x1e\x1f"),
                         bytes.fromhex("00 1c d7 65"))

    def test_center_wire_payload_counts_encoded_characters(self):
        service = SimpleNamespace(region_y_offset=27, region_height=48)
        service.translate_to_audscii = lambda text: CENTER["translate_to_audscii"](service, text)
        self.assertEqual(service.translate_to_audscii("¾→🙂"), [0xbe, 0x1a, 0x20])
        payload = CENTER["get_text_payload"](service, "¾→🙂", 3, 4, 0x06)
        self.assertEqual(payload, [0x57, 6, 0x06, 3, 4, 0xbe, 0x1a, 0x20])

    def test_top_encoder_and_continuous_gap_share_symbol_mapping(self):
        self.assertEqual(TOP["_encode_text"]("↑¾\x00"), bytes.fromhex("18 be 00"))
        self.assertEqual(TOP["_encode_continuous_text"]("↑ 🙂"), bytes.fromhex("18 65 20"))

    def test_optional_top_transliteration_preserves_captured_aliases(self):
        previous = TOP["_unidecode"]
        try:
            TOP["_unidecode"] = lambda char: "X"
            self.assertEqual(TOP["_normalize"]("↑漢éŒ"), "↑XéŒ")
            TOP["_unidecode"] = None
            self.assertEqual(TOP["_normalize"]("↑漢"), "↑漢")
            self.assertEqual(TOP["_encode_text"]("↑漢"), b"\x18 ")
        finally:
            TOP["_unidecode"] = previous

    def test_short_scroller_remains_eight_display_bytes(self):
        scroller = TOP["TextScroller"]()
        scroller.set_text("¾→↑")
        self.assertEqual(scroller.snapshot(), b"  \xbe\x1a\x18   ")

    def test_continuous_scroll_stream_preserves_one_byte_per_character(self):
        scroller = TOP["TextScroller"](continuous=True, continuous_gap=2)
        scroller.set_text("↑ 12345678")
        self.assertEqual(scroller._stream,
                         icons.encode_audscii("↑\x1f12345678") + b"\x65\x65")
        self.assertEqual(len(scroller.snapshot()), 8)
        self.assertEqual(scroller._stream_len, 12)


if __name__ == "__main__":
    unittest.main()
