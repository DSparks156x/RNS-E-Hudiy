import unittest
import sys
import os

# Adjust path to import apps
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apps.base import BaseApp
from apps.nav import NavApp
from apps.car_info import CarInfoApp
from apps.acceleration_test import AccelerationTestApp

class TestConfigurableUnits(unittest.TestCase):
    def test_get_effective_unit(self):
        # Setup config
        config = {
            'display': {
                'units': {
                    'speed': 'car',
                    'cartemp': 'car',
                    'boost': 'car',
                    'ambient_temp': 'metric'
                }
            },
            'car_units': {
                'speed': 'imperial',
                'temp': 'metric',
                'pressure': 'psi'
            }
        }
        app = BaseApp(config)
        
        # 'speed' configured as 'car' should resolve to car_units['speed'] which is 'imperial'
        self.assertEqual(app.get_effective_unit('speed'), 'imperial')
        
        # 'cartemp' configured as 'car' should resolve to car_units['temp'] which is 'metric'
        self.assertEqual(app.get_effective_unit('cartemp'), 'metric')
        
        # 'boost' configured as 'car' should resolve to 'imperial' because pressure is 'psi'
        self.assertEqual(app.get_effective_unit('boost'), 'imperial')
        
        # 'ambient_temp' configured as 'metric' should resolve to 'metric' directly
        self.assertEqual(app.get_effective_unit('ambient_temp'), 'metric')

    def test_format_temp(self):
        app = BaseApp()
        # Metric C formatting
        self.assertEqual(app.format_temp(0, 'metric'), '0°C')
        self.assertEqual(app.format_temp(100, 'metric'), '100°C')
        
        # Imperial F formatting: F = C * 1.8 + 32
        self.assertEqual(app.format_temp(0, 'imperial'), '32°F')
        self.assertEqual(app.format_temp(100, 'imperial'), '212°F')
        self.assertEqual(app.format_temp(37, 'imperial'), '99°F')

    def test_nav_distance_conversion(self):
        # Setup config for metric speed
        config_metric = {
            'display': {
                'units': {
                    'speed': 'metric'
                }
            }
        }
        nav_metric = NavApp(config_metric)
        
        # Test low meters (should display in meters)
        nav_metric.distance_label = "250 m"
        nav_metric._meters = 250.0
        # Call get_view to verify the returned commands structure
        view_metric = nav_metric.get_view()
        # Find dist group commands
        dist_cmds = [c for c in view_metric if c.get('group') == 'dist' and c.get('cmd') == 'draw_text']
        self.assertTrue(any(c['text'] == '250' for c in dist_cmds))
        self.assertTrue(any(c['text'] == 'm' for c in dist_cmds))

        # Test high meters (should convert to km)
        nav_metric.distance_label = "1500 m"
        nav_metric._meters = 1500.0
        view_metric_high = nav_metric.get_view()
        dist_cmds_high = [c for c in view_metric_high if c.get('group') == 'dist' and c.get('cmd') == 'draw_text']
        self.assertTrue(any(c['text'] == '1.5' for c in dist_cmds_high))
        self.assertTrue(any(c['text'] == 'km' for c in dist_cmds_high))

        # Setup config for imperial speed
        config_imperial = {
            'display': {
                'units': {
                    'speed': 'imperial'
                }
            }
        }
        nav_imperial = NavApp(config_imperial)
        
        # Test low meters (should convert to ft)
        nav_imperial.distance_label = "100 m"
        nav_imperial._meters = 100.0 # ~328 ft
        view_imp = nav_imperial.get_view()
        dist_cmds_imp = [c for c in view_imp if c.get('group') == 'dist' and c.get('cmd') == 'draw_text']
        self.assertTrue(any(c['text'] == '328' for c in dist_cmds_imp))
        self.assertTrue(any(c['text'] == 'ft' for c in dist_cmds_imp))

        # Test high meters (should convert to mi)
        nav_imperial.distance_label = "1609.34 m"
        nav_imperial._meters = 1609.34 # 1 mile
        view_imp_high = nav_imperial.get_view()
        dist_cmds_imp_high = [c for c in view_imp_high if c.get('group') == 'dist' and c.get('cmd') == 'draw_text']
        self.assertTrue(any(c['text'] == '1.0' for c in dist_cmds_imp_high))
        self.assertTrue(any(c['text'] == 'mi' for c in dist_cmds_imp_high))

    def test_acceleration_test_app(self):
        config = {
            'display': {
                'units': {
                    'speed': 'car'
                },
                'center_display': {
                    'acceleration_test': {
                        'line_1': '0-60',
                        'line_2': '0-100',
                        'line_3': '1/4',
                        'line_4': 'speed'
                    }
                }
            },
            'car_units': {
                'speed': 'metric'
            }
        }
        acc_app = AccelerationTestApp(config)
        self.assertEqual(acc_app.speed_unit, 'metric')
        self.assertEqual(acc_app.speed_unit_str, 'kmh')
        
        # Switch car speed unit to imperial
        config['car_units']['speed'] = 'imperial'
        acc_app.update_units()
        self.assertEqual(acc_app.speed_unit, 'imperial')
        self.assertEqual(acc_app.speed_unit_str, 'mph')

    def test_car_info_temperatures(self):
        config = {
            'display': {
                'units': {
                    'cartemp': 'car'
                }
            },
            'car_units': {
                'temp': 'imperial'
            }
        }
        car_info = CarInfoApp(config)
        # Update with diagnostic payload for group 0
        car_info.update_hudiy(b'HUDIY_DIAG', {
            'module': 0,
            'group': 0,
            'data': [
                {'value': 90, 'unit': 'C'}, # oil
                {'value': 20, 'unit': 'C'}, # ambient
                {'value': 85, 'unit': 'C'}, # coolant
                {'value': 30, 'unit': 'C'}  # iat
            ]
        })
        # F = C * 1.8 + 32
        # oil: 90 * 1.8 + 32 = 194
        # coolant: 85 * 1.8 + 32 = 185
        self.assertEqual(car_info.data['oil'], '194°F')
        self.assertEqual(car_info.data['coolant'], '185°F')

    def test_fraction_parsing(self):
        # 1/2 mi should parse as 0.5 miles = 804.67 meters
        self.assertAlmostEqual(NavApp.parse_distance("1/2 mi"), 804.67, places=1)
        # 1/4 mi should parse as 0.25 miles = 402.335 meters
        self.assertAlmostEqual(NavApp.parse_distance("1/4 mi"), 402.335, places=1)
        # 1/8 mi should parse as 0.125 miles = 201.1675 meters
        self.assertAlmostEqual(NavApp.parse_distance("1/8 mi"), 201.1675, places=1)

if __name__ == '__main__':
    unittest.main()
