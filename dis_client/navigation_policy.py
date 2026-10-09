"""Navigation interruptions, separate from the driver's manually selected app."""
from dataclasses import dataclass
import math


@dataclass
class NavigationPolicy:
    approach_m: float = 500
    return_m: float = 1000
    peek_s: float = 5
    active: bool = False
    maneuver: object = None
    peek_until: float = 0
    approaching: bool = False
    approach_armed: bool = True

    def __post_init__(self):
        for name, fallback in (('approach_m', 500), ('return_m', 1000), ('peek_s', 5)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                setattr(self, name, fallback)
        self.return_m = max(self.return_m, self.approach_m)

    def reset(self):
        self.active = False
        self.maneuver = None
        self.peek_until = 0
        self.approaching = False
        self.approach_armed = True

    def manual_select(self):
        # Suppress this approach until the maneuver changes or the distance
        # retreats past the return threshold. Repeated updates are not events.
        self.peek_until = 0
        self.approaching = False
        self.approach_armed = False

    def update(self, available, maneuver, meters, now, enabled=True):
        if not available:
            self.reset()
            return False
        changed = not self.active or maneuver != self.maneuver
        self.active = True
        self.maneuver = maneuver
        if changed:
            self.peek_until = now + self.peek_s
            self.approach_armed = True
        try:
            known = not isinstance(meters, bool) and math.isfinite(meters) and meters >= 0
        except TypeError:
            known = False
        if known and meters > self.return_m:
            self.approaching = False
            self.approach_armed = True
        elif known and meters <= self.approach_m and self.approach_armed:
            self.approaching = True
            self.approach_armed = False
        return bool(enabled and (self.approaching or now < self.peek_until))
