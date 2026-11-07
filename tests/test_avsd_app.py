"""A/V over SD app: settings, status parsing, and the flash sequence against a simulated RNS-E."""
import json
import os
import re
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'avsd' / 'app'))

import can_link
import chain as chain_module
import operations
import rnse_flash
import sd_link
import settings_store

BLOBS = {'sdboot': bytes(range(256)) * 3 + b'\x01\x02\x03\x04', 'tramp': bytes(64), 'sdstage': bytes(348)}
LOAD_ID = 0x1234567
SECTOR_96 = bytes((i * 7) & 255 for i in range(rnse_flash.SECTOR))


class FakeUnit:
    """Answers B1, stores B9, and plays the stub and commit results the real unit would."""

    def __init__(self, staged_ok=True, b6_status=0, restart=0, fw_good=True, tva=True, live=None):
        self.ram = {}
        self.frames = []
        self.replies = []
        self.staged_ok, self.b6_status, self.restart = staged_ok, b6_status, restart
        self.fw_good = fw_good
        self.committed = None
        self.flash = dict(live or {})
        self.staged = b''
        self.b7 = {}
        for addr, value in rnse_flash.FW_CHECKS + rnse_flash.FW_SDBOOT:
            self.store(addr, bytes.fromhex(value))
        if not fw_good:
            self.store(rnse_flash.FW_CHECKS[0][0], bytes(8))
        self.store(rnse_flash.TCB159 + 4, struct.pack('>H', rnse_flash.TASK_DORMANT))
        if tva:
            self.store(rnse_flash.TVA, struct.pack('>2I', rnse_flash.TVA_MAGIC, 0))
        self.store(rnse_flash.BOOTSTATE + 0x1A, struct.pack('>h', 99))

    def store(self, addr, data):
        for i, b in enumerate(data):
            self.ram[addr + i] = b

    def fetch(self, addr, n):
        return bytes(self.ram.get(addr + i, 0) for i in range(n))

    # Bus interface
    def drain(self):
        self.replies.clear()

    def close(self):
        pass

    def recv(self, timeout):
        return (can_link.REPLY_ID, self.replies.pop(0)) if self.replies else None

    def send(self, frame):
        frame = bytes(frame)
        self.frames.append(frame)
        op = frame[0]
        if op == 0xB1:
            addr = struct.unpack('>I', frame[1:5])[0]
            n = frame[5]
            nf = (n + 5) // 6
            self.replies.append(bytes((0x80, 0)) + frame[1:5] + bytes((n, nf)))
            data = self.fetch(addr, n).ljust(nf * 6, b'\0')
            for s in range(nf):
                chunk = data[s * 6:s * 6 + 6]
                self.replies.append(bytes((0x81 + s,)) + chunk + bytes((sum(chunk) & 255,)))
        elif op == 0xB9:
            i = int.from_bytes(frame[1:4], 'big')
            self.store(can_link.RAM_LOW + i * 4, frame[4:8])
        elif op == 0xB3:
            n = int.from_bytes(frame[3:6], 'big')
            crc = zlib.crc32(self.staged[:n]) if self.staged_ok else 0xBAD
            self.replies.append(bytes((0x83,)) + struct.pack('>I', crc) + bytes((0, 0, 0)))
        elif op == 0xB7:
            self.b7[frame[1]] = (int.from_bytes(frame[2:4], 'big'), int.from_bytes(frame[4:8], 'big'))
        elif op == 0xB6:
            self.replies.append(bytes((0x84, self.b6_status, 0, frame[1], frame[1], 0, 0, 0)))
            if self.b6_status == 0:
                self.committed = dict(self.b7)
                for slot, (sidx, crc) in self.b7.items():
                    self.flash[sidx] = crc
                self.store(rnse_flash.BOOTSTATE + 0x1A, struct.pack('>h', self.restart))
                self.store(rnse_flash.BOOTSTATE, bytes(4))
        elif op == 0xB8:
            self._bootstrap_ran()

    def _bootstrap_ran(self):
        self.store(rnse_flash.SDBOOT_RES, struct.pack('>8I', rnse_flash.RES_MAGIC, LOAD_ID, rnse_flash.CODE_JUMP, 0, 0, 0, 0, 0))
        off, chunk, rd = self.pending
        if rd:
            sidx = (rd - rnse_flash.FLASH_P2) // rnse_flash.SECTOR
            self.store(rnse_flash.STUB_RESULT, struct.pack('>4I', LOAD_ID, 3, self.flash.get(sidx, 0), rnse_flash.SECTOR))
            return
        self.staged = self.staged[:off] + chunk
        self.store(rnse_flash.STAGE_BASE, self.staged)
        self.store(rnse_flash.STUB_RESULT, struct.pack('>4I', LOAD_ID, 3, zlib.crc32(chunk), len(chunk)))


