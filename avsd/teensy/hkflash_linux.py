#!/usr/bin/env python3
"""Flash the Teensy 4.1 from Linux/Pi over hidraw, no packages but pyserial. Run with sudo.
    sudo python3 hkflash_linux.py firmware.hex [/dev/ttyACM0]
Soft-reboots into HalfKay (134 baud), then sends the same blocks as hkflash.py / teensy_loader_cli: 64-B header + 1024 B data,
behind a report id byte. The first block triggers the flash erase, so it may be refused for a while."""
import glob, os, sys, time

BLOCK = 1024
FLASH_BASE = 0x60000000


def read_hex(path):
    mem, base = {}, 0
    for ln in open(path):
        ln = ln.strip()
        if not ln.startswith(':'):
            continue
        b = bytes.fromhex(ln[1:])
        n, addr, typ = b[0], (b[1] << 8) | b[2], b[3]
        if typ == 0:
            a = base + addr
            for i in range(n):
                mem[a + i] = b[4 + i]
        elif typ == 2:
            base = ((b[4] << 8) | b[5]) << 4
        elif typ == 4:
            base = ((b[4] << 8) | b[5]) << 16
        elif typ == 1:
            break
    return mem


def find_halfkay():
    for p in glob.glob('/sys/class/hidraw/hidraw*'):
        try:
            ue = open(os.path.join(p, 'device', 'uevent')).read()
        except OSError:
            continue
        if 'HID_ID=0003:000016C0:00000478' in ue.upper().replace('0003:000016C0', '0003:000016C0'):
            return '/dev/' + os.path.basename(p)
    return None


def main():
    hexf = sys.argv[1]
    port = sys.argv[2] if len(sys.argv) > 2 else '/dev/ttyACM0'
    mem = read_hex(hexf)
    lo, hi = min(mem), max(mem)
    print('image %08X-%08X, %d bytes' % (lo, hi, len(mem)), flush=True)
    assert lo >= FLASH_BASE and hi < FLASH_BASE + 8126464, 'hex is not a Teensy 4.1 flash image'
    if not find_halfkay():
        import serial
        try:
            s = serial.Serial(port, 134)                 # 134 baud = reboot request to the bootloader
            s.close()
        except Exception as e:
            print('soft reboot failed:', e, flush=True)
    t = time.time()
    dev = None
    while time.time() - t < 15:
        dev = find_halfkay()
        if dev:
            break
        time.sleep(0.1)
    if not dev:
        sys.exit('HalfKay did not appear: press the Teensy button and run this again')
    print('HalfKay at', dev, flush=True)
    time.sleep(0.2)
    fd = os.open(dev, os.O_RDWR)
    offs = sorted({(a - FLASH_BASE) // BLOCK for a in mem})
    sent = 0
    t0 = time.time()
    for k, blk in enumerate(offs):
        addr = blk * BLOCK
        data = bytes(mem.get(FLASH_BASE + addr + i, 0xFF) for i in range(BLOCK))
        pkt = bytes([0, addr & 255, (addr >> 8) & 255, (addr >> 16) & 255]) + bytes(61) + data
        lim = time.time() + (180 if k == 0 else 10)
        while True:
            try:
                os.write(fd, pkt)
                break
            except OSError as e:
                if time.time() > lim:
                    sys.exit('block %06X refused: %s (press the Teensy button, run again)' % (addr, e))
                time.sleep(0.02)
        sent += 1
    print('%d blocks in %.1f s; booting' % (sent, time.time() - t0), flush=True)
    pkt = bytes([0, 0xFF, 0xFF, 0xFF]) + bytes(61) + bytes(BLOCK)
    try:
        os.write(fd, pkt)
    except OSError:
        pass
    os.close(fd)


if __name__ == '__main__':
    main()
