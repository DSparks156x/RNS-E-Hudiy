"""Thin adapter, argument, and controller-dispatch shell for the PQ flasher."""
import argparse
import json
import logging
import struct
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def number(value):
    return int(value, 0)


def add_adapter_arguments(parser, default="j2534"):
    parser.add_argument("--adapter", choices=("j2534", "panda", "socketcan"), default=default)
    parser.add_argument("--dll", help="J2534 DLL path (default: registry discovery)")
    parser.add_argument("--baud", type=int, default=500000)
    parser.add_argument("--bus", type=int, choices=(0, 1, 2), default=0,
                        help="Physical Panda CAN bus; protocol sees logical bus 0")
    parser.add_argument("--serial", help="Panda serial number")
    parser.add_argument("--channel", default="can0", help="SocketCAN interface (default can0)")


class PandaAdapter:
    def __init__(self, device, bus):
        self.device = device
        self.bus = bus
        self.description = f"Panda CAN {bus}"

    def can_send(self, address, data, bus=0):
        self.device.can_send(address, data, self.bus)

    def can_recv(self, timeout_ms=10):
        deadline = time.monotonic() + timeout_ms / 1000
        while True:
            frames = []
            for frame in self.device.can_recv():
                if len(frame) == 3:
                    address, data, bus = frame
                else:
                    address, _, data, bus = frame
                if bus == self.bus:
                    frames.append((address, bytes(data), 0))
            if frames or time.monotonic() >= deadline:
                return frames
            time.sleep(0.001)

    def can_clear(self, flags=0xffff):
        self.device.can_clear(flags)

    def disconnect(self):
        pass

    def close(self):
        try:
            self.device.set_safety_mode(0)
        finally:
            self.device.close()


class SocketCANAdapter:
    def __init__(self, bus, message_type, channel):
        self.device = bus
        self.message_type = message_type
        self.description = f"SocketCAN {channel}"

    def can_send(self, address, data, bus=0):
        self.device.send(self.message_type(arbitration_id=address, data=data,
                                           is_extended_id=False))

    def can_recv(self, timeout_ms=10):
        message = self.device.recv(timeout=timeout_ms / 1000)
        if (message is None or message.is_error_frame or message.is_remote_frame
                or message.is_extended_id):
            return []
        return [(message.arbitration_id, bytes(message.data), 0)]

    def can_clear(self, flags=0xffff):
        for _ in range(4096):
            if self.device.recv(timeout=0) is None:
                break

    def disconnect(self):
        pass

    def close(self):
        self.device.shutdown()


def open_adapter(args):
    """Open one adapter; caller owns close(), including on protocol failures."""
    if args.adapter == "j2534":
        if args.bus != 0:
            raise ValueError("--bus is a Panda option; J2534 uses bus 0")
        if struct.calcsize("P") != 4:
            raise RuntimeError(
                "J2534 requires 32-bit Python; use the project's Python311-32 interpreter")
        from flasher.j2534 import J2534Device
        device = J2534Device(args.dll)
        try:
            device.open()
            device.connect_can(baudrate=args.baud)
            device.description = f"J2534 {device.dll_path}"
            return device
        except BaseException:
            device.close()
            raise
    if args.adapter == "panda":
        from panda import Panda
        device = Panda(args.serial) if args.serial else Panda()
        adapter = PandaAdapter(device, args.bus)
        try:
            device.set_can_speed_kbps(args.bus, args.baud / 1000)
            device.can_clear(0xffff)
            device.set_safety_mode(Panda.SAFETY_ALLOUTPUT)
            return adapter
        except BaseException:
            adapter.close()
            raise
    if args.adapter == "socketcan":
        if args.bus != 0:
            raise ValueError("Use --channel to select SocketCAN; --bus is a Panda option")
        import can
        bus = can.Bus(interface="socketcan", channel=args.channel, receive_own_messages=False)
        return SocketCANAdapter(bus, can.Message, args.channel)
    raise ValueError(f"Unknown CAN adapter: {args.adapter}")


