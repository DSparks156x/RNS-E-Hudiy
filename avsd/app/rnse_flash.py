"""Check, rehearse and flash RNS-E sectors from the Pi: stage over SD, commit over CAN.

Port of the bench tools sd_flash.py and cowcan_flash.py. No ignition keep-alive here: in the car the bus is real.
Nothing writes flash except commit_multi, reached only after every check passed.
"""
import os
import re
import struct
import time
import zlib

from can_link import UnitError
from sd_link import LinkError, make_header

SECTOR = 0x20000
LOADER_LIMIT = 0x00400000
CHIP_SIZE = 0x04000000
MAX_SIDX = 0x1FF
MAX_TARGETS = 4
STAGE_BASE = 0xACE00000
FLASH_P2 = 0xA0000000

LOAD_BASE = 0x8F780000
LOAD_WINDOW = 0x20000
CHUNK = 248 * 512
STUB_SIZE = 0x1E0
STUB_RESULT = 0x8F720FC0
STUB_CODES = {1: 'running or stuck', 2: 'bad params', 3: 'ok', 4: 'CRC of the staged RAM differs'}

SDBOOT_BASE = 0x8F71F000
SDBOOT_STAMP = 0x8F71FDF0
SDBOOT_MAGIC = 0x53444231
SDBOOT_ARG = 0x8F720FD0
SDBOOT_RES = 0x8F720FE0
SDBOOT_SEQ = 0xBE
SDBOOT_LBA = 0x10000 + SDBOOT_SEQ * 256
RES_MAGIC = 0x52534252
CODE_JUMP = 8
BOOT_CODES = {1: 'bootstrap running or stuck', 2: 'bad header', 3: 'range check', 4: 'SD read failed', 5: 'image CRC bad',
              6: 'firmware bytes differ', 7: 'loaded, not started', 8: 'jumped to the program'}

TRAMP_BASE = 0x8F710000
TRAMP_SIZE = 0x40
TRAMP_SLOTS = 960
TCB159 = 0x8E8D7B6C
ENTRY_OFF = 0x20
DOOM_ENTRY = 0x80B06000
TASK_DORMANT = 0x10
DORMANT_WAIT_S = 20

TVA = 0x8F72F000
TVA_MAGIC = 0x54564131
TVA_OFF_WORD = 0x4F464621

BOOTSTATE = 0xB8000000
RESET_WAIT_S = 25
RESET_LIMIT_S = 120

STAT_BASE = 0x8F720100
STAT_MAGIC = 0x41565344
STAT_FIELDS = ['seq', 'sf_ok', 'hdr_bad', 'retry', 'expired', 'seq_mism', 'rd_calls', 'rd_err', 'rd_sect', 'rd_cnt_lo',
               'rd_cnt_max', 'v_dec', 'v_dec_err', 'v_crc_bad', 'v_drop', 'v_repeat', 'v_late', 'dec_max', 'dec_lo', 'dec_hi',
               'v_shown', 'tlv_ok', 'tlv_bad', 'a_crc_bad', 'a_in', 'a_under']
STAT_SHOWN = ['sf_ok', 'v_dec', 'v_shown', 'v_dec_err', 'v_crc_bad', 'a_crc_bad', 'a_under', 'rd_err']

FW_CHECKS = [
    (0x8062D654, '2fd62fe64f22d186'),   # Snd_opn
    (0x8062D6CC, '2fb62fc62fd62fe6'),   # Snd_dyD
    (0x8062D71A, '2fe64f22d1576e43'),   # Snd_stp
    (0x8062D742, '2fe64f22d14d6e43'),   # Snd_cls
    (0x80653598, '2f862f962fa62fb6'),   # sd_raw_read
    (0x804D04D8, '0002c8f08bd7e226'),   # dly_tsk
    (0x804D027C, '0002c8f08b74e201'),   # ext_tsk
]
FW_SDBOOT = [(0x8067D108, '4f22626366537ffc')]  # read core sdboot calls

# Decoder compatibility. The encoder sends R3; decoders up to this one reject every R3 frame.
OLD_DECODERS = {0x29D3E06A}
DECODER_SECTOR = 96
# r61 candidates carry this sector 53. The unit's own has the Doom knob fix.
REFUSED_IMAGES = {0x3F4BE504: 'an old sector 53 from an r61 candidate, without the Doom knob fix'}
B6_STATUS = {0: 'committing', 1: 'CRC mismatch', 2: 'range', 3: 'arm', 5: 'forbidden'}

SECTOR_NAME = re.compile(r'sector[_-]?(\d{1,3})', re.IGNORECASE)


class FlashError(Exception):
    pass