class FakePort:
    def __init__(self, unit):
        self.unit = unit
        self.closed = False

    def put(self, seq, header, image):
        _, off, dlen, _, rd = struct.unpack('>5I', image[rnse_flash.STUB_SIZE:rnse_flash.STUB_SIZE + 20])
        self.unit.pending = (off, image[rnse_flash.STUB_SIZE + 32:], rd)

    def close(self):
        self.closed = True


def flasher(unit, slot='/dev/null', lines=None):
    bus_unit = can_link.Unit(unit, sleep=lambda s: None)
    port = FakePort(unit)
    return rnse_flash.Flasher(bus_unit, port, BLOBS, slot, (lines if lines is not None else []).append,
                              sleep=lambda s: None, load_id=lambda: LOAD_ID)


class FrameTests(unittest.TestCase):
    def test_off_word_write_frame(self):
        fake = FakeUnit()
        can_link.Unit(fake, sleep=lambda s: None).poke(0x8F72F004, 0x4F464621)
        self.assertEqual(fake.frames[-1], bytes.fromhex('B9DCBC014F464621'))

    def test_read_ignores_a_reply_for_another_address(self):
        fake = FakeUnit()
        fake.store(0x8F720000, b'\x11\x22\x33\x44')
        real_send = fake.send

        def send(frame):
            real_send(frame)
            if frame[0] == 0xB1:
                fake.replies.insert(0, bytes((0x80, 0, 0x80, 0, 0, 0, 4, 1)))
                fake.replies.insert(1, bytes((0x81, 9, 9, 9, 9, 0, 0, 36)))
        fake.send = send
        self.assertEqual(can_link.Unit(fake, sleep=lambda s: None).read(0x8F720000, 4), b'\x11\x22\x33\x44')

    def test_poke_refuses_outside_ram(self):
        with self.assertRaises(ValueError):
            can_link.Unit(FakeUnit(), sleep=lambda s: None).poke(0x80000000, 0)


class CanStateTests(unittest.TestCase):
    def run_ip(self, flags, ctrl):
        class Out:
            returncode = 0
            stdout = json.dumps([{'flags': flags, 'linkinfo': {'info_data': {'ctrlmode': ctrl}}}])
        return can_link.can_state(run=lambda *a, **k: Out)

    def test_listen_only_means_turn_the_ignition_on(self):
        state = self.run_ip(['UP', 'LOWER_UP'], ['LISTEN-ONLY'])
        self.assertTrue(state['listen_only'])
        self.assertIn('ignition', can_link.not_ready_reason(state))

    def test_normal_mode_is_ready(self):
        self.assertIsNone(can_link.not_ready_reason(self.run_ip(['UP'], [])))

    def test_down_is_not_ready(self):
        self.assertIn('not up', can_link.not_ready_reason(self.run_ip([], [])))


class ImageRuleTests(unittest.TestCase):
    def test_name_gives_the_sector(self):
        self.assertEqual(rnse_flash.sector_from_name('/x/r59_sector_44.bin'), 44)
        self.assertEqual(rnse_flash.sector_from_name('sector-96.bin'), 96)
        self.assertIsNone(rnse_flash.sector_from_name('firmware.bin'))

    def test_refusals(self):
        good = bytes(rnse_flash.SECTOR)
        self.assertIsNone(rnse_flash.image_problem(96, good))
        self.assertIn('name', rnse_flash.image_problem(None, good))
        self.assertIn('bytes', rnse_flash.image_problem(96, good[:-1]))
        self.assertIn('outside', rnse_flash.image_problem(1, good))
        self.assertIn('outside', rnse_flash.image_problem(0x200, good))

    def test_old_sector_53_is_refused_by_crc(self):
        original = rnse_flash.REFUSED_IMAGES
        image = bytes(rnse_flash.SECTOR)
        rnse_flash.REFUSED_IMAGES = {zlib.crc32(image): 'old'}
        try:
            self.assertIn('old', rnse_flash.image_problem(53, image))
        finally:
            rnse_flash.REFUSED_IMAGES = original
        self.assertIn(0x3F4BE504, rnse_flash.REFUSED_IMAGES)


