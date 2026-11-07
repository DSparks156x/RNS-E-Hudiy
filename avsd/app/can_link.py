"""RNS-E debug commands over the Pi's SocketCAN interface. Python stdlib only.

Request 0x7B0, reply 0x7B6. CAN_PROTOCOL.md is out of date for flash, so the layouts are repeated here:
  B1 a3 a2 a1 a0 LEN 00 00   read. Reply: 80 st a3 a2 a1 a0 LEN nf, then (80|seq) d0..d5 ck
  B9 i2 i1 i0 d3 d2 d1 d0    RAM word write at 0x8C000000 + i*4. Silent.
  B8 5A                      start task 159. Silent.
"""
import errno
import json
import socket
import struct
import subprocess
import time

REQ_ID = 0x7B0
REPLY_ID = 0x7B6
CAN_FMT = '=IB3x8s'
READ_CHUNK = 48
SEND_GAP_S = 0.004
READ_TRIES = 5
RAM_LOW, RAM_HIGH = 0x8C000000, 0x8FFFFFFC


class UnitError(Exception):
    """The unit did not answer, or answered with something unusable."""


def can_state(interface='can0', run=subprocess.run):
    """What can be sent right now: {'present', 'up', 'listen_only'}."""
    try:
        out = run(['ip', '-details', '-json', 'link', 'show', interface], capture_output=True, text=True, timeout=3)
        if out.returncode:
            return {'present': False, 'up': False, 'listen_only': False}
        link = json.loads(out.stdout)[0]
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return {'present': False, 'up': False, 'listen_only': False}
    ctrl = link.get('linkinfo', {}).get('info_data', {}).get('ctrlmode', [])
    return {'present': True, 'up': 'UP' in link.get('flags', []), 'listen_only': 'LISTEN-ONLY' in ctrl}


def not_ready_reason(state):
    """None when frames can go out. can0 is listen-only only while the ignition is off."""
    if not state['present'] or not state['up']:
        return 'can0 is not up.'
    if state['listen_only']:
        return 'Turn the ignition on. can0 is listen-only while it is off.'
    return None


class SocketCanBus:
    def __init__(self, interface='can0'):
        self.s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_FILTER, struct.pack('=II', REPLY_ID, 0x7FF))
        self.s.bind((interface,))

    def send(self, payload):
        frame = struct.pack(CAN_FMT, REQ_ID, 8, bytes(payload).ljust(8, b'\0'))
        end = time.monotonic() + 1.0
        while True:
            try:
                self.s.send(frame)
                return
            except OSError as e:                        # can0's queue is 10 frames and the bus is shared
                if e.errno != errno.ENOBUFS or time.monotonic() > end:
                    raise UnitError('CAN send failed: %s' % e)
                time.sleep(0.002)

    def recv(self, timeout):
        self.s.settimeout(max(timeout, 0.001))
        try:
            can_id, dlc, data = struct.unpack(CAN_FMT, self.s.recv(16))
        except socket.timeout:
            return None
        return can_id & 0x7FF, data[:dlc]

    def drain(self):
        while self.recv(0.001) is not None:
            pass

    def close(self):
        self.s.close()


class Unit:
    """B1, B9 and B8 on top of a bus. The bus only needs send, recv, drain and close."""

    def __init__(self, bus, sleep=time.sleep):
        self.bus = bus
        self.sleep = sleep

    def close(self):
        self.bus.close()

    def send(self, payload):
        self.bus.send(bytes(payload))
        self.sleep(SEND_GAP_S)

    def read(self, addr, n):
        out = b''
        while n:
            k = min(n, READ_CHUNK)
            out += self._read_chunk(addr, k)
            addr += k
            n -= k
        return out

    def u32(self, addr):
        return struct.unpack('>I', self.read(addr, 4))[0]

    def _read_chunk(self, addr, n):
        req = bytes((0xB1, addr >> 24 & 255, addr >> 16 & 255, addr >> 8 & 255, addr & 255, n, 0, 0))
        nf = (n + 5) // 6
        for _ in range(READ_TRIES):
            self.bus.drain()
            self.bus.send(req)
            header_ok = False
            frames = {}
            end = time.monotonic() + 1.0 + nf * 0.05
            while time.monotonic() < end:
                m = self.bus.recv(max(0.01, end - time.monotonic()))
                if not m:
                    continue
                d = m[1]
                if len(d) != 8 or d[0] & 0xF0 != 0x80:
                    continue
                seq = d[0] & 0x0F
                if seq == 0:
                    # Manager's ADC tools read on the same IDs: a reply for another address is not ours.
                    if struct.unpack('>I', d[2:6])[0] != addr or d[6] != n:
                        header_ok, frames = False, {}
                        continue
                    if d[1] != 0:
                        raise UnitError('read %08X refused, status %d' % (addr, d[1]))
                    header_ok = True
                elif header_ok and 1 <= seq <= nf and (sum(d[1:7]) & 255) == d[7]:
                    frames[seq] = d[1:7]
                if header_ok and len(frames) == nf:
                    return b''.join(frames[i] for i in range(1, nf + 1))[:n]
        raise UnitError('no answer reading %08X. Is the RNS-E awake?' % addr)

    def poke(self, addr, value):
        if addr % 4 or not RAM_LOW <= addr <= RAM_HIGH:
            raise ValueError('poke outside RAM: %08X' % addr)
        i = (addr - RAM_LOW) >> 2
        self.send([0xB9, i >> 16 & 255, i >> 8 & 255, i & 255] + list(struct.pack('>I', value & 0xFFFFFFFF)))

    def write_block(self, addr, data):
        data = data + bytes(-len(data) % 4)
        for k in range(0, len(data), 4):
            self.poke(addr + k, struct.unpack('>I', data[k:k + 4])[0])
        if self.read(addr, len(data)) != data:
            raise UnitError('RAM write did not verify at %08X' % addr)
