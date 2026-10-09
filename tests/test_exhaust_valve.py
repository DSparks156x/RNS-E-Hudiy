"""Offline SB2209 contract tests; no CAN hardware is opened."""
import ast
from contextlib import nullcontext
import io
import json
import logging
from pathlib import Path
import os
import struct
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
import zlib
import zipfile

from flasher.exhaust_valve import (
    command, control, chunk, load_bundle, validate_upload, reserve_generation,
    ExhaustValveUpdater,
)

ROOT = Path(__file__).resolve().parents[1]


def write_bundle(directory, length=800):
    images = []
    for slot in (0, 1):
        data = bytearray(length)
        struct.pack_into('<II', data, 256, 0x20042000,
                         (0x10011000 + slot * 0x40000 + 264) | 1)
        name = f'sb2209_app_{slot}.bin'
        (directory / name).write_bytes(data)
        images.append({'slot': slot, 'path': name, 'length': length, 'crc32': zlib.crc32(data)})
    manifest = directory / 'can-update.json'
    manifest.write_text(json.dumps({'format': 'exhaust-native-can-v1', 'generation': 1, 'images': images}))
    return manifest


def definitions(file, names, namespace):
    tree = ast.parse((ROOT / file).read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and node.name in names]
    for node in nodes:
        node.decorator_list = []
    exec(compile(ast.Module(body=nodes, type_ignores=[]), file, 'exec'), namespace)
    return namespace


class ExhaustProtocolTests(unittest.TestCase):
    def test_zip_bundle_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root)
            archive_path = root / 'update.zip'
            with zipfile.ZipFile(archive_path, 'w') as archive:
                for name in ('can-update.json', 'sb2209_app_0.bin', 'sb2209_app_1.bin'):
                    archive.write(root / name, name)
            validated = validate_upload(archive_path)
            self.assertEqual(len(validated['files']), 3)
            self.assertEqual(validated['artifact_id'], load_bundle(root / 'can-update.json')[2])
            with zipfile.ZipFile(archive_path, 'a') as archive:
                archive.writestr('../unexpected.bin', b'bad')
            with self.assertRaises(ValueError):
                validate_upload(archive_path)

    def test_endpoint_namespace_tx_and_chunk_endianness(self):
        self.assertEqual(command(100, 1).hex(), 'c33c030100006400')
        self.assertEqual(command(0, 2).hex(), 'c33c030200000000')
        self.assertEqual(control(0x50, 0xE7C0B007).hex(), 'c33c500007b0c0e7')
        self.assertEqual(chunk(0x1234, b'\xab').hex(), 'c33c801234abffff')
        for invalid in (-1, 101, True, 50.5, '100', None):
            with self.assertRaises(ValueError):
                command(invalid, 1)

    def test_bundle_crc_vectors_companions_and_path_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_bundle(root)
            doc, images, artifact = load_bundle(path)
            self.assertEqual([slot for slot, _ in images], [0, 1])
            self.assertEqual(len(artifact), 64)
            validate_upload(path)
            validate_upload(root / doc['images'][0]['path'])
            image_path = root / doc['images'][0]['path']
            data = bytearray(image_path.read_bytes())
            data[-1] = 7
            image_path.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'CRC'):
                load_bundle(path)
            path = write_bundle(root)
            doc = json.loads(path.read_text())
            doc['images'][0]['path'] = '../outside.bin'
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'basenames'):
                load_bundle(path)
            path = write_bundle(root)
            doc = json.loads(path.read_text())
            doc['images'][1]['slot'] = 0
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'both slots'):
                load_bundle(path)
            path = write_bundle(root)
            doc = json.loads(path.read_text())
            image_path = root / doc['images'][0]['path']
            data = bytearray(image_path.read_bytes())
            struct.pack_into('<I', data, 260, 0x10051001)  # Slot B vector in A image.
            image_path.write_bytes(data)
            doc['images'][0]['crc32'] = zlib.crc32(data)
            path.write_text(json.dumps(doc))
            with self.assertRaisesRegex(ValueError, 'vectors'):
                load_bundle(path)

    def test_generation_reserved_before_transfer_and_reused_only_for_same_code(self):
        with tempfile.TemporaryDirectory() as directory:
            journal = Path(directory) / 'generation.json'
            self.assertEqual(reserve_generation(journal, 'a', 1), 17)
            self.assertEqual(reserve_generation(journal, 'a', 1), 17)
            self.assertEqual(reserve_generation(journal, 'b', 1), 18)
            self.assertEqual(reserve_generation(journal, 'a', 1), 19)
            self.assertEqual(reserve_generation(journal, 'c', 22), 22)
            journal.write_text('{corrupt')
            with self.assertRaises(ValueError):
                reserve_generation(journal, 'd', 1)

    def test_blind_transfer_repeats_manifest_and_both_slots_without_reentering(self):
        with tempfile.TemporaryDirectory() as directory:
            _, images, _ = load_bundle(write_bundle(Path(directory)))
            device = Mock()
            sleeps = []
            updater = ExhaustValveUpdater(device, sleep=sleeps.append)
            result = updater.run(images, 17)
            frames = [call.args[1] for call in device.can_send.call_args_list]
            self.assertTrue(all(call.args[0] == 0x67A for call in device.can_send.call_args_list))
            self.assertTrue(all(len(frame) == 8 and frame[:2] == b'\xc3\x3c' for frame in frames))
            self.assertEqual(sum(frame[2] == 0x50 for frame in frames), 3)
            self.assertEqual(sum(frame[2] == 0x55 for frame in frames), 6)
            self.assertEqual(sum(frame[2] == 0x51 for frame in frames), 12)
            self.assertEqual([int.from_bytes(frame[4:], 'little') for frame in frames if frame[2] == 0x52],
                             [0, 0, 1, 1] * 3)
            self.assertEqual(sleeps.count(0.002), len(frames))
            self.assertEqual(sleeps.count(4), 6)
            self.assertEqual(result['status'], 'sent_unconfirmed')
            self.assertFalse(result['boot_verified'])

    def test_cancel_stops_without_committing_partial_section(self):
        device = Mock()
        updater = ExhaustValveUpdater(device, sleep=lambda delay: None)
        def send(can_id, frame):
            if frame[2] == 0x80:
                updater.cancel()
        device.can_send.side_effect = send
        with self.assertRaisesRegex(RuntimeError, 'cancelled'):
            updater.run([(0, bytes(800)), (1, bytes(800))], 17)
        self.assertFalse(any(call.args[1][2] == 0x55 for call in device.can_send.call_args_list))


