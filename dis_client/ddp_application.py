"""Stock193PU application records; transport headers are removed by caller.

Only fields demonstrated by the native parsers are named. Unknown capability
bytes and extension records remain observable, rather than invented limits.
"""
from dataclasses import dataclass


def _record(payload):
    values = tuple(payload)
    if any(type(v) is not int or not 0 <= v <= 255 for v in values):
        raise ValueError('Application record must contain byte integers')
    return values


@dataclass(frozen=True)
class ClusterCapabilities:
    raw: tuple
    format_code: int
    company_code: int
    command_family: int
    opaque_fields: tuple

    @classmethod
    def parse(cls, payload):
        raw = _record(payload)
        if not 6 <= len(raw) <= 128 or raw[0] != 0x09:
            raise ValueError('Capabilities09 requires6..128 bytes')
        fmt, company = raw[1:3]
        if fmt == 0x20:
            family = 0x52
        elif fmt == 0x10:
            # Stock8055A4EE maps company03 to its third format. Unknown
            # companies retain the normal10 family, with raw data observable.
            family = 0x7A if company == 0x03 else 0x5A
        else:
            raise ValueError('Unsupported capability format%02X' % fmt)
        return cls(raw, fmt, company, family, raw[3:])


@dataclass(frozen=True)
class CapabilityObservation:
    """8055A4EE eligibility and last-valid-format retention, without I/O.

    An unknown wire format is an eligible09 in mode1, not a new typed family.
    Short/wrong-mode records do not change the previous family. Native timer
    cancellation precedes these checks; no native tick cadence is exposed here.
    """
    raw: tuple
    eligible: bool
    decoded: object
    selected: object
    disposition: str

    @classmethod
    def parse(cls, payload, mode, previous=None):
        raw = _record(payload)
        if not raw or raw[0] != 0x09 or len(raw) > 128:
            raise ValueError('Capability observation requires09 and at most128 bytes')
        if type(mode) is not int or mode != 1:
            return cls(raw, False, None, previous, 'wrong-mode')
        if len(raw) < 6:
            return cls(raw, False, None, previous, 'short')
        try:
            decoded = ClusterCapabilities.parse(raw)
        except ValueError:
            return cls(raw, True, None, previous, 'unknown-format-retained')
        return cls(raw, True, decoded, decoded, 'known-format')


@dataclass(frozen=True)
class WindowStatus:
    raw: tuple
    family: int
    value: int
    outcome: str

    @classmethod
    def parse(cls, payload):
        raw = _record(payload)
        if len(raw) < 2 or raw[0] not in (0x53, 0x5B, 0x7B):
            raise ValueError('Window status53/5B/7B requires at least2 bytes')
        value = raw[1]
        # Exactly the masks in stock805549D2, exhaustively p-code checked.
        outcome = ('fault' if value & 0x40 else 'unavailable' if not value & 3
                   else 'granted' if value & 0x80 else 'available')
        return cls(raw, raw[0], value, outcome)


@dataclass(frozen=True)
class ApplicationReply:
    raw: tuple
    reason: int
    command: int
    subcommand: object
    meaning: str

    @classmethod
    def parse(cls, payload):
        raw = _record(payload)
        if len(raw) < 3 or raw[0] != 0x0B:
            raise ValueError('Application reply0B requires at least3 bytes')
        command = raw[2]
        if command >= 0xE0 and len(raw) < 4:
            raise ValueError('Extended application reply requires subcommand')
        reason = raw[1]
        meanings = {1: 'unsupported-command', 2: 'incompatible-context',
                    3: 'invalid-parameters'}
        return cls(raw, reason, command, raw[3] if command >= 0xE0 else None,
                   meanings.get(reason, 'unknown-reason'))


def validate_priority(payload, full=False):
    """Native80554870 checks bytes2/3; byte1 is retained, not hardcoded."""
    raw = _record(payload)
    if len(raw) < 4 or raw[0] != 0x21:
        raise ValueError('Application setup21 requires at least4 bytes')
    if raw[2:4] == (0xFF, 0xFF):
        # Native80554870 returns1 for this sentinel; caller80554906 accepts
        #all nonnegative results as configured. Sentinel meaning is unknown.
        return raw
    if raw[2:4] != ((0x10 if full else 0xA0), 0):
        raise ValueError('Application setup priority does not match request')
    return raw
