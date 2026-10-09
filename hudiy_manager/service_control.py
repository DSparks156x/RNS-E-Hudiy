"""Allowlisted systemd control and bounded journal snapshots; no shell execution."""
from contextlib import contextmanager
from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
import threading

from .config_store import ConfigError

try:
    import fcntl
except ImportError:
    fcntl = None

MAX_LOG_BYTES = 128 * 1024


class ServiceError(ConfigError):
    status = 503


class BusyError(ServiceError):
    status = 409


@dataclass(frozen=True)
class Service:
    id: str
    label: str
    description: str
    disruptive: bool = False
    control: bool = True

    @property
    def unit(self):
        return self.id + '.service'


SERVICES = (
    Service('can_handler', 'CAN transport', 'Shared CAN input and output. Stopping it also stops dependent DIS services.', True),
    Service('can_base_function', 'RNS-E functions', 'Power, time and head-unit CAN functions.', True),
    Service('tp2_worker', 'Diagnostic transport', 'TP2 diagnostic sessions and measuring groups.', True),
    Service('can_keyboard_control', 'Buttons and wheel', 'Faceplate and steering-wheel input.'),
    Service('dark_mode_api', 'Hudiy day/night', 'Hudiy appearance from the vehicle light status.'),
    Service('hudiy_data_api', 'Hudiy data bridge', 'Navigation, phone and media information.'),
    Service('hudiy_dataview', 'Hudiy DataView', 'Diagnostics, recordings and the network file portal.', True),
    Service('hudiy_status_service', 'Vehicle values', 'Shared live values and the recording workspace.', True),
    Service('dis_service', 'DIS driver', 'Cluster display transport; startup includes a ten-second delay.'),
    Service('dis_display', 'DIS pages', 'Center display apps; startup includes a ten-second delay.'),
    Service('dis_top_display', 'DIS top lines', 'Upper cluster text and icons.'),
    Service('haldex_manager', 'Haldex modes', 'AWD mode commands and persistence.', True),
    Service('hudiy_manager', 'RNS-E Manager', 'This management app; control is unavailable here.', control=False),
)


def bounded_run(args, timeout=10, limit=MAX_LOG_BYTES):
    """Keep subprocess output bounded even when a single journal message is huge."""
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    chunks = []
    truncated = [False]

    def read():
        remaining = limit
        while True:
            chunk = process.stdout.read(min(4096, remaining + 1))
            if not chunk:
                break
            if len(chunk) > remaining:
                chunks.append(chunk[:remaining])
                truncated[0] = True
                process.terminate()
                break
            chunks.append(chunk)
            remaining -= len(chunk)

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=2)
        reader.join(timeout=2)
        raise ServiceError('The service command timed out. Refresh its status before retrying.') from None
    finally:
        reader.join(timeout=2)
        if process.stdout:
            process.stdout.close()
    return {'returncode': process.returncode,
            'text': b''.join(chunks).decode('utf-8', errors='replace'),
            'truncated': truncated[0]}