class ValveManagerTests(unittest.TestCase):
    def manager(self, directory):
        import typing
        config = {'exhaust_valve': {'intent_file': str(Path(directory) / 'intent.json')},
                  'haldex': {'default_mode': 0}}
        zmq = types.SimpleNamespace(Context=Mock, PUSH=1, LINGER=2, SNDTIMEO=3)
        namespace = definitions('rns-e_can/haldex_manager.py', {'HaldexManager'}, {
            'Optional': typing.Optional, 'Dict': typing.Dict, 'Any': typing.Any,
            'os': os, 'json': json, 'time': types.SimpleNamespace(sleep=lambda delay: None),
            'threading': threading, 'zmq': zmq, 'logger': logging.getLogger('test'),
            'MODE_STOCK': 0, 'MODE_NAMES': {0: 'Stock'},
            'CAN_ID_MODE_CMD': 0x67A, 'valve_command': command, 'flashing_mode_enabled': lambda: False,
        })
        cls = namespace['HaldexManager']
        with patch.object(cls, '_load_config', return_value=config), patch.object(cls, '_init_desired_mode'):
            return cls(), namespace

    def test_unknown_then_toggle_and_restore_intent_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            manager, _ = self.manager(directory)
            self.assertIsNone(manager.get_valve_status()['target'])
            self.assertFalse(manager.context.socket.called)
            self.assertEqual(manager.set_valve()['target'], 100)
            calls = manager.context.socket.return_value.send_multipart.call_args_list
            self.assertEqual(len(calls), 3)
            self.assertTrue(all(call.args[0] == [b'1658', b'c33c030100006400'] for call in calls))
            self.assertEqual(manager.set_valve()['target'], 0)
            manager, _ = self.manager(directory)
            self.assertEqual(manager.get_valve_status()['target'], 0)
            self.assertFalse(manager.context.socket.called)

    def test_commands_rejected_during_flash_or_diagnostic_ownership(self):
        with tempfile.TemporaryDirectory() as directory:
            manager, namespace = self.manager(directory)
            manager.inhibited = True
            with self.assertRaises(RuntimeError):
                manager.set_valve(100)
            manager.inhibited = False
            namespace['flashing_mode_enabled'] = lambda: True
            with self.assertRaises(RuntimeError):
                manager.set_valve(100)
            self.assertFalse(manager.context.socket.called)


