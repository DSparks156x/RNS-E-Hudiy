"""What the buttons run: RNS-E operations with the chain down, the Teensy, updates and rollback."""
import hashlib
import json
import os
import subprocess
import time
import zlib

import can_link
import rnse_flash
import sd_link

UPDATE_CHECK_LIMIT_S = 180
UPDATE_RESTARTS_LIMIT = 3


def load_blobs(app_dir):
    blobs = {}
    for name in ('sdboot', 'tramp', 'sdstage'):
        with open(os.path.join(app_dir, 'blobs', name + '.bin'), 'rb') as f:
            blobs[name] = f.read()
    return blobs


def firmware_files(paths):
    items = []
    try:
        names = sorted(os.listdir(paths.firmware))
    except OSError:
        return items
    for name in names:
        path = paths.firmware / name
        if not name.lower().endswith('.bin') or not path.is_file():
            continue
        with open(path, 'rb') as f:
            image = f.read(rnse_flash.SECTOR + 1)
        sidx = rnse_flash.sector_from_name(name)
        items.append({'name': name, 'size': len(image), 'sector': sidx, 'crc': '%08X' % zlib.crc32(image),
                      'problem': rnse_flash.image_problem(sidx, image)})
    return items


def safe_firmware_paths(paths, names):
    known = {item['name'] for item in firmware_files(paths)}
    if not isinstance(names, list) or any(name not in known for name in names):
        raise rnse_flash.FlashError('Choose files from the list.')
    return [str(paths.firmware / name) for name in names]


class RnseOperations:
    def __init__(self, paths, chain, app_dir, open_unit=None, open_port=sd_link.TeensyPort, can=can_link.can_state, stop_stream=sd_link.stop_stream):
        self.paths, self.chain, self.app_dir = paths, chain, app_dir
        self.open_unit = open_unit or (lambda: can_link.Unit(can_link.SocketCanBus()))
        self.open_port, self.can, self.stop_stream = open_port, can, stop_stream

    def _record_decoder(self, crc):
        with open(self.paths.unit_state, 'w') as f:
            json.dump({'decoder_crc': '%08X' % crc, 'read_at': time.time()}, f)

    def decoder(self):
        """Last seen CRC of the decoder sector, and whether it can show the encoder's R3 stream."""
        try:
            with open(self.paths.unit_state) as f:
                crc = json.load(f)['decoder_crc']
        except (OSError, ValueError, KeyError):
            return {'crc': None, 'old': False}
        return {'crc': crc, 'old': int(crc, 16) in rnse_flash.OLD_DECODERS}

    def run(self, op, names, log):
        """op: check, rehearse, flash or decoder. The chain goes down, comes back in every case."""
        reason = can_link.not_ready_reason(self.can())
        if reason:
            raise rnse_flash.FlashError(reason)
        targets = rnse_flash.load_targets(safe_firmware_paths(self.paths, names)) if op != 'decoder' else []
        unit = self.open_unit()
        port = self.open_port()
        chain_was_on = not self.chain.disabled()
        auto_start = False
        try:
            flasher = rnse_flash.Flasher(unit, port, load_blobs(self.app_dir), str(self.paths.slot), log)
            flasher.firmware_check()
            log('Firmware identity OK.')
            auto_start = flasher.auto_start_off()
            if chain_was_on:
                self.stop_stream()
            self.chain.stop()
            log('Chain stopped.')
            flasher.wait_dormant()
            if op == 'decoder':
                crc = flasher.live_crc(rnse_flash.DECODER_SECTOR)
                self._record_decoder(crc)
                return 'Decoder sector %d: CRC %08X.' % (rnse_flash.DECODER_SECTOR, crc)
            if op == 'check':
                live = flasher.check(targets)
                self._note_decoder(live)
                same = sum(live[t.sidx] == t.crc for t in targets)
                return '%d of %d sectors match the file.' % (same, len(targets))
            if op == 'rehearse':
                flasher.rehearse(targets)
                return 'Dry run passed. Flash was not touched.'
            live = flasher.flash(targets)
            self._note_decoder(live)
            return 'Flashed and verified sector %s.' % ', '.join(str(t.sidx) for t in targets)
        finally:
            port.close()
            if auto_start:
                try:
                    rnse_flash.Flasher(unit, port, {}, str(self.paths.slot), log).restore_auto_start()
                except can_link.UnitError as error:
                    log('Could not turn auto start back on: %s. A power cycle does it.' % error)
            unit.close()
            if chain_was_on:
                self.chain.start()
                log('Chain started.')

    def _note_decoder(self, live):
        if rnse_flash.DECODER_SECTOR in live:
            self._record_decoder(live[rnse_flash.DECODER_SECTOR])

    def counters(self):
        reason = can_link.not_ready_reason(self.can())
        if reason:
            raise rnse_flash.FlashError(reason)
        unit = self.open_unit()
        try:
            return rnse_flash.read_unit_counters(unit)
        finally:
            unit.close()