class FlashSequenceTests(unittest.TestCase):
    def setUp(self):
        self.target = rnse_flash.Target(96, SECTOR_96, 'sector_96.bin')

    def bs(self, fake, op):
        return [f for f in fake.frames if f[0] == op]

    def test_flash_sends_targets_then_commit_and_verifies(self):
        fake = FakeUnit()
        result = flasher(fake).flash([self.target])
        self.assertEqual(self.bs(fake, 0xB7), [bytes((0xB7, 0, 0, 96)) + struct.pack('>I', self.target.crc)])
        self.assertEqual(self.bs(fake, 0xB6), [bytes((0xB6, 1, 0, 0, 0, 0, 0, 0x5A))])
        self.assertEqual(result, {96: self.target.crc})

    def test_commit_never_goes_out_when_staged_crc_is_wrong(self):
        fake = FakeUnit(staged_ok=False)
        with self.assertRaisesRegex(rnse_flash.FlashError, 'Staged RAM is wrong'):
            flasher(fake).flash([self.target])
        self.assertEqual(self.bs(fake, 0xB7) + self.bs(fake, 0xB6), [])

    def test_commit_never_goes_out_when_a_sample_differs(self):
        fake = FakeUnit()
        unit_flasher = flasher(fake)
        real = unit_flasher._stage

        def stage(targets):
            staged = real(targets)
            fake.store(rnse_flash.STAGE_BASE + 0x7FC0, b'\xEE')
            return staged
        unit_flasher._stage = stage
        with self.assertRaisesRegex(rnse_flash.FlashError, 'differs'):
            unit_flasher.flash([self.target])
        self.assertEqual(self.bs(fake, 0xB6), [])

    def test_dry_run_never_sends_targets_or_commit(self):
        fake = FakeUnit()
        flasher(fake).rehearse([self.target])
        self.assertEqual(self.bs(fake, 0xB7) + self.bs(fake, 0xB6), [])
        self.assertEqual(len(self.bs(fake, 0xB3)), 1)

    def test_refused_commit_is_an_error(self):
        fake = FakeUnit(b6_status=1)
        with self.assertRaisesRegex(rnse_flash.FlashError, 'CRC mismatch'):
            flasher(fake).flash([self.target])

    def test_restart_count_must_be_zero(self):
        fake = FakeUnit(restart=2)
        with self.assertRaisesRegex(rnse_flash.FlashError, 'Restart count'):
            flasher(fake).flash([self.target])

    def test_live_crc_must_match_after_flash(self):
        fake = FakeUnit()
        unit_flasher = flasher(fake)
        real = unit_flasher.check
        unit_flasher.check = lambda targets: {96: 0}
        with self.assertRaisesRegex(rnse_flash.FlashError, 'does not match'):
            unit_flasher.flash([self.target])
        unit_flasher.check = real

    def test_entry_is_put_back_after_a_start(self):
        fake = FakeUnit(live={96: 5})
        flasher(fake).live_crc(96)
        self.assertEqual(fake.fetch(rnse_flash.TCB159 + rnse_flash.ENTRY_OFF, 4), struct.pack('>I', rnse_flash.DOOM_ENTRY))

    def test_bootstrap_uploads_once(self):
        with tempfile.TemporaryDirectory() as folder:
            fake = FakeUnit(live={96: 5})
            f = flasher(fake, slot=os.path.join(folder, 'slot'))
            f.live_crc(96)
            first = len(self.bs(fake, 0xB9))
            f.live_crc(96)
            again = len(self.bs(fake, 0xB9)) - first
        self.assertGreater(first, 200)
        self.assertEqual(again, 3)                      # only the LBA, the entry, and the entry put back

    def test_firmware_check_refuses_other_firmware(self):
        with self.assertRaisesRegex(rnse_flash.FlashError, 'Firmware bytes differ'):
            flasher(FakeUnit(fw_good=False)).firmware_check()

    def test_wait_dormant_gives_a_way_out(self):
        fake = FakeUnit()
        fake.store(rnse_flash.TCB159 + 4, struct.pack('>H', 2))
        f = flasher(fake)
        times = iter(range(0, 100, 30))
        f.clock = lambda: next(times)
        with self.assertRaisesRegex(rnse_flash.FlashError, 'away from TV'):
            f.wait_dormant()