class ValveUpdateWorkflowTests(unittest.TestCase):
    def namespace(self, root):
        thread = Mock()
        thread.start.side_effect = lambda: thread.target()
        def make_thread(target, daemon):
            thread.target = target
            return thread
        operation_log = Mock(path='offline.log')
        owner = Mock()
        namespace = definitions('hudiy_dataview/app.py',
            {'exhaust_artifacts', 'handle_start_exhaust_valve_update'}, {
                'os': os, 'load_bundle': load_bundle, 'reserve_generation': reserve_generation,
                '_cfg': {'exhaust_valve': {'firmware_dir': str(root), 'generation_file': str(root / 'generation.json')}},
                'emit': Mock(), 'socketio': Mock(), 'logger': logging.getLogger('test'),
                'threading': types.SimpleNamespace(Thread=make_thread),
                '_flasher_lock': threading.Lock(), '_flasher_running': False,
                '_exhaust_update_running': False, '_exhaust_update_result': None,
                'DiagnosticOwnership': Mock(return_value=owner),
                'FlashOperationLog': Mock(return_value=operation_log),
                'flashing_operation': nullcontext, 'set_flashing_mode': Mock(),
                'ExhaustValveUpdater': Mock(),
            })
        return namespace, owner, operation_log

    def test_dry_run_never_owns_vehicle_or_opens_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root)
            namespace, owner, log = self.namespace(root)
            artifact_id = next(iter(namespace['exhaust_artifacts']()))
            namespace['handle_start_exhaust_valve_update']({'artifact_id': artifact_id, 'dry_run': True})
            owner.acquire.assert_not_called()
            namespace['set_flashing_mode'].assert_not_called()
            namespace['ExhaustValveUpdater'].assert_not_called()
            self.assertFalse(namespace['_flasher_running'])
            self.assertFalse(namespace['_exhaust_update_running'])
            self.assertEqual(namespace['_exhaust_update_result']['status'], 'dry_run')
            self.assertFalse((root / 'generation.json').exists())
            log.close.assert_called_once()

    def test_live_cleanup_restores_senders_even_when_device_close_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root)
            namespace, owner, log = self.namespace(root)
            artifact_id = next(iter(namespace['exhaust_artifacts']()))
            device = Mock()
            device.close.side_effect = RuntimeError('close failed')
            namespace['ExhaustValveUpdater'].return_value.run.return_value = {
                'status': 'sent_unconfirmed', 'message': 'Sent / unconfirmed'}
            with patch('flasher.socketcan_device.SocketCANDevice', return_value=device), \
                    patch('flasher.traffic.flashing_mode_enabled', return_value=False):
                namespace['handle_start_exhaust_valve_update']({'artifact_id': artifact_id})
            owner.acquire.assert_called_once()
            owner.release.assert_called_once()
            self.assertEqual([call.args for call in namespace['set_flashing_mode'].call_args_list], [(True,), (False,)])
            self.assertEqual(json.loads((root / 'generation.json').read_text())['generation'], 17)
            self.assertFalse(namespace['_flasher_running'])
            self.assertFalse(namespace['_exhaust_update_running'])
            self.assertIsNone(namespace['_active_flasher'])
            log.close.assert_called_once()

    def test_active_other_module_and_invalid_artifacts_do_not_start_a_transfer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_bundle(root)
            namespace, owner, _ = self.namespace(root)
            artifact_id = next(iter(namespace['exhaust_artifacts']()))
            namespace['_flasher_running'] = True
            namespace['handle_start_exhaust_valve_update']({'artifact_id': artifact_id})
            namespace['emit'].assert_called_with('exhaust_valve_error', {
                'message': 'A flash or readout operation is already in progress', 'stopped': False})
            owner.acquire.assert_not_called()
            namespace['_flasher_running'] = False
            namespace['handle_start_exhaust_valve_update']({'artifact_id': 'missing'})
            owner.acquire.assert_not_called()
            namespace['ExhaustValveUpdater'].assert_not_called()


try:
    from flask import Flask
except ImportError:
    Flask = None


@unittest.skipIf(Flask is None, 'Flask is installed by the Pi installer')
class ValvePortalTests(unittest.TestCase):
    def test_two_zip_versions_install_without_filename_collisions_and_failed_zip_adds_nothing(self):
        from hudiy_dataview.file_portal import register_file_portal
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'source'
            source.mkdir()
            firmware = root / 'firmware'
            app = Flask(__name__)
            register_file_portal(app, {'exhaust_valve': {'firmware_dir': str(firmware)}},
                                 {'exhaust-valve': validate_upload})
            client = app.test_client()
            for length in (800, 900):
                path = write_bundle(source, length=length)
                content = io.BytesIO()
                with zipfile.ZipFile(content, 'w') as archive:
                    for name in ('can-update.json', 'sb2209_app_0.bin', 'sb2209_app_1.bin'):
                        archive.write(source / name, name)
                content.seek(0)
                response = client.post('/api/files/upload/firmware_exhaust-valve',
                                       data={'file': (content, 'update.zip')})
                self.assertEqual(response.status_code, 201, response.json)
                self.assertTrue((firmware / load_bundle(path)[2] / 'can-update.json').is_file())
            self.assertEqual(len(list(firmware.iterdir())), 2)
            response = client.post('/api/files/upload/firmware_exhaust-valve',
                                   data={'file': (io.BytesIO(b'invalid'), 'bad.zip')})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(len(list(firmware.iterdir())), 2)


if __name__ == '__main__':
    unittest.main()
