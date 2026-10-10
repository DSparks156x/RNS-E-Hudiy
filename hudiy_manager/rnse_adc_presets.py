"""Named ADC byte maps saved separately; reading a preset never applies it."""
import json
import os
import tempfile

from .config_store import ConfigError, ConfigTarget, _no_symlink, parse_document
from .rnse_adc_protocol import validate_values

MAX_PRESET_BYTES = 16384
MAX_PRESETS = 32


def validate_name(name):
    if (not isinstance(name, str) or not name.strip() or name != name.strip()
            or len(name) > 64 or any(ord(char) < 32 for char in name)):
        raise ConfigError('Preset names must contain 1 to 64 characters without surrounding whitespace or control characters.')
    return name


class AdcPresets:
    def __init__(self, store):
        self.store = store
        self.path = store.home / '.hudiy' / 'rnse-adc-presets.json'

    def _read(self):
        content = self.store._read_bytes(ConfigTarget('adc-presets', 'ADC presets', self.path))
        if content is None:
            return {}
        if len(content) > MAX_PRESET_BYTES:
            raise ConfigError('ADC preset file exceeds the 16 KiB limit.')
        document = parse_document(content)
        if not isinstance(document, dict) or len(document) > MAX_PRESETS:
            raise ConfigError('ADC preset file must contain at most 32 named presets.')
        result = {}
        for name, values in document.items():
            validate_name(name)
            try:
                result[name] = validate_values(values)
            except ValueError as error:
                raise ConfigError(str(error)) from None
        return result

    def list(self):
        with self.store.locked():
            return {'presets': self._read()}

    def save(self, name, values):
        validate_name(name)
        try:
            values = validate_values(values)
        except ValueError as error:
            raise ConfigError(str(error)) from None
        with self.store.locked():
            document = self._read()
            if name not in document and len(document) >= MAX_PRESETS:
                raise ConfigError('ADC presets are limited to 32 names.')
            document[name] = values
            content = (json.dumps(document, indent=2, sort_keys=True) + '\n').encode('utf-8')
            if len(content) > MAX_PRESET_BYTES:
                raise ConfigError('ADC presets exceed the 16 KiB limit.')
            _no_symlink(self.path)
            descriptor, temporary = tempfile.mkstemp(prefix='.adc-presets-', dir=self.path.parent)
            try:
                with os.fdopen(descriptor, 'wb') as handle:
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.chmod(temporary, 0o600)
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {'presets': document}
