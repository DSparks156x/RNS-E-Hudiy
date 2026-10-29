"""Volatile AK5406 ADC commands and readbacks; no hardware or web dependencies.

Register map: RNSE hacking/analysis/ak5406_v1/PI_UI_REGISTERS.md.
"""
import re
import time

COMMAND_ID = 0x7B0
DEFAULT_REPLY_ID = '0x7B6'
# The BD dump is 39 bytes on the wire, but only 00-1D and 24 are real; the
# rest are aliases or test space and stay hidden.
REGISTERS = tuple(range(0x1E)) + (0x24, 0x31, 0x35, 0x36, 0x37, 0x41, 0x43, 0x45, 0x46)
DUMP_VISIBLE = tuple(range(0x1E)) + (0x24,)
# Not in the dump: shown from the last confirmed W readback.
CACHED = tuple(range(0x1E, 0x24)) + tuple(range(0x25, 0x29))
# 0B-0D and 14 are reserved, 0F holds power-down, 15/16 the output format.
WRITABLE = (frozenset(range(0x01, 0x14)) - {0x0B, 0x0C, 0x0D, 0x0F}) | frozenset(range(0x17, 0x29))
# Stock BC range; 17/18, 1C and 1D-28 need the BC widening patch.
WRITABLE_NOW = frozenset(register for register in WRITABLE if register < 0x14 or 0x19 <= register <= 0x1B)
# Multi-byte values latch on the second byte; both bytes go in one batch, first then second.
PAIRS = (('01', '02'), ('17', '18'), ('19', '1A'), ('1B', '1C'), ('1D', '1E'), ('1F', '20'), ('21', '22'))
CLOCK_REGISTERS = ('01', '02', '03')
CLAMP_LIMIT = 104
EXACT = {'0E': (0x25, 0x2D), '24': (0x58, 0x78), '28': (0xA0, 0xB0, 0xE0, 0xF0)}
# Firmware (r36-r53) values at 480p.
FIRMWARE = {'01': 0x3F, '02': 0x50, '03': 0x30, '04': 0x80, '05': 0x16, '06': 0x2F, '07': 0x70,
            '08': 0x70, '09': 0x70, '0A': 0x70, '0E': 0x2D, '10': 0x00, '11': 0x20, '12': 0x06,
            '13': 0x06, '17': 0x01, '18': 0x00, '19': 0x01, '1A': 0x00, '1B': 0x01, '1C': 0x00,
            '1D': 0, '1E': 0, '1F': 0, '20': 0, '21': 0, '22': 0, '23': 0x00, '24': 0x58,
            '25': 0, '26': 0, '27': 0, '28': 0xF0}
# Stock-writable registers first: without the widening patch the batch stops at 23.
REVERT_DEFAULTS = {key: FIRMWARE[key] for key in (
    '01', '02', '03', '04', '05', '06', '07', '08', '09', '0A', '0E', '10', '11', '12', '13',
    '23', '24', '25', '26', '27', '28')}


def reply_identifier(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'0[xX][0-9a-fA-F]{1,3}', value):
        raise ValueError('can_ids.rnse_adc_reply must be null or a standard hexadecimal CAN ID.')
    result = int(value, 16)
    if result > 0x7FF or result == COMMAND_ID:
        raise ValueError('ADC reply ID must be a standard CAN ID different from 0x7B0.')
    return result


def _signed9(msb, lsb):
    value = (msb << 8) | lsb
    return value - 0x200 if value & 0x100 else value


def _check_byte(key, value):
    if key in EXACT and value not in EXACT[key]:
        raise ValueError(f'ADC register {key} only accepts ' + ', '.join(f'{byte:02X}' for byte in EXACT[key]) + '.')
    if key == '03' and (value & 7 or value >> 6 > 2 or (value >> 3) & 7 > 6):
        raise ValueError('ADC register 03 needs VCO range 0-2, charge pump 0-6 and bits 2:0 clear.')
    if key in ('04', '10') and value & 7:
        raise ValueError(f'ADC register {key} must have its low three bits clear.')
    if key == '02' and value & 0x0F:
        raise ValueError('ADC register 02 must have its low four bits clear.')
    if key in ('05', '06', '07') and value == 0:
        raise ValueError(f'ADC register {key} must be 1-255.')
    if key in ('17', '19', '1B', '1D', '1F', '21') and value > 1:
        raise ValueError(f'ADC register {key} is a 9-bit MSB and must be 0 or 1.')
    if key == '25' and value == 255:
        raise ValueError('ADC register 25 must be 0-254.')


