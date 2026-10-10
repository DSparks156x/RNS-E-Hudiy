"""Volatile r21 ADC commands and readbacks; no hardware or web dependencies."""
import re
import time

COMMAND_ID = 0x7B0
DEFAULT_REPLY_ID = '0x462'
REGISTERS = tuple(range(0x1E)) + (0x24, 0x31, 0x35, 0x36, 0x37, 0x41, 0x43, 0x45, 0x46)
WRITABLE = frozenset((0x03, 0x04, 0x05, 0x06, 0x08, 0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x11, 0x12, 0x13))
# The Pi tuning page targets the 480p TV path; 15 kHz boot uses 03=10.
DEFAULTS = {'03': 0x30, '04': 0x80, '05': 0x16, '06': 0x2F, '08': 0x70, '09': 0x70,
            '0A': 0x70, '0B': 0x7E, '0C': 0x7E, '0D': 0x7E,
            '11': 0x20, '12': 0x06, '13': 0x06}
# Only this fixed operation may restore PLL and non-slider boot registers.
# Reg 24 is absent because firmware rejects every address above 13.
REVERT_DEFAULTS = {'01': 0x3F, '02': 0x50, **DEFAULTS,
                   '07': 0x70, '0E': 0x2D, '0F': 0x2A, '10': 0}
REVERT_DEFAULTS = dict(sorted(REVERT_DEFAULTS.items()))


def reply_identifier(value):
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r'0[xX][0-9a-fA-F]{1,3}', value):
        raise ValueError('can_ids.rnse_adc_reply must be null or a standard hexadecimal CAN ID.')
    result = int(value, 16)
    if result > 0x7FF or result == COMMAND_ID:
        raise ValueError('ADC reply ID must be a standard CAN ID different from 0x7B0.')
    return result


def validate_values(values):
    if not isinstance(values, dict) or not values or len(values) > len(WRITABLE):
        raise ValueError('Provide a non-empty ADC register-to-byte object.')
    result = {}
    for key, value in values.items():
        if not isinstance(key, str) or not re.fullmatch(r'[0-9A-Fa-f]{2}', key):
            raise ValueError('ADC register keys must be two hexadecimal digits.')
        register = int(key, 16)
        if register not in WRITABLE:
            raise ValueError('ADC register is locked or unavailable for tuning: ' + key)
        if type(value) is not int or not 0 <= value <= 255:
            raise ValueError('ADC values must be integer bytes from 0 to 255.')
        if register in (0x0B, 0x0C, 0x0D) and (value > 254 or value & 1):
            raise ValueError('ADC offsets must be even encoded bytes from 0 to 254 (slider 0 to 127).')
        if register in (0x03, 0x04) and value & 7:
            raise ValueError('ADC phase and VCO values must have their low three bits clear.')
        canonical = f'{register:02X}'
        if canonical in result:
            raise ValueError('Duplicate ADC register: ' + canonical)
        result[canonical] = value
    if '05' in result and '06' in result and result['05'] + result['06'] >= 110:
        raise ValueError('ADC clamp placement plus duration must be below 110 clocks.')
    return result


