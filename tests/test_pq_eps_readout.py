"""Offline tests for PQ35 EPS image policy and flash registration."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flasher import runner
from flasher.controllers import registry
from flasher.controllers.pq_eps import protocol as eps


def dataset(fill=0x42):
    body = bytearray(bytes([fill]) * (eps.EPS_BLOCK_SIZE - 2))
    for index in range(8):
        body[index * 4:index * 4 + 4] = (eps.EPS_DATASET_START + 0x200 + index * 4).to_bytes(4, "little")
    payload = bytes(body)
    return payload + eps.crc16_xmodem(payload).to_bytes(2, "big")


class PQEPSImageTests(unittest.TestCase):
    def test_full_image_can_supply_all_three_regions(self):
        image = bytearray((index & 0xFF) for index in range(eps.EPS_IMAGE_SIZE))
        image[eps.EPS_DATASET_START:eps.EPS_DATASET_START + eps.EPS_BLOCK_SIZE] = dataset()
        for name, (start, end) in eps.FLASH_REGIONS.items():
            prepared = eps.prepare_image(bytes(image), start, end)
            self.assertEqual(prepared["metadata"]["selection"], name)
            self.assertEqual(prepared["region"], bytes(image[start:end + 1]))
            self.assertEqual(prepared["metadata"]["source_kind"], "full-firmware")

    def test_standalone_dataset_is_only_accepted_for_5e(self):
        data = dataset()
        prepared = eps.prepare_image(
            data, eps.EPS_DATASET_START,
            eps.EPS_DATASET_START + eps.EPS_BLOCK_SIZE - 1)
        self.assertEqual(prepared["region"], data)
        self.assertTrue(prepared["metadata"]["dataset_validation"]["valid"])
        for name in ("firmware", "configuration"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "only accepted"):
                eps.prepare_image(data, *eps.FLASH_REGIONS[name])

    def test_dataset_crc_and_blank_checks_fail_closed(self):
        bad = bytearray(dataset())
        bad[12] ^= 1
        with self.assertRaisesRegex(ValueError, "CRC-16/XMODEM mismatch"):
            eps.validate_dataset(bad)
        for value in (0x00, 0xFF):
            with self.assertRaisesRegex(ValueError, "blank"):
                eps.validate_dataset(bytes([value]) * eps.EPS_BLOCK_SIZE)
        config_like = bytearray(dataset())
        config_like[:32] = bytes(range(32))
        config_like[-2:] = eps.crc16_xmodem(config_like[:-2]).to_bytes(2, "big")
        with self.assertRaisesRegex(ValueError, "pointer table"):
            eps.validate_dataset(config_like)

    def test_arbitrary_partial_ranges_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "complete EPS flash region"):
            eps.prepare_image(bytes(eps.EPS_IMAGE_SIZE), 0x5E000, 0x5EFFE)

    def test_protocol_payloads_match_pq_eps_flasher(self):
        profile = eps.make_eps_profile(
            kwp_factory=lambda *args: None, prepare_image_fn=eps.prepare_image,
            device_factory=lambda channel: None, transport_factory=lambda *args, **kwargs: None,
            identify=lambda kwp, tp: {})
        metadata = {"checksum": 0x1234}
        self.assertEqual(
            profile.erase_payload(0x5E000, 0x5EFFF, metadata),
            bytes.fromhex("05e00005efff"))
        self.assertEqual(
            profile.checksum_payload(0x5E000, 0x5EFFF, metadata),
            bytes.fromhex("05e00005efff1234"))
        self.assertEqual(profile.commit_services, (0x82,))
        self.assertEqual(profile.programming_session, 0x85)

    def test_partial_flash_requires_live_revision_3000_or_newer(self):
        profile = eps.make_eps_profile(
            kwp_factory=lambda *args: None, prepare_image_fn=eps.prepare_image,
            device_factory=lambda channel: None, transport_factory=lambda *args, **kwargs: None,
            identify=lambda kwp, tp: {})
        partial = {"selection": "steer-dataset"}
        profile.validate_controller(
            {"software_part_number": "8J0909144", "sw_version": "3000"}, partial)
        for revision in ("2999", "", "3A01"):
            with self.subTest(revision=revision), self.assertRaisesRegex(
                    RuntimeError, "does not approve partial-region"):
                profile.validate_controller(
                    {"software_part_number": "8J0909144", "sw_version": revision}, partial)
        profile.validate_controller(
            {"software_part_number": "8J0909144", "sw_version": "2301"},
            {"selection": "firmware"})


class PQEPSDispatchTests(unittest.TestCase):
    def test_registry_enables_flash_and_experimental_readout(self):
        family = registry.get_family("pq-eps")
        self.assertTrue(family.supports("flash"))
        self.assertTrue(family.supports("identify"))
        self.assertTrue(family.supports("readout"))
        self.assertIs(registry.family_for_module("eps", operation="flash"), family)
        self.assertIs(registry.family_for_module("eps", operation="readout"), family)

    def test_cli_dry_run_validates_without_adapter_access(self):
        image = bytearray(eps.EPS_IMAGE_SIZE)
        image[eps.EPS_DATASET_START:eps.EPS_DATASET_START + eps.EPS_BLOCK_SIZE] = dataset()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "eps.bin"
            path.write_bytes(image)
            output = io.StringIO()
            with patch.object(runner, "open_adapter") as opened, contextlib.redirect_stdout(output):
                result = runner.main([
                    "--module", "eps", "--input", str(path), "--dry-run",
                    "--start", hex(eps.EPS_DATASET_START),
                    "--end", hex(eps.EPS_DATASET_START + eps.EPS_BLOCK_SIZE - 1),
                ])
        self.assertEqual(result, 0)
        opened.assert_not_called()
        self.assertIn('"selection": "steer-dataset"', output.getvalue())
        self.assertIn("No CAN traffic sent.", output.getvalue())

    def test_cli_eps_readout_dry_run_never_opens_adapter(self):
        output = io.StringIO()
        with patch.object(runner, "open_adapter") as opened, contextlib.redirect_stdout(output):
            result = runner.main([
                "--module", "eps", "--readout", "--dry-run",
                "--start", "0x5d000", "--end", "0x5dfff"])
        self.assertEqual(result, 0)
        opened.assert_not_called()
        self.assertIn('"firmware_writes": false', output.getvalue())
        self.assertIn('"method": "auto"', output.getvalue())


if __name__ == "__main__":
    unittest.main()
