"""SB2209 native A/B updates over the one-way vehicle CAN route.

The controller restores its own saved target; this module never enables a
reply ID, arms the motor, or claims that transmitted firmware booted.
"""
import hashlib
import json
import os
from pathlib import Path
import struct
import threading
import time
import zlib
import zipfile
import tempfile

CAN_ID = 0x67A
MAGIC = 0xE7C0B007


def command(position, tx):
    if type(position) is not int or not 0 <= position <= 100:
        raise ValueError('Valve target must be an integer from 0 to 100')
    return struct.pack('<BBBBHH', 0xC3, 0x3C, 0x03, tx & 255, 0, position)


def control(op, value, tx=0):
    return bytes((0xC3, 0x3C, op, tx & 255)) + struct.pack('<I', value)


def chunk(index, data):
    return b'\xc3\x3c\x80' + struct.pack('>H', index) + data.ljust(3, b'\xff')


def validate_vectors(data, slot):
    if not 264 <= len(data) <= 131072:
        raise ValueError('Native slot image must be 264–131072 bytes')
    sp, pc = struct.unpack_from('<II', data, 256)
    origin = 0x10011000 + slot * 0x40000
    if not (0x20000000 <= sp <= 0x20042000 and sp % 8 == 0 and pc & 1
            and origin + 256 <= (pc & ~1) < origin + len(data)):
        raise ValueError('Invalid native slot image vectors')


def manifest_document(path):
    try:
        doc = json.loads(Path(path).read_text(encoding='utf-8'))
        if doc['format'] != 'exhaust-native-can-v1':
            raise ValueError('Unknown valve bundle format')
        if type(doc.get('generation')) is not int or not 1 <= doc['generation'] <= 0xFFFFFFFF:
            raise ValueError('Invalid bundle generation')
        images = doc['images']
        if not isinstance(images, list) or len(images) != 2:
            raise ValueError('Bundle must contain both slots exactly once')
        slots = []
        for item in images:
            slot, name = item['slot'], item['path']
            if type(slot) is not int or slot not in (0, 1):
                raise ValueError('Invalid slot')
            slots.append(slot)
            if (not isinstance(name, str) or not name.endswith('.bin')
                    or name != os.path.basename(name) or any(c in name for c in '/\\:')
                    or name.startswith('.')):
                raise ValueError('Images must use local .bin basenames')
            if type(item['length']) is not int or not 264 <= item['length'] <= 131072:
                raise ValueError('Invalid image length')
            if type(item['crc32']) is not int or not 0 <= item['crc32'] <= 0xFFFFFFFF:
                raise ValueError('Invalid image CRC32')
        if sorted(slots) != [0, 1] or images[0]['path'] == images[1]['path']:
            raise ValueError('Bundle must contain distinct images for both slots')
        return doc
    except (KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError('Malformed valve update manifest') from error


def validate_upload(path):
    if str(path).lower().endswith('.zip'):
        try:
            with zipfile.ZipFile(path) as archive:
                entries = archive.infolist()
                names = [entry.filename for entry in entries]
                if (len(entries) != 3 or len(set(names)) != 3 or 'can-update.json' not in names
                        or sum(entry.file_size for entry in entries) > 300000
                        or any(name != os.path.basename(name) or any(c in name for c in '/\\:')
                               or name.startswith('.') for name in names)):
                    raise ValueError('ZIP must contain can-update.json and both slot images at its root')
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    for name in names:
                        (root / name).write_bytes(archive.read(name))
                    doc, images, artifact_id = load_bundle(root / 'can-update.json')
                    if set(names) != {'can-update.json', *(item['path'] for item in doc['images'])}:
                        raise ValueError('ZIP files do not match the manifest')
                    return {'artifact_id': artifact_id, 'files': {
                        name: (root / name).read_bytes() for name in names}}
        except zipfile.BadZipFile as error:
            raise ValueError('Invalid valve bundle ZIP') from error
    if str(path).lower().endswith('.json'):
        return manifest_document(path)  # Companions may be uploaded afterward.
    data = Path(path).read_bytes()
    for slot in (0, 1):
        try:
            validate_vectors(data, slot)
            return {'slot': slot}
        except ValueError:
            pass
    raise ValueError('Expected a native SB2209 slot .bin image')


def load_bundle(path):
    path = Path(path)
    doc = manifest_document(path)
    images = []
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    for item in sorted(doc['images'], key=lambda image: image['slot']):
        image_path = path.parent / item['path']
        if image_path.is_symlink():
            raise ValueError('Symlink firmware images are not allowed')
        data = image_path.read_bytes()
        if len(data) != item['length'] or zlib.crc32(data) != item['crc32']:
            raise ValueError('Slot length/CRC mismatch')
        validate_vectors(data, item['slot'])
        digest.update(data)
        images.append((item['slot'], data))
    return doc, images, digest.hexdigest()


def reserve_generation(path, artifact_id, requested, installed_floor=16):
    """Persist before ENTER; identical interrupted/sent bundles reuse generation."""
    path = Path(path)
    state = json.loads(path.read_text()) if path.exists() else {}
    floor = max(int(installed_floor), int(state.get('generation', 0)))
    if state.get('artifact_id') == artifact_id and floor == state.get('generation'):
        return floor
    generation = max(floor + 1, requested)
    if not 1 <= generation <= 0xFFFFFFFF:
        raise ValueError('Deployment generation exhausted')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump({'generation': generation, 'artifact_id': artifact_id}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if hasattr(os, 'O_DIRECTORY'):
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    return generation


class ExhaustValveUpdater:
    def __init__(self, device, progress=None, sleep=time.sleep):
        self.device = device
        self.progress = progress or (lambda *args: None)
        self.sleep = sleep
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def send(self, frame):
        if self.cancelled.is_set():
            raise RuntimeError('Valve update cancelled; receipt and boot remain unconfirmed')
        self.device.can_send(CAN_ID, frame)
        self.sleep(0.002)

    def run(self, images, generation, passes=3):
        total = passes * sum((len(data) + 2) // 3 for _, data in images)
        sent = 0
        self.progress(0, 'Entering resident loader')
        for _ in range(3):
            self.send(control(0x50, MAGIC))
            self.sleep(0.25)
        self.sleep(1)
        for pass_index in range(passes):
            for slot, data in images:
                manifest = [(0x51, generation), (0x52, slot),
                            (0x53, len(data)), (0x54, zlib.crc32(data))]
                for index, offset in enumerate(range(0, len(data), 3)):
                    if index % 256 == 0:
                        for op, value in manifest:
                            self.send(control(op, value))
                    self.send(chunk(index, data[offset:offset + 3]))
                    sent += 1
                    if index % 256 == 0:
                        self.progress(100 * sent / total,
                                      f'Pass {pass_index + 1}/{passes}, slot {"AB"[slot]}')
                self.send(control(0x55, generation))
                self.sleep(4)
        self.progress(100, 'Sent / unconfirmed')
        return {'status': 'sent_unconfirmed', 'generation': generation,
                'boot_verified': False, 'message': 'Sent / unconfirmed: no vehicle return route'}
