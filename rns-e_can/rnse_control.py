"""RNS-E bridge policy and encoder; this module never transmits CAN frames.

Targets the r38 firmware protocol: B7 sets the dial, BB the LCD override and
BA the source label, each deduplicated on its own. The base service commits
each distinct desired payload to the existing gateway once. Radio wake is the
only automatic reason to repeat a committed payload.
"""
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Protocol, Tuple


class BrightnessProtocol(Protocol):
    def validate_level(self, level: int) -> None:
        """Raise ValueError for unsupported dial levels."""

    def encode_dial(self, level: int) -> Tuple[int, bytes]:
        """Return a brightness dial command."""

    def encode_lcd(self, lcd_brightness: int) -> Tuple[int, bytes]:
        """Return an LCD brightness override command."""

    def encode_source(self, source: int) -> Tuple[int, bytes]:
        """Return a source label and icon command."""


class RnseCanBrightnessProtocol:
    @staticmethod
    def validate_level(level: int) -> None:
        if type(level) is not int or not 0 <= level <= 10:
            raise ValueError('RNS-E brightness must be an integer from 0 to 10')

    @staticmethod
    def validate_lcd(level: int) -> None:
        if type(level) is not int or not 0 <= level <= 100:
            raise ValueError('RNS-E LCD brightness must be an integer from 0 to 100')

    @staticmethod
    def validate_source(source: int) -> None:
        if type(source) is not int or not 0 <= source <= 2:
            raise ValueError('RNS-E source must be 0 (Hudiy), 1 (CarPlay) or 2 (Android Auto)')

    def encode_dial(self, level: int) -> Tuple[int, bytes]:
        self.validate_level(level)
        return 0x7B0, bytes([0xB7, level, 0, 0, 0, 0, 0, 0])

    def encode_lcd(self, lcd_brightness: int) -> Tuple[int, bytes]:
        # 0 restores native cluster dimming plus the dial; 1-100 is absolute.
        self.validate_lcd(lcd_brightness)
        return 0x7B0, bytes([0xBB, lcd_brightness, 0, 0, 0, 0, 0, 0])

    def encode_source(self, source: int) -> Tuple[int, bytes]:
        self.validate_source(source)
        return 0x7B0, bytes([0xBA, source, 0, 0, 0, 0, 0, 0])


@dataclass(frozen=True)
class BrightnessSettings:
    # Keep the original fields for existing base-service callers.
    enabled: bool = False
    day_brightness: Optional[int] = 10
    night_brightness: Optional[int] = 5
    manual_brightness: int = 10
    manual_lcd_brightness: int = 0
    lcd_enabled: bool = False
    lcd_day_brightness: Optional[int] = 100
    lcd_night_brightness: Optional[int] = 6
    source_label_enabled: bool = False
    manual_fields_present: bool = False

    @classmethod
    def from_config(cls, rnse: Mapping[str, Any]):
        if not isinstance(rnse, Mapping):
            raise ValueError('rnse must be an object')
        defaults = cls()
        values = {}
        for section, prefix, validator in (
                ('auto_brightness', '', RnseCanBrightnessProtocol.validate_level),
                ('auto_lcd_brightness', 'lcd_', RnseCanBrightnessProtocol.validate_lcd)):
            config = rnse.get(section, {})
            if not isinstance(config, Mapping):
                raise ValueError(f'rnse.{section} must be an object')
            enabled = config.get('enabled', False)
            if type(enabled) is not bool:
                raise ValueError(f'rnse.{section}.enabled must be boolean')
            values[prefix + 'enabled'] = enabled
            for name in ('day_brightness', 'night_brightness'):
                value = config.get(name, getattr(defaults, prefix + name))
                if value is not None:
                    validator(value)
                values[prefix + name] = value
        for name, validator in (
                ('manual_brightness', RnseCanBrightnessProtocol.validate_level),
                ('manual_lcd_brightness', RnseCanBrightnessProtocol.validate_lcd)):
            value = rnse.get(name, getattr(defaults, name))
            validator(value)
            values[name] = value
        source = rnse.get('source_label', {})
        if not isinstance(source, Mapping):
            raise ValueError('rnse.source_label must be an object')
        enabled = source.get('enabled', False)
        if type(enabled) is not bool:
            raise ValueError('rnse.source_label.enabled must be boolean')
        values['source_label_enabled'] = enabled
        values['manual_fields_present'] = any(
            name in rnse for name in ('manual_brightness', 'manual_lcd_brightness'))
        return cls(**values)


@dataclass(frozen=True)
class BrightnessStatus:
    state: str
    mode: Optional[str]
    desired_level: Optional[int]
    protocol_available: bool
    error: Optional[str] = None
    lcd_brightness: Optional[int] = None
    source: int = 0


@dataclass(frozen=True)
class BrightnessCommand:
    mode: str
    level: Optional[int]
    arbitration_id: int
    payload: bytes
    lcd_brightness: int = 0
    source: int = 0
    kind: str = 'dial'


