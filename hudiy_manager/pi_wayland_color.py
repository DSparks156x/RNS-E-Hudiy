#!/usr/bin/env python3
"""Per-output Wayland RGB gamma/contrast adapter; no configuration edits.

Originally supplied from RNSE hacking/tools/pi_wayland_color.py by the owner.
Manager integration adds explicit socket selection, reusable controls and a
single-iteration event pump; the standalone CLI remains available.

Uses system libwayland-client and wlr-gamma-control-v1. --list never creates a
gamma control. --apply holds exclusive control until Ctrl+C; destroying the
control restores the compositor's original table. Actual Pi testing is pending.
"""
import argparse
import array
import ctypes as C
import ctypes.util
from dataclasses import dataclass, field
import errno
import json
import math
import os
import select
import signal
import sys
import tempfile
import time


def finite_bound(name, value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f'{name} must be a finite real number')
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError(f'{name} must be a finite real number') from exc
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f'{name} must be within {low}..{high}')
    return value


@dataclass(frozen=True)
class ColorSettings:
    gamma: float = 1.0
    contrast: float = 1.0
    black_point: float = 0.0
    gains: tuple = (1.0, 1.0, 1.0)

    def __post_init__(self):
        for name, lo, hi in [('gamma', .25, 4), ('contrast', 0, 4),
                             ('black_point', 0, .5)]:
            object.__setattr__(self, name, finite_bound(name, getattr(self, name), lo, hi))
        if not isinstance(self.gains, (tuple, list)) or len(self.gains) != 3:
            raise ValueError('gains must contain exactly R/G/B values')
        object.__setattr__(self, 'gains', tuple(finite_bound(f'gain_{c}', v, 0, 4)
                                             for c, v in zip('rgb', self.gains)))


def gamma_ramps(size, settings=ColorSettings()):
    """Native-endian uint16, planar R then G then B, not RNSE5-bit pixels.

    x=i/(size-1); u=clamp((x-black)/(1-black));
    v=clamp(contrast*(u-.5)+.5); y=clamp(gain*v**(1/gamma)).
    Gamma>1 brightens midtones. Independent gains adjust white balance.
    """
    if type(size) is not int or not 2 <= size <= 65536:
        raise ValueError('gamma size must be an integer within2..65536')
    if not isinstance(settings, ColorSettings):
        raise ValueError('settings must be ColorSettings')
    values = array.array('H')
    if values.itemsize != 2:
        raise RuntimeError('platform uint16 storage is unavailable')
    clamp = lambda x: max(0.0, min(1.0, x))
    for gain in settings.gains:
        for i in range(size):
            u = clamp((i/(size-1)-settings.black_point)/(1-settings.black_point))
            v = clamp(settings.contrast*(u-.5)+.5)
            y = clamp(gain*v**(1/settings.gamma))
            values.append(min(65535, math.floor(y*65535+.5)))
    return values.tobytes()


class Interface(C.Structure):
    pass


class Message(C.Structure):
    _fields_ = [('name', C.c_char_p), ('signature', C.c_char_p),
                ('types', C.POINTER(C.POINTER(Interface)))]


Interface._fields_ = [('name', C.c_char_p), ('version', C.c_int),
                     ('method_count', C.c_int), ('methods', C.POINTER(Message)),
                     ('event_count', C.c_int), ('events', C.POINTER(Message))]


class Argument(C.Union):
    _fields_ = [('i', C.c_int32), ('u', C.c_uint32), ('f', C.c_int32),
                ('s', C.c_char_p), ('o', C.c_void_p), ('n', C.c_uint32),
                ('a', C.c_void_p), ('h', C.c_int32)]