class TeensyUpdate:
    def __init__(self, paths, chain, run=subprocess.run):
        self.paths, self.chain, self.run = paths, chain, run

    def hex_path(self):
        return self.paths.current / 'teensy' / 'firmware.hex'

    def hex_sha(self):
        try:
            with open(self.hex_path(), 'rb') as f:
                return hashlib.sha256(f.read()).hexdigest()
        except OSError:
            return None

    def status(self):
        repo = self.hex_sha()
        try:
            flashed = self.paths.teensy_record.read_text().strip()
        except OSError:
            flashed = None
        return {'repo': repo[:8] if repo else None, 'flashed': flashed[:8] if flashed else None,
                'update_available': bool(repo and repo != flashed), 'present': bool(sd_link.find_port())}

    def flash(self, log):
        repo = self.hex_sha()
        if not repo:
            raise rnse_flash.FlashError('No Teensy firmware in this release.')
        if not sd_link.find_port():
            raise rnse_flash.FlashError('Teensy not on USB.')
        was_on = not self.chain.disabled()
        self.chain.stop()
        log('Chain stopped.')
        try:
            result = self.run(['sudo', '-n', 'python3', str(self.paths.current / 'teensy' / 'hkflash_linux.py'), str(self.hex_path())],
                              capture_output=True, text=True, timeout=240)
            for line in (result.stdout + result.stderr).splitlines()[-8:]:
                log(line)
            if result.returncode:
                raise rnse_flash.FlashError('Teensy flash failed, exit %d.' % result.returncode)
            self.paths.teensy_record.write_text(repo + '\n')
        finally:
            if was_on:
                self.chain.start()
        return 'Teensy flashed. If the picture does not return, power-cycle the RNS-E.'


class Releases:
    def __init__(self, paths, chain, run=subprocess.run, clock=time.time):
        self.paths, self.chain, self.run, self.clock = paths, chain, run, clock

    def _info(self, link):
        try:
            with open(link / 'version.json') as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def status(self):
        try:
            with open(self.paths.update_check) as f:
                check = json.load(f)
        except (OSError, ValueError):
            check = None
        return {'current': self._info(self.paths.current), 'previous': self._info(self.paths.previous), 'check': check,
                'updates_with_rnse': self.updates_with_rnse()}

    def updates_with_rnse(self):
        """The full install's Update RNS-E carries this along."""
        return (self.paths.home / 'hudiy_client' / 'update_rnse.sh').exists()

    def rollback(self):
        """current and previous swap. The app restarts itself from the other release."""
        current, previous = self.paths.current, self.paths.previous
        if not previous.exists():
            raise ValueError('No previous version.')
        new_target, old_target = os.readlink(previous), os.readlink(current)
        temporary = str(current) + '.new'
        os.symlink(new_target, temporary)
        os.replace(temporary, current)
        os.symlink(old_target, temporary)
        os.replace(temporary, previous)
        self.chain.restart()
        self.run(['systemctl', '--user', '--no-block', 'restart', 'avsd-app'], capture_output=True, timeout=10)

    def _write_check(self, data):
        temporary = str(self.paths.update_check) + '.tmp'
        with open(temporary, 'w') as f:
            json.dump(data, f)
        os.replace(temporary, self.paths.update_check)

    def watch_step(self, started, chain_status, restarts):
        """After an update: rolls back if the new chain doesn't run. Returns True when there's nothing left to watch.
        A chain waiting on something (no Teensy, Hudiy not up) says nothing about the update: that stays "not verifiable"."""
        try:
            with open(self.paths.update_check) as f:
                check = json.load(f)
        except (OSError, ValueError):
            return True
        if check.get('state') != 'pending':
            return True
        verdict = chain_status.get('verdict')
        if verdict in ('streaming', 'not_on_tv'):
            self._write_check({**check, 'state': 'ok', 'message': 'New version running.' if verdict == 'streaming' else 'New version encoding. Unit is not on TV, so the picture is not confirmed.'})
            return True
        if chain_status.get('disabled'):
            self._write_check({**check, 'state': 'unverified', 'message': 'Not verifiable now: the chain is switched off.'})
            return True
        waiting = chain_status.get('supervisor', {}).get('state') == 'waiting'
        failed = restarts >= UPDATE_RESTARTS_LIMIT or (not waiting and self.clock() - started > UPDATE_CHECK_LIMIT_S)
        if failed and self.paths.previous.exists():
            self._write_check({**check, 'state': 'rolled_back', 'message': 'New version did not produce frames. Rolled back.'})
            self.rollback()
            return True
        if waiting and self.clock() - started > UPDATE_CHECK_LIMIT_S:
            self._write_check({**check, 'state': 'unverified', 'message': 'Not verifiable now: chain is waiting for %s.' % chain_status['supervisor']['detail']})
            return True
        return False


def start_update(script, run=subprocess.run):
    """In a unit of its own: the update replaces this app and quits Hudiy."""
    result = run(['systemd-run', '--user', '--unit=avsd-update', '--collect', '--setenv=WAYLAND_DISPLAY=wayland-0',
                  'foot', '--fullscreen', '--font=monospace:size=18:weight=bold', 'bash', str(script)],
                 capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError((result.stderr or 'Could not start the update.').strip())
