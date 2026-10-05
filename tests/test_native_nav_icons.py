import hashlib
import json
import sys
import unittest
import importlib.util
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / 'dis_client'))

from apps.nav import NavApp
from nav_icons import ICON_NAMES, canvas_for_icon, icon_bitmap
from nav_icons_data import ICON_SOURCES, RASTER_POLICY

spec = importlib.util.spec_from_file_location(
    'native_nav_generator', REPO_ROOT / 'tools/generate_native_nav_icons.py')
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


def pixels(data, width, height):
    stride = width // 8
    return [[bool(data[y * stride + x // 8] & (0x80 >> (x % 8)))
             for x in range(width)] for y in range(height)]


def config(native=False, road_side='right'):
    return {'display': {'road_side': road_side, 'units': {'speed': 'metric'},
                       'center_display': {'navigation': {'high_resolution': native}}}}


def app_with_route(native=False, road_side='right'):
    app = NavApp(config(native, road_side))
    app.update_hudiy(b'HUDIY_NAV', {'maneuver_type': 4, 'maneuver_side': 2,
                                  'description': 'Turn right onto Main St',
                                  'distance': '100 m'})
    return app


class NativeNavigationGeometryTests(unittest.TestCase):
    def assertMirror(self, first, second):
        self.assertEqual([row[::-1] for row in pixels(icon_bitmap(first), 72, 72)],
                         pixels(icon_bitmap(second), 72, 72))

    def test_complete_binary_assets_and_reserved_layout(self):
        self.assertEqual(len(ICON_NAMES), 44)
        for name in ICON_NAMES:
            with self.subTest(name=name):
                icon = icon_bitmap(name)
                self.assertEqual(len(icon), 648)
                self.assertTrue(any(icon))
                canvas = canvas_for_icon(name)
                self.assertIsInstance(canvas, bytes)
                self.assertEqual(len(canvas), 1536)
                grid = pixels(canvas, 128, 96)
                self.assertFalse(any(value for y, row in enumerate(grid)
                                     for x, value in enumerate(row)
                                     if not (6 <= x < 78 and 2 <= y < 74)))
                self.assertEqual([row[6:78] for row in grid[2:74]], pixels(icon, 72, 72))

    def test_opaque_authored_sided_turns_are_exact_mirrors(self):
        # Context checkers and authored MERGE aliases are intentionally not
        # forced into synthetic mirrored assets.
        for prefix in ('TURN', 'TURN_SLIGHT', 'TURN_SHARP', 'RAMP_ON', 'DESTINATION'):
            self.assertMirror(prefix + '_LEFT', prefix + '_RIGHT')
        self.assertMirror('TURN_U_TURN_CLOCKWISE', 'TURN_U_TURN_COUNTERCLOCKWISE')

    def test_approved_turn_head_symmetry_and_default_pixel_phase(self):
        grid = pixels(icon_bitmap('TURN_RIGHT'), 72, 72)
        self.assertEqual(sum(grid[54][:30]), 8)
        self.assertEqual(sum(grid[y][30] for y in range(15, 45)), 7)
        for y in range(10, 47):
            for x in range(44, 72):
                self.assertEqual(grid[y][x], grid[56-y][x])

    def test_authored_aliases_are_preserved(self):
        for side in ('LEFT', 'RIGHT'):
            self.assertEqual(icon_bitmap('TURN_' + side), icon_bitmap('RAMP_ON_' + side))
        self.assertEqual(icon_bitmap('MERGE'), icon_bitmap('MERGE_LEFT'))
        self.assertEqual(icon_bitmap('MERGE'), icon_bitmap('MERGE_RIGHT'))
        self.assertEqual(ICON_SOURCES['ROUNDABOUT_COUNTERCLOCKWISE'],
                         'maneuver_roundabout_enter_and_exit_ccw.svg')

    def test_distinct_turn_branch_and_roundabout_exit_geometry(self):
        names = ['TURN_RIGHT', 'TURN_SLIGHT_RIGHT', 'TURN_SHARP_RIGHT',
                 'FORK_RIGHT', 'RAMP_OFF_RIGHT']
        self.assertEqual(len(set(icon_bitmap(name) for name in names)), len(names))
        for direction in ('CLOCKWISE', 'COUNTERCLOCKWISE'):
            self.assertNotEqual(icon_bitmap('ROUNDABOUT_' + direction),
                                icon_bitmap('ROUNDABOUT_EXIT_' + direction))
            self.assertNotEqual(icon_bitmap('ROUNDABOUT_U_TURN_' + direction),
                                icon_bitmap('ROUNDABOUT_' + direction))

    def test_unknown_icon_falls_back_to_straight(self):
        self.assertEqual(canvas_for_icon('unknown'), canvas_for_icon('STRAIGHT'))


class MapsVectorSourceConversionTests(unittest.TestCase):
    def test_runtime_assets_match_every_approved_source_reference(self):
        from PIL import Image
        manifest = generator.source_manifest()
        self.assertEqual(set(manifest['icons']), set(ICON_NAMES))
        self.assertEqual(RASTER_POLICY['phase'], [0, 0])
        for name in ICON_NAMES:
            item = manifest['icons'][name]
            self.assertEqual(ICON_SOURCES[name], item['svg'])
            self.assertEqual(hashlib.sha256(icon_bitmap(name)).hexdigest(),
                             item['native72_mask_sha256'])
            with Image.open(generator.DEFAULT_SOURCE / 'reference72' / (name + '.png')) as reference:
                self.assertEqual(reference.mode, '1')
                self.assertEqual(reference.size, (72, 72))
                self.assertEqual(icon_bitmap(name), reference.tobytes())

    def test_semantic_source_mapping_does_not_invent_handedness(self):
        self.assertEqual(ICON_SOURCES['TURN_U_TURN_COUNTERCLOCKWISE'], 'maneuver_u_turn_left.svg')
        self.assertEqual(ICON_SOURCES['TURN_U_TURN_CLOCKWISE'], 'maneuver_u_turn_right.svg')
        for direction, token in [('CLOCKWISE', 'cw'), ('COUNTERCLOCKWISE', 'ccw')]:
            self.assertEqual(ICON_SOURCES['ROUNDABOUT_EXIT_' + direction],
                             'maneuver_roundabout_exit_' + token + '.svg')
            self.assertEqual(ICON_SOURCES['ROUNDABOUT_RIGHT_' + direction],
                             'maneuver_roundabout_enter_and_exit_' + token + '_normal_right.svg')

    def test_context_opacity_is_separated_without_losing_path_geometry(self):
        source = ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><g transform="translate(2 3)"><path d="M0,0Z" fill="#000000" fill-opacity=".5"/><path d="M1,1Z" fill="#000000"/></g></svg>')
        for kind, expected in [('active', 'M1,1Z'), ('context', 'M0,0Z')]:
            layer = generator.layer_svg(source, kind)
            paths = [p for p in layer.iter() if generator.local_tag(p) == 'path']
            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0].get('d'), expected)
            self.assertEqual(paths[0].get('fill-opacity'), '1')
            self.assertEqual(list(layer)[0].get('transform'), 'translate(2 3)')

    def test_invisible_ferry_path_remains_invisible(self):
        source = ET.fromstring('<svg><path d="M0,0L1,1Z" fill="none"/><path d="M2,2Z" fill="#E65345"/></svg>')
        active = generator.layer_svg(source, 'active')
        self.assertEqual([p.get('d') for p in active], ['M2,2Z'])

    def test_binary_coverage_threshold_and_secondary_checker(self):
        from PIL import Image
        active = Image.new('L', (72, 72))
        context = Image.new('L', (72, 72))
        active.putpixel((10, 10), 127)
        active.putpixel((11, 10), 128)
        for x in range(4):
            context.putpixel((x, 4), 255)
            active.putpixel((x, 5), 255)
        result = generator.native_from_layers(active, context)
        self.assertEqual(result.mode, '1')
        self.assertFalse(result.getpixel((10, 10)))
        self.assertTrue(result.getpixel((11, 10)))
        self.assertEqual([bool(result.getpixel((x, 4))) for x in range(4)],
                         [True, False, True, False])
        self.assertTrue(all(result.getpixel((x, 5)) for x in range(4)))

    def test_source_viewport_is_contained_without_stretching_or_cropping(self):
        from PIL import Image
        active = Image.new('L', (120, 60), 255)
        context = Image.new('L', (120, 60))
        result = generator.native_from_layers(active, context)
        self.assertEqual(result.size, (72, 72))
        self.assertEqual(result.getbbox(), (0, 18, 72, 54))