class AdcController:
    """Explicit user commands only. Queue success never implies chip success."""
    def __init__(self, reply_id=None, clock=time.monotonic):
        self.reply_id = reply_id
        self.clock = clock
        self.values = {}
        self.baseline = None
        self.failed = set()
        self.writes = {}
        self.dump = {'state': 'idle', 'received_sequences': [], 'error': None}
        self.partial = None
        self.dump_deadline = None
        self.dump_generation = 0
        self.identification = {'state': 'idle', 'chip': None, 'probe': None,
                               'restore': None, 'restore_confirmed': False, 'error': None}
        self._probe_send = None
        self._probe_deadline = None
        self._restore_deadline = None
        self.clamp_uncertain = False
        self._write_queue = []
        self._write_send = None
        self._active_write = None
        self._unconfirmed_deadline = None
        self._dump_blocked = False

    @property
    def identifying(self):
        return self.identification['state'] in ('pending', 'restoring')

    @property
    def busy(self):
        return (self.identifying or self.dump_deadline is not None
                or self._active_write is not None or bool(self._write_queue)
                or self._unconfirmed_deadline is not None)

    def advance(self, send):
        """Refresh guarded callbacks and expire explicitly requested operations."""
        self._probe_send = send
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
        if self._probe_deadline is not None and now >= self._probe_deadline:
            self._probe_deadline = None
            self.identification['probe']['state'] = 'timeout'
            self.identification['error'] = 'Chip probe reply timed out; identification is unconfirmed.'
            self._restore_identification()
        if self._restore_deadline is not None and now >= self._restore_deadline:
            self._restore_deadline = None
            self.identification['restore']['state'] = 'timeout'
            self.identification.update(state='unconfirmed', error='Chip probe restore reply timed out; restoration is unconfirmed.')

    def write(self, values, send):
        values = validate_values(values)
        return self._write(values, send)

    def revert(self, send):
        return self._write(REVERT_DEFAULTS, send)

    def _write(self, values, send):
        self.expire()
        if self.busy:
            raise ValueError('Wait for pending ADC commands before writing registers.')
        if self.reply_id is None and len(values) > 1:
            raise ValueError('Configure the ADC reply CAN ID before sending a multi-register batch.')
        if any(key in values for key in ('05', '06')):
            if self.clamp_uncertain:
                raise ValueError('ADC clamp write is unconfirmed. Complete a fresh Dump before changing the clamp again.')
            clamp = {}
            known_clamp = {}
            for key in ('05', '06'):
                pending = self.writes.get(key, {})
                if pending.get('state') == 'pending':
                    raise ValueError('Wait for the pending ADC clamp acknowledgement before changing the clamp.')
                known = self.values.get(int(key, 16))
                if pending.get('state') == 'queued_unconfirmed':
                    known = pending['requested']
                known_clamp[key] = known if known is not None else DEFAULTS[key]
                clamp[key] = values.get(key, known_clamp[key])
            if clamp['05'] + clamp['06'] >= 110:
                raise ValueError('ADC clamp placement plus duration must be below 110 clocks.')
            if '05' in values and '06' in values:
                keys = list(values)
                first, second = sorted(('05', '06'), key=keys.index)
                if clamp[first] + known_clamp[second] >= 110:
                    # Reduce the other component first so the intermediate
                    # hardware window does not cross the limit.
                    first_index, second_index = keys.index(first), keys.index(second)
                    keys[first_index], keys[second_index] = second, first
                    values = {key: values[key] for key in keys}
        self._write_send = send
        for key, value in values.items():
            self.writes[key] = {'requested': value, 'readback': None, 'status': None,
                                'state': 'queued'}
        self._write_queue = list(values)
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

    def identify(self, send):
        self.expire()
        if self.busy:
            raise ValueError('Wait for pending ADC commands before identifying the chip.')
        if self.reply_id is None:
            raise ValueError('Configure the ADC reply CAN ID before identifying the chip.')
        if self.baseline is None or self.values.get(0x1D) != 0 or 0x1D in self.failed:
            raise ValueError('Dump registers first and verify register 1D is 00 (auto offset off) before chip identification.')
        self._probe_send = send
        self.identification = {'state': 'pending', 'chip': None, 'restore_confirmed': False, 'error': None,
            'probe': {'requested': 4, 'readback': None, 'status': None, 'state': 'pending'},
            'restore': {'requested': 0, 'readback': None, 'status': None, 'state': 'not_sent'}}
        queued = send(COMMAND_ID, 'bc1a040000000000')
        if queued:
            self._probe_deadline = self.clock() + 2
        else:
            self.identification['probe']['state'] = 'queue_failed'
            self.identification.update(state='error', error='CAN gateway did not queue the chip probe; no restore was needed.')
        return queued

    def _restore_identification(self):
        if self.identification['restore']['state'] != 'not_sent':
            return
        self.identification['state'] = 'restoring'
        if self._probe_send(COMMAND_ID, 'bc1a000000000000'):
            self.identification['restore']['state'] = 'pending'
            self._restore_deadline = self.clock() + 2
        else:
            self.identification['restore']['state'] = 'queue_failed'
            self.identification.update(state='error', error='Chip probe restore was inhibited or could not be queued; restoration is unconfirmed.')

    def _observe_identification(self, payload):
        if not self.identifying:
            return False
        probe_reply = self.identification['state'] == 'pending'
        item = self.identification['probe' if probe_reply else 'restore']
        status = payload[3]
        item.update(readback=payload[2], status=status,
                    state='ok' if status == 0 else 'rejected' if status == 0xEE else 'i2c_error')
        if probe_reply:
            self._probe_deadline = None
            if status == 0:
                self.identification['chip'] = {4: 'AD9985', 0: 'AD9883A'}.get(payload[2], 'unknown')
            else:
                self.identification['error'] = 'Chip probe was rejected or returned an I2C error; identification is unconfirmed.'
            self._restore_identification()
        else:
            self._restore_deadline = None
            restored = status == 0 and payload[2] == 0
            self.identification['restore_confirmed'] = restored
            if not restored:
                self.identification.update(state='error', error='Chip probe restore failed or did not read back 00.')
            elif self.identification['probe']['state'] == 'ok':
                self.identification['state'] = 'identified'
            elif self.identification['probe']['state'] == 'timeout':
                self.identification['state'] = 'unconfirmed'
            else:
                self.identification['state'] = 'error'
            if restored:
                self.values[0x1A] = 0
                self.failed.discard(0x1A)
        return True

    def observe(self, arbitration_id, payload, dlc=8, extended=False, remote=False):
        self.expire()
        if (self.reply_id is None or type(arbitration_id) is not int or arbitration_id != self.reply_id
                or extended or remote or type(dlc) is not int or dlc != 8):
            return False
        if not isinstance(payload, bytes) or len(payload) != 8:
            return False
        if payload[0] == 0x57:
            if payload[1] == 0x1A:
                return False if any(payload[4:]) else self._observe_identification(payload)
            if any(payload[4:]) or not 1 <= payload[1] <= 0x13:
                return False
            key = f'{payload[1]:02X}'
            item = self.writes.get(key)
            if key != self._active_write or item is None or item['state'] != 'pending':
                return False
            item.update(readback=payload[2], status=payload[3],
                        state='ok' if payload[3] == 0 else 'rejected' if payload[3] == 0xEE else 'i2c_error')
            if payload[3] == 0:
                self.values[payload[1]] = payload[2]
                self.failed.discard(payload[1])
            elif payload[1] in (0x05, 0x06) and payload[3] != 0xEE:
                self.clamp_uncertain = True
            # An error or unexpected readback cannot safely justify the rest
            # of a batch (especially an intermediate clamp reduction).
            if payload[3] != 0 or payload[2] != item['requested']:
                self._stop_writes()
            else:
                self._active_write = None
                self._send_next_write()
            return True
        sequence = payload[0]
        if sequence != 0x41 and not 1 <= sequence <= 7:
            return False
        if self.identifying or self._active_write is not None or self._unconfirmed_deadline is not None or self._dump_blocked:
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
        self.values, self.failed = values, failed
        if 0x05 not in failed and 0x06 not in failed:
            self.clamp_uncertain = False
        if self.baseline is None:
            self.baseline = dict(values)
        self.dump_generation += 1
        self.dump.update(state='complete', received_sequences=list(range(8)), error=None,
                         generation=self.dump_generation, chip_ids=list(self.partial[0x41][4:]))
        self.partial = None
        self.dump_deadline = None
        return True

    def snapshot(self, inhibited=False, radio_active=True):
        self.expire()
        rows = []
        for register in REGISTERS:
            value = self.values.get(register)
            baseline = self.baseline.get(register) if self.baseline is not None else None
            rows.append({'register': f'{register:02X}', 'value': value, 'baseline': baseline,
                         'changed': value is not None and baseline is not None and value != baseline,
                         'failed': register in self.failed})
        return {'reply_id': self.reply_id, 'reply_configured': self.reply_id is not None,
                'inhibited': inhibited, 'radio_active': radio_active,
                'busy': self.busy,
                'state': 'inhibited' if inhibited else 'waiting_radio' if not radio_active else 'busy' if self.busy else 'ready',
                'registers': rows, 'writes': {key: {name: value for name, value in item.items() if not name.startswith('_')}
                                            for key, item in self.writes.items()},
                'dump': dict(self.dump), 'defaults': dict(DEFAULTS), 'clamp_duration_default': 0x2F,
                'revert_defaults': dict(REVERT_DEFAULTS), 'revert_omitted': {'24': 0x58},
                'identification': {**self.identification,
                    'probe': dict(self.identification['probe']) if self.identification['probe'] is not None else None,
                    'restore': dict(self.identification['restore']) if self.identification['restore'] is not None else None},
                'baseline_available': self.baseline is not None, 'clamp_uncertain': self.clamp_uncertain, 'volatile': True}