class OperationTests(unittest.TestCase):
    def make(self, fake, can=None, disabled=False):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        home = Path(self.folder.name)
        self.paths = chain_module.Paths(home)
        self.paths.firmware.mkdir()
        self.paths.root.mkdir()
        (self.paths.firmware / 'sector_96.bin').write_bytes(SECTOR_96)
        calls = self.calls = []

        class FakeChain:
            def disabled(self):
                return disabled

            def stop(self):
                calls.append('stop')

            def start(self):
                calls.append('start')
        self.ports = []

        def open_port():
            port = FakePort(fake)
            self.ports.append(port)
            return port
        app_dir = str(Path(__file__).resolve().parents[1] / 'avsd' / 'app')
        ops = operations.RnseOperations(self.paths, FakeChain(), app_dir, open_unit=lambda: can_link.Unit(fake, sleep=lambda s: None),
                                        open_port=open_port, can=can or (lambda: {'present': True, 'up': True, 'listen_only': False}),
                                        stop_stream=lambda: calls.append('stop_stream'))
        return ops

    def patch_timing(self):
        real = rnse_flash.Flasher.__init__

        def init(flasher_self, unit, port, blobs, slot, log, **kw):
            real(flasher_self, unit, port, blobs, slot, log, sleep=lambda s: None, load_id=lambda: LOAD_ID)
        rnse_flash.Flasher.__init__ = init
        self.addCleanup(setattr, rnse_flash.Flasher, '__init__', real)

    def test_listen_only_refused_before_anything_happens(self):
        fake = FakeUnit()
        ops = self.make(fake, can=lambda: {'present': True, 'up': True, 'listen_only': True})
        with self.assertRaisesRegex(rnse_flash.FlashError, 'ignition'):
            ops.run('flash', ['sector_96.bin'], lambda line: None)
        self.assertEqual(fake.frames, [])
        self.assertEqual(self.calls, [])

    def test_flash_stops_and_restarts_chain_and_restores_auto_start(self):
        self.patch_timing()
        fake = FakeUnit()
        ops = self.make(fake)
        message = ops.run('flash', ['sector_96.bin'], lambda line: None)
        self.assertIn('Flashed', message)
        self.assertEqual(self.calls, ['stop_stream', 'stop', 'start'])
        self.assertEqual(fake.fetch(rnse_flash.TVA + 4, 4), bytes(4))
        self.assertEqual(ops.decoder()['crc'], '%08X' % zlib.crc32(SECTOR_96))
        self.assertTrue(self.ports[0].closed)

    def test_failure_still_restores_everything(self):
        self.patch_timing()
        fake = FakeUnit(staged_ok=False)
        ops = self.make(fake)
        with self.assertRaises(rnse_flash.FlashError):
            ops.run('flash', ['sector_96.bin'], lambda line: None)
        self.assertEqual(self.calls[-1], 'start')
        self.assertEqual(fake.fetch(rnse_flash.TVA + 4, 4), bytes(4))
        self.assertEqual([f for f in fake.frames if f[0] == 0xB6], [])

    def test_firmware_mismatch_leaves_the_chain_running(self):
        self.patch_timing()
        ops = self.make(FakeUnit(fw_good=False))
        with self.assertRaises(rnse_flash.FlashError):
            ops.run('check', ['sector_96.bin'], lambda line: None)
        self.assertEqual(self.calls, ['start'])

    def test_chain_switched_off_stays_off(self):
        self.patch_timing()
        ops = self.make(FakeUnit(live={96: 1}), disabled=True)
        ops.run('check', ['sector_96.bin'], lambda line: None)
        self.assertEqual(self.calls, ['stop'])

    def test_only_listed_files_can_be_used(self):
        fake = FakeUnit()
        ops = self.make(fake)
        with self.assertRaisesRegex(rnse_flash.FlashError, 'from the list'):
            ops.run('flash', ['../../etc/passwd'], lambda line: None)
        self.assertEqual(fake.frames, [])

    def test_old_decoder_is_flagged(self):
        ops = self.make(FakeUnit())
        ops._record_decoder(0x29D3E06A)
        self.assertTrue(ops.decoder()['old'])
        ops._record_decoder(0x0696DDE4)
        self.assertFalse(ops.decoder()['old'])