class NativeNavigationMappingTests(unittest.TestCase):
    def test_primary_hudiy_maneuver_semantics(self):
        # Api.proto values; do not substitute the unrelated Android enum.
        expected = {0: 'STRAIGHT', 1: 'DEPART', 2: 'STRAIGHT',
                    3: 'TURN_SLIGHT_RIGHT', 4: 'TURN_RIGHT',
                    5: 'TURN_SHARP_RIGHT', 6: 'TURN_U_TURN_COUNTERCLOCKWISE',
                    7: 'RAMP_ON_RIGHT', 8: 'RAMP_OFF_RIGHT', 9: 'FORK_RIGHT',
                    10: 'MERGE_RIGHT', 11: 'ROUNDABOUT_COUNTERCLOCKWISE',
                    12: 'ROUNDABOUT_EXIT_COUNTERCLOCKWISE', 14: 'STRAIGHT',
                    16: 'FERRY_BOAT', 17: 'FERRY_TRAIN', 19: 'DESTINATION_RIGHT'}
        app = NavApp(config())
        app.maneuver_side = 2
        for maneuver, name in expected.items():
            with self.subTest(maneuver=maneuver):
                app.maneuver_type = maneuver
                self.assertEqual(app._get_icon_name(), name)
                self.assertIn(name, ICON_NAMES)

    def test_roundabout_angle_controls_macro_exit_and_traffic_direction(self):
        for road_side, direction in (('right', 'COUNTERCLOCKWISE'), ('left', 'CLOCKWISE')):
            app = NavApp(config(road_side=road_side))
            self.assertEqual(app.road_side, road_side)
            app.maneuver_type = 13
            for angle in range(0, 360, 45):
                app.maneuver_angle = angle
                app.maneuver_side = 1
                name = app._get_icon_name()
                app.maneuver_side = 2
                self.assertEqual(app._get_icon_name(), name)
                self.assertIn(name, ICON_NAMES)
                self.assertTrue(name.endswith(direction))
            app.maneuver_angle = 90
            side = 'RIGHT' if road_side == 'right' else 'LEFT'
            self.assertEqual(app._get_icon_name(), 'ROUNDABOUT_' + side + '_' + direction)
            app.maneuver_angle = 180
            self.assertEqual(app._get_icon_name(), 'ROUNDABOUT_STRAIGHT_' + direction)

    def test_unspecified_merge_destination_and_unknown_fallback(self):
        app = NavApp(config())
        for maneuver, name in ((10, 'MERGE'), (19, 'DESTINATION'), (999, 'STRAIGHT')):
            app.maneuver_type = maneuver
            self.assertEqual(app._get_icon_name(), name)


