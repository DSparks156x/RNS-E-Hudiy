"""One owner for the navigation wheel, with release-based click recognition.

This module is independent of uinput and ZeroMQ so timing and ownership can be
tested without vehicle hardware. Volume/PTT remain in the keyboard service.
"""
import logging
import time


logger = logging.getLogger(__name__)


class WheelControlRouter:
    SUPPORTED_APPS = frozenset(('app_car_info', 'app_readings', 'app_phone'))

    def __init__(self, emit, normal, *, double_click_ms=350, long_count=5,
                 heartbeat_timeout=3.0, auto_phone=False, clock=time.monotonic):
        self.emit, self.normal, self.clock = emit, normal, clock
        self.double_window = max(0.15, min(0.8, double_click_ms / 1000))
        self.long_count = max(2, int(long_count))
        self.timeout = heartbeat_timeout
        self.auto_phone = auto_phone
        self.app = None
        self.context_id = None
        self.ready = False
        self.context_time = None
        self.owner = 'normal'
        self.target = 'center'
        self.controllable = True
        self.top_ready = False
        self.top_time = None
        self.phone_active = False
        self.call_override = None
        self.pressed = None
        self.press_count = 0
        self.long_fired = False
        self.pending = {}
        self.scroll_lock = None

    @property
    def supported(self):
        return self.ready and self.controllable and self.app in self.SUPPORTED_APPS

    @property
    def top_supported(self):
        return self.ready and self.phone_active and self.top_ready

    def _emit(self, event):
        self.emit(event, self.owner, 'app_phone_top' if self.owner == 'dis' and self.target == 'top' else self.app)

    def heartbeat(self):
        self._emit('mode')

    def _auto_phone(self):
        if not self.auto_phone or not self.phone_active or self.call_override == 'normal':
            return
        if self.owner == 'dis' and self.target == 'center' and self.app != 'app_phone':
            return  # Explicit readings control takes priority over call auto takeover.
        if self.app == 'app_phone' and self.supported:
            self.target = 'center'
            self._set_owner('dis')
        elif self.top_supported:
            self.target = 'top'
            self._set_owner('dis')

    def top_context(self, ready, now=None):
        self.top_ready = bool(ready)
        self.top_time = self.clock() if now is None else now
        if self.target == 'top' and self.owner == 'dis' and not self.top_ready:
            self._set_owner('normal')
        self._auto_phone()

    def _clear_gestures(self):
        self.pressed = None
        self.press_count = 0
        self.long_fired = False
        self.pending.clear()
        self.scroll_lock = None

    def _set_owner(self, owner):
        valid = self.top_supported if self.target == 'top' else self.supported
        owner = owner if valid else 'normal'
        if owner != self.owner:
            self.owner = owner
            self._clear_gestures()
            logger.info('Wheel control changed to %s (app=%s, target=%s)',
                        owner, self.app, self.target)
        self._emit('mode')

    def context(self, app, ready, now=None, context_id=None, controllable=True):
        now = self.clock() if now is None else now
        changed = (app != self.app or bool(ready) != self.ready or context_id != self.context_id
                   or bool(controllable) != self.controllable)
        if changed and self.phone_active and self.app == 'app_phone' and self.ready:
            # A stalk/app change explicitly gives the wheel back for this call.
            self.call_override = 'normal'
        elif changed and self.phone_active and self.owner == 'dis' and app != 'app_phone':
            self.call_override = 'normal'
        self.app, self.ready, self.context_time = app, bool(ready), now
        self.context_id = context_id
        self.controllable = bool(controllable)
        if changed:
            logger.info('DIS wheel context: app=%s, ready=%s, controllable=%s, epoch=%s',
                        self.app, self.ready, self.controllable, self.context_id)
            self._clear_gestures()
            self._set_owner('normal')
        self._auto_phone()

    def phone(self, active):
        active = bool(active)
        if active != self.phone_active:
            self.call_override = None
            self.phone_active = active
            if not active and (self.app == 'app_phone' or self.target == 'top'):
                self._set_owner('normal')
        self._auto_phone()

    def toggle(self):
        if not self.supported and not self.top_supported:
            logger.warning('MODE toggle unavailable: app=%s, ready=%s, controllable=%s, '
                           'top_ready=%s, phone_active=%s', self.app, self.ready,
                           self.controllable, self.top_ready, self.phone_active)
            self._set_owner('normal')
            return
        desired = 'normal' if self.owner == 'dis' else 'dis'
        if desired == 'dis':
            self.target = 'center' if self.supported else 'top'
        if self.phone_active:
            self.call_override = desired
        self._set_owner(desired)

    def tick(self, now=None):
        now = self.clock() if now is None else now
        if self.context_time is not None and now - self.context_time > self.timeout:
            self.context_time = None
            self.ready = False
            self._clear_gestures()
            self._set_owner('normal')
        if self.top_time is not None and now - self.top_time > self.timeout:
            self.top_ready = False
            self.top_time = None
            if self.target == 'top':
                self._clear_gestures()
                self._set_owner('normal')
        for button, deadline in list(self.pending.items()):
            # A second press that began inside the window remains a candidate
            # until release (or a long press). Do not fire the first click while
            # that second press is still down.
            if now >= deadline and button != self.pressed:
                self.pending.pop(button, None)
                if button == 'mode':
                    self.normal('mode_short')
                elif self.owner == 'dis':
                    self._emit('select')

    def disconnect(self):
        self.ready = False
        self.context_time = None
        self._clear_gestures()
        self._set_owner('normal')

    def handle(self, action, now=None):
        """Accept mode/click repeated press frames, scroll pulses and release."""
        now = self.clock() if now is None else now
        self.tick(now)
        if action in ('scroll_up', 'scroll_down'):
            if self.scroll_lock != action:
                self.scroll_lock = action
                if self.owner == 'dis':
                    self._emit('previous' if action == 'scroll_up' else 'next')
                else:
                    self.normal(action)
            return
        if action == 'release':
            button, held = self.pressed, self.long_fired
            self.pressed = None
            self.press_count = 0
            self.long_fired = False
            self.scroll_lock = None
            if button is None or held:
                return
            if button == 'click' and self.owner == 'normal':
                self.normal('scroll_click_short')
                return
            if button in self.pending:
                self.pending.pop(button, None)
                if button == 'mode':
                    logger.info('MODE double-click recognized')
                    self.toggle()
                elif self.owner == 'dis':
                    self._emit('back')
            else:
                self.pending[button] = now + self.double_window
            return
        if action not in ('mode', 'click'):
            return
        if action != self.pressed:
            self.pressed = action
            self.press_count = 0
            self.long_fired = False
        self.press_count += 1
        if not self.long_fired and self.press_count >= self.long_count:
            self.long_fired = True
            self.pending.pop(action, None)
            if action == 'mode':
                self.normal('mode_long')
            elif self.owner == 'normal':
                self.normal('scroll_click_long')
