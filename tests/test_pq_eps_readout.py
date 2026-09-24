"""Offline tests for the PQ EPS KWP readout and flash paths."""
import contextlib
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flasher import engine, runner
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
            return b"\x5A\x9B" + b"8J0909144J  3104" + bytes(10) + b"EPS_ZFLS BB"
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
             b"1K0909144E  2501" + bytes(10) + b"EPS_ZFLS Kl. 236    "),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
        ])
        info = pq_eps.decorate_identification(
            pq_eps.PQEPSReader(transport).identification())
        self.assertEqual(info["software_part_number"], "1K0909144E")
        self.assertEqual(info["firmware_revision"], "2501")
        self.assertEqual(info["flash_status"], 0)
        self.assertIn("EPS_ZFLS", info["system_desc"])
        self.assertEqual(info["dataset_version"], "236")
        self.assertFalse(info["in_bootloader"])

    def test_loader_identification_has_no_application_dataset(self):
        info = pq_eps.decorate_identification({"system_desc": "EPS_ZFLS BB"})
        self.assertTrue(info["in_bootloader"])
        self.assertIsNone(info["dataset_version"])

    def test_ident_command_reports_dataset_and_application_state(self):
        transport = ScriptedTransport([
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"1K0909144E  2501" + bytes(10) + b"EPS_ZFLS Kl. 236    "),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
        ])
        transport.disconnect = Mock()
        device = Mock()
        stdout = io.StringIO()
        with patch.object(runner, "open_adapter", return_value=device), \
                patch("flasher.vag_protocols.tp2.TP20Transport",
                      return_value=transport), contextlib.redirect_stdout(stdout):
            result = runner.main(["--module", "eps", "--ident-only"])
        report = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(report["dataset_version"], "236")
        self.assertFalse(report["in_bootloader"])
        transport.disconnect.assert_called_once_with()
        device.close.assert_called_once_with()

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
        with patch.object(pq_eps, "TP20Transport", SimulatedFlashTransport), \
                patch.object(engine.time, "sleep") as sleep:
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
        sleep.assert_any_call(1.0)

    def test_programming_channel_rejects_application_personality(self):
        transport = ScriptedTransport([
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
        ])
        flasher = pq_eps.PQEPSFlasher(device=Mock())
        with self.assertRaisesRegex(RuntimeError, "did not enter its resident loader"):
            flasher.profile.verify_programming_channel(transport)
        self.assertNotIn(b"\x27\x01", transport.requests)