class WireTests(unittest.TestCase):
    def test_wire_sector_shape(self):
        wire = sd_link.wire4(bytes(512))
        self.assertEqual(len(wire), 528)
        self.assertEqual(wire[:4], b'\xff\xff\xff\x0f')
        self.assertEqual(wire[-4:], b'\xff\xff\xff\xff')

    def test_header_crc_covers_it(self):
        header = sd_link.make_header(1, 0x8F780000, b'x' * 512, 0x8F780000, 0x20000, rnse_flash.FW_CHECKS)
        self.assertEqual(len(header), 512)
        self.assertEqual(struct.unpack('>I', header[508:])[0], zlib.crc32(header[:508]))
        self.assertEqual(struct.unpack('>I', header[:4])[0], sd_link.HDR_MAGIC)


class StatusTests(unittest.TestCase):
    STAT = 'STAT sf built=1 sent=1 frames=%d drop=0 keyreq=2 | teensy status=1 served=%d | rd_stalled=%d waitkey=0'

    def test_streaming(self):
        lines = [self.STAT % (10, 5, 0), self.STAT % (20, 9, 0)]
        self.assertEqual(chain_module.stream_health(lines, [])['verdict'], 'streaming')

    def test_off_tv_is_normal(self):
        lines = [self.STAT % (10, 5, 1), self.STAT % (20, 5, 1)]
        self.assertEqual(chain_module.stream_health(lines, [])['verdict'], 'not_on_tv')

    def test_no_frames(self):
        lines = [self.STAT % (10, 5, 0), self.STAT % (10, 5, 0)]
        self.assertEqual(chain_module.stream_health(lines, [])['verdict'], 'no_frames')

    def test_encoder_limits_are_counted(self):
        enc = ['rnv3enc: frame 3 over the cycle cap (5 > 4)', 'frame 60: 100 B qp 3', 'rnv3enc: frame 9 over the superframe (9)']
        self.assertEqual(chain_module.stream_health([], enc)['encoder_over'], 2)

    def test_waiting_for_teensy_is_shown_though_the_service_is_active(self):
        journal = ['avsd: hudiy ok after 3 s', 'avsd: sink hudiy_equalizer_sink ok after 0 s', 'avsd: waiting for Teensy on USB']
        self.assertEqual(chain_module.supervisor_state(journal), {'state': 'waiting', 'detail': 'Teensy on USB'})

    def test_running_and_restart_lines(self):
        self.assertEqual(chain_module.supervisor_state(['avsd: starting chain on x, logs in y'])['state'], 'running')
        self.assertEqual(chain_module.supervisor_state(['avsd: starting chain', 'avsd: restart: encoder gone'])['detail'], 'encoder gone')


