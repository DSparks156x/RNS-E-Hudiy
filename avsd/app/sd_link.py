"""Puts a RAM program on the Teensy for the unit's SD bootstrap to read. Python stdlib only.

The chain must be down: this needs the Teensy's USB port. Same bytes as the bench tools sdfast.py and sdloadd.py,
without the ssh hop.
"""
import glob
import hashlib
import os
import select
import struct
import threading
import time
import zlib

SECTOR = 512
WIRE_SECTOR = 528
HDR_MAGIC = 0x5253424C
MSG_MAGIC = 0x4B4E4C54
SF_BEGIN, WIRE, SF_END, CONFIG, STATUS, SERVED = 0x01, 0x02, 0x03, 0x05, 0x83, 0x85
WIRE_BATCH = 32
SERVE_WAIT_S = 3.0
SWAP = bytes(((b >> 4) | (b << 4)) & 255 for b in range(256))

# crc = (crc << 2) ^ T[(crc >> 14) ^ bits]
_T2 = []
for _i in range(4):
    _c = _i << 14
    for _ in range(2):
        _c = ((_c << 1) ^ 0x1021) & 0xFFFF if _c & 0x8000 else (_c << 1) & 0xFFFF
    _T2.append(_c)
_BITS = [[((_b >> (4 + _k)) & 1) << 1 | ((_b >> _k) & 1) for _b in range(256)] for _k in range(4)]


class LinkError(Exception):
    pass


def wire4(sec):
    """One 512-B sector to its 528-B wire image: start word, nibble-swapped data, 4 line CRCs, end word."""
    if len(sec) != SECTOR:
        raise ValueError('sector must be 512 B')
    crcs = []
    for k in range(4):
        c = 0
        bk = _BITS[k]
        for b in sec:
            c = ((c << 2) & 0xFFFF) ^ _T2[(c >> 14) ^ bk[b]]
        crcs.append(c)
    w0 = w1 = 0
    for j in range(16):
        nib = 0
        for k in range(4):
            nib |= ((crcs[k] >> (15 - j)) & 1) << k
        if j < 8:
            w0 |= nib << (4 * j)
        else:
            w1 |= nib << (4 * (j - 8))
    return struct.pack('<I', 0x0FFFFFFF) + sec.translate(SWAP) + struct.pack('<III', w0, w1, 0xFFFFFFFF)


def wire_image(data):
    data = data + bytes(-len(data) % SECTOR)
    return b''.join(wire4(data[i:i + SECTOR]) for i in range(0, len(data), SECTOR))


def make_header(load_id, base, img, entry, win, checks):
    """The sector the bootstrap reads first. The checks are live firmware bytes it compares before running anything."""
    nsect = (len(img) + 511) // 512
    if len(checks) > 15 or nsect > 255:
        raise LinkError('image too large for the bootstrap')
    h = bytearray(512)
    struct.pack_into('>11I', h, 0, HDR_MAGIC, load_id, base, len(img), entry, win, zlib.crc32(img), nsect, 0, 1, len(checks))
    for i, (addr, expected) in enumerate(checks):
        struct.pack_into('>I', h, 320 + 12 * i, addr)
        h[320 + 12 * i + 4:320 + 12 * i + 12] = bytes.fromhex(expected)
    struct.pack_into('>I', h, 508, zlib.crc32(bytes(h[:508])))
    return bytes(h)


def find_port():
    ports = sorted(glob.glob('/dev/serial/by-id/usb-Teensyduino_SDemu_Touch_*-if00'))
    return ports[0] if ports else None


def port_holders(device):
    target = os.path.realpath(device)
    who = []
    for pid in os.listdir('/proc'):
        if not pid.isdigit() or int(pid) == os.getpid():
            continue
        try:
            for fd in os.listdir('/proc/%s/fd' % pid):
                if os.path.realpath('/proc/%s/fd/%s' % (pid, fd)) == target:
                    with open('/proc/%s/comm' % pid) as f:
                        who.append(f.read().strip())
                    break
        except OSError:
            pass
    return who