class Target:
    def __init__(self, sidx, image, name=''):
        self.sidx, self.image, self.name = sidx, image, name
        self.crc = zlib.crc32(image)


def sector_from_name(name):
    match = SECTOR_NAME.search(os.path.basename(name))
    return int(match.group(1)) if match else None


def image_problem(sidx, image):
    """Why this file can't go to this sector, or None."""
    if sidx is None:
        return 'The file name must say the sector, like sector_96.bin.'
    if len(image) != SECTOR:
        return 'A sector image is %d bytes. This one is %d.' % (SECTOR, len(image))
    if sidx * SECTOR < LOADER_LIMIT or (sidx + 1) * SECTOR > CHIP_SIZE or sidx > MAX_SIDX:
        return 'Sector %d is outside the area that can be flashed.' % sidx
    reason = REFUSED_IMAGES.get(zlib.crc32(image))
    return 'This is %s.' % reason if reason else None


def load_targets(paths):
    if not 1 <= len(paths) <= MAX_TARGETS:
        raise FlashError('Choose 1 to %d files.' % MAX_TARGETS)
    targets = []
    for path in paths:
        with open(path, 'rb') as f:
            image = f.read(SECTOR + 1)
        sidx = sector_from_name(path)
        problem = image_problem(sidx, image)
        if problem:
            raise FlashError('%s: %s' % (os.path.basename(path), problem))
        targets.append(Target(sidx, image, os.path.basename(path)))
    if len({t.sidx for t in targets}) != len(targets):
        raise FlashError('Two files name the same sector.')
    return targets


