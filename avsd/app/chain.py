"""The chain's supervisor, its logs and what they say about its health. Python stdlib only."""
import os
import re
import subprocess
from pathlib import Path

UNIT = 'avsd-chain'
STAT_VALUE = re.compile(r'(\w+)=(-?\d+)')
ENC_OVER = re.compile(r'rnv3enc: frame \d+ over ')
LOG_SOURCES = ('live', 'enc', 'cap', 'supervisor')


class Paths:
    def __init__(self, home=None):
        self.home = Path(home or os.path.expanduser('~'))
        self.root = self.home / 'avsd'
        self.current = self.root / 'current'
        self.previous = self.root / 'previous'
        self.disable = self.root / 'car' / 'DISABLE'
        self.env = self.root / 'avsd.env'
        self.logs = self.root / 'logs'
        self.job = self.root / 'last_job.json'
        self.unit_state = self.root / 'unit_state.json'
        self.slot = self.root / 'tramp_slot.txt'
        self.teensy_record = self.root / 'teensy_flashed.sha256'
        self.update_check = self.root / 'update_check.json'
        self.firmware = self.home / 'rnsefw'
        runtime = os.environ.get('XDG_RUNTIME_DIR') or '/run/user/%d' % getattr(os, 'getuid', lambda: 1000)()
        self.chaindir = Path(runtime) / 'avsd'
        self.trial = Path(runtime) / 'avsd-trial.env'


def parse_stat(line):
    return {key: int(value) for key, value in STAT_VALUE.findall(line)}


def read_tail(path, lines):
    """Last lines of a file without reading all of it."""
    try:
        with open(path, 'rb') as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - max(lines, 1) * 400))
            return f.read().decode('utf-8', 'replace').splitlines()[-lines:]
    except OSError:
        return []


def supervisor_state(lines):
    """What the supervisor is doing, from its journal lines. systemd's 'active' also covers waiting with no Teensy."""
    for line in reversed(lines):
        match = re.search(r'avsd: waiting for (.+)$', line)
        if match:
            return {'state': 'waiting', 'detail': match.group(1)}
        if 'avsd: starting chain' in line:
            return {'state': 'running', 'detail': ''}
        match = re.search(r'avsd: restart: (.+)$', line)
        if match:
            return {'state': 'restarting', 'detail': match.group(1)}
        match = re.search(r'avsd: (.+) ok after', line)
        if match:
            return {'state': 'starting', 'detail': match.group(1)}
    return {'state': 'unknown', 'detail': ''}


def stream_health(live_lines, enc_lines):
    """Compares the last two STAT lines (avlink writes one every 5 s).
    rd_stalled=1 and waitkey=1 are normal whenever the unit isn't on TV, so frames decide if the Pi side works, served if the unit is reading."""
    stats = [parse_stat(line) for line in live_lines if line.startswith('STAT ')]
    over = sum(1 for line in enc_lines if ENC_OVER.search(line))
    if len(stats) < 2:
        return {'verdict': 'no_data', 'stat': stats[-1] if stats else {}, 'encoder_over': over}
    old, new = stats[-2], stats[-1]
    frames_rising = new.get('frames', 0) > old.get('frames', 0)
    served_rising = new.get('served', 0) > old.get('served', 0)
    if not frames_rising:
        verdict = 'no_frames'
    elif served_rising and not new.get('rd_stalled'):
        verdict = 'streaming'
    else:
        verdict = 'not_on_tv'
    return {'verdict': verdict, 'stat': new, 'encoder_over': over}


class Chain:
    def __init__(self, paths, run=subprocess.run):
        self.paths = paths
        self.run = run

    def _systemctl(self, *args):
        return self.run(['systemctl', '--user', *args], capture_output=True, text=True, timeout=20)

    def disabled(self):
        return self.paths.disable.exists()

    def stop(self):
        """Stays down across a reboot until start()."""
        self.paths.disable.parent.mkdir(parents=True, exist_ok=True)
        self.paths.disable.touch()
        self._systemctl('stop', UNIT)

    def start(self):
        try:
            self.paths.disable.unlink()
        except FileNotFoundError:
            pass
        self._systemctl('start', UNIT)

    def restart(self):
        """Applies new settings. Does nothing while the chain is switched off."""
        if not self.disabled():
            self._systemctl('restart', UNIT)

    def active(self):
        return self._systemctl('is-active', UNIT).stdout.strip()

    def journal(self, lines=60):
        try:
            # This boot only: the update check counts restarts. "--user -u" finds nothing on Pi OS.
            out = self.run(['journalctl', '-b', '_SYSTEMD_USER_UNIT=%s.service' % UNIT, '-n', str(lines), '-o', 'cat', '--no-pager'],
                           capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return []
        return out.stdout.splitlines()

    def log_lines(self, source, lines):
        if source == 'supervisor':
            return self.journal(lines)
        if source not in LOG_SOURCES:
            raise ValueError('unknown log')
        return read_tail(self.paths.chaindir / (source + '.log'), lines)

    def status(self):
        active = self.active()
        disabled = self.disabled()
        supervisor = supervisor_state(self.journal(40))
        health = stream_health(self.log_lines('live', 6), self.log_lines('enc', 400))
        # live.log is only truncated after the waits, so it can be stale while waiting.
        if supervisor['state'] != 'running' or active != 'active':
            health = {**health, 'verdict': 'no_data'}
        return {'active': active, 'disabled': disabled, 'supervisor': supervisor, **health}