class GammaProtocol:
    """Descriptors derived from the primary wlr-gamma-control-v1 XML.

    https://github.com/swaywm/wlr-protocols/blob/master/unstable/wlr-gamma-control-unstable-v1.xml
    Uses libwayland marshalling/listeners, never constructs a socket packet.
    All backing arrays live as long as this object.
    """
    def __init__(self, output_interface):
        self.control = Interface()
        self.manager = Interface()
        self.get_types = (C.POINTER(Interface)*2)(C.pointer(self.control), output_interface)
        self.null_type = (C.POINTER(Interface)*1)()
        self.manager_methods = (Message*2)(
            Message(b'get_gamma_control', b'no', self.get_types),
            Message(b'destroy', b'', None))
        self.control_methods = (Message*2)(
            Message(b'set_gamma', b'h', self.null_type), Message(b'destroy', b'', None))
        self.control_events = (Message*2)(
            Message(b'gamma_size', b'u', self.null_type), Message(b'failed', b'', None))
        self.manager = self._set(self.manager, b'zwlr_gamma_control_manager_v1',
                                 self.manager_methods, None)
        self.control = self._set(self.control, b'zwlr_gamma_control_v1',
                                 self.control_methods, self.control_events)

    @staticmethod
    def _set(obj, name, methods, events):
        obj.name, obj.version = name, 1
        obj.method_count, obj.methods = len(methods), methods
        obj.event_count, obj.events = (len(events), events) if events is not None else (0, None)
        return obj


class WaylandAPI:
    """Minimal native libwayland ABI adapter; injectable library supports tests."""
    def __init__(self, library=None, core_interfaces=None):
        if library is None:
            path = ctypes.util.find_library('wayland-client') or 'libwayland-client.so.0'
            library = C.CDLL(path, use_errno=True)
        self.lib = library
        signatures = {
            'wl_display_connect': (C.c_void_p, [C.c_char_p]),
            'wl_display_disconnect': (None, [C.c_void_p]),
            'wl_display_roundtrip': (C.c_int, [C.c_void_p]),
            'wl_display_dispatch': (C.c_int, [C.c_void_p]),
            'wl_display_dispatch_pending': (C.c_int, [C.c_void_p]),
            'wl_display_flush': (C.c_int, [C.c_void_p]),
            'wl_display_get_fd': (C.c_int, [C.c_void_p]),
            'wl_proxy_get_version': (C.c_uint32, [C.c_void_p]),
            'wl_proxy_add_listener': (C.c_int, [C.c_void_p, C.POINTER(C.c_void_p), C.c_void_p]),
            'wl_proxy_marshal_array': (None, [C.c_void_p, C.c_uint32, C.POINTER(Argument)]),
            'wl_proxy_marshal_array_constructor_versioned':
                (C.c_void_p, [C.c_void_p, C.c_uint32, C.POINTER(Argument), C.POINTER(Interface), C.c_uint32]),
            'wl_proxy_destroy': (None, [C.c_void_p]),
        }
        for name, (result, args) in signatures.items():
            fn = getattr(library, name)
            fn.restype, fn.argtypes = result, args
        self.core = core_interfaces or {
            name: Interface.in_dll(library, name+'_interface')
            for name in ['wl_registry', 'wl_output', 'wl_callback']}
        self.protocol = GammaProtocol(C.pointer(self.core['wl_output']))

    def construct(self, proxy, opcode, interface, version, args):
        result = self.lib.wl_proxy_marshal_array_constructor_versioned(
            proxy, opcode, args, C.pointer(interface), version)
        if not result:
            raise RuntimeError(f'could not create {interface.name.decode()}')
        return result

    def bind(self, registry, global_id, interface, version):
        args = (Argument*4)()
        args[0].u, args[1].s, args[2].u, args[3].o = global_id, interface.name, version, None
        return self.construct(registry, 0, interface, version, args)

    def destroy(self, proxy, opcode=None):
        if proxy:
            if opcode is not None:
                self.lib.wl_proxy_marshal_array(proxy, opcode, None)
            self.lib.wl_proxy_destroy(proxy)


