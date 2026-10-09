"""Static tiny units and semantic symbols. Dynamic text never enters this layer.

Every reading symbol fits the reserved10-pixel icon column. Outlined conventional
vehicle/fluid/electrical symbols preserve black counters at the native LCD size.
"""


def _icon(rows):
    rows = rows.strip().splitlines()
    if not rows or len(rows) > 14 or any(len(row) != 10 for row in rows):
        raise ValueError('Reading icons must fit10x14 physical pixels')
    if any(set(row) - {'.', '#'} for row in rows):
        raise ValueError('Invalid icon pixel')
    return [row.replace('.', '0').replace('#', '1') for row in rows]


ICONS = {
    'oil': _icon("""
...####...
.....#....
.........#
.#######.#
#.#....##.
#.#....#..
.#######..
........#.
.......###
........#.
"""),
    'cool': _icon("""
...##.....
..#..#....
..#.##....
..#..#....
..#.##....
..#..#....
..#..#....
.##..##...
.#.##.#...
..####....
..........
##..##..##
..##..##..
##..##..##
"""),
    'temperature': _icon("""
....##....
...#..#...
...#.###..
...#..#...
...#.###..
...#..#...
...#.###..
...#..#...
..##..##..
..#.##.#..
..#.##.#..
...####...
"""),
    'boost': _icon("""
..######..
.#......#.
#...##...#
#..####..#
#.#.##.#.#
#...##...#
#...##...#
.#......#.
..######..
....##....
..######..
"""),
    'intake': _icon("""
.....#####
.....#...#
.....#.#.#
...#.#.#.#
....##.#.#
########.#
....##.#.#
...#.#.#.#
.....#.#.#
.....#...#
.....#####
"""),
    'air': _icon("""
.......#..
........#.
##########
........#.
.......#..
..........
.......#..
........#.
##########
........#.
.......#..
"""),
    'engine': _icon("""
...####...
....##....
..######..
..#....###
###....#.#
#.#....###
###....#..
..#....#..
..######..
"""),
    'gear': _icon("""
....##....
.#..##..#.
.########.
..##..##..
###....###
###....###
..##..##..
.########.
.#..##..#.
....##....
"""),
    'awd': _icon("""
##......##
##......##
##########
##..##..##
...#..#...
....##....
....##....
....##....
....##....
...#..#...
##..##..##
##########
##......##
##......##
"""),
    'ambient': _icon("""
....#.....
.#..#..#..
..#...#...
...###....
###...###.
...#.#....
###...###.
...###....
..#...#...
.#..#..#..
....#.....
"""),
    'fuel': _icon("""
.#####....
.#...#....
.#...#.#..
.#####.##.
.#...#..#.
.#...#.##.
.#...#.#.#
.#...#.#.#
.#...###.#
.#...#..#.
.#####....
#######...
"""),
    'target': _icon("""
....##....
..######..
.#..##..#.
.#......#.
###.##.###
###.##.###
.#......#.
.#..##..#.
..######..
....##....
"""),
    'spark': _icon("""
.....###..
....###...
...###....
..###.....
.#######..
....###...
...###....
..###.....
.###......
.##.......
.#........
"""),
    'inject': _icon("""
....##....
....##....
..######..
..#....#..
..#....#..
..######..
....##....
....##....
..#.##.#..
...####...
....##....
..#....#..
"""),
    'valve': _icon("""
..######..
....##....
....##....
.##....##.
.###..###.
.########.
.###..###.
.##....##.
"""),
    'voltage': _icon("""
..##..##..
##########
#........#
#..#.....#
#.###.##.#
#..#.....#
#........#
##########
"""),
    'steering': _icon("""
..######..
.#......#.
#........#
#........#
#.######.#
##..##..##
#...##...#
.#..##..#.
..######..
"""),
    'brake': _icon("""
...####...
..#....#..
.#..##..#.
##..##..##
##..##..##
##......##
.#..##..#.
..#....#..
...####...
"""),
    'speed': _icon("""
..######..
.#......#.
#.#....#.#
#.....#..#
#....#...#
##..#...##
#...#....#
.#......#.
..######..
"""),
    'lambda': _icon("""
..##......
...##.....
....##....
....##....
...#.##...
..#..##...
..#...##..
.#....##..
.#.....##.
"""),
    'pressure': _icon("""
..######..
.#......#.
#.#....#.#
#....#...#
#...#....#
#...##...#
.#......#.
..######..
....##....
....##....
..######..
"""),
    'torque': _icon("""
......#..#
.....##..#
....#.#..#
....#..##.
....#...#.
...#...#..
..#...#...
.#...#....
#...#.....
#..#......
#.#.......
.##.......
"""),
    'exhaust': _icon("""
..######..
..#....#..
###....###
###....###
..#....#..
..######..
"""),
    'clutch': _icon("""
...#..#...
..##..##..
.###..###.
.#.#..#.#.
##.#..#.##
##.#..#.##
.#.#..#.#.
.###..###.
..##..##..
...#..#...
"""),
    'pump': _icon("""
...####...
..#....#..
..#.#..#..
###.##.###
#.#.###.#.
###.##.###
..#.#..#..
..#....#..
...####...
...#..#...
..######..
"""),
    'timing': _icon("""
...####...
....##....
..######..
.#......#.
#...#....#
#...#....#
#...###..#
#........#
.#......#.
..######..
"""),
    'distance': _icon("""
...#..#...
...#..#...
..#....#..
..#.##.#..
..#.##.#..
.#......#.
.#......#.
.#..##..#.
#...##...#
#........#
#........#
"""),
    'level': _icon("""
.#......#.
.#......#.
.#......#.
.#......#.
.###..###.
.#..##..#.
.########.
.########.
.########.
.########.
.########.
"""),
    'status': _icon("""
##########
#........#
#......#.#
#.....#..#
#.#..#...#
#..##....#
#...#....#
#........#
##########
"""),
    'fan': _icon("""
...###....
...#..#...
...#..#...
.###.#.##.
#..#.##..#
#..##.#..#
.##.#.###.
...#..#...
...#..#...
....###...
"""),
    'throttle': _icon("""
##########
#........#
#..#.....#
#...#....#
#....##..#
#....##..#
#.....#..#
#......#.#
#........#
##########
"""),
    'pedal': _icon("""
..#####...
..#...#...
.#.#.#....
.#...#....
#.#.#.....
#...#.....
#####.....
..#.......
..#.......
..#######.
"""),
    'sparkplug': _icon("""
...####...
....##....
...####...
..######..
...#..#...
...####...
....##....
...####...
....##....
...####...
.....#....
....##....
"""),
    'camshaft': _icon("""
....##....
...####...
..#....#..
...####...
....##....
....####..
...#....#.
....####..
....##....
...####...
..#....#..
...####...
....##....
"""),
    'piston': _icon("""
.########.
.#......#.
.########.
.#......#.
.########.
.#......#.
.########.
...#..#...
....##....
....##....
...#..#...
...#..#...
....##....
"""),
    'wheel': _icon("""
..######..
.#......#.
#..####..#
#.#....#.#
#.#.##.#.#
#.#.##.#.#
#.#....#.#
#..####..#
.#......#.
..######..
"""),
    'abs': _icon("""
..######..
.#......#.
..........
.#..##..##
#.#.#.#.#.
###.##..##
#.#.#.#..#
#.#.##..##
..........
.#......#.
..######..
"""),
    'traction': _icon("""
..######..
.#......#.
##########
##......##
##########
.##....##.
..#....#..
.#....#...
..#....#..
...#....#.
..#....#..
.#....#...
"""),
    'compressor': _icon("""
.#..#..#..
..#.#.#...
...###....
####.####.
...###....
..#.#.#...
.#..#..#..
"""),
    'heater': _icon("""
.#..#..#..
..#..#..#.
.#..#..#..
##########
#.#.#.#..#
#.#.#.#..#
#.#.#.#..#
#.#.#.#..#
##########
.#......#.
"""),
    'door': _icon("""
.########.
.#......#.
.#......#.
.########.
.#......#.
.#...##.#.
.#......#.
.#......#.
.#......#.
.########.
"""),
    'hood': _icon("""
........#.
.......#..
......#...
...###....
..#....#..
.#......#.
##########
#........#
##......##
#........#
##########
.##....##.
"""),
    'lights': _icon("""
....####..
###.#...#.
....#....#
###.#....#
....#....#
###.#...#.
....####..
"""),
    'wiper': _icon("""
...####...
..#....#..
.#....#.#.
#....#...#
#...#....#
#..#.....#
#...#....#
##########
"""),
    'parking': _icon("""
##########
#........#
#..####..#
#..#..#..#
#..####..#
#..#.....#
#..#.....#
#........#
##########
"""),
    'seatbelt': _icon("""
...##.....
..#..#....
...##.....
..######..
.#....#.#.
.#...#..#.
.#..#...#.
..######..
...#..#...
..#....#..
..#....#..
"""),
}
# Saved IDs and friendly picker names remain interchangeable.
ICONS['rpm'] = ICONS['speed']
ICONS['flow'] = ICONS['air']
ICONS['ignition'] = ICONS['spark']
ICONS['current'] = ICONS['spark']