class FakeChain:
    def __init__(self):
        self.restarts = 0

    def restart(self):
        self.restarts += 1


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.paths = chain_module.Paths(self.folder.name)
        self.paths.trial = Path(self.folder.name) / 'run' / 'avsd-trial.env'
        self.chain = FakeChain()
        self.store = settings_store.SettingsStore(self.paths, self.chain)

    def changed(self, **kw):
        return {**settings_store.DEFAULTS, **kw}

    def saved_text(self):
        return self.paths.env.read_text()

    def test_fields_are_the_documented_ones(self):
        self.assertEqual(set(settings_store.BY_ID), {'GAIN', 'LINKCAP', 'MAXVID', 'CYC', 'KEYINT', 'ENCTHREADS', 'DITHER', 'SRCDEAD', 'SRCMEAN', 'FILLPEN', 'RTPRIO'})

    def test_defaults_match_the_template_file(self):
        template = (Path(__file__).resolve().parents[1] / 'avsd' / 'chain' / 'avsd.env').read_text()
        self.assertEqual(settings_store.parse_env(template), settings_store.DEFAULTS)
        for name in re.findall(r'^([A-Z]+)=', template, re.MULTILINE):
            self.assertIn(name, settings_store.BY_ID)

    def test_gain_and_maxvid_caps(self):
        self.assertEqual(settings_store.BY_ID['GAIN']['max'], -3)
        self.assertEqual(settings_store.BY_ID['MAXVID']['max'], 161)
        for bad in (self.changed(GAIN=-2), self.changed(GAIN=0), self.changed(MAXVID=162)):
            with self.assertRaises(ValueError):
                self.store.apply(bad)
            with self.assertRaises(ValueError):
                self.store.save(bad)

    def test_only_plain_numbers_get_written(self):
        for bad in (self.changed(GAIN='-3; rm -rf /'), self.changed(GAIN=True), self.changed(CYC=4100000), self.changed(LINKCAP=3250000),
                    self.changed(KEYINT=100), self.changed(DITHER=2), {'GAIN': -3}, {**settings_store.DEFAULTS, 'ENCFLAGS': 1}):
            with self.assertRaises(ValueError):
                self.store.apply(bad)
        self.assertEqual(self.chain.restarts, 0)
        self.assertFalse(self.paths.env.exists())
        self.assertFalse(self.paths.trial.exists())

    def test_apply_is_temporary(self):
        self.store.apply(self.changed(GAIN=-9))
        self.assertEqual(self.chain.restarts, 1)
        self.assertFalse(self.paths.env.exists())
        self.assertIn('GAIN=-9\n', self.paths.trial.read_text())
        self.assertEqual(self.store.values()['GAIN'], -9)
        self.assertEqual(self.store.saved()['GAIN'], -3)
        self.assertTrue(self.store.snapshot()['temporary'])

    def test_reboot_drops_what_was_only_applied(self):
        self.store.apply(self.changed(GAIN=-9))
        self.paths.trial.unlink()                       # tmpfs at power-off
        self.assertEqual(self.store.values()['GAIN'], -3)
        self.assertFalse(self.store.snapshot()['temporary'])

    def test_save_keeps_it_and_needs_no_restart_if_already_running(self):
        self.store.apply(self.changed(GAIN=-9))
        self.store.save(self.changed(GAIN=-9))
        self.assertEqual(self.chain.restarts, 1)
        self.assertEqual(self.saved_text(), 'GAIN=-9\n')
        self.assertFalse(self.paths.trial.exists())
        self.assertFalse(self.store.snapshot()['temporary'])

    def test_save_of_new_values_restarts(self):
        self.store.save(self.changed(GAIN=-6))
        self.assertEqual(self.chain.restarts, 1)
        self.assertEqual(self.store.values()['GAIN'], -6)

    def test_applying_the_saved_values_clears_the_temporary_file(self):
        self.store.apply(self.changed(GAIN=-9))
        self.store.apply(self.changed())
        self.assertFalse(self.paths.trial.exists())

    def test_restore_defaults_deletes_the_lines_and_keeps_the_rest(self):
        self.paths.root.mkdir()
        self.paths.env.write_text('# my note\nGAIN=-9\nDITHER=1\nENCEXTRA="--x 1"\n')
        self.store.apply(self.changed(GAIN=-12, DITHER=1))
        self.store.restore_defaults()
        self.assertEqual(self.saved_text(), '# my note\nENCEXTRA="--x 1"\n')
        self.assertFalse(self.paths.trial.exists())
        self.assertEqual(self.store.values(), settings_store.DEFAULTS)
        self.assertEqual(self.chain.restarts, 2)

    def test_comments_and_other_lines_stay_on_save(self):
        self.paths.root.mkdir()
        self.paths.env.write_text('# my note\nGAIN=-3\nCYC=4.05e6\nENCEXTRA="--r3 1"\n')
        self.store.save(self.changed(GAIN=-6))
        self.assertEqual(self.saved_text(), '# my note\nGAIN=-6\nCYC=4050000\nENCEXTRA="--r3 1"\n')

    def test_reads_the_template_notation(self):
        self.assertEqual(settings_store.parse_env('LINKCAP=4.2e6\nCYC=3.5e6\n')['LINKCAP'], 4200000)

    def test_a_bad_line_reads_as_if_it_was_not_there(self):
        values = settings_store.parse_env('GAIN=$(reboot)\nMAXVID=999\nFILLPEN=3\n')
        self.assertEqual(values['GAIN'], -3)
        self.assertEqual(values['MAXVID'], 161)
        self.assertEqual(values['FILLPEN'], 3)

    def test_encflags_is_flagged(self):
        self.assertFalse(self.store.snapshot()['encflags_override'])
        self.paths.root.mkdir()
        self.paths.env.write_text('ENCFLAGS="--cyc 5e6"\n')
        self.assertTrue(self.store.snapshot()['encflags_override'])

    def test_hud2_reads_saved_then_temporary(self):
        text = (Path(__file__).resolve().parents[1] / 'avsd' / 'chain' / 'hud2.sh').read_text()
        self.assertLess(text.index('. "$A/avsd.env"'), text.index('. "$XDG_RUNTIME_DIR/avsd-trial.env"'))


class ReleaseWatchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.paths = chain_module.Paths(self.folder.name)
        self.paths.root.mkdir()
        self.paths.update_check.write_text('{"state": "pending", "version": "abc"}')
        self.now = 1000.0
        self.releases = operations.Releases(self.paths, FakeChain(), run=lambda *a, **k: None, clock=lambda: self.now)
        self.rolled = []
        self.releases.rollback = lambda: self.rolled.append(True)
        self.has_previous = self.paths.previous

    def check(self):
        return json.loads(self.paths.update_check.read_text())

    def previous(self):
        (self.paths.root / 'old').mkdir()
        os.symlink(str(self.paths.root / 'old'), str(self.paths.previous), target_is_directory=True)

    def test_frames_mean_ok(self):
        self.assertTrue(self.releases.watch_step(1000, {'verdict': 'not_on_tv'}, 0))
        self.assertEqual(self.check()['state'], 'ok')
        self.assertIn('not confirmed', self.check()['message'])

    def test_a_switched_off_chain_is_not_a_failure(self):
        self.now += operations.UPDATE_CHECK_LIMIT_S + 1
        self.assertTrue(self.releases.watch_step(1000, {'verdict': 'no_data', 'disabled': True, 'supervisor': {'state': 'unknown'}}, 0))
        self.assertEqual(self.check()['state'], 'unverified')
        self.assertEqual(self.rolled, [])

    def test_waiting_is_not_a_failure(self):
        status = {'verdict': 'no_data', 'supervisor': {'state': 'waiting', 'detail': 'Teensy on USB'}}
        self.assertFalse(self.releases.watch_step(1000, status, 0))
        self.now += 500
        self.assertTrue(self.releases.watch_step(1000, status, 0))
        self.assertEqual(self.check()['state'], 'unverified')
        self.assertEqual(self.rolled, [])

    @unittest.skipIf(os.name == 'nt', 'symlink rights')
    def test_repeated_restarts_roll_back(self):
        self.previous()
        self.assertTrue(self.releases.watch_step(1000, {'verdict': 'no_data', 'supervisor': {'state': 'restarting'}}, 3))
        self.assertEqual(self.rolled, [True])
        self.assertEqual(self.check()['state'], 'rolled_back')

    @unittest.skipIf(os.name == 'nt', 'symlink rights')
    def test_no_frames_for_too_long_rolls_back(self):
        self.previous()
        status = {'verdict': 'no_frames', 'supervisor': {'state': 'running'}}
        self.assertFalse(self.releases.watch_step(1000, status, 0))
        self.now += operations.UPDATE_CHECK_LIMIT_S + 1
        self.assertTrue(self.releases.watch_step(1000, status, 0))
        self.assertEqual(self.rolled, [True])


try:
    import flask  # noqa: F401
    HAVE_FLASK = True
except ImportError:
    HAVE_FLASK = False


