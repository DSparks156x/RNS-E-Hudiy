"""Synthetic peer through the actual framed receiver; no CAN/socket construction."""
import importlib.util
import sys
import types
from collections import deque
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def deny(*args, **kwargs):
    raise AssertionError('Hardware/socket construction is prohibited in this harness')


can = types.ModuleType('can')
can.Bus = deny
can.Message = lambda **kwargs: types.SimpleNamespace(**kwargs)
can.CanError = type('CanError', (Exception,), {})
sys.modules.setdefault('can', can)
sys.path.insert(0, str(REPO))
from flasher.vag_protocols import tp2 as tp
sys.path.insert(0, str(REPO / 'dis_client'))
# Dependencies follow normal import caching; do not replace shared class types.
protocol = load('white_opening_protocol_under_test', REPO / 'dis_client/ddp_protocol.py')
protocol.logger.disabled = True


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    perf_counter = monotonic
    time = monotonic

    def sleep(self, seconds):
        self.now += seconds


BENCH = [9, 32, 11, 80, 8, 11, 80]
TABLE_ALT = [9, 32, 11, 80, 9, 36, 74]
GEOMETRY = [48, 57, 0, 50, 0]


def opening(module, shape, prefetch, prefix=TABLE_ALT, late=None, start_seq=0,
            setup_reply=True, geometry=GEOMETRY, compound_extra=()):
    d = module.DDPProtocol.__new__(module.DDPProtocol)
    d.config = d.cfg = {}
    d.transport_profile = module.DDPTransportProfile(frame_gap_s=0, white_post_message_delay_s=0)
    d.state, d.dis_mode = module.DDPState.SESSION_ACTIVE, module.DisMode.WHITE
    d.state_generation = d.presentation_request_generation = d.send_seq_num = 0
    d.i_am_opener = d.screen_released_by_cluster = False
    d.last_ka_sent = 0
    d._last_received_ack = d._last_received_data = d._last_screen_status = None
    d._data_inbox, d.bus = deque(), None
    d.tx_id, d.rx_id = 0x6C0, 0x6C1
    d._reset_receive_transport()
    d._reset_application_session()
    d._receive_seq_num = start_seq
    d._flashing_inhibited = lambda: False
    clock = Clock()
    module.time = clock
    incoming, sent, received, commands = deque(), [], [], []
    partial = bytearray()
    peer_seq = start_seq
    config_count = setup_count = query_count = 0

    def recv(timeout=.01):
        if incoming:
            return incoming.popleft()
        clock.sleep(max(timeout, .001))
        return None

    def respond(payload):
        nonlocal peer_seq
        frames, _ = tp.segment_message(bytes(payload), peer_seq, block_size=6, length_prefixed=False)
        peer_seq = (peer_seq + len(frames)) & 15
        received.extend(list(frame) for frame in frames)
        incoming.extend(list(frame) for frame in frames)

    def send(cid, data):
        nonlocal config_count, setup_count, query_count
        data = list(data)
        sent.append(data)
        if data == d.KA_KEEP_PING:
            if late is not None:
                respond(late)
            incoming.append(list(d.KA_WHITE_ACCEPT))
            return
        op, seq = tp.classify_frame(data)
        if op not in (0, 1, 2, 3):
            return
        if not prefetch and op in (0, 1):
            incoming.append([0xB0 | ((seq + 1) & 15)])
        partial.extend(data[1:])
        if op in (1, 3):
            payload = list(partial)
            partial.clear()
            commands.append(payload)
            if payload[0] == 0x15:
                respond([0, 1])
            elif payload == [1, 1, 0]:
                config_count += 1
                if shape == 'long' and config_count == 2:
                    respond(geometry)
            elif payload == [8]:
                query_count += 1
                if query_count == 1 and shape == 'compound':
                    respond(prefix + geometry + list(compound_extra))
                else:
                    respond(prefix)
                    if query_count == 1 and shape == 'separate_prefetched':
                        respond(geometry)
            elif payload[0] == 0x20:
                setup_count += 1
                if shape != 'compound' and setup_count == 1:
                    respond(geometry)
                if setup_reply:
                    respond([0x21, 0x3B, payload[2], 0])
        if prefetch and op in (0, 1):
            incoming.append([0xB0 | ((seq + 1) & 15)])

    d._recv, d.send_can = recv, send
    result = d.perform_initialization()
    return dict(shape=shape, prefix=prefix, prefetch=prefetch, result=result,
                state=d.state.name, commands=commands, tx=sent, rx=received,
                geometry=d.geometry_record,
                exchanges=list(getattr(d, 'application_exchange_history', ())))