try:
    from .readings_units import UNITS, unit_rows
except ImportError:
    from readings_units import UNITS, unit_rows


# One ordered source for the DIS renderer and generated touchscreen picker.
# Recognizable components win over generic quantity/status terms. Explicit
# saved icon selections still override all automatic rules.
ICON_TERMS = (
    ('awd.oil_temperature', 'awd'),
    ('transmission.fluid_temperature', 'gear'),
    ('transmission.oil_temperature', 'gear'),
    ('transmission.gearbox_temperature', 'gear'),
    ('seatbelt', 'seatbelt'), ('seat_belt', 'seatbelt'),
    ('parking', 'parking'), ('handbrake', 'parking'),
    ('traction', 'traction'), ('stability', 'traction'), ('esp_', 'traction'),
    ('abs_', 'abs'), ('.abs', 'abs'),
    ('steering', 'steering'), ('brak', 'brake'),
    ('wheel_speed', 'wheel'), ('.wheel.', 'wheel'), ('tire', 'wheel'), ('tyre', 'wheel'),
    ('throttle', 'throttle'), ('pedal', 'pedal'),
    ('spark_plug', 'sparkplug'), ('sparkplug', 'sparkplug'), ('misfire', 'sparkplug'),
    ('camshaft', 'camshaft'), ('cam_', 'camshaft'),
    ('piston', 'piston'), ('compression', 'piston'),
    ('compressor', 'compressor'), ('air_condition', 'compressor'), ('ac_', 'compressor'),
    ('heater', 'heater'), ('heating', 'heater'),
    ('wiper', 'wiper'), ('washer', 'wiper'),
    ('headlight', 'lights'), ('headlamp', 'lights'), ('lighting', 'lights'),
    ('tail_light', 'lights'), ('fog_light', 'lights'),
    ('lights', 'lights'), ('_light', 'lights'), ('park_terminal', 'lights'),
    ('door', 'door'), ('hood', 'hood'), ('bonnet', 'hood'),
    ('oil_temperature', 'oil'), ('oil_level', 'oil'), ('oil_pressure', 'oil'),
    ('intake_temperature', 'intake'), ('coolant', 'cool'),
    ('ambient.', 'ambient'), ('boost', 'boost'),
    ('lambda', 'lambda'), ('oxygen', 'lambda'), ('catalyst', 'exhaust'),
    ('exhaust', 'exhaust'), ('emission', 'exhaust'),
    ('clutch', 'clutch'), ('fuel_pump', 'fuel'), ('pump', 'pump'),
    ('fuel_rail', 'pressure'), ('pressure', 'pressure'),
    ('torque', 'torque'),
    ('ignition_timing', 'spark'), ('timing_retard', 'spark'),
    ('injection', 'inject'), ('ignition', 'spark'), ('timing', 'timing'),
    ('maf', 'flow'), ('air_flow', 'flow'), ('flow', 'flow'), ('fan', 'fan'),
    ('battery', 'voltage'), ('voltage', 'voltage'), ('current', 'current'),
    ('sensor_fault', 'status'), ('warning', 'status'), ('switch', 'status'),
    ('_status', 'status'), ('_state', 'status'), ('_active', 'status'),
    ('_enabled', 'status'), ('_valid', 'status'), ('_ready', 'status'),
    ('rpm', 'rpm'), ('speed', 'speed'), ('distance', 'distance'),
    ('odometer', 'distance'), ('range', 'distance'),
    ('temperature', 'temperature'), ('level', 'level'),
    ('fuel', 'fuel'), ('valve', 'valve'), ('gear', 'gear'),
    ('transmission', 'gear'), ('awd', 'awd'),
    ('status', 'status'), ('state', 'status'),
)