class Flasher:
    """unit: can_link.Unit. port: sd_link.TeensyPort. blobs: {'sdboot', 'tramp', 'sdstage'} bytes.
    slot_path keeps the launcher counter across runs. log is called with one line at a time."""

    def __init__(self, unit, port, blobs, slot_path, log, sleep=time.sleep, clock=time.monotonic, load_id=None):
        self.unit, self.port, self.blobs = unit, port, blobs
        self.slot_path, self.log, self.sleep, self.clock = slot_path, log, sleep, clock
        self.load_id = load_id or (lambda: int(time.time() * 1000) & 0x7FFFFFFF)

    # ---- identity
    def firmware_check(self):
        for addr, expected in FW_CHECKS:
            got = self.unit.read(addr, len(expected) // 2).hex()
            if got != expected:
                raise FlashError('Firmware bytes differ at %08X: %s, expected %s. Stopping.' % (addr, got, expected))

    def task_state(self):
        return struct.unpack('>H', self.unit.read(TCB159 + 4, 2))[0]

    def auto_start_off(self):
        """True when this unit has r61 auto start and it was on. It must stay off until restore_auto_start."""
        magic, off = struct.unpack('>2I', self.unit.read(TVA, 8))
        if magic != TVA_MAGIC:
            return False
        if off != TVA_OFF_WORD:
            self.unit.poke(TVA + 4, TVA_OFF_WORD)
            self.log('Auto start off for now.')
        return True

    def restore_auto_start(self):
        self.unit.poke(TVA + 4, 0)
        if self.unit.u32(TVA + 4) != 0:
            raise UnitError('auto start word did not change')
        self.log('Auto start back on.')

    def wait_dormant(self):
        end = self.clock() + DORMANT_WAIT_S
        while True:
            state = self.task_state()
            if state == TASK_DORMANT:
                return
            if self.clock() > end:
                raise FlashError('The RNS-E stream task is still running (%04X). Switch the RNS-E away from TV and try again.' % state)
            self.sleep(0.2)

    # ---- bootstrap
    def _boot_image(self):
        code = self.blobs['sdboot']
        code += bytes(-len(code) % 4)
        return code, struct.pack('>IIII', SDBOOT_MAGIC, zlib.crc32(code), len(code), 0)

    def _boot_resident(self):
        """Uploads the SD bootstrap over CAN if it isn't there, once per power-on. True = uploaded now."""
        code, stamp = self._boot_image()
        if self.unit.read(SDBOOT_STAMP, 16) == stamp:
            return False
        for addr, expected in FW_SDBOOT:
            if self.unit.read(addr, len(expected) // 2).hex() != expected:
                raise FlashError('Firmware bytes differ at %08X. Stopping.' % addr)
        self.log('Uploading the SD bootstrap over CAN (%d B).' % len(code))
        self.unit.poke(SDBOOT_STAMP, 0)
        self.unit.write_block(SDBOOT_BASE, code)
        self.unit.write_block(SDBOOT_STAMP, stamp)
        return True

    def _next_slot(self):
        try:
            with open(self.slot_path) as f:
                k = int(f.read().strip())
        except (OSError, ValueError):
            k = 0
        with open(self.slot_path, 'w') as f:
            f.write('%d\n' % ((k + 1) % TRAMP_SLOTS))
        return TRAMP_BASE + TRAMP_SIZE * k

    def _stub_image(self, load_id, off, chunk, rd, dlen):
        stub = self.blobs['sdstage']
        if len(stub) > STUB_SIZE or len(chunk) % 4:
            raise FlashError('bad stub or chunk size')
        return (stub + bytes(STUB_SIZE - len(stub)) +
                struct.pack('>5I', load_id, off, dlen or len(chunk), zlib.crc32(chunk), rd) + bytes(12) + chunk)

    def _run_stub(self, off, chunk, rd=0, dlen=0):
        """Stub + chunk through the Teensy, started as task 159. rd: CRC that flash address instead of copying the chunk."""
        state = self.task_state()
        if state != TASK_DORMANT:
            raise FlashError('Task 159 is not dormant (%04X).' % state)
        uploaded = self._boot_resident()
        load_id = self.load_id()
        img = self._stub_image(load_id, off, chunk, rd, dlen)
        header = make_header(load_id, LOAD_BASE, img, LOAD_BASE, LOAD_WINDOW, FW_CHECKS)
        self.port.put(SDBOOT_SEQ, header, img)
        entry = SDBOOT_BASE
        if uploaded:
            tramp = bytearray(self.blobs['tramp'])
            struct.pack_into('>III', tramp, 0x20, SDBOOT_BASE, SDBOOT_BASE + 0x1000, SDBOOT_BASE)
            entry = self._next_slot()
            self.unit.write_block(entry, bytes(tramp))
        self.unit.poke(SDBOOT_ARG, 1 + SDBOOT_LBA)
        self.unit.poke(TCB159 + ENTRY_OFF, entry)
        res = None
        try:
            self.unit.send([0xB8, 0x5A, 0, 0, 0, 0, 0, 0])
            end = self.clock() + 1.5
            while self.clock() < end:
                res = struct.unpack('>8I', self.unit.read(SDBOOT_RES, 32))
                if res[0] == RES_MAGIC and res[1] == load_id and res[2] >= 2:
                    break
                self.sleep(0.01)
        finally:
            self.unit.poke(TCB159 + ENTRY_OFF, DOOM_ENTRY)
        if not (res and res[1] == load_id and res[2] == CODE_JUMP):
            raise FlashError('Bootstrap: %s' % (BOOT_CODES.get(res[2], res[2]) if res else 'no result'))
        end = self.clock() + 3
        while True:
            rid, code, crc, n = struct.unpack('>4I', self.unit.read(STUB_RESULT, 16))
            if rid == load_id and code >= 2:
                break
            if self.clock() > end:
                raise FlashError('The stub gave no result.')
            self.sleep(0.02)
        return code, crc, n

    def _wait_stub_end(self):
        end = self.clock() + 2
        while self.task_state() != TASK_DORMANT:
            if self.clock() > end:
                raise FlashError('Task 159 did not end.')
            self.sleep(0.02)

    def live_crc(self, sidx):
        code, crc, n = self._run_stub(0, bytes(512), rd=FLASH_P2 + sidx * SECTOR, dlen=SECTOR)
        if code != 3 or n != SECTOR:
            raise FlashError('Flash CRC of sector %d: %s' % (sidx, STUB_CODES.get(code, code)))
        self._wait_stub_end()
        return crc

    def _stage(self, targets):
        staged = b''.join(t.image for t in targets)
        for off in range(0, len(staged), CHUNK):
            chunk = staged[off:off + CHUNK]
            code, crc, n = self._run_stub(off, chunk)
            if code != 3 or crc != zlib.crc32(chunk) or n != len(chunk):
                raise FlashError('Staging at +%X: %s, CRC %08X, expected %08X.' % (off, STUB_CODES.get(code, code), crc, zlib.crc32(chunk)))
            self._wait_stub_end()
        self.log('Staged %d B in RAM. Each chunk CRC-checked on the unit.' % len(staged))
        return staged

    def _stage_end(self, n):
        """B3 END: the unit CRCs the whole staged region and records its length. It only answers, so a retry is safe."""
        frame = bytes((0xB3, 0xFF, 0xFF, n >> 16 & 255, n >> 8 & 255, n & 255, 0, 0))
        bus = self.unit.bus
        for _ in range(6):
            bus.drain()
            bus.send(frame)
            end = self.clock() + 1.0
            while self.clock() < end:
                m = bus.recv(end - self.clock())
                if m and len(m[1]) == 8 and m[1][0] == 0x83:
                    return m[1][5], int.from_bytes(m[1][1:5], 'big')
        raise FlashError('No answer to B3 END.')

    def _verify_staged(self, targets, staged):
        status, unit_crc = self._stage_end(len(staged))
        if status != 0 or unit_crc != zlib.crc32(staged):
            raise FlashError('Staged RAM is wrong: status %d, CRC %08X, expected %08X.' % (status, unit_crc, zlib.crc32(staged)))
        for i, t in enumerate(targets):
            for off in (0, 0x7FC0, 0x10000, SECTOR - 48):
                if self.unit.read(STAGE_BASE + i * SECTOR + off, 48) != t.image[off:off + 48]:
                    raise FlashError('Staged RAM differs: sector %d +%05X.' % (t.sidx, off))
        self.log('Staged RAM verified: whole CRC and samples.')

    def _commit(self, targets):
        """B7 for each target, then B6. Returns the ack status, or None when the unit is already resetting."""
        bus = self.unit.bus
        for i, t in enumerate(targets):
            bus.send(bytes((0xB7, i, t.sidx >> 8 & 255, t.sidx & 255)) + struct.pack('>I', t.crc))
        bus.drain()
        bus.send(bytes((0xB6, len(targets), 0, 0, 0, 0, 0, 0x5A)))
        end = self.clock() + 3.0
        while self.clock() < end:
            m = bus.recv(end - self.clock())
            if m and len(m[1]) == 8 and m[1][0] == 0x84:
                return m[1][1]
        return None

    def bootstate(self):
        raw = self.unit.read(BOOTSTATE, 0x20)
        restart = struct.unpack('>h', raw[0x1A:0x1C])[0]
        return restart

    def _wait_reset(self):
        self.log('Waiting for the unit to reset.')
        self.sleep(RESET_WAIT_S)
        end = self.clock() + RESET_LIMIT_S
        while True:
            try:
                return self.bootstate()
            except UnitError:
                if self.clock() > end:
                    raise FlashError('No answer from the unit %d s after the flash. If it stays dark, reinstall from the disc.' % (RESET_WAIT_S + RESET_LIMIT_S))
                self.sleep(2)

    # ---- operations. The caller has stopped the chain and turned auto start off.
    def check(self, targets):
        """Returns {sidx: crc} and logs same or different per sector."""
        live = {}
        for t in targets:
            live[t.sidx] = self.live_crc(t.sidx)
            same = live[t.sidx] == t.crc
            self.log('Sector %d: %s. Live CRC %08X, file %08X.' % (t.sidx, 'same' if same else 'DIFFERENT', live[t.sidx], t.crc))
        return live

    def rehearse(self, targets):
        """RAM only. Everything a flash does before B7."""
        staged = self._stage(targets)
        self._verify_staged(targets, staged)
        self.log('Staged, not flashed. Nothing was sent to the flash path.')

    def flash(self, targets):
        """Returns {sidx: crc} of the flash afterwards. Raises if any of it isn't the file."""
        staged = self._stage(targets)
        self._verify_staged(targets, staged)
        self.log('Flashing sector %s. Erase, program, one reset.' % ', '.join(str(t.sidx) for t in targets))
        status = self._commit(targets)
        if status is not None and status != 0:
            raise FlashError('The unit refused the commit: %s. Flash was not touched.' % B6_STATUS.get(status, status))
        restart = self._wait_reset()
        self.log('Unit answered. Restart count %d.' % restart)
        if restart != 0:
            raise FlashError('Restart count is %d, must be 0.' % restart)
        live = self.check(targets)
        if any(live[t.sidx] != t.crc for t in targets):
            raise FlashError('The live CRC does not match the file after flashing.')
        self.log('Flash done and verified.')
        return live


def read_unit_counters(unit):
    """The unit's own decode and underrun counters. CAN reads stall the unit, so this runs when asked, never on a timer."""
    words_needed = 8 + len(STAT_FIELDS)
    raw = unit.read(STAT_BASE, words_needed * 4)
    words = struct.unpack('>%dI' % words_needed, raw)
    if words[0] != STAT_MAGIC:
        return {'valid': False, 'counters': {}}
    fields = dict(zip(STAT_FIELDS, words[8:]))
    return {'valid': True, 'counters': {name: fields[name] for name in STAT_SHOWN}}


__all__ = ['Flasher', 'FlashError', 'Target', 'LinkError', 'UnitError', 'load_targets', 'image_problem', 'sector_from_name', 'read_unit_counters', 'OLD_DECODERS', 'DECODER_SECTOR']