@dataclass
class Output:
    global_id: int
    version: int
    proxy: int
    name: str = ''
    description: str = ''
    make: str = ''
    model: str = ''
    modes: list = field(default_factory=list)
    scale: int = 1
    removed: bool = False

    @property
    def identifier(self):
        return self.name or f'global-{self.global_id}'

    def info(self):
        return dict(output=self.identifier, name=self.name or None,
                    description=self.description, make=self.make, model=self.model,
                    scale=self.scale, modes=self.modes, global_id=self.global_id,
                    wl_output_version=self.version)


def choose_output(outputs, requested):
    outputs = [o for o in outputs if not o.removed]
    if requested is None:
        if len(outputs) != 1:
            raise ValueError('use --output with an exact identifier from --list; automatic selection requires one output')
        return outputs[0]
    matches = [o for o in outputs if o.identifier == requested]
    if len(matches) != 1:
        raise ValueError(f'output {requested!r} does not identify exactly one current output')
    return matches[0]


class WaylandSession:
    def __init__(self, api=None, display_name=None):
        self.api = api or WaylandAPI()
        self.display_name = display_name
        self.display = self.registry = self.manager = self.control = None
        self.outputs = []
        self.manager_global = None
        self.gamma_size = None
        self.failed = False
        self.selected = None
        self.callbacks = []  # Keep CFUNCTYPE and listener arrays alive.
        self.callback_errors = []

    def listen(self, proxy, definitions):
        callbacks = []
        for types, callback in definitions:
            def guarded(*args, target=callback):
                try:
                    target(*args)
                except Exception as exc:
                    self.callback_errors.append(str(exc))
                    self.failed = True
            callbacks.append(C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, *types)(guarded))
        listener = (C.c_void_p*len(callbacks))(*(C.cast(c, C.c_void_p).value for c in callbacks))
        self.callbacks.append((callbacks, listener))
        if self.api.lib.wl_proxy_add_listener(proxy, listener, None) != 0:
            raise RuntimeError('could not register Wayland listener')

    def check(self, result):
        if result < 0:
            raise RuntimeError('Wayland connection failed or compositor disconnected')
        if self.callback_errors:
            raise RuntimeError('Wayland event: '+self.callback_errors[0])

    def roundtrip(self, timeout=2.0):
        """A bounded wl_display.sync roundtrip, so a stalled compositor cannot
        leave the manager's sole native worker permanently blocked.
        """
        completed = [False]
        args = (Argument*1)()
        callback = self.api.construct(self.display, 0, self.api.core['wl_callback'], 1, args)
        listener = None
        try:
            self.listen(callback, [([C.c_uint32], lambda *_: completed.__setitem__(0, True))])
            listener = self.callbacks[-1]
            fd = self.api.lib.wl_display_get_fd(self.display)
            if fd < 0:
                raise RuntimeError('Wayland connection has no file descriptor')
            deadline = time.monotonic() + timeout
            while not completed[0]:
                self.check(self.api.lib.wl_display_dispatch_pending(self.display))
                if completed[0]:
                    break
                result = self.api.lib.wl_display_flush(self.display)
                writable = result < 0 and C.get_errno() == errno.EAGAIN
                if result < 0 and not writable:
                    self.check(result)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('Wayland compositor did not answer within two seconds')
                readable, _, _ = select.select([fd], [fd] if writable else [], [], remaining)
                if readable:
                    self.check(self.api.lib.wl_display_dispatch(self.display))
        finally:
            self.api.destroy(callback)
            if listener is not None:
                self.callbacks = [item for item in self.callbacks if item is not listener]

    def discover(self):
        display_name = os.fsencode(self.display_name) if self.display_name else None
        self.display = self.api.lib.wl_display_connect(display_name)
        if not self.display:
            raise RuntimeError('cannot connect to Wayland; run as the desktop user with WAYLAND_DISPLAY and XDG_RUNTIME_DIR')
        args = (Argument*1)()
        self.registry = self.api.construct(self.display, 1, self.api.core['wl_registry'], 1, args)
        self.listen(self.registry, [([C.c_uint32, C.c_char_p, C.c_uint32], self.global_added),
                                    ([C.c_uint32], self.global_removed)])
        self.roundtrip()  # Registry globals; output bind requests get queued.
        self.roundtrip()  # Bound outputs' name/mode information.
        return dict(gamma_protocol=bool(self.manager_global),
                    gamma_protocol_version=self.manager_global[1] if self.manager_global else None,
                    outputs=[o.info() for o in self.outputs if not o.removed])

    def global_added(self, _data, _proxy, global_id, name, version):
        if name == b'zwlr_gamma_control_manager_v1':
            self.manager_global = (global_id, version)
        elif name == b'wl_output':
            bound_version = min(version, 4)
            proxy = self.api.bind(self.registry, global_id, self.api.core['wl_output'], bound_version)
            output = Output(global_id, bound_version, proxy)
            self.outputs.append(output)
            decode = lambda x: x.decode('utf-8', 'replace') if x else ''
            def geometry(_d, _p, x, y, pw, ph, subpixel, make, model, transform):
                output.make, output.model = decode(make), decode(model)
            def mode(_d, _p, flags, w, h, rate):
                item = dict(width=w, height=h, refresh_mhz=rate,
                            current=bool(flags & 1), preferred=bool(flags & 2))
                output.modes.append(item)
            def scale(_d, _p, value):
                output.scale = value
            def text(attribute):
                return lambda _d, _p, value: setattr(output, attribute, decode(value))
            self.listen(proxy, [([C.c_int32]*5+[C.c_char_p, C.c_char_p, C.c_int32], geometry),
                                ([C.c_uint32, C.c_int32, C.c_int32, C.c_int32], mode),
                                ([], lambda *_: None), ([C.c_int32], scale),
                                ([C.c_char_p], text('name')), ([C.c_char_p], text('description'))])

    def global_removed(self, _data, _proxy, global_id):
        for output in self.outputs:
            if output.global_id == global_id:
                output.removed = True
                if output is self.selected:
                    self.failed = True
        if self.manager_global and self.manager_global[0] == global_id:
            self.manager_global = None

    def apply(self, requested, settings):
        # No gamma-control object is acquired until this exact selection succeeds.
        self.selected = choose_output(self.outputs, requested)
        if not self.manager_global:
            raise RuntimeError('compositor does not advertise wlr-gamma-control-v1')
        self.manager = self.api.bind(self.registry, self.manager_global[0], self.api.protocol.manager, 1)
        args = (Argument*2)()
        args[0].o, args[1].o = None, self.selected.proxy
        self.control = self.api.construct(self.manager, 0, self.api.protocol.control, 1, args)
        self.listen(self.control, [([C.c_uint32], self.size_received), ([], self.control_failed)])
        self.roundtrip()
        self.ensure_control()
        if self.gamma_size is None:
            raise RuntimeError('compositor did not advertise a gamma ramp size')
        return self.update_settings(settings)

    def update_settings(self, settings):
        """Update the existing exclusive control without creating another one."""
        self.ensure_control()
        if not self.control or self.gamma_size is None or self.selected is None:
            raise RuntimeError('gamma control has not been acquired')
        data = gamma_ramps(self.gamma_size, settings)
        # libwayland duplicates/queues the fd as part of marshalling; the source
        # fd can close after marshal. tempfile supplies anonymous seekable storage.
        with tempfile.TemporaryFile() as ramp:
            ramp.write(data)
            ramp.flush()
            ramp.seek(0)
            args = (Argument*1)()
            args[0].h = ramp.fileno()
            self.api.lib.wl_proxy_marshal_array(self.control, 0, args)
            self.roundtrip()
        self.ensure_control()
        return dict(output=self.selected.identifier, gamma_size=self.gamma_size,
                    gamma=settings.gamma, contrast=settings.contrast,
                    black_point=settings.black_point, gains=settings.gains)

    def size_received(self, _data, _proxy, size):
        if not 2 <= size <= 65536:
            raise ValueError(f'unsupported gamma ramp size {size}; expected2..65536')
        self.gamma_size = size

    def control_failed(self, *_args):
        self.failed = True

    def ensure_control(self):
        if self.failed:
            raise RuntimeError('gamma control failed: output unsupported, another gamma client owns it, or compositor revoked it')

    def hold(self, stopped):
        while not stopped():
            self.pump(.25)

    def pump(self, timeout=.05):
        """Dispatch pending events on the same thread that owns this session."""
        fd = self.api.lib.wl_display_get_fd(self.display)
        if fd < 0:
            raise RuntimeError('Wayland connection has no file descriptor')
        self.check(self.api.lib.wl_display_dispatch_pending(self.display))
        self.ensure_control()
        result = self.api.lib.wl_display_flush(self.display)
        if result < 0 and C.get_errno() != errno.EAGAIN:
            self.check(result)
        readable, _, _ = select.select([fd], [], [], timeout)
        if readable:
            self.check(self.api.lib.wl_display_dispatch(self.display))
            self.ensure_control()

    def close(self):
        if self.display:
            errors = []
            def attempt(operation):
                try:
                    operation()
                except Exception as exc:
                    errors.append(str(exc))
            try:
                # Destructor is the protocol-defined restoration operation.
                attempt(lambda: self.api.destroy(self.control, 1))
                attempt(lambda: self.api.destroy(self.manager, 1))
                for output in self.outputs:
                    attempt(lambda o=output: self.api.destroy(o.proxy, 0 if o.version >= 3 else None))
                attempt(lambda: self.api.destroy(self.registry))
                attempt(lambda: self.api.lib.wl_display_flush(self.display))
            finally:
                # Disconnect also releases server-side objects if a destructor
                # could not be queued or the compositor connection failed.
                attempt(lambda: self.api.lib.wl_display_disconnect(self.display))
                self.control = self.manager = self.registry = self.display = None
                self.outputs.clear()
                self.callbacks.clear()
            if errors:
                raise RuntimeError('Wayland cleanup: '+errors[0])


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument('--list', action='store_true', help='read-only protocol/output discovery')
    operation.add_argument('--apply', action='store_true', help='temporarily apply and hold until Ctrl+C')
    parser.add_argument('--output', help='exact output identifier from --list; required unless one output exists')
    parser.add_argument('--gamma', type=float, default=1)
    parser.add_argument('--contrast', type=float, default=1)
    parser.add_argument('--black-point', type=float, default=0)
    parser.add_argument('--gain-r', type=float, default=1)
    parser.add_argument('--gain-g', type=float, default=1)
    parser.add_argument('--gain-b', type=float, default=1)
    args = parser.parse_args(argv)
    try:
        args.settings = ColorSettings(args.gamma, args.contrast, args.black_point,
                                      (args.gain_r, args.gain_g, args.gain_b))
    except ValueError as exc:
        parser.error(str(exc))
    return args


def main(argv=None, session_factory=WaylandSession):
    args = parse_args(argv)
    session = None
    previous = {}
    stopped = False
    status = 1
    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True
    try:
        session = session_factory()
        inventory = session.discover()
        if args.list:
            print(json.dumps(inventory, indent=2))
            status = 0
        else:
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, stop)
            if not stopped:
                result = session.apply(args.output, args.settings)
                print(json.dumps(result, indent=2))
                print('Temporary output color active. Ctrl+C restores original gamma tables.', flush=True)
                session.hold(lambda: stopped)
            status = 0
    except KeyboardInterrupt:
        status = 0
    except (OSError, AttributeError, ValueError, RuntimeError) as exc:
        print(f'pi_wayland_color: {exc}', file=sys.stderr)
        status = 1
    finally:
        try:
            if session is not None:
                session.close()
        except Exception as exc:
            print(f'pi_wayland_color: cleanup failed: {exc}', file=sys.stderr)
            status = 1
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)
    return status


if __name__ == '__main__':
    raise SystemExit(main())