def icon_for(slot):
    explicit = slot.get('icon', 'auto')
    if explicit in ICONS:
        return ICONS[explicit]
    value = str(slot.get('value_id', '')).lower()
    return ICONS[next((icon for term, icon in ICON_TERMS if term in value), 'engine')]


def static_layer(slots, units, focused, editing, control_mode, recording):
    canvas = bytearray(128 * 96 // 8)
    def mask(rows, x, y):
        for dy, row in enumerate(rows):
            for dx, bit in enumerate(row):
                xx, yy = x + dx, y + dy
                if bit == '1' and 0 <= xx < 128 and 0 <= yy < 96:
                    canvas[yy * 16 + xx // 8] |= 0x80 >> (xx % 8)
    for index, slot in enumerate(slots):
        x, y = (index % 2) * 64, 24 + index // 2 * 18
        mask(icon_for(slot), x, y + 1)
        rows = unit_rows(units[index])
        mask(rows, x + 54, y + max(1, (18-len(rows))//2))
    if control_mode:
        mask(ICONS['steering'], 118, 1)
    if recording:
        mask(['11','11'], 70, 6)
    if focused:
        left, width = {'page': (0, 68), 'start': (72, 42),
                       'mark': (76, 14), 'stop': (98, 14)}[focused]
        mask(['1' * width], left, 19)
        if editing:
            mask(['10101010'], 0, 21)
    return bytes(canvas)
