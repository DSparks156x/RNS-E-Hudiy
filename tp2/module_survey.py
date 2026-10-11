#!/usr/bin/env python3
"""Survey every TP2 logical ID and identify whatever answers.

Builds the module ID mapping the Diagnostics tab needs:
  1. captures the gateway's coded installation bitmap (0x655 mSollverbau_neu),
  2. sweeps channel setup on 0x01-0x7F, recording any reply (accepted or refused),
  3. opens a full session to each responder and reads ECU identification.

Pauses the TP2 worker and Haldex sender for the duration. Writes JSON next to
this script (or --out) and prints a summary table.

    python3 tp2/module_survey.py [--ids 01,1F,..] [--out file.json] [--no-pause]
"""
import argparse
import json
import logging
import os
import sys
import time
import uuid

import can

from tp2_protocol import TP2Protocol, TP2Error
from installation_list import parse_installation_list

logging.getLogger("tp2_protocol").setLevel(logging.WARNING)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BROADCAST = 0x200
TESTER_ID = 0x300
SOLLVERBAU_ID = 0x655

# mSollverbau_neu bit order from references/PQ35_46_ICAN.dbc
VBN_BITS = [
    "Motor_A", "Getriebe_A", "Bremse_A", "Kombi_A", "LSM_A", "Airbag_A",
    "Lenkhilfe_A", "dyn_LWR_A", "Niveau_A", "Allrad_A", "ADR_Sensor_A",
    "ADR_getrennt", "Parkbremse_A", "EZS_A", "Daempfer_A", "Quersperre",
    "Motor_Slave_A", "SWA_A", "LDW_A", "RKA_Plus_A", "PLA_A", "WFS_KBI",
    "Kombi_KBI", "Soll_Ist_OK", "BSG_K", "KSG_K", "TSG_FT_K", "TSG_BT_K",
    "TSG_HL_K", "TSG_HR_K", "Memory_K", "Dachmodul_K", "Zentralelektrik_II_K",
    "RDK_K", "SMLS_K", "Gateway_K", "Clima_K", "APS_K", "PTC_Heizung_K",
    "Standhzg_K", "VSG_K", "RSE_I", "Wischer_K", "MDI_I", "AAG_K", "Mem_BF_K",
    "Easy_Entry_VF", "Easy_Entry_VB", "Heckdeckel_K", "Rearview_I",
    "Sonderfahrzeug_SG_K", "Tastenmodul_I", "Kompass_I", "WFS_K",
    "GSM_Pager_I", "InfoElektronik", "DSP_I", "DAB_I", "Telematik_I",
    "Navigation_I", "TV_Tuner_I", "Neigungsmodul_I", "Radio_I", "Telefon_I",
]

# 1A identifiers to try on each module. 9F is the gateway installation list;
# other modules just reject it.
IDENT_PARAMS = [0x9B, 0x91, 0x80, 0x86, 0x9A, 0x9F]


def load_config():
    try:
        with open(os.path.join(ROOT, 'config.json')) as f:
            return json.load(f)
    except Exception:
        return {}


def zmq_cmd(address, payload, timeout_ms):
    import zmq
    ctx = zmq.Context()
    sock = ctx.socket(zmq.REQ)
    sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
    sock.setsockopt(zmq.LINGER, 0)
    try:
        sock.connect(address)
        sock.send_json(payload)
        return sock.recv_json()
    except Exception:
        return None
    finally:
        sock.close()
        ctx.term()