def validate_values(values):
    """Check bytes against the AK5406 map and return them in send order."""
    if not isinstance(values, dict) or not values or len(values) > len(WRITABLE):
        raise ValueError('Provide a non-empty ADC register-to-byte object.')
    result = {}
    for key, value in values.items():
        if not isinstance(key, str) or not re.fullmatch(r'[0-9A-Fa-f]{2}', key):
            raise ValueError('ADC register keys must be two hexadecimal digits.')
        register = int(key, 16)
        if register not in WRITABLE:
            raise ValueError('ADC register is read-only or unsafe to write: ' + key)
        if type(value) is not int or not 0 <= value <= 255:
            raise ValueError('ADC values must be integer bytes from 0 to 255.')
        canonical = f'{register:02X}'
        if canonical in result:
            raise ValueError('Duplicate ADC register: ' + canonical)
        _check_byte(canonical, value)
        result[canonical] = value
    for first, second in PAIRS:
        if (first in result) != (second in result):
            raise ValueError(f'ADC registers {first} and {second} are one value; send both.')
    if '01' in result and not 223 <= (result['01'] << 4) | (result['02'] >> 4) <= 4095:
        raise ValueError('ADC line length must be 224-4096 clocks.')
    for first, second in (('1D', '1E'), ('1F', '20'), ('21', '22')):
        if first in result and not -16 <= _signed9(result[first], result[second]) <= 80:
            raise ValueError('ADC black targets must be -4 to +20 codes.')
    if '05' in result and '06' in result and result['05'] + result['06'] > CLAMP_LIMIT:
        raise ValueError(f'ADC clamp start plus length must be at most {CLAMP_LIMIT} clocks.')
    if '25' in result and '06' in result and result['25'] >= result['06']:
        raise ValueError('ADC clamp/black-loop split must be less than the clamp length.')
    return dict(sorted(result.items()))


