"""Named configuration files with revision checks and recoverable replacement."""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile
import threading

try:
    import fcntl
except ImportError:  # Offline Windows tests; installed services use flock.
    fcntl = None

MAX_CONFIG_BYTES = 2 * 1024 * 1024
_locks = {}
_lock_registry = threading.Lock()


class ConfigError(ValueError):
    status = 400


class ConflictError(ConfigError):
    status = 409


@dataclass(frozen=True)
class ConfigTarget:
    id: str
    label: str
    path: Path
    required_arrays: tuple = ()
    affected_services: tuple = ()


def _no_symlink(path):
    path = Path(path).absolute()
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise ConfigError('Configuration and backup paths cannot use symbolic links.')
    return path


def _object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def parse_document(content):
    if len(content) > MAX_CONFIG_BYTES:
        raise ConfigError('Configuration exceeds the 2 MiB limit.')
    try:
        return json.loads(content.decode('utf-8-sig'), object_pairs_hook=_object_pairs,
                          parse_constant=lambda value: (_ for _ in ()).throw(
                              ConfigError(f'Nonfinite JSON number: {value}')))
    except (UnicodeDecodeError, ValueError, RecursionError) as error:
        if isinstance(error, ConfigError):
            raise
        raise ConfigError(f'Invalid JSON: {error}') from None