class ServicePause:
    """Same QUIESCE/RELEASE lease the dataview uses before flashing."""

    def __init__(self, cfg):
        z = cfg.get('interfaces', {}).get('zmq', {})
        self.services = [
            ('TP2 worker', z.get('tp2_command', 'ipc:///run/rnse_control/tp2_cmd.ipc'), 12000),
            ('Haldex sender', z.get('haldex_command', 'ipc:///run/rnse_control/haldex_cmd.ipc'), 12000),
        ]
        self.token = uuid.uuid4().hex
        self.held = []

    def __enter__(self):
        for name, addr, timeout in self.services:
            resp = zmq_cmd(addr, {'cmd': 'QUIESCE', 'owner': self.token}, timeout)
            if resp is None:
                print(f"[ ] {name} not answering, assuming it is not running")
                continue
            if resp.get('status') != 'ok' or resp.get('quiescent') is not True:
                self.__exit__()
                raise RuntimeError(f"{name} refused pause: {resp.get('message', resp)}")
            self.held.append((name, addr))
            print(f"[+] {name} paused")
        return self

    def __exit__(self, *exc):
        for name, addr in self.held:
            resp = zmq_cmd(addr, {'cmd': 'RELEASE', 'owner': self.token}, 2000)
            if not resp or resp.get('status') != 'ok':
                print(f"[!] {name} release failed: {resp}")
        self.held = []


def capture_sollverbau(channel, seconds=2.0):
    """Wait for one 0x655 frame on the infotainment bus."""
    try:
        bus = can.Bus(interface='socketcan', channel=channel,
                      can_filters=[{'can_id': SOLLVERBAU_ID, 'can_mask': 0x7FF}])
    except Exception as e:
        print(f"[-] Could not open {channel} for 0x655: {e}")
        return None
    try:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            msg = bus.recv(0.2)
            if msg and msg.arbitration_id == SOLLVERBAU_ID and len(msg.data) == 8:
                value = int.from_bytes(bytes(msg.data), 'little')
                return {
                    'raw': bytes(msg.data).hex(' '),
                    'set': [VBN_BITS[i] for i in range(64) if value >> i & 1],
                }
        print("[-] No 0x655 seen (gateway asleep or wrong bus?)")
        return None
    finally:
        bus.shutdown()


def progress(label, done, total, note=''):
    width = 30
    filled = width * done // max(total, 1)
    line = f"{label} [{'#' * filled}{'.' * (width - filled)}] {done}/{total} {note}"
    sys.stdout.write('\r' + line.ljust(100)[:100])
    sys.stdout.flush()


def sweep(proto, ids, wait_s, label='Sweep'):
    """Channel-setup every ID. Any 7-byte reply on 0x200+id means something is there."""
    found = {}
    for n, mod in enumerate(ids):
        progress(label, n, len(ids), f"0x{mod:02X}  found: " +
                 ' '.join(f"{m:02X}" for m in found))
        proto._send(BROADCAST, [mod, 0xC0, 0x00, 0x10,
                                TESTER_ID & 0xFF, (TESTER_ID >> 8) & 0xFF, 0x01], pace=False)
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            msg = proto.bus.recv(0.01)
            if not msg or msg.arbitration_id != BROADCAST + mod or len(msg.data) != 7:
                continue
            data = bytes(msg.data)
            found[mod] = {'setup_reply': data.hex(' '), 'status': f"{data[1]:02X}"}
            if data[1] == 0xD0:
                # Close the half-open channel; the module's receive ID is bytes 4-5.
                rx = data[4] | (data[5] & 0x07) << 8
                proto._send(rx, [0xA8], pace=False)
            break
        time.sleep(0.02)
    progress(label, len(ids), len(ids), f"found {len(found)}")
    print()
    return found


def ascii_of(data):
    return ''.join(chr(b) if 32 <= b <= 126 else '.' for b in data).strip('. ')