class NativeNavigationViewTests(unittest.TestCase):
    def test_default_keeps_legacy_arrow(self):
        for native in (False, None, 'false'):
            view = app_with_route(native).get_view()
            self.assertEqual(view[0]['type'], 'nav_graphic_v2')
            self.assertEqual(view[1], {'group': 'arrow', 'cmd': 'draw_bitmap',
                                       'icon': 'TURN_RIGHT', 'x': 4, 'y': 1})
            self.assertFalse(any(item.get('cmd') == 'native_bitmap' for item in view))

    def test_opt_in_native_snapshot_then_hardware_overlays(self):
        view = app_with_route(True).get_view()
        self.assertEqual(view[0]['type'], 'nav_graphic_native')
        self.assertFalse(view[0]['clear_on_update'])
        icon = view[1]
        self.assertEqual(icon['group'], 'icon')
        self.assertEqual(icon['cmd'], 'native_bitmap')
        self.assertEqual(icon['render_order'], 'tiles')
        self.assertEqual(bytes.fromhex(icon['data_hex']), canvas_for_icon('TURN_RIGHT'))
        self.assertTrue(all('type' not in item for item in view[1:]))
        text = [item for item in view if item.get('cmd') == 'draw_text']
        self.assertEqual([(item['x'], item['y']) for item in text[:2]], [(42, 8), (42, 17)])
        self.assertEqual(text[-1]['y'], 39)
        self.assertTrue(any(item.get('cmd') == 'draw_line' and item['x'] == 61 for item in view))

    def test_distance_update_preserves_identical_native_snapshot(self):
        app = app_with_route(True)
        previous = app.get_view()
        app.update_hudiy(b'HUDIY_NAV_DISTANCE', {'label': '50 m'})
        changed = app.get_view()
        self.assertEqual(previous[1], changed[1])
        self.assertNotEqual(previous[2:], changed[2:])

    def test_no_route_stays_text_only(self):
        view = NavApp(config(True)).get_view()
        self.assertEqual(view[0]['type'], 'nav_no_route')
        self.assertEqual([item.get('cmd') for item in view[1:]], ['draw_text', 'draw_text'])


if __name__ == '__main__':
    unittest.main()
