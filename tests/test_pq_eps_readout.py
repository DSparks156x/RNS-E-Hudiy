"""Offline tests for the PQ EPS KWP readout and flash paths."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flasher import runner
from flasher.controllers.pq_eps import protocol as pq_eps
from flasher.controllers.pq_eps import patches as eps_images
from flasher.vag_protocols.kwp import KWPNegativeResponse


class ScriptedTransport:
    def __init__(self, pairs):
        self.pairs = list(pairs)
        self.requests = []

    def send(self, request):
        self.requests.append(request)
        expected, self.response = self.pairs.pop(0)
        if expected != request:
            raise AssertionError(f"expected {expected.hex()}, got {request.hex()}")

    def recv(self):
        return self.response


class SimulatedFlashTransport:
    requests = []

    def __init__(self, device, **kwargs):
        self.device = device
        self.disconnect = Mock()
        self.keepalive_after_response = False

    def send(self, request):
        self.requests.append(request)
        self.pending = request

    def recv(self):
        request = self.pending
        if request == b"\x1A\x9B":
            return b"\x5A\x9B" + b"8J0909144J  3104" + bytes(10) + b"EPS_ZFLS"
        if request == b"\x1A\x9C":
            return b"\x5A\x9C\x00\x12\x03" + bytes(15)
        if request == b"\x10\x85":
            return b"\x50\x85"
        if request == b"\x27\x01":
            return b"\x67\x01\x12\x34\x56\x78"
        if request[:2] == b"\x27\x02":
            return b"\x67\x02"
        if request[:1] == b"\x34":
            return b"\x74\xF0"
        if request[:2] == b"\x31\xC4":
            return b"\x71\xC4\x01"
        if request == b"\x33\xC4":
            return b"\x73\xC4\x00"
        if request[:1] == b"\x36":
            return b"\x76"
        if request == b"\x37":
            return b"\x77"
        if request[:2] == b"\x31\xC5":
            return b"\x71\xC5"
        if request == b"\x33\xC5":
            return b"\x73\xC5\x00"
        if request == b"\x82":
            return b"\xC2"
        raise AssertionError(request.hex())


class PQEPSProtocolTests(unittest.TestCase):
    def setUp(self):
        SimulatedFlashTransport.requests = []

    def test_identification_exposes_software_identity_and_flash_status(self):
        transport = ScriptedTransport([
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"1K0909144E  2501" + bytes(10) + b"EPS_ZFLS Kl. 184    "),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
        ])
        info = pq_eps.PQEPSReader(transport).identification()
        self.assertEqual(info["software_part_number"], "1K0909144E")
        self.assertEqual(info["firmware_revision"], "2501")
        self.assertEqual(info["flash_status"], 0)
        self.assertIn("EPS_ZFLS", info["system_desc"])

    def test_additive_read_key_and_engineering_session(self):
        transport = ScriptedTransport([
            (b"\x10\x89", b"\x50\x89"),
            (b"\x23\x00\x00\x00\x10", b"\x7F\x23\x33"),
            (b"\x35\x00\x00\x00\x00\x00\x00\x10", b"\x7F\x35\x33"),
            (b"\x27\x03", bytes.fromhex("67031234ffff")),
            (bytes.fromhex("270412351595"), b"\x67\x04"),
            (b"\x10\x86", b"\x50\x86"),
            (b"\x23\x00\x00\x00\x10", b"\x63" + bytes(range(16))),
            (b"\x10\x89", b"\x50\x89"),
        ])
        reader = pq_eps.PQEPSReader(transport)
        probe = reader.probe([0])
        self.assertEqual(probe.method, "read-memory")
        self.assertTrue(probe.security_unlocked)
        self.assertEqual(reader.leave(), [])
        self.assertFalse(any(request[:1] in (b"\x34", b"\x31", b"\x3D", b"\x82")
                             for request in transport.requests))

    def test_upload_accepts_two_byte_limit_and_never_retries_transfer(self):
        transport = ScriptedTransport([
            (bytes.fromhex("3500a00000000100"), bytes.fromhex("750100")),
            (b"\x36", b"\x76" + bytes(range(200))),
            (b"\x36", b"\x76" + bytes(range(56))),
            (b"\x37", b"\x77"),
        ])
        reader = pq_eps.PQEPSReader(transport)
        self.assertEqual(len(reader.read_upload(0xA000, 0x100)), 0x100)
        self.assertEqual(transport.requests.count(b"\x36"), 2)

    def test_zero_seed_means_already_unlocked_and_sends_no_key(self):
        transport = ScriptedTransport([
            (b"\x27\x03", b"\x67\x03\x00\x00\x00\x00"),
            (b"\x10\x86", b"\x50\x86"),
        ])
        reader = pq_eps.PQEPSReader(transport)
        reader.unlock_engineering()
        self.assertEqual(transport.requests, [b"\x27\x03", b"\x10\x86"])

    def test_allowlist_rejects_every_mutating_service(self):
        reader = pq_eps.PQEPSReader(ScriptedTransport([]))
        for request in (b"\x10\x85", b"\x34", b"\x31\xC4", b"\x3D", b"\x82", b"\x11"):
            with self.subTest(request=request.hex()), self.assertRaises(ValueError):
                reader.exchange(request)

    def test_partial_capture_preserves_holes(self):
        class Reader:
            def read_memory(self, address, length):
                if address == 0xF0:
                    raise KWPNegativeResponse(b"\x23", b"\x7F\x23\x31")
                return bytes([address // 0xF0]) * length

        with tempfile.TemporaryDirectory() as directory:
            result = pq_eps.capture_eps(Reader(), Path(directory), 0, 0x200,
                                        "read-memory", chunk=0xF0)
            image = (Path(directory) / "kwp_readout.bin").read_bytes()
            self.assertEqual(len(image), 0x60000)
            self.assertEqual(result["unreadable_bytes"], 0xF0)
            self.assertEqual(image[0xF0:0x1E0], b"\xFF" * 0xF0)

    def test_shared_flash_lifecycle_uses_eps_programming_sequence(self):
        device = Mock()
        replacement = Mock()
        prepared = eps_images.prepare_image(bytes(eps_images.IMAGE_SIZE),
                                             0x5D000, 0x5D00F)
        with patch.object(pq_eps, "TP20Transport", SimulatedFlashTransport):
            flasher = pq_eps.PQEPSFlasher(
                device=device, device_factory=lambda: replacement)
            result = flasher.flash_prepared(prepared)
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["checksum_verified"])
        self.assertTrue(result["boot_verified"])
        requests = SimulatedFlashTransport.requests
        self.assertIn(b"\x10\x85", requests)
        self.assertIn(b"\x27\x01", requests)
        self.assertIn(bytes.fromhex("31c405d00005d00f"), requests)
        self.assertIn(bytes.fromhex("31c505d00005d00f0000"), requests)
        self.assertEqual([request for request in requests if request[:1] == b"\x36"],
                         [b"\x36" + bytes(16)])
        self.assertIn(b"\x82", requests)


class PQEPSCLITests(unittest.TestCase):
    def test_full_eeprom_read_uses_secured_upload_and_saves_all_bytes(self):
        blocks = [bytes([index]) * 8 for index in range(128)]
        pairs = [
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
            (b"\x10\x89", b"\x50\x89"),
            (b"\x27\x03", bytes.fromhex("67031234ffff")),
            (bytes.fromhex("270412351595"), b"\x67\x04"),
            (b"\x10\x86", b"\x50\x86"),
            (bytes.fromhex("3500000000000400"), b"\x75\x08"),
            *[(b"\x36", b"\x76" + block) for block in blocks],
            (b"\x37", b"\x77"),
            (b"\x10\x89", b"\x50\x89"),
        ]
        transport = ScriptedTransport(pairs)
        transport.disconnect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "eps_eeprom.bin"
            with patch.object(pq_eps, "TP20Transport", return_value=transport), \
                    patch.object(runner, "open_adapter", return_value=Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.main(["--module", "eps", "--read-eeprom",
                                      "--out", str(output)])
            self.assertEqual(result, 0)
            self.assertEqual(output.read_bytes(), b"".join(blocks))
            self.assertFalse(transport.pairs)
            self.assertFalse(any(request[:1] in (b"\x34", b"\x31", b"\x3D")
                                 for request in transport.requests))

    def test_eeprom_dry_run_is_eps_only_and_has_no_hardware_access(self):
        output = io.StringIO()
        with patch.object(runner, "open_adapter") as opened, \
                contextlib.redirect_stdout(output):
            result = runner.main(["--module", "eps", "--read-eeprom",
                                  "--out", "sample.bin", "--dry-run"])
        self.assertEqual(result, 0)
        opened.assert_not_called()
        plan = json.loads(output.getvalue())
        self.assertEqual(plan["kwp_upload_request"], "35 00 00 00 00 00 04 00")
        self.assertFalse(plan["hardware_access"])

    def test_rejected_eeprom_security_stops_without_upload_or_file(self):
        pairs = [
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
            (b"\x10\x89", b"\x50\x89"),
            (b"\x27\x03", bytes.fromhex("67031234ffff")),
            (bytes.fromhex("270412351595"), b"\x7F\x27\x35"),
        ]
        transport = ScriptedTransport(pairs)
        transport.disconnect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "rejected.bin"
            with patch.object(pq_eps, "TP20Transport", return_value=transport), \
                    patch.object(runner, "open_adapter", return_value=Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.main(["--module", "eps", "--read-eeprom",
                                      "--out", str(output)])
            self.assertEqual(result, 1)
            self.assertFalse(output.exists())
            self.assertFalse(transport.pairs)
            self.assertNotIn(bytes.fromhex("3500000000000400"), transport.requests)

    def test_dry_run_uses_eps_defaults_and_no_writes(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = runner.main(["--module", "eps", "--readout", "--dry-run"])
        self.assertEqual(result, 0)
        plan = json.loads(out.getvalue())
        self.assertEqual((plan["module"], plan["start"], plan["end"]),
                         (0x09, 0, 0x5FFFF))
        self.assertEqual(plan["security_constant"], 0x1596)
        self.assertFalse(plan["firmware_writes"])

    def test_eps_flash_dry_run_accepts_ende_and_erased_trailers(self):
        for trailer, expected in ((b"Ende", "Ende"), (b"\xFF" * 4, "erased")):
            with self.subTest(trailer=expected), tempfile.TemporaryDirectory() as directory:
                source = Path(directory) / "rack.bin"
                image = bytearray(eps_images.IMAGE_SIZE)
                image[eps_images.END_MARKER_OFFSET:] = trailer
                source.write_bytes(image)
                out = io.StringIO()
                with patch.object(runner, "open_adapter") as opened, \
                        contextlib.redirect_stdout(out):
                    result = runner.main([
                        "--module", "0x09", "--input", str(source), "--dry-run"])
                self.assertEqual(result, 0)
                opened.assert_not_called()
                report = json.loads(out.getvalue().split("\nNo CAN traffic sent.")[0])
                self.assertEqual(report["end_marker"], expected)
                self.assertEqual((report["start_addr"], report["end_addr"]),
                                 (0x5D000, 0x5DFFF))

    def test_eps_flash_preparation_uses_unmodified_range_and_c5_sum(self):
        image = bytearray(eps_images.IMAGE_SIZE)
        image[0x5D000:0x5D010] = bytes(range(16))
        prepared = eps_images.prepare_image(image, 0x5D000, 0x5D00F)
        self.assertEqual(prepared["region"], bytes(range(16)))
        self.assertEqual(prepared["metadata"]["checksum"], sum(range(16)))
        self.assertEqual(prepared["image"], bytes(image))

    def test_eps_flash_rejects_cpu_space_below_obd_programming_window(self):
        with self.assertRaisesRegex(ValueError, "0x00A000"):
            eps_images.prepare_image(bytes(eps_images.IMAGE_SIZE), 0, 0x0FFF)

    def test_eps_flash_profile_matches_legacy_loader_payloads(self):
        profile = pq_eps.make_eps_flash_profile(
            kwp_factory=Mock(), image_preparer=Mock(), device_factory=Mock(),
            transport_factory=Mock(), identify=Mock())
        metadata = {"checksum": 0x1234}
        self.assertEqual(profile.programming_session, 0x85)
        self.assertEqual(profile.erase_payload(0x5D000, 0x5DFFF, metadata),
                         bytes.fromhex("05d00005dfff"))
        self.assertEqual(profile.checksum_payload(0x5D000, 0x5DFFF, metadata),
                         bytes.fromhex("05d00005dfff1234"))
        self.assertEqual(profile.commit_services, (0x82,))

    def test_eps_partial_flash_requires_revision_3000_or_newer(self):
        profile = pq_eps.make_eps_flash_profile(
            kwp_factory=Mock(), image_preparer=Mock(), device_factory=Mock(),
            transport_factory=Mock(), identify=Mock())
        partial = {"start_addr": 0x5E000, "end_addr": 0x5EFFF}
        profile.validate_controller(
            {"software_part_number": "8J0909144J", "sw_version": "3000"}, partial)
        for revision in ("2999", "", "3A01"):
            with self.subTest(revision=revision), self.assertRaisesRegex(
                    RuntimeError, "does not approve partial-region"):
                profile.validate_controller(
                    {"software_part_number": "8J0909144J", "sw_version": revision},
                    partial)
        profile.validate_controller(
            {"software_part_number": "8J0909144J", "sw_version": "2301"},
            {"start_addr": 0x0A000, "end_addr": 0x5FFFF})


if __name__ == "__main__":
    unittest.main()
