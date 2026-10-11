"""Phone portal address discovery, using canned `ip`/`iw` output."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hudiy_manager.network_info import addresses, _wifi
import hudiy_manager.network_info as network_info

IP_OUTPUT = """\
2: eth0    inet 192.168.1.50/24 brd 192.168.1.255 scope global dynamic eth0\       valid_lft 86000sec preferred_lft 86000sec
3: wlan0    inet 10.42.0.1/24 brd 10.42.0.255 scope global noprefixroute wlan0\       valid_lft forever preferred_lft forever
4: wlan1    inet 192.168.0.20/24 brd 192.168.0.255 scope global wlan1\       valid_lft forever preferred_lft forever
5: can0    inet 10.0.0.9/8 scope global can0
6: eth1    inet 169.254.3.3/16 scope global eth1
"""


class NetworkInfoTests(unittest.TestCase):
    def test_orders_hotspot_wifi_wired_and_skips_unreachable(self):
        wifi = {'wlan0': ('Hudiy', True), 'wlan1': ('HomeWiFi', False)}
        result = addresses(run=lambda argv: IP_OUTPUT, wifi=lambda name: wifi[name])
        self.assertEqual([(item['kind'], item['address'], item['ssid']) for item in result],
                         [('hotspot', '10.42.0.1', 'Hudiy'), ('wifi', '192.168.0.20', 'HomeWiFi'), ('wired', '192.168.1.50', None)])
        self.assertEqual(result[0]['url'], 'http://10.42.0.1:5003/files')

    def test_missing_tools_mean_no_addresses(self):
        self.assertEqual(addresses(run=lambda argv: ''), [])

    def test_iw_ap_and_client_modes(self):
        original = network_info._run
        try:
            network_info._run = lambda argv: 'Interface wlan0\n\tifindex 3\n\tssid Hudiy\n\ttype AP\n'
            self.assertEqual(_wifi('wlan0'), ('Hudiy', True))
            network_info._run = lambda argv: 'Interface wlan0\n\tssid My Home 5G\n\ttype managed\n'
            self.assertEqual(_wifi('wlan0'), ('My Home 5G', False))
        finally:
            network_info._run = original


if __name__ == '__main__':
    unittest.main()