class RnseBrightnessController:
    def __init__(self, settings: BrightnessSettings,
                 protocol: Optional[BrightnessProtocol] = None):
        self.settings = settings
        self.protocol = protocol
        self.mode: Optional[str] = None
        self.source = 0
        self.manual_overrides = {'brightness': None, 'lcd_brightness': None}
        self.last_dial_queued: Optional[bytes] = None
        self.last_lcd_queued: Optional[bytes] = None
        self.last_source_queued: Optional[bytes] = None
        self._radio_active: Optional[bool] = None

    @classmethod
    def from_config(cls, rnse: Mapping[str, Any]):
        return cls(BrightnessSettings.from_config(rnse), RnseCanBrightnessProtocol())

    def inherit_state(self, previous, clear_manual: bool = True) -> None:
        """Reload policy without inventing vehicle changes or repeating payloads."""
        if not isinstance(previous, RnseBrightnessController):
            return
        self.mode = previous.mode
        self.source = previous.source
        self.last_dial_queued = previous.last_dial_queued
        self.last_lcd_queued = previous.last_lcd_queued
        self.last_source_queued = previous.last_source_queued
        self._radio_active = previous._radio_active
        if not clear_manual:
            self.manual_overrides = dict(previous.manual_overrides)

    @property
    def enabled(self) -> bool:
        return self.brightness_enabled or self.settings.source_label_enabled

    @property
    def brightness_enabled(self) -> bool:
        settings = self.settings
        return (settings.enabled or settings.lcd_enabled or settings.manual_fields_present
                or any(value is not None for value in self.manual_overrides.values()))

    @property
    def has_control(self) -> bool:
        return self.enabled

    @property
    def needs_lights(self) -> bool:
        # Subscribe even while testing: the next real light edge resumes automation.
        return self.settings.enabled or self.settings.lcd_enabled

    def observe_lights(self, night: bool) -> bool:
        if type(night) is not bool:
            raise ValueError('confirmed night state must be boolean')
        mode = 'night' if night else 'day'
        changed = self.mode != mode
        if changed and self.mode is not None:
            if self.settings.enabled:
                self.manual_overrides['brightness'] = None
            if self.settings.lcd_enabled:
                self.manual_overrides['lcd_brightness'] = None
        self.mode = mode
        return changed

    def observe_source(self, source: int) -> bool:
        RnseCanBrightnessProtocol.validate_source(source)
        changed = self.source != source
        self.source = source
        return changed

    def set_manual(self, values: Mapping[str, Any]) -> bool:
        """Atomically update live test values; no config writes."""
        if not isinstance(values, Mapping) or not values:
            raise ValueError('manual overrides must be a non-empty object')
        if set(values) - set(self.manual_overrides):
            raise ValueError('manual overrides only accept brightness and lcd_brightness')
        validators = {'brightness': RnseCanBrightnessProtocol.validate_level,
                      'lcd_brightness': RnseCanBrightnessProtocol.validate_lcd}
        for name, value in values.items():
            if value is not None:
                validators[name](value)
        updated = {**self.manual_overrides, **values}
        changed = updated != self.manual_overrides
        self.manual_overrides = updated
        return changed

    def _desired(self):
        level = self.manual_overrides['brightness']
        if level is None:
            level = (getattr(self.settings, self.mode + '_brightness') if self.mode else None
                     ) if self.settings.enabled else self.settings.manual_brightness
        lcd = self.manual_overrides['lcd_brightness']
        if lcd is None:
            lcd = (getattr(self.settings, 'lcd_' + self.mode + '_brightness') if self.mode else None
                   ) if self.settings.lcd_enabled else self.settings.manual_lcd_brightness
        source = self.source if self.settings.source_label_enabled else 0
        return level, lcd, source

    def _brightness_state(self, inhibited: bool = False):
        level, lcd, _source = self._desired()
        available = self.protocol is not None
        error = None
        unresolved_auto = ((self.settings.enabled and self.manual_overrides['brightness'] is None)
                           or (self.settings.lcd_enabled and self.manual_overrides['lcd_brightness'] is None))
        if not self.brightness_enabled:
            state = 'disabled'
        elif not available:
            state = 'waiting_protocol'
        elif inhibited:
            state = 'inhibited'
        elif unresolved_auto and self.mode is None:
            state = 'waiting_vehicle_state'
        elif level is None or lcd is None:
            state = 'waiting_brightness'
        else:
            try:
                RnseCanBrightnessProtocol.validate_level(level)
                self.protocol.validate_level(level)
                RnseCanBrightnessProtocol.validate_lcd(lcd)
                state = 'ready'
            except ValueError as exc:
                state, error = 'invalid_brightness', str(exc)
        return state, error

    def _source_state(self, inhibited: bool = False):
        if not self.settings.source_label_enabled:
            return 'disabled', None
        if self.protocol is None:
            return 'waiting_protocol', None
        if inhibited:
            return 'inhibited', None
        try:
            RnseCanBrightnessProtocol.validate_source(self.source)
        except ValueError as exc:
            return 'invalid_source', str(exc)
        return 'ready', None

    def status(self, inhibited: bool = False) -> BrightnessStatus:
        level, lcd, source = self._desired()
        brightness_state, brightness_error = self._brightness_state(inhibited)
        source_state, source_error = self._source_state(inhibited)
        if brightness_state == 'ready' or source_state == 'ready':
            state, error = 'ready', brightness_error or source_error
        elif self.brightness_enabled:
            state, error = brightness_state, brightness_error
        else:
            state, error = source_state, source_error
        return BrightnessStatus(state, self.mode, level, self.protocol is not None,
                                error, lcd, source)

    def target(self, inhibited: bool = False) -> Optional[Tuple[str, int]]:
        """Compatibility view of the dial policy target, never applied state."""
        status = self.status(inhibited)
        return ((status.mode or 'manual', status.desired_level)
                if self._brightness_state(inhibited)[0] == 'ready' else None)

    def snapshot(self, inhibited: bool = False):
        status = self.status(inhibited)
        level, lcd, source = self._desired()
        brightness_state, _ = self._brightness_state(inhibited)
        source_state, _ = self._source_state(inhibited)
        ready = brightness_state == 'ready'
        dial_queued = ready and self.protocol.encode_dial(level)[1] == self.last_dial_queued
        lcd_queued = ready and self.protocol.encode_lcd(lcd)[1] == self.last_lcd_queued
        brightness_queued = dial_queued and lcd_queued
        source_payload = (self.protocol.encode_source(source)[1]
                          if source_state == 'ready' else None)
        source_queued = source_payload is not None and source_payload == self.last_source_queued
        return {
            'state': status.state, 'mode': status.mode,
            'level': level, 'desired_level': level, 'lcd_brightness': lcd,
            'effective_lcd_brightness': (max(6, lcd) if lcd else lcd),
            'source': source, 'observed_source': self.source,
            'manual_overrides': dict(self.manual_overrides),
            'settings': {
                'auto_brightness': {'enabled': self.settings.enabled,
                                    'day_brightness': self.settings.day_brightness,
                                    'night_brightness': self.settings.night_brightness},
                'manual_brightness': self.settings.manual_brightness,
                'manual_lcd_brightness': self.settings.manual_lcd_brightness,
                'auto_lcd_brightness': {'enabled': self.settings.lcd_enabled,
                                        'day_brightness': self.settings.lcd_day_brightness,
                                        'night_brightness': self.settings.lcd_night_brightness},
                'source_label': {'enabled': self.settings.source_label_enabled},
            },
            'enabled': self.enabled, 'needs_lights': self.needs_lights,
            'protocol_available': status.protocol_available, 'error': status.error,
            'brightness_state': brightness_state, 'source_state': source_state,
            'brightness_queued': brightness_queued, 'dial_queued': dial_queued,
            'lcd_queued': lcd_queued, 'source_queued': source_queued,
            'queued': (status.state == 'ready'
                       and (brightness_state != 'ready' or brightness_queued)
                       and (source_state != 'ready' or source_queued)),
        }

    def force_reapply(self) -> None:
        """Explicit radio wake re-arms each enabled command once."""
        self.last_dial_queued = None
        self.last_lcd_queued = None
        self.last_source_queued = None

    def pending_command(self, radio_active: bool,
                        inhibited: bool = False) -> Optional[BrightnessCommand]:
        """Compatibility view of the first independently pending command."""
        commands = self.pending_commands(radio_active, inhibited)
        return commands[0] if commands else None

    def pending_commands(self, radio_active: bool,
                         inhibited: bool = False) -> List[BrightnessCommand]:
        """Propose independent B7, BB and BA commands without committing any."""
        if not radio_active:
            if self._radio_active is not False:
                self.force_reapply()
            self._radio_active = False
            return []
        self._radio_active = True
        level, lcd, source = self._desired()
        commands = []
        if self._brightness_state(inhibited)[0] == 'ready':
            arbitration_id, payload = self.protocol.encode_dial(level)
            if payload != self.last_dial_queued:
                commands.append(BrightnessCommand(self.mode or 'manual', level,
                    arbitration_id, payload, lcd, kind='dial'))
            arbitration_id, payload = self.protocol.encode_lcd(lcd)
            if payload != self.last_lcd_queued:
                commands.append(BrightnessCommand(self.mode or 'manual', level,
                    arbitration_id, payload, lcd, kind='lcd'))
        if self._source_state(inhibited)[0] == 'ready':
            arbitration_id, payload = self.protocol.encode_source(source)
            if payload != self.last_source_queued:
                commands.append(BrightnessCommand(self.mode or 'manual', None,
                    arbitration_id, payload, source=source, kind='source'))
        return commands

    def mark_queued(self, command: BrightnessCommand) -> None:
        """Record one committed payload; this is not an RNS-E acknowledgment."""
        if command.kind == 'dial':
            self.last_dial_queued = command.payload
        elif command.kind == 'lcd':
            self.last_lcd_queued = command.payload
        elif command.kind == 'source':
            self.last_source_queued = command.payload
        else:
            raise ValueError('unknown RNS-E command kind')