class PQEPSCLITests(unittest.TestCase):
    def test_stationary_assist_capture_preserves_raw_group05_without_security(self):
        pairs = [
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
            (b"\x21\x05", bytes.fromhex(
                "61 05 5D 10 81 5D 20 82 5D 30 84 5E 40 88")),
            (b"\x21\x05", bytes.fromhex(
                "61 05 5D 11 81 5D 22 82 5D 33 84 5E 44 88")),
        ]
        transport = ScriptedTransport(pairs)
        transport.disconnect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assist.json"
            with patch.object(pq_eps, "TP20Transport", return_value=transport), \
                    patch.object(pq_eps.time, "sleep"), \
                    patch.object(runner, "open_adapter", return_value=Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.main(["--module", "eps", "--read-eps-assist",
                                      "--assist-samples", "2", "--out", str(output)])
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual(record["status"], "captured_complete")
            self.assertEqual(record["samples"][0]["field_triples"],
                             ["5D 10 81", "5D 20 82", "5D 30 84", "5E 40 88"])
            self.assertEqual([request[0] for request in transport.requests],
                             [0x1A, 0x1A, 0x21, 0x21])

    def test_stationary_assist_capture_retains_unexpected_layout(self):
        pairs = [
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
            (b"\x21\x05", bytes.fromhex("61 05 00 11 22")),
        ]
        transport = ScriptedTransport(pairs)
        transport.disconnect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "assist_unexpected.json"
            with patch.object(pq_eps, "TP20Transport", return_value=transport), \
                    patch.object(runner, "open_adapter", return_value=Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.main(["--module", "eps", "--read-eps-assist",
                                      "--out", str(output)])
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertEqual(record["status"], "captured_partial")
            self.assertEqual(record["samples"][0]["response"], "61 05 00 11 22")
            self.assertFalse(record["samples"][0]["layout_valid"])
            self.assertTrue(record["errors"])

    def test_stationary_motion_capture_decodes_threshold_without_security(self):
        pairs = [
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
            (b"\x21\x01", bytes.fromhex("61 01 1A 46 26 25 00 00 74 0E 41 25 00 00")),
            (b"\x21\x01", bytes.fromhex("61 01 1A 46 2A 25 00 00 74 F1 BE 25 00 00")),
        ]
        transport = ScriptedTransport(pairs)
        transport.disconnect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "motion.json"
            with patch.object(pq_eps, "TP20Transport", return_value=transport), \
                    patch.object(pq_eps.time, "sleep"), \
                    patch.object(runner, "open_adapter", return_value=Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.main(["--module", "eps", "--read-eps-motion",
                                      "--motion-samples", "2", "--out", str(output)])
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 0)
            self.assertEqual([row["signed_rate"] for row in record["samples"]],
                             [3649, -3650])
            self.assertEqual([row["at_or_above_branch"] for row in record["samples"]],
                             [False, True])
            self.assertEqual([row["post_slew_cap_selector"] for row in record["samples"]],
                             [38, 42])
            self.assertEqual([row["at_min_post_slew_cap_knot"] for row in record["samples"]],
                             [True, False])
            self.assertEqual([request[0] for request in transport.requests],
                             [0x1A, 0x1A, 0x21, 0x21])

    def test_fault_capture_reads_all_pages_without_security_or_mutating_services(self):
        header = bytes.fromhex("61 32 4B 00 43 4B 3C 6A A1 00 00 6B 0E 00")
        pairs = [
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
            *[(bytes((0x21, group)), header if group == 0x32
               else bytes((0x61, group, 0x00))) for group in range(0x32, 0x46)],
        ]
        transport = ScriptedTransport(pairs)
        transport.disconnect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "faults.json"
            with patch.object(pq_eps, "TP20Transport", return_value=transport), \
                    patch.object(runner, "open_adapter", return_value=Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.main(["--module", "eps", "--read-eps-faults",
                                      "--out", str(output)])
            self.assertEqual(result, 0)
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(record["headers"]["32"]["internal_id"], 0x43)
            self.assertEqual(record["headers"]["32"]["subcode"], 0x3C6A)
            self.assertEqual(len(record["responses"]), 20)
            self.assertFalse(transport.pairs)
            self.assertEqual([request[0] for request in transport.requests],
                             [0x1A, 0x1A] + [0x21] * 20)

    def test_fault_capture_preserves_other_pages_after_one_negative_response(self):
        pairs = [
            (b"\x1A\x9B", b"\x5A\x9B" +
             b"8J0909144J  3001" + bytes(10) + b"EPS_ZFLS"),
            (b"\x1A\x9C", b"\x5A\x9C\x00\x12\x03" + bytes(15)),
            *[(bytes((0x21, group)), bytes.fromhex("7F 21 31") if group == 0x34
               else bytes((0x61, group, 0x00))) for group in range(0x32, 0x46)],
        ]
        transport = ScriptedTransport(pairs)
        transport.disconnect = Mock()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "faults_partial.json"
            with patch.object(pq_eps, "TP20Transport", return_value=transport), \
                    patch.object(runner, "open_adapter", return_value=Mock()), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = runner.main(["--module", "eps", "--read-eps-faults",
                                      "--out", str(output)])
            record = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result, 1)
            self.assertEqual(record["status"], "captured_partial")
            self.assertEqual(len(record["responses"]), 19)
            self.assertIn("45", record["responses"])
            self.assertIn("21 34", record["errors"][0])
            self.assertFalse(transport.pairs)

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

    def test_eps_flash_dry_run_maps_4k_input_to_steer_dataset(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "dataset.bin"
            source.write_bytes(bytes(range(256)) * 16)
            out = io.StringIO()
            with patch.object(runner, "open_adapter") as opened, \
                    contextlib.redirect_stdout(out):
                result = runner.main([
                    "--module", "eps", "--input", str(source), "--dry-run"])
            self.assertEqual(result, 0)
            opened.assert_not_called()
            report = json.loads(out.getvalue().split("\nNo CAN traffic sent.")[0])
            self.assertEqual((report["start_addr"], report["end_addr"]),
                             (0x5E000, 0x5EFFF))
            self.assertEqual(report["source_kind"],
                             "4 KiB steer dataset block (0x5E)")

    def test_eps_flash_preparation_uses_unmodified_range_and_c5_sum(self):
        image = bytearray(eps_images.IMAGE_SIZE)
        image[0x5D000:0x5D010] = bytes(range(16))
        prepared = eps_images.prepare_image(image, 0x5D000, 0x5D00F)
        self.assertEqual(prepared["region"], bytes(range(16)))
        self.assertEqual(prepared["metadata"]["checksum"], sum(range(16)))
        self.assertEqual(prepared["image"], bytes(image))

    def test_eps_block_image_is_accepted_only_as_steer_dataset(self):
        dataset = bytes(range(256)) * 16
        prepared = eps_images.prepare_image(
            dataset, eps_images.DATASET_START, eps_images.DATASET_END)
        self.assertEqual(prepared["region"], dataset)
        self.assertEqual(prepared["metadata"]["source_kind"],
                         "4 KiB steer dataset block (0x5E)")
        self.assertEqual(prepared["metadata"]["checksum"], sum(dataset) & 0xFFFF)
        for start, end in ((0x5D000, 0x5DFFF), (0x0A000, 0x5FFFF)):
            with self.subTest(start=start), self.assertRaisesRegex(
                    ValueError, "only be flashed.*0x5E"):
                eps_images.prepare_image(dataset, start, end)

    def test_tt3001_loader_partition_check_rejects_local_only_range(self):
        image = bytes(eps_images.IMAGE_SIZE)
        low_bank_hash = hashlib.sha256(image[:eps_images.FLASH_START]).hexdigest().upper()
        with patch.object(eps_images, "TT3001_LOADER_SHA256", low_bank_hash):
            accepted = eps_images.prepare_image(image, 0xA000, 0x5DFFF)
            self.assertEqual(accepted["metadata"]["selection_policy"],
                             "exact TT 3001 resident-loader partition")
            with self.assertRaisesRegex(ValueError, "exact partition bounds"):
                eps_images.prepare_image(image, 0x28000, 0x5DFFF)

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