def _finite(value, depth=0):
    if depth > 64:
        raise ConfigError('Configuration nesting exceeds 64 levels.')
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigError('Configuration numbers must be finite.')
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ConfigError('Configuration object keys must be strings.')
            _finite(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _finite(child, depth + 1)
    elif value is not None and type(value) not in (str, int, float, bool):
        raise ConfigError('Configuration must contain JSON values.')


def validate_document(target, document):
    if not isinstance(document, dict):
        raise ConfigError('Configuration must be a JSON object.')
    _finite(document)
    if target.id == 'rnse':
        # Check structural contracts, without deleting custom/forward-compatible settings.
        sections = ('interfaces', 'diagnostics', 'haldex', 'eps', 'exhaust_valve',
                    'data_logger', 'data_logs', 'file_portal', 'openpilot', 'display',
                    'features', 'can_ids', 'input_mappings', 'rnse')
        for section in sections:
            if section in document and not isinstance(document[section], dict):
                raise ConfigError(f'{section} must be an object.')
        if not isinstance(document.get('interfaces'), dict):
            raise ConfigError('Integration configuration needs an interfaces object.')
        for section in ('can', 'zmq'):
            if section in document['interfaces'] and not isinstance(document['interfaces'][section], dict):
                raise ConfigError(f'interfaces.{section} must be an object.')
        for key in ('branch', 'repo', 'config_restore_branch', 'config_restore_repo'):
            if key in document and not isinstance(document[key], str):
                raise ConfigError(f'{key} must be text.')
        for section in ('diagnostics', 'haldex', 'openpilot'):
            value = document.get(section, {})
            if 'enabled' in value and type(value['enabled']) is not bool:
                raise ConfigError(f'{section}.enabled must be boolean.')
        rnse = document.get('rnse', {})
        if 'auto_brightness' in rnse:
            brightness = rnse['auto_brightness']
            if not isinstance(brightness, dict):
                raise ConfigError('rnse.auto_brightness must be an object.')
            if 'enabled' in brightness and type(brightness['enabled']) is not bool:
                raise ConfigError('rnse.auto_brightness.enabled must be boolean.')
            for key in ('day_brightness', 'night_brightness'):
                value = brightness.get(key)
                if value is not None and (type(value) is not int or not 0 <= value <= 10):
                    raise ConfigError(f'rnse.auto_brightness.{key} must be an integer from 0 to 10 or null.')
                if brightness.get('enabled') is True and value is None:
                    raise ConfigError(f'Set rnse.auto_brightness.{key} to a level from 0 to 10 before enabling it.')
    elif target.id == 'hudiy-main':
        if not document:
            raise ConfigError('Hudiy main configuration cannot be empty.')
        # Validate known section shapes; custom/new fields remain untouched.
        sections = ('application', 'appearance', 'theme', 'sound', 'androidAuto',
                    'hotspot', 'equalizer', 'notificatons', 'notifications', 'fmRadio',
                    'autobox', 'obd', 'api', 'reverseCamera', 'bluetooth')
        for key in sections:
            if key in document and not isinstance(document[key], dict):
                raise ConfigError(f'Hudiy main section {key} must be an object.')
    for key in target.required_arrays:
        value = document.get(key)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ConfigError(f'{key} must be an array of objects.')
    try:
        content = (json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')
    except (ValueError, TypeError, RecursionError) as error:
        raise ConfigError(f'Invalid JSON document: {error}') from None
    if len(content) > MAX_CONFIG_BYTES:
        raise ConfigError('Configuration exceeds the 2 MiB limit.')
    return content


class ConfigStore:
    def __init__(self, project_root=None, home=None):
        self.project_root = Path(project_root or Path(__file__).resolve().parents[1]).absolute()
        self.home = Path(home or Path.home()).absolute()
        hudiy = self.home / '.hudiy' / 'share' / 'config'
        services = ('can_handler', 'can_base_function', 'tp2_worker', 'can_keyboard_control',
                    'dark_mode_api', 'hudiy_data_api', 'hudiy_dataview', 'hudiy_status_service',
                    'dis_service', 'dis_display', 'dis_top_display', 'haldex_manager')
        self.targets = {target.id: target for target in (
            ConfigTarget('rnse', 'RNS-E integration', self.project_root / 'config.json', affected_services=services),
            ConfigTarget('hudiy-main', 'Hudiy main settings', hudiy / 'main_configuration.json'),
            ConfigTarget('hudiy-applications', 'Hudiy applications', hudiy / 'applications.json', ('applications',)),
            ConfigTarget('hudiy-menu', 'Hudiy applications menu', hudiy / 'applications_menu.json', ('categories', 'items')),
            ConfigTarget('hudiy-shortcuts', 'Hudiy shortcuts', hudiy / 'shortcuts.json', ('shortcuts',)),
            ConfigTarget('hudiy-dashboards', 'Hudiy dashboards', hudiy / 'dashboards.json', ('dashboards',)),
        )}

    def target(self, target_id):
        if target_id not in self.targets:
            raise ConfigError('Unknown configuration target.')
        target = self.targets[target_id]
        _no_symlink(target.path)
        return target

    @contextmanager
    def locked(self):
        directory = _no_symlink(self.home / '.hudiy')
        directory.mkdir(parents=True, exist_ok=True)
        path = _no_symlink(directory / 'management-config.lock')
        with _lock_registry:
            lock = _locks.setdefault(str(path), threading.RLock())
        with lock:
            flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(path, flags, 0o600)
            try:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_EX)
                yield
            finally:
                if fcntl:
                    fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def _read_bytes(self, target):
        _no_symlink(target.path)
        try:
            if not stat.S_ISREG(target.path.lstat().st_mode):
                raise ConfigError('Configuration target must be a regular file.')
            fd = os.open(target.path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        except FileNotFoundError:
            return None
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ConfigError('Configuration target must be a regular file.')
            content = stream.read(MAX_CONFIG_BYTES + 1)
        if len(content) > MAX_CONFIG_BYTES:
            raise ConfigError('Existing configuration exceeds the 2 MiB limit.')
        return content

    @staticmethod
    def _revision(content):
        return hashlib.sha256(content).hexdigest() if content is not None else 'missing'

    def list(self):
        result = []
        for target in self.targets.values():
            result.append({'id': target.id, 'label': target.label, 'filename': target.path.name,
                           'exists': target.path.is_file(), 'affected_services': list(target.affected_services)})
        return result

    def read(self, target_id):
        target = self.target(target_id)
        with self.locked():
            content = self._read_bytes(target)
            return {'id': target.id, 'label': target.label, 'filename': target.path.name,
                    'document': parse_document(content) if content is not None else {},
                    'revision': self._revision(content), 'exists': content is not None,
                    'affected_services': list(target.affected_services)}

    def pin(self):
        try:
            with self.locked():
                content = self._read_bytes(self.target('rnse'))
            config = parse_document(content) if content else {}
            return str(config.get('file_portal', {}).get('upload_pin', ''))
        except (ConfigError, OSError, AttributeError):
            # An unreadable installed config must not silently bypass its PIN.
            raise ConfigError('Installed integration configuration is unreadable; restore it locally first.') from None

    def save(self, target_id, document, revision):
        target = self.target(target_id)
        if not isinstance(revision, str) or not revision:
            raise ConflictError('Load the current configuration before saving; a revision is required.')
        content = validate_document(target, document)
        with self.locked():
            old = self._read_bytes(target)
            if self._revision(old) != revision:
                raise ConflictError('This configuration changed since it was opened. Reload before saving.')
            backup = None
            mode = stat.S_IMODE(target.path.stat().st_mode) if old is not None else 0o600
            if old is not None:
                backup_root = _no_symlink(self.home / 'confbackup' / datetime.now().strftime('%Y-%m-%d'))
                backup_root.mkdir(parents=True, exist_ok=True)
                index = 1
                while True:
                    folder = _no_symlink(backup_root / str(index))
                    try:
                        folder.mkdir()
                        break
                    except FileExistsError:
                        index += 1
                backup = folder / target.path.name
                with open(backup, 'xb') as output:
                    output.write(old)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(backup, mode)
            _no_symlink(target.path.parent).mkdir(parents=True, exist_ok=True)
            temporary_path = None
            try:
                fd, temporary_path = tempfile.mkstemp(prefix='.management-', suffix='.json', dir=target.path.parent)
                with os.fdopen(fd, 'wb') as output:
                    output.write(content)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary_path, mode)
                _no_symlink(target.path)
                # Check again immediately before publication; catches cooperating external edits.
                if self._revision(self._read_bytes(target)) != revision:
                    raise ConflictError('Configuration changed during save. Reload before saving.')
                os.replace(temporary_path, target.path)
                temporary_path = None
                if hasattr(os, 'O_DIRECTORY'):
                    directory_fd = os.open(target.path.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
            finally:
                if temporary_path is not None:
                    os.unlink(temporary_path)
            return {'id': target.id, 'document': document, 'revision': self._revision(content),
                    'backup': str(backup) if backup else None,
                    'affected_services': list(target.affected_services),
                    'message': 'Configuration saved. Running services retain their settings until restarted.'}