def build_parser(family=None):
    description = "VAG TP2/KWP shared flasher/readout"
    if family is not None:
        description += f" ({family.name})"
    parser = argparse.ArgumentParser(description=description)
    add_adapter_arguments(parser)
    from flasher.controllers.registry import parse_module
    parser.add_argument(
        "--module", type=parse_module, required=True, metavar="MODULE",
        help="TP2 logical module ID or alias (for example awd/0x0A or eps/0x09)")
    parser.add_argument("--input", help="CPU-linear image to flash")
    parser.add_argument("--start", type=number)
    parser.add_argument("--end", type=number, help="Inclusive end address")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Skip the destructive YES prompt")
    parser.add_argument("--ident-only", action="store_true")
    parser.add_argument("--readout", action="store_true")
    parser.add_argument("--read-eeprom", action="store_true",
                        help="Read the complete 1 KiB serial EEPROM (EPS only)")
    parser.add_argument("--out")
    parser.add_argument("--reference")
    parser.add_argument("--readout-passes", type=int, choices=(1, 2), default=1)
    parser.add_argument("--readout-window", type=number, default=0x10000)
    parser.add_argument(
        "--recovery", action="store_true",
        help="Flash an already-bootloadered module; skip application identification/session entry")
    parser.add_argument("--log")
    parser.add_argument("--verbose", action="store_true")
    if family is not None:
        family.protocol().add_cli_arguments(parser)
    return parser


def _family_from_argv(argv):
    from flasher.controllers.registry import family_for_module, parse_module
    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--module", type=parse_module)
    selected, _ = bootstrap.parse_known_args(argv)
    if selected.module is None:
        return None
    try:
        return family_for_module(selected.module)
    except ValueError:
        # Let the full parser report an unsupported raw module consistently.
        return None


def _operation(args):
    if args.ident_only:
        return "identify"
    if args.read_eeprom:
        return "eeprom"
    if args.readout:
        return "readout"
    return "flash"


def _progress(stage, percent, detail="", speed=0.0, eta_sec=0.0):
    suffix = f" {speed:.1f} B/s" if speed else ""
    if eta_sec:
        suffix += f" ETA {eta_sec:.1f}s"
    print(f"[{stage:>10}] {percent:6.1f}% {detail}{suffix}", flush=True)


def _configure_logging(args):
    handlers = [logging.StreamHandler(sys.stderr)]
    if args.log:
        handlers.append(logging.FileHandler(args.log, encoding="utf-8"))
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)


def run_ident(args, runtime):
    from flasher.engine import parse_vag_identification
    from flasher.vag_protocols.kwp import KWPClient
    from flasher.vag_protocols.tp2 import TP20Transport
    device = tp = None
    try:
        device = runtime.open_adapter(args)
        protocol_log = logging.getLogger("ModuleIdentify").info
        tp = TP20Transport(device, module=args.module, timeout=2.0,
                           debug=args.verbose, log_fn=protocol_log)
        kwp = KWPClient(tp, debug=args.verbose, log_fn=protocol_log)
        result = parse_vag_identification(
            kwp.read_ecu_ident(0x9B), kwp.read_ecu_ident(0x9C))
        args.family.validate_identification(result)
        result.update(connected=True, module=args.module,
                      controller_family=args.family.name)
    finally:
        if tp is not None:
            tp.disconnect()
        if device is not None:
            device.close()
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main(argv=None):
    from flasher.controllers.registry import family_for_module
    from flasher.engine import ControllerRuntime

    argv = list(sys.argv[1:] if argv is None else argv)
    family = _family_from_argv(argv)
    parser = build_parser(family)
    args = parser.parse_args(argv)
    if sum((args.ident_only, args.readout, args.read_eeprom)) > 1:
        parser.error("--ident-only, --readout and --read-eeprom cannot be combined")
    operation = _operation(args)
    try:
        args.family = family_for_module(args.module, operation=operation)
        if args.recovery and operation != "flash":
            parser.error("--recovery cannot be combined with readout or identification")
        controller = args.family.protocol()
        controller.apply_defaults(args)
        controller.validate_cli(parser, args)
    except ValueError as exc:
        parser.error(str(exc))

    _configure_logging(args)
    runtime = ControllerRuntime(open_adapter=open_adapter, progress=_progress)
    if operation == "identify":
        return run_ident(args, runtime)
    return getattr(controller, f"run_{operation}")(args, runtime)


if __name__ == "__main__":
    raise SystemExit(main())