@contextmanager
def inactive_flash_guard(home):
    """Take the same cross-process operation lock as the controller flashers."""
    from .config_store import _no_symlink
    path = _no_symlink(Path(home) / '.hudiy' / 'flashing_operation.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    # Share the flasher's local lock too, so tests and same-process callers work
    # on Windows; installed Linux processes are additionally protected by flock.
    from flasher import traffic
    with traffic._registry_lock:
        lock = traffic._local_locks.setdefault(str(path), threading.Lock())
    if not lock.acquire(blocking=False):
        raise BusyError('A controller operation is active. Wait for it to finish before changing this service.')
    fd = None
    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        if fcntl:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise BusyError('A controller operation is active. Wait for it to finish before changing this service.') from None
        yield
    finally:
        if fd is not None:
            if fcntl:
                fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        lock.release()


class ServiceController:
    def __init__(self, home=None, runner=None, flash_guard=None, systemctl=None, journalctl=None, sudo=None):
        self.home = Path(home or Path.home()).absolute()
        self.runner = runner or bounded_run
        self.flash_guard = flash_guard or (lambda: inactive_flash_guard(self.home))
        # Fixed paths match the exact installer sudo policy, regardless of PATH.
        self.systemctl = systemctl or '/usr/bin/systemctl'
        self.journalctl = journalctl or '/usr/bin/journalctl'
        self.sudo = sudo or '/usr/bin/sudo'
        self.services = {service.id: service for service in SERVICES}
        self._action_lock = threading.Lock()

    def service(self, service_id):
        if service_id not in self.services:
            raise ConfigError('Unknown service.')
        return self.services[service_id]

    @staticmethod
    def _item(service, values, error=None):
        return {'id': service.id, 'label': service.label, 'unit': service.unit,
                'description': service.description, 'can_control': service.control,
                'active_state': values.get('ActiveState', 'unknown'),
                'sub_state': values.get('SubState', 'unknown'),
                'load_state': values.get('LoadState', 'unknown'),
                **({'error': error} if error else {})}

    def list(self):
        try:
            result = self.runner([self.systemctl, 'show', '--property=Id,ActiveState,SubState,LoadState',
                                  '--', *(service.unit for service in SERVICES)], timeout=5, limit=32 * 1024)
        except (OSError, ServiceError) as error:
            return [self._item(service, {}, str(error)) for service in SERVICES]
        by_unit = {}
        for block in result['text'].strip().split('\n\n'):
            properties = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
            if properties.get('Id'):
                by_unit[properties['Id']] = properties
        error = result['text'].strip() if result['returncode'] and not by_unit else None
        return [self._item(service, by_unit.get(service.unit, {}), error) for service in SERVICES]

    def action(self, service_id, action):
        service = self.service(service_id)
        if not service.control:
            raise ConfigError('Manager cannot stop or restart itself from this app.')
        if action not in ('start', 'stop', 'restart'):
            raise ConfigError('Choose start, stop or restart.')
        if not self._action_lock.acquire(blocking=False):
            raise BusyError('Another service action is running. Refresh before retrying.')
        try:
            @contextmanager
            def no_guard():
                yield
            with self.flash_guard() if service.disruptive else no_guard():
                # Disruptive operations keep the flash lock until systemd has
                # completed the job. Queuing and releasing early would permit a
                # flasher to start while its transport is still being stopped.
                # Delayed DIS units can report activating without a long UI wait.
                args = [self.sudo, '-n', self.systemctl,
                        *([] if service.disruptive else ['--no-block']), action, service.unit]
                try:
                    result = self.runner(args, timeout=30 if service.disruptive else 10, limit=16 * 1024)
                except OSError as error:
                    raise ServiceError(f'Service control is unavailable: {error}') from None
                if result['returncode']:
                    raise ServiceError(result['text'].strip() or 'Service action failed. Check installed permissions.')
            return {'message': f'{service.label}: {action} requested. Refresh to see its current state.',
                    'service': next(item for item in self.list() if item['id'] == service_id)}
        finally:
            self._action_lock.release()

    def logs(self, service_id, lines=100):
        service = self.service(service_id)
        if type(lines) is not int or not 1 <= lines <= 500:
            raise ConfigError('Log line count must be between 1 and 500.')
        args = [self.journalctl, '-u', service.unit, '-n', str(lines),
                '--no-pager', '-o', 'short-iso']
        try:
            result = self.runner(args, timeout=10, limit=MAX_LOG_BYTES)
        except OSError as error:
            raise ServiceError(f'Journal access is unavailable: {error}') from None
        if result['returncode'] and not result['truncated']:
            raise ServiceError(result['text'].strip() or 'Cannot read this service journal. Check installed permissions.')
        return {'unit': service.unit, 'text': result['text'], 'lines': lines,
                'truncated': result['truncated']}
