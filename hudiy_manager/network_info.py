"""Read-only LAN addresses so a phone user can find the file portal."""
import ipaddress
import re
import subprocess

PORTAL_PORT = 5003


def _run(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=2, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return ''


def _wifi(interface):
    """Return (ssid, is_hotspot) from `iw`; works for client and AP mode."""
    info = _run(['iw', 'dev', interface, 'info'])
    ssid = re.search(r'^\s*ssid (.+)$', info, re.MULTILINE)
    kind = re.search(r'^\s*type (\S+)', info, re.MULTILINE)
    return (ssid.group(1).strip() if ssid else None), bool(kind and kind.group(1) == 'AP')


def addresses(run=_run, wifi=_wifi):
    """IPv4 addresses a phone could reach, hotspot first, then Wi-Fi, then wired."""
    found = []
    # `ip -4 -o addr show`: "2: wlan0    inet 10.42.0.1/24 brd ... scope global ..."
    for line in run(['ip', '-4', '-o', 'addr', 'show', 'scope', 'global']).splitlines():
        match = re.match(r'^\d+:\s+(\S+)\s+inet\s+([0-9.]+)/', line)
        if not match:
            continue
        interface, address = match.group(1).split('@')[0], match.group(2)
        try:
            ip = ipaddress.IPv4Address(address)
        except ValueError:
            continue
        if ip.is_loopback or ip.is_link_local or interface.startswith(('can', 'docker', 'veth', 'lo')):
            continue
        ssid, hotspot = wifi(interface) if interface.startswith('wl') else (None, False)
        kind = 'hotspot' if hotspot else 'wifi' if interface.startswith('wl') else 'wired'
        found.append({'interface': interface, 'address': address, 'kind': kind, 'ssid': ssid,
                      'url': f'http://{address}:{PORTAL_PORT}/files'})
    order = {'hotspot': 0, 'wifi': 1, 'wired': 2}
    return sorted(found, key=lambda item: order[item['kind']])