@unittest.skipUnless(HAVE_FLASK, 'Flask not installed')
class RouteTests(unittest.TestCase):
    def setUp(self):
        import app as avsd_app
        self.avsd_app = avsd_app
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.calls = []
        calls = self.calls
        self.paths = chain_module.Paths(self.folder.name)
        self.paths.root.mkdir()

        class Chain:
            def status(self):
                return {'active': 'active', 'disabled': False, 'supervisor': {'state': 'running', 'detail': ''}, 'verdict': 'not_on_tv', 'stat': {}, 'encoder_over': 0}

            def restart(self):
                calls.append('restart')

            def disabled(self):
                return False

            def log_lines(self, source, lines):
                if source not in chain_module.LOG_SOURCES:
                    raise ValueError('unknown log')
                return ['line']

            def stop(self):
                calls.append('stop')

            def start(self):
                calls.append('start')

        self.can = {'present': True, 'up': True, 'listen_only': False}
        self.app = avsd_app.create_app(home=self.folder.name, chain=Chain(), can=lambda: self.can, updater=lambda script: calls.append(('update', str(script))))
        self.app.extensions['avsd_settings'].paths.trial = Path(self.folder.name) / 'run' / 'avsd-trial.env'
        self.client = self.app.test_client()
        self.write = {'X-AVSD': '1'}

    def test_read_works_from_anywhere(self):
        response = self.client.get('/api/status', environ_base={'REMOTE_ADDR': '10.42.0.9'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()['can_change'])

    def test_writes_refused_from_the_network(self):
        response = self.client.post('/api/chain', json={'action': 'stop'}, headers=self.write, environ_base={'REMOTE_ADDR': '10.42.0.9'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.calls, [])

    def test_writes_refused_without_the_header(self):
        self.assertEqual(self.client.post('/api/chain', json={'action': 'stop'}).status_code, 403)
        self.assertEqual(self.calls, [])

    def test_chain_action(self):
        self.assertEqual(self.client.post('/api/chain', json={'action': 'stop'}, headers=self.write).status_code, 200)
        self.assertEqual(self.calls, ['stop'])

    def test_flash_with_ignition_off_says_so(self):
        self.can = {'present': True, 'up': True, 'listen_only': True}
        response = self.client.post('/api/rnse', json={'op': 'flash', 'files': []}, headers=self.write)
        self.assertEqual(response.status_code, 409)
        self.assertIn('ignition', response.get_json()['error'])

    def test_unknown_file_refused_without_a_job(self):
        response = self.client.post('/api/rnse', json={'op': 'flash', 'files': ['nope.bin']}, headers=self.write)
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(self.client.get('/api/job').get_json()['job'])

    def test_firmware_list_explains_bad_files(self):
        self.paths.firmware.mkdir()
        (self.paths.firmware / 'sector_96.bin').write_bytes(SECTOR_96)
        (self.paths.firmware / 'other.bin').write_bytes(bytes(10))
        files = {f['name']: f for f in self.client.get('/api/firmware').get_json()['files']}
        self.assertIsNone(files['sector_96.bin']['problem'])
        self.assertEqual(files['sector_96.bin']['sector'], 96)
        self.assertIn('name', files['other.bin']['problem'])

    def test_settings_apply_and_bad_value(self):
        values = dict(settings_store.DEFAULTS, GAIN=-9)
        self.assertEqual(self.client.post('/api/settings', json={'values': values}, headers=self.write).status_code, 200)
        self.assertEqual(self.calls, ['restart'])
        self.assertEqual(self.client.post('/api/settings', json={'values': dict(values, GAIN=5)}, headers=self.write).status_code, 400)

    def test_unknown_log_refused(self):
        self.assertEqual(self.client.get('/api/logs?source=../../etc').status_code, 400)

    def test_full_install_updates_through_update_rnse(self):
        script = Path(self.folder.name) / 'hudiy_client' / 'update_rnse.sh'
        script.parent.mkdir()
        script.touch()
        response = self.client.post('/api/update', json={}, headers=self.write)
        self.assertEqual(response.status_code, 409)
        self.assertIn('Update RNS-E', response.get_json()['error'])
        self.assertEqual(self.calls, [])

    def test_update_runs_the_script_of_this_version(self):
        self.assertEqual(self.client.post('/api/update', json={}, headers=self.write).status_code, 200)
        self.assertEqual(self.calls[0][0], 'update')
        self.assertTrue(self.calls[0][1].endswith('update_avsd.sh'))


class MainInstallerTests(unittest.TestCase):
    ROOT = Path(__file__).resolve().parents[1]

    def test_avsd_is_staged_and_only_updates_once_enabled(self):
        text = (self.ROOT / 'install.sh').read_text(encoding='utf-8')
        sparse = next(line for line in text.splitlines() if line.startswith('SPARSE_PATHS='))
        self.assertIn(' avsd)', sparse)
        self.assertIn('[ -L "$REAL_HOME/avsd/current" ]', text)
        self.assertIn('"$STAGING_DIR/avsd/install.sh" --update', text)
        self.assertNotIn('install_folder "avsd"', text)

    def test_update_marks_the_chain_before_hudiy_quits(self):
        text = (self.ROOT / 'hudiy_client' / 'hudiy_data.py').read_text(encoding='utf-8')
        action = text.index('message.action in ("update_rnse"')
        self.assertLess(text.index('keep_av_chain_up()', action), text.index('"quit_hudiy"', action))

    def test_every_file_the_installer_needs_is_here(self):
        avsd = self.ROOT / 'avsd'
        for name in ('update_avsd.sh', 'app/app.py', 'app/blobs/sdboot.bin', 'app/blobs/tramp.bin', 'app/blobs/sdstage.bin',
                     'chain/hud2.sh', 'chain/avsd.env', 'chain/avsd_run.sh', 'chain/avsd-chain.service', 'chain/avsd-app.service',
                     'chain/avsd-governor.service', 'chain/enc3/src/enc.c', 'chain/enc3/include/rnv2enc.h',
                     'chain/avlink/Makefile', 'chain/wlcap/wlcap.c', 'teensy/firmware.hex', 'teensy/hkflash_linux.py'):
            self.assertTrue((avsd / name).is_file(), name)


if __name__ == '__main__':
    unittest.main()