class TeensyPort:
    """One image at a time. put() returns once it is complete on the Teensy, and the port stays open until the unit has read it."""

    def __init__(self, device=None):
        self.device = device
        self.fd = None
        self.seq = 0
        self.rx = b''
        self.status = None
        self._waiter = None

    def _open(self):
        import termios
        device = self.device or find_port()
        if not device:
            raise LinkError('Teensy not on USB')
        who = port_holders(device)
        if who:
            raise LinkError('Teensy port is held by %s' % ','.join(who))
        self.fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        t = termios.tcgetattr(self.fd)
        t[0] = t[1] = t[3] = 0
        t[2] |= termios.CLOCAL | termios.CREAD
        t[6][termios.VMIN] = 0
        t[6][termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, t)
        termios.tcflush(self.fd, termios.TCIFLUSH)
        self.seq = 0
        self.rx = b''
        self.status = None

    def _close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _write(self, data):
        m = memoryview(data)
        end = time.monotonic() + 2
        while m:
            try:
                m = m[os.write(self.fd, m):]
            except BlockingIOError:
                if time.monotonic() > end:
                    raise LinkError('USB write stuck')
                select.select([], [self.fd], [], 0.01)

    def _msg(self, typ, payload=b''):
        self._write(struct.pack('<IHHII', MSG_MAGIC, typ, 0, len(payload), self.seq) + payload)
        self.seq += 1

    def _pump(self, wait):
        r, _, _ = select.select([self.fd], [], [], wait)
        if r:
            try:
                self.rx += os.read(self.fd, 65536)
            except BlockingIOError:
                pass
        while True:
            i = self.rx.find(b'TLNK')
            if i < 0:
                self.rx = self.rx[-3:]
                return
            self.rx = self.rx[i:]
            if len(self.rx) < 16:
                return
            _, typ, _, ln, _ = struct.unpack('<IHHII', self.rx[:16])
            if ln > 4096:
                self.rx = self.rx[4:]
                continue
            if len(self.rx) < 16 + ln:
                return
            p = self.rx[16:16 + ln]
            self.rx = self.rx[16 + ln:]
            if typ == STATUS and ln >= 76:
                fields = struct.unpack('<7I', p[4:32])
                self.status = {'newest': fields[4], 'srv_sect': fields[6], 'flags': p[75]}

    def finish(self):
        """Wait for the previous image to be read, or to time out."""
        if self._waiter:
            self._waiter.join()
            self._waiter = None

    def put(self, seq, header, image):
        """Header and image onto the Teensy as superframe seq."""
        self.finish()
        wire = wire4(bytes(SECTOR)) + wire4(header) + wire_image(image)
        total = len(wire) // WIRE_SECTOR
        self._open()
        try:
            time.sleep(0.03)                            # a message before the Teensy's DTR debounce (15 ms) resets the link
            cfg = struct.pack('<HHHHB7x', 0, 0, 0, 5000, 200)
            end = time.monotonic() + 1.0
            n = 0
            while not self.status:
                if time.monotonic() > end:
                    raise LinkError('no STATUS from the Teensy')
                if n % 5 == 0:
                    self._msg(CONFIG, cfg)
                n += 1
                self._pump(0.01)
            base = self.status['srv_sect']
            self._msg(SF_BEGIN, struct.pack('<IHH', seq, total, 0))
            for k in range(0, total, WIRE_BATCH):
                c = wire[k * WIRE_SECTOR:(k + WIRE_BATCH) * WIRE_SECTOR]
                self._msg(WIRE, struct.pack('<IHHI', seq, k, len(c) // WIRE_SECTOR, 4) + c)
            self._msg(SF_END, struct.pack('<I', seq))
            end = time.monotonic() + 1.0
            while not (self.status['flags'] & 1 and self.status['newest'] == seq):
                if time.monotonic() > end:
                    raise LinkError('image not complete on the Teensy')
                self._pump(0.005)
        except Exception:
            self._close()
            raise
        self._waiter = threading.Thread(target=self._wait_served, args=(base, total), daemon=True)
        self._waiter.start()

    def _wait_served(self, base, total):
        # Sector 0 is a dummy the bootstrap never reads. Reading it would mark the slot served.
        try:
            end = time.monotonic() + SERVE_WAIT_S
            while time.monotonic() < end:
                self._pump(0.005)
                if self.status['srv_sect'] - base >= total - 1:
                    time.sleep(0.01)
                    return
        except OSError:
            pass
        finally:
            self._close()

    def close(self):
        self.finish()
        self._close()


def stop_stream(fifo='/tmp/avlink_sdctl'):
    """Ask a running sdstream to exit through avlink's control FIFO. False when there is no avlink."""
    try:
        fd = os.open(fifo, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return False
    try:
        os.write(fd, b'STOP')
    except OSError:
        return False
    finally:
        os.close(fd)
    return True


def sha256(data):
    return hashlib.sha256(data).hexdigest()
