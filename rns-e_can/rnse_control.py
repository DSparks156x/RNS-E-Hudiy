"""RNS-E brightness policy and the confirmed standard CAN command encoder.

This module never transmits. The base service queues commands through the
existing CAN gateway, which owns the final transmission inhibition guard.
"""
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol, Tuple


class BrightnessProtocol(Protocol):
    def validate_level(self, level: int) -> None:
        """Raise ValueError when a native level is outside the confirmed range."""

    def encode(self, level: int) -> Tuple[int, bytes]:
        """Return a standard CAN identifier and payload for a validated level."""


class RnseCanBrightnessProtocol:
    @staticmethod
    def validate_level(level: int) -> None:
        if type(level) is not int or not 0 <= level <= 10:
            raise ValueError('RNS-E brightness must be an integer from 0 to 10')

    def encode(self, level: int) -> Tuple[int, bytes]:
        self.validate_level(level)
        return 0x7B0, bytes([0xB7, level, 0, 0, 0, 0, 0, 0])


@dataclass(frozen=True)
class BrightnessSettings:
    enabled: bool = False
    day_brightness: Optional[int] = 10
    night_brightness: Optional[int] = 5

    @classmethod
    def from_config(cls, rnse: Mapping[str, Any]):
        if not isinstance(rnse, Mapping):
            raise ValueError('rnse must be an object')
        config = rnse.get('auto_brightness', {})
        if not isinstance(config, Mapping):
            raise ValueError('rnse.auto_brightness must be an object')
        enabled = config.get('enabled', False)
        if type(enabled) is not bool:
            raise ValueError('rnse.auto_brightness.enabled must be boolean')
        defaults = cls()
        levels = {}
        for name in ('day_brightness', 'night_brightness'):
            level = config.get(name, getattr(defaults, name))
            if level is not None and type(level) is not int:
                raise ValueError(f'rnse.auto_brightness.{name} must be an integer or null')
            if level is not None:
                RnseCanBrightnessProtocol.validate_level(level)
            levels[name] = level
        return cls(enabled=enabled, **levels)


@dataclass(frozen=True)
class BrightnessStatus:
    state: str
    mode: Optional[str]
    desired_level: Optional[int]
    protocol_available: bool
    error: Optional[str] = None


@dataclass(frozen=True)
class BrightnessCommand:
    mode: str
    level: int
    arbitration_id: int
    payload: bytes


class RnseBrightnessController:
    def __init__(self, settings: BrightnessSettings,
                 protocol: Optional[BrightnessProtocol] = None):
        self.settings = settings
        self.protocol = protocol
        self.mode: Optional[str] = None
        self.last_queued: Optional[Tuple[str, int]] = None

    @classmethod
    def from_config(cls, rnse: Mapping[str, Any]):
        return cls(BrightnessSettings.from_config(rnse), RnseCanBrightnessProtocol())

    def observe_lights(self, night: bool) -> bool:
        if type(night) is not bool:
            raise ValueError('confirmed night state must be boolean')
        mode = 'night' if night else 'day'
        changed = self.mode != mode
        self.mode = mode
        return changed

    def status(self, inhibited: bool = False) -> BrightnessStatus:
        level = (getattr(self.settings, self.mode + '_brightness')
                 if self.mode else None)
        available = self.protocol is not None
        error = None
        if not self.settings.enabled:
            state = 'disabled'
        elif not available:
            state = 'waiting_protocol'
        elif inhibited:
            state = 'inhibited'
        elif self.mode is None:
            state = 'waiting_vehicle_state'
        elif level is None:
            state = 'waiting_brightness'
        else:
            try:
                self.protocol.validate_level(level)
                state = 'ready'
            except ValueError as exc:
                state, error = 'invalid_brightness', str(exc)
        return BrightnessStatus(state, self.mode, level, available, error)

    def target(self, inhibited: bool = False) -> Optional[Tuple[str, int]]:
        """Return a validated policy target, never an applied/transmitted state."""
        status = self.status(inhibited)
        return ((status.mode, status.desired_level)
                if status.state == 'ready' else None)

    def force_reapply(self) -> None:
        self.last_queued = None

    def pending_command(self, radio_active: bool,
                        inhibited: bool = False) -> Optional[BrightnessCommand]:
        if not radio_active or inhibited or not self.settings.enabled:
            self.force_reapply()
            return None
        target = self.target()
        if target is None or target == self.last_queued:
            return None
        mode, level = target
        arbitration_id, payload = self.protocol.encode(level)
        return BrightnessCommand(mode, level, arbitration_id, payload)

    def mark_queued(self, command: BrightnessCommand) -> None:
        """Remember a queued event; this is not acknowledgment by the RNS-E."""
        self.last_queued = (command.mode, command.level)