class AdcController:
    """Explicit user commands only. Queue success never implies chip success."""
    def __init__(self, reply_id=None, clock=time.monotonic):
        self.reply_id = reply_id
        self.clock = clock
        self.values = {}
        self.baseline = None
        self.failed = set()
        self.writes = {}
        # Last confirmed 01-03; TV mode re-initialisation overwrites them.
        self.clock_tuned = {}
        self.dump = {'state': 'idle', 'received_sequences': [], 'error': None}
        self.partial = None
        self.dump_deadline = None
        self.dump_generation = 0
        self.clamp_uncertain = False
        self._write_queue = []
        self._write_send = None
        self._active_write = None
        self._unconfirmed_deadline = None
        self._dump_blocked = False

    @property
    def busy(self):
        return (self.dump_deadline is not None
                or self._active_write is not None or bool(self._write_queue)
                or self._unconfirmed_deadline is not None)

    def advance(self, send):
        """Refresh the guarded callback and expire explicitly requested operations."""
        self._write_send = send
        self.expire()

    def expire(self):
        now = self.clock()
        if self._unconfirmed_deadline is not None and now >= self._unconfirmed_deadline:
            self._unconfirmed_deadline = None
        if self._active_write is not None:
            key = self._active_write
            item = self.writes[key]
            if now >= item['_deadline']:
                item['state'] = 'timeout'
                if key in ('05', '06'):
                    self.clamp_uncertain = True
                self._stop_writes()
        if self.dump_deadline is not None and now >= self.dump_deadline:
            self._invalid('ADC dump timed out before all eight frames arrived.', 'timeout')

    def write(self, values, send):
        values = validate_values(values)
        return self._write(values, send)

    def revert(self, send):
        return self._write(REVERT_DEFAULTS, send)

    def resend_clock(self, send):
        values = {key: self.clock_tuned[key] for key in CLOCK_REGISTERS if key in self.clock_tuned}
        if '01' not in values or '02' not in values:
            values.pop('01', None)
            values.pop('02', None)
        if not values:
            raise ValueError('No confirmed clock writes (01-03) to re-send.')
        return self._write(values, send)

    def _known(self, key):
        pending = self.writes.get(key, {})
        if pending.get('state') == 'queued_unconfirmed':
            return pending['requested']
        known = self.values.get(int(key, 16))
        return known if known is not None else FIRMWARE[key]

    def _write(self, values, send):
        self.expire()
        if self.busy:
            raise ValueError('Wait for pending ADC commands before writing registers.')
        if self.reply_id is None and len(values) > 1:
            raise ValueError('Configure the ADC reply CAN ID before sending a multi-register batch.')
        keys = list(values)
        if any(key in values for key in ('05', '06', '25')):
            if self.clamp_uncertain and ('05' in values or '06' in values):
                raise ValueError('ADC clamp write is unconfirmed. Complete a fresh Dump before changing the clamp again.')
            if any(self.writes.get(key, {}).get('state') == 'pending' for key in ('05', '06')):
                raise ValueError('Wait for the pending ADC clamp acknowledgement before changing the clamp.')
            known = {key: self._known(key) for key in ('05', '06', '25')}
            final = {key: values.get(key, known[key]) for key in known}
            if final['05'] + final['06'] > CLAMP_LIMIT:
                raise ValueError(f'ADC clamp start plus length must be at most {CLAMP_LIMIT} clocks.')
            if final['25'] >= final['06']:
                raise ValueError('ADC clamp/black-loop split must be less than the clamp length.')
            # Order so no intermediate hardware state breaks either rule:
            # shrink the length last when start grows, and the split first.
            if '05' in values and '06' in values and values['05'] + known['06'] > CLAMP_LIMIT:
                keys.remove('06')
                keys.insert(keys.index('05'), '06')
            if '06' in values and '25' in values and known['25'] >= values['06']:
                keys.remove('25')
                keys.insert(keys.index('06'), '25')
        self._write_send = send
        for key in keys:
            self.writes[key] = {'requested': values[key], 'readback': None, 'status': None,
                                'state': 'queued'}
        self._write_queue = keys
        return self._send_next_write()

    def _stop_writes(self):
        for key in self._write_queue:
            self.writes[key]['state'] = 'not_sent'
        self._write_queue = []
        self._active_write = None

    def _send_next_write(self):
        if not self._write_queue:
            self._active_write = None
            return True
        key = self._write_queue.pop(0)
        item = self.writes[key]
        queued = self._write_send(COMMAND_ID, bytes((0xBC, int(key, 16), item['requested'], 0, 0, 0, 0, 0)).hex())
        if not queued:
            item['state'] = 'queue_failed'
            self._stop_writes()
            return False
        if self.reply_id is None:
            item['state'] = 'queued_unconfirmed'
            self._unconfirmed_deadline = self.clock() + 0.2
        else:
            item.update(state='pending', _deadline=self.clock() + 2)
            self._active_write = key
        return True

    def request_dump(self, send):
        self.expire()
        if self.busy:
            raise ValueError('Wait for pending ADC commands before requesting a dump.')
        self.partial = None
        self._dump_blocked = False
        queued = send(COMMAND_ID, bytes((0xBD, 0, 0, 0, 0, 0, 0, 0)).hex())
        self.dump = {'state': ('waiting' if self.reply_id is not None else 'queued_unconfirmed') if queued else 'queue_failed',
                     'received_sequences': [], 'error': None}
        self.dump_deadline = self.clock() + 3 if queued and self.reply_id is not None else None
        if queued and self.reply_id is None:
            self._unconfirmed_deadline = self.clock() + 0.2
        return queued

    def _invalid(self, message, state='invalid'):
        self.partial = None
        self.dump_deadline = None
        self._dump_blocked = True
        self.dump.update(state=state, error=message)

    def observe(self, arbitration_id, payload, dlc=8, extended=False, remote=False):
        self.expire()
        if (self.reply_id is None or type(arbitration_id) is not int or arbitration_id != self.reply_id
                or extended or remote or type(dlc) is not int or dlc != 8):
            return False
        if not isinstance(payload, bytes) or len(payload) != 8:
            return False
        if payload[0] == 0x57:
            if any(payload[4:]) or payload[1] not in WRITABLE:
                return False
            key = f'{payload[1]:02X}'
            item = self.writes.get(key)
            if key != self._active_write or item is None or item['state'] != 'pending':
                return False
            status = payload[3]
            item.update(readback=payload[2], status=status,
                        state={0: 'ok', 0xEE: 'rejected', 0xFC: 'readback_failed'}.get(status, 'i2c_error'))
            if status == 0:
                self.values[payload[1]] = payload[2]
                self.failed.discard(payload[1])
                if key in CLOCK_REGISTERS and payload[2] == item['requested']:
                    self.clock_tuned[key] = payload[2]
            elif payload[1] in (0x05, 0x06) and status != 0xEE:
                self.clamp_uncertain = True
            # An error or unexpected readback cannot safely justify the rest
            # of a batch (especially an intermediate clamp reduction).
            if status != 0 or payload[2] != item['requested']:
                self._stop_writes()
            else:
                self._active_write = None
                self._send_next_write()
            return True
        sequence = payload[0]
        if sequence != 0x41 and not 1 <= sequence <= 7:
            return False
        if self._active_write is not None or self._unconfirmed_deadline is not None or self._dump_blocked:
            return False
        if sequence == 0x41 and (payload[:3] != b'ADC' or payload[3] != len(REGISTERS)):
            self._invalid('ADC dump header must have the ADC signature and report 39 registers.')
            return False
        if sequence == 6 and any(payload[5:]):
            self._invalid('ADC dump padding is invalid.')
            return False
        if sequence == 7 and (any(payload[6:]) or payload[5] & 0x80):
            self._invalid('ADC failed-read bitmap padding is invalid.')
            return False
        if self.partial is None:
            self.partial = {}
            self.dump = {'state': 'receiving', 'received_sequences': [], 'error': None}
            if self.dump_deadline is None:
                self.dump_deadline = self.clock() + 3
        if sequence in self.partial:
            self._invalid('Duplicate ADC dump frame; request a fresh Dump.')
            return False
        self.partial[sequence] = payload
        self.dump['received_sequences'] = sorted(0 if key == 0x41 else key for key in self.partial)
        if len(self.partial) != 8:
            return True
        raw_values = b''.join(self.partial[key][1:] for key in range(1, 7))
        bitmap = int.from_bytes(self.partial[7][1:6], 'little')
        failed = {register for index, register in enumerate(REGISTERS) if bitmap & (1 << index)}
        values = dict(zip(REGISTERS, raw_values[:len(REGISTERS)]))
        for register in failed:
            values[register] = None
        for register in CACHED:
            if register in self.values:
                values[register] = self.values[register]
        self.values, self.failed = values, failed
        if 0x05 not in failed and 0x06 not in failed:
            self.clamp_uncertain = False
        if self.baseline is None:
            self.baseline = {register: values[register] for register in DUMP_VISIBLE}
        self.dump_generation += 1
        self.dump.update(state='complete', received_sequences=list(range(8)), error=None,
                         generation=self.dump_generation, chip_ids=list(self.partial[0x41][4:]))
        self.partial = None
        self.dump_deadline = None
        return True

    def snapshot(self, inhibited=False, radio_active=True):
        self.expire()
        rows = []
        for register in sorted(DUMP_VISIBLE + CACHED):
            value = self.values.get(register)
            baseline = self.baseline.get(register) if self.baseline is not None else None
            rows.append({'register': f'{register:02X}', 'value': value, 'baseline': baseline,
                         'changed': value is not None and baseline is not None and value != baseline,
                         'failed': register in self.failed, 'in_dump': register in DUMP_VISIBLE,
                         'access': 'now' if register in WRITABLE_NOW else 'widen' if register in WRITABLE else 'read_only'})
        return {'reply_id': self.reply_id, 'reply_configured': self.reply_id is not None,
                'inhibited': inhibited, 'radio_active': radio_active,
                'busy': self.busy,
                'state': 'inhibited' if inhibited else 'waiting_radio' if not radio_active else 'busy' if self.busy else 'ready',
                'registers': rows, 'writes': {key: {name: value for name, value in item.items() if not name.startswith('_')}
                                            for key, item in self.writes.items()},
                'dump': dict(self.dump), 'defaults': dict(FIRMWARE), 'revert_defaults': dict(REVERT_DEFAULTS),
                'clock_tuned': dict(self.clock_tuned),
                'baseline_available': self.baseline is not None, 'clamp_uncertain': self.clamp_uncertain, 'volatile': True}
