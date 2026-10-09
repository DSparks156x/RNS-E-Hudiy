"""Content checks shared by the Hudiy producer and navigation page."""
import math
import re

MANEUVER_TYPES = frozenset(range(1, 15)) | {16, 17, 19}
NO_ROUTE_LABELS = frozenset({
    'no route', 'no active route', 'no navigation', 'no guidance',
    'not navigating', 'navigation inactive', 'navigation ended',
})
EMPTY_LABELS = NO_ROUTE_LABELS | {'unknown', 'n/a', 'none'}


def label_text(value):
    return '' if value is None else str(value).strip()


def is_no_route(value):
    return label_text(value).casefold().rstrip('.!').strip() in NO_ROUTE_LABELS


def distance_meters(value):
    """Parse a finite nonnegative distance; absent/invalid content returns -1."""
    if isinstance(value, bool):
        return -1.0
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and value >= 0 else -1.0
    text = label_text(value).casefold()
    if text in ('now', 'arrived'):
        return 0.0
    match = re.fullmatch(r'(\d+(?:[.,]\d+)*(?:/\d+)?)\s*(m|km|mi|ft)?', text)
    if not match:
        return -1.0
    number, unit = match.groups()
    try:
        if '/' in number:
            numerator, denominator = number.split('/')
            result = float(numerator) / float(denominator)
        else:
            # Preserve decimal comma and common thousands separators. For
            # mixed separators, the rightmost separator marks decimals.
            if ',' in number and '.' in number:
                if number.rfind(',') > number.rfind('.'):
                    number = number.replace('.', '').replace(',', '.')
                else:
                    number = number.replace(',', '')
            elif ',' in number:
                number = (number.replace(',', '') if len(number.split(',')[-1]) == 3
                          else number.replace(',', '.'))
            result = float(number)
        result *= {'km': 1000.0, 'mi': 1609.344, 'ft': .3048}.get(unit, 1.0)
        return result if math.isfinite(result) else -1.0
    except (ValueError, ZeroDivisionError, OverflowError):
        return -1.0


def has_distance_content(value):
    """Zero and arrival are route content; status labels and bad units are not."""
    return distance_meters(value) >= 0


def has_route_content(data):
    """Explicit route absence overrides cached/type/default provider fields."""
    if data.get('has_route') is False:
        return False
    description = label_text(data.get('description'))
    distance = data.get('distance')
    if is_no_route(description) or is_no_route(distance):
        return False
    if description and description.casefold().rstrip('.!').strip() not in EMPTY_LABELS:
        return True
    # Default/cached maneuver types are attributes, not evidence of guidance.
    return has_distance_content(distance)