def identify(proto, mod):
    info = {}
    if not proto.connect(mod):
        info['error'] = 'connect failed'
        return info
    try:
        resp = proto.send_kwp_request([0x10, 0x89])
        info['session_89'] = bytes(resp).hex(' ') if resp else None
        for param in IDENT_PARAMS:
            key = f"1A{param:02X}"
            try:
                resp = proto.send_kwp_request([0x1A, param])
            except TP2Error as e:
                info[key] = {'error': str(e)}
                if not proto.connected:
                    break
                continue
            if resp and resp[0] == 0x5A:
                body = bytes(resp[2:])
                info[key] = {'hex': body.hex(' '), 'ascii': ascii_of(body)}
            elif resp and resp[0] == 0x7F:
                info[key] = {'nrc': f"{resp[2]:02X}" if len(resp) > 2 else '??'}
            else:
                info[key] = {'unexpected': bytes(resp or b'').hex(' ')}
    except TP2Error as e:
        info['error'] = str(e)
    finally:
        proto.disconnect()
        time.sleep(0.1)
    return info


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ids', help='comma-separated hex IDs to survey instead of 01-7F')
    ap.add_argument('--wait', type=float, default=0.25, help='seconds to wait per ID in sweep')
    ap.add_argument('--retry-wait', type=float, default=1.0,
                    help='seconds per ID on a second pass over silent IDs (0 to skip)')
    ap.add_argument('--out', default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  'module_survey.json'))
    ap.add_argument('--no-pause', action='store_true', help="don't QUIESCE worker/haldex")
    args = ap.parse_args()

    cfg = load_config()
    can_cfg = cfg.get('interfaces', {}).get('can', {})
    diag_ch = can_cfg.get('diagnostic', 'can0')
    info_ch = can_cfg.get('infotainment', diag_ch)
    ids = ([int(x, 16) for x in args.ids.split(',')] if args.ids
           else list(range(0x01, 0x80)))

    result = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'channel': diag_ch}
    result['sollverbau'] = capture_sollverbau(info_ch)
    if result['sollverbau']:
        print(f"[+] 0x655 {result['sollverbau']['raw']}: {', '.join(result['sollverbau']['set'])}")

    pause = ServicePause(cfg) if not args.no_pause else None
    proto = TP2Protocol(channel=diag_ch, tester_id=TESTER_ID)
    try:
        if pause:
            pause.__enter__()
        proto.open()
        print(f"[ ] Sweeping {len(ids)} IDs on {diag_ch}...")
        found = sweep(proto, ids, args.wait, 'Pass 1')
        if args.retry_wait > 0:
            silent = [m for m in ids if m not in found]
            print(f"[ ] {len(found)} on first pass, retrying {len(silent)} silent IDs...")
            late = sweep(proto, silent, args.retry_wait, 'Pass 2')
            for v in late.values():
                v['late'] = True
            found.update(late)
        print(f"[+] {len(found)} responded: " + ' '.join(f"{m:02X}({v['status']})"
                                                         for m, v in sorted(found.items())))
        to_ident = [m for m in sorted(found) if found[m]['status'] == 'D0']
        for n, mod in enumerate(to_ident, 1):
            print(f"[ ] Identifying 0x{mod:02X} ({n}/{len(to_ident)})...")
            found[mod].update(identify(proto, mod))
        result['modules'] = {f"{m:02X}": v for m, v in sorted(found.items())}
        for mod in found.values():
            install = mod.get('1A9F')
            if isinstance(install, dict) and 'hex' in install:
                result['installation_list'] = parse_installation_list(
                    bytes.fromhex(install['hex']))
    finally:
        proto.close()
        if pause:
            pause.__exit__()

    with open(args.out, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\n{'ID':<4} {'St':<3} {'Part (1A9B)':<16} Component")
    print('-' * 70)
    for key, mod in result.get('modules', {}).items():
        ident = mod.get('1A9B', {})
        text = ident.get('ascii', '') if isinstance(ident, dict) else ''
        part, comp = text[:12].strip(), text[12:].strip()
        if not text:
            alt = mod.get('1A91', {}) if isinstance(mod.get('1A91'), dict) else {}
            comp = alt.get('ascii', mod.get('error', ''))
        print(f"{key:<4} {mod['status']:<3} {part:<16} {comp}")

    coded = [e for e in result.get('installation_list', []) if e['coded']]
    if coded:
        print(f"\nGateway installation list (coded only)")
        print(f"{'Addr':<5} {'TP2':<4} {'Bus':<4} {'St':<3} {'Ans':<4} Name")
        print('-' * 30)
        for e in coded:
            answered = 'yes' if f"{e['tp2']:02X}" in result.get('modules', {}) else 'no'
            print(f"{e['addr']:<5} {e['tp2']:02X}   {e['bus']:02X}   {e['status']:02X}  {answered:<4} {e['name']}")
    print(f"\nSaved {args.out}")


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, TP2Error) as e:
        print(f"[-] {e}")
        sys.exit(1)
