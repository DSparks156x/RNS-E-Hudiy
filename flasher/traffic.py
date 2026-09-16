"""Persistent application TX inhibition; the flasher's private CAN path is exempt.

Linux flock serializes mode changes with actual sends across processes. The
Windows lock is provided for offline tests only; production runs on Linux.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading

try:
    import fcntl
except ImportError:
    fcntl = None

_local_locks = {}
_registry_lock = threading.Lock()


def _directory():
    return Path(os.path.expanduser('~/.hudiy'))


@contextmanager
def _locked(name, nonblocking=False):
    directory = _directory()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (name + '.lock' if name.endswith('.json') else name)
    with _registry_lock:
        lock = _local_locks.setdefault(str(path), threading.Lock())
    if not lock.acquire(blocking=not nonblocking):
        raise RuntimeError('A flasher operation is active; Flashing Mode cannot be turned off')
    handle = None
    try:
        handle = open(path, 'a+b')
        if fcntl:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
            except BlockingIOError:
                raise RuntimeError('A flasher operation is active; Flashing Mode cannot be turned off') from None
        yield handle
    finally:
        if handle is not None:
            if fcntl:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()
        lock.release()


def _enabled(handle):
    if (_directory() / 'haldex_recovery_required.json').exists():
        return True
    path = _directory() / 'flashing_mode.json'
    if not path.exists():
        return False
    try:
        value = json.loads(path.read_bytes())
        return value.get('enabled') is not False
    except (ValueError, AttributeError):
        return True  # Corrupt/partial saved state must not enable transmissions.


def _write(handle, enabled):
    path = _directory() / 'flashing_mode.json'
    temporary = path.with_suffix('.tmp')
    with open(temporary, 'wb') as output:
        output.write(json.dumps({'enabled': bool(enabled)}).encode('utf-8'))
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
    if hasattr(os, 'O_DIRECTORY'):
        fd = os.open(_directory(), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def flashing_mode_enabled():
    with _locked('flashing_mode.json') as handle:
        return _enabled(handle)


def set_flashing_mode(enabled):
    if type(enabled) is not bool:
        raise ValueError('Flashing Mode must be boolean')
    if enabled:
        with _locked('flashing_mode.json') as handle:
            _write(handle, True)
    else:
        with _locked('flashing_operation.lock', nonblocking=True):
            if (_directory() / 'haldex_recovery_required.json').exists():
                raise RuntimeError('Controller has an incomplete flash; Flashing Mode remains on until flashing completes')
            with _locked('flashing_mode.json') as handle:
                _write(handle, False)
    return enabled


def toggle_flashing_mode():
    with _locked('flashing_operation.lock', nonblocking=True):
        with _locked('flashing_mode.json') as handle:
            enabled = not _enabled(handle)
            if not enabled and (_directory() / 'haldex_recovery_required.json').exists():
                raise RuntimeError('Controller has an incomplete flash; Flashing Mode remains on until flashing completes')
            _write(handle, enabled)
            return enabled


@contextmanager
def transmission_guard():
    """Hold across a single actual send; a returned False means discard it."""
    with _locked('flashing_mode.json') as handle:
        yield not _enabled(handle)


@contextmanager
def flashing_operation():
    """Prevent manual disable throughout acquisition, flashing and cleanup."""
    with _locked('flashing_operation.lock', nonblocking=True):
        yield
