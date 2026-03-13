#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DIS top display — pure ZMQ rx+tx via can_handler, fixed-interval write.

Priority: Phone > Media > No Media

Write strategy:
    Heartbeat at HB_INTERVAL (100ms) maintains display ownership.
    Scroll advances write immediately on each tick.
    CANWatcher responds to OEM writes with OEM_RESPONSE_N frames (~2ms).
    OEM cadence ~800ms; 100ms HB covers it 8x with no display flicker.

CAN I/O:
    rx — ZMQ SUB on can_raw_stream (can_handler publishes all received frames)
    tx — ZMQ PUSH to can_handler send_address (dedicated send_worker thread)
    can_handler uses receive_own_messages=False so our tx frames are not echoed.

Config: display.top_display (enabled, media_line[12]_mode, phone_line[12]_mode,
    nav_line[12]_mode, line_start_offset).
    Uses display.text_scrolling for speed/delays/continuity.
    'No Media' text and boot delay are hardcoded.
"""

import json
import logging
import os
import signal
import sys
import threading
import time

import zmq

CONFIG_PATH = "/home/pi/config.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] (DIS) %(message)s"
)
logger = logging.getLogger(__name__)

try:
    from icons import audscii_trans
except Exception:
    sys.exit("ERROR: icons.py not found or failed to import.")

try:
    from unidecode import unidecode as _unidecode
except ImportError:
    _unidecode = None


# --- Timing ---
HB_INTERVAL       = 0.100   # heartbeat — keeps display asserted at 10 Hz

# --- Metadata ---
DEBOUNCE          = 0.18
SKIP_DEBOUNCE     = 0.50
SKIP_WINDOW       = 2.0
NO_MEDIA_DEBOUNCE = 0.50
MEDIA_TIMEOUT     = 8.0

# --- CAN ---
CAN_FAIL_WARN     = 5
OEM_RESPONSE_N    = 3      # immediate writes on OEM detection (no burst gap)
OEM_COOLDOWN      = 0.02   # min seconds between OEM reactive responses per line

CALL_ACTIVE = {"INCOMING", "ALERTING", "ACTIVE"}
CALL_LABELS = {
    "INCOMING": "Incoming",
    "ALERTING": "Calling",
    "ACTIVE":   "Active",
}

PRIO_NONE  = 0
PRIO_MEDIA = 1
PRIO_NAV   = 2
PRIO_PHONE = 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _nice():
    try:
        os.nice(-10)
    except Exception:
        pass


def _hex(val, default):
    if isinstance(val, int):
        return val
    try:
        if val is None:
            return default
        s = str(val).strip()
        return default if not s else int(s, 16)
    except (ValueError, TypeError):
        return default


def _float(val, default):
    try:
        if val is None:
            return default
        s = str(val).strip()
        return default if not s else float(s)
    except (ValueError, TypeError):
        return default


def _int(val, default):
    try:
        if val is None:
            return default
        s = str(val).strip()
        return default if not s else int(s)
    except (ValueError, TypeError):
        return default


def _bool(val, default=False):
    if isinstance(val, bool):
        return val
    if val is None:
        return default
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "on"):
        return True
    if s in ("0", "false", "no", "off"):
        return False
    return default


def _normalize(text: str) -> str:
    if not text or _unidecode is None or all(ord(c) < 256 for c in text):
        return text
    return "".join(c if ord(c) < 256 else _unidecode(c) for c in text)


_TRANS = bytes(audscii_trans)
_BLANK = audscii_trans[ord(" ")]
_CONT_GAP = 0x65


def _encode_text(text: str) -> bytes:
    return bytes(_TRANS[ord(c)] if ord(c) < 256 else _BLANK for c in text)


def _encode_continuous_text(text: str) -> bytes:
    return bytes(
        _CONT_GAP if c == " " else (_TRANS[ord(c)] if ord(c) < 256 else _BLANK)
        for c in text
    )


# ---------------------------------------------------------------------------
# TextScroller
# ---------------------------------------------------------------------------

class TextScroller:
    def __init__(
        self,
        width=8,
        speed_seconds=0.35,
        start_delay=2.0,
        end_delay=2.0,
        stagger=0.0,
        continuous=False,
        continuous_gap=3,
        continuous_loop_delay=False,
    ):
        self.width = width
        self.scroll_speed = float(speed_seconds)
        self.start_delay = max(0.0, float(start_delay))
        self.end_delay = max(0.0, float(end_delay))
        self.stagger_delay = max(0.0, float(stagger))
        self.continuous = bool(continuous)
        self.continuous_gap = max(0, int(continuous_gap))
        self.continuous_loop_delay = bool(continuous_loop_delay)

        self.lock = threading.Lock()
        self._reset("")

    def _reset(self, text: str):
        self.raw_text = text
        self.raw_len = len(text)
        self.pos = 0
        now = time.monotonic()
        self.last_tick = now - self.scroll_speed

        if self.raw_len > self.width:
            self.wait_timer = now + self.start_delay + self.stagger_delay
        else:
            self.wait_timer = now

        self._stream = b""
        self._stream_len = 1
        self._stream_x2 = b""
        if self.continuous:
            gap = bytes([_CONT_GAP] * self.continuous_gap)
            txt = _encode_continuous_text(text)
            self._stream = (txt + gap) if text else gap
            self._stream_len = max(1, len(self._stream))
            self._stream_x2 = self._stream + self._stream[:self.width]

        self._recompute()

    def set_text(self, text: str) -> bool:
        text = (text or "").strip()
        with self.lock:
            if text == self.raw_text:
                return False
            self._reset(text)
            return True

    def clear(self) -> bool:
        with self.lock:
            if not self.raw_text:
                return False
            self._reset("")
            return True

    def restart(self):
        with self.lock:
            if self.raw_len <= self.width:
                return
            self.pos = 0
            now = time.monotonic()
            self.last_tick = now - self.scroll_speed
            self.wait_timer = now + self.start_delay + self.stagger_delay
            self._recompute()

    def snapshot(self) -> bytes:
        with self.lock:
            return self.current_bytes

    def tick(self):
        now = time.monotonic()
        with self.lock:
            if self.raw_len <= self.width:
                return None
            if (now - self.last_tick) <= self.scroll_speed:
                return None
            if now < self.wait_timer:
                return None

            if self.continuous:
                self.pos = (self.pos + 1) % self._stream_len
                self._recompute()
                if self.pos == 0:
                    self.wait_timer = now + self.start_delay
            else:
                max_pos = self.raw_len - self.width
                self.pos = self.pos + 1 if self.pos < max_pos else 0
                self._recompute()
                if self.pos == 0:
                    self.wait_timer = now + self.start_delay
                elif self.pos == max_pos:
                    self.wait_timer = now + self.end_delay

            self.last_tick = now
            return self.current_bytes

    def _recompute(self):
        if self.raw_len <= self.width:
            txt = _encode_text(self.raw_text)
            pad = self.width - self.raw_len
            left = pad // 2
            self.current_bytes = bytes([_BLANK] * left) + txt + bytes([_BLANK] * (pad - left))
        elif self.continuous:
            self.current_bytes = self._stream_x2[self.pos:self.pos + self.width]
        else:
            window = self.raw_text[self.pos:self.pos + self.width]
            txt = _encode_text(window)
            self.current_bytes = txt + bytes([_BLANK] * (self.width - len(txt)))


# ---------------------------------------------------------------------------
# LineController
# ---------------------------------------------------------------------------

class LineController:
    W = 8

    def __init__(self, can_id, zmq_ctx, can_send_addr, name,
                 speed_seconds, start_delay, end_delay, stagger,
                 continuous, continuous_gap, continuous_loop_delay,
                 no_scroll, watcher=None, mock=False):
        self.can_id = can_id
        self._zmq_ctx = zmq_ctx
        self._can_send_addr = can_send_addr
        self.name = name
        self._watcher = watcher
        self.no_scroll = no_scroll
        self.mock = mock
        self.hb_interval = 5.0 if mock else HB_INTERVAL
        
        # Map CAN ID to top line index (1 or 2)
        self.line_num = 1 if can_id == 0x363 else (2 if can_id == 0x365 else 0)

        self.scroller = TextScroller(
            width=self.W,
            speed_seconds=speed_seconds,
            start_delay=start_delay,
            end_delay=end_delay,
            stagger=stagger,
            continuous=continuous,
            continuous_gap=continuous_gap,
            continuous_loop_delay=continuous_loop_delay,
        )

        self._fail_count = 0
        self._next_write = 0.0

    # --- Text control ---

    def set_text(self, text: str) -> bool:
        return self.scroller.set_text(text)

    def clear(self) -> bool:
        return self.scroller.clear()

    def snapshot(self) -> bytes:
        return self.scroller.snapshot()

    def restart(self):
        if not self.no_scroll:
            self.scroller.restart()

    # --- Send ---

    def _send(self, data: bytes) -> bool:
        try:
            if self.mock and self.line_num > 0:
                # Top display mock packets are sent as "draw_top_text" JSON commands
                payload = {
                    "command": "draw_top_text",
                    "line": self.line_num,
                    "data_hex": data.hex(),
                    "centered": True,
                    "fixed_width": True
                }
                logger.info("[%s] Sending mock top text: %s", self.name, data.hex())
                self._push.send_json(payload)
                self._fail_count = 0
                return True
                
            self._push.send_multipart([str(self.can_id).encode(), data.hex().encode()])
            self._fail_count = 0
            return True
        except Exception:
            self._fail_count += 1
            if self._fail_count == CAN_FAIL_WARN:
                logger.warning("[%s] %d consecutive ZMQ send failures", self.name, CAN_FAIL_WARN)
            return False

    # --- Run loop ---

    def run(self):
        self._push = self._zmq_ctx.socket(zmq.PUSH)
        self._push.setsockopt(zmq.LINGER, 0)
        self._push.connect(self._can_send_addr)
        while True:
            now = time.monotonic()
            tv = self._watcher is not None and self._watcher.tv_active

            # Write immediately when scroll content changes
            if tv and not self.no_scroll:
                new_frame = self.scroller.tick()
                if new_frame is not None:
                    self._send(new_frame)
                    self._next_write = now + HB_INTERVAL

            # Heartbeat — maintain display at low rate
            if tv and now >= self._next_write:
                if self.mock:
                    logger.debug("[%s] Heartbeat", self.name)
                self._send(self.snapshot())
                self._next_write = now + self.hb_interval

            time.sleep(0.005)


# ---------------------------------------------------------------------------
# CANWatcher
# ---------------------------------------------------------------------------

class CANWatcher:
    def __init__(self, zmq_ctx, can_sub_addr, can_send_addr,
                 id_source, dis_ctrl, tv_source_byte, mock=False):
        self._zmq_ctx = zmq_ctx
        self._can_sub_addr = can_sub_addr
        self._can_send_addr = can_send_addr
        self._id_src = id_source
        self._lines = {}  # populated by DISController after construction
        self._dis = dis_ctrl
        self.mock = mock
        self.tv_active = True if mock else False
        self._tv_source_byte = tv_source_byte
        self._last_oem: dict = {}
        
        if mock:
            logger.info("Mock Mode: CANWatcher forcing tv_active = True")

    def _isend(self, cid: int, data: bytes):
        try:
            logger.debug("CANWatcher reactive send: 0x%03X -> %s", cid, data.hex())
            self._push.send_multipart([str(cid).encode(), data.hex().encode()])
        except Exception as e:
            logger.debug("CANWatcher isend failed: %s", e)

    def run(self):
        self._sub = self._zmq_ctx.socket(zmq.SUB)
        self._sub.connect(self._can_sub_addr)
        for cid in (self._id_src, *self._lines.keys()):
            self._sub.subscribe(f"CAN_{cid:03X}".encode())

        self._push = self._zmq_ctx.socket(zmq.PUSH)
        self._push.setsockopt(zmq.LINGER, 0)
        self._push.connect(self._can_send_addr)

        poller = zmq.Poller()
        poller.register(self._sub, zmq.POLLIN)

        while True:
            try:
                if not poller.poll(500):
                    continue

                try:
                    while True:
                        parts = self._sub.recv_multipart(flags=zmq.NOBLOCK)
                        if len(parts) != 2:
                            continue

                        topic = parts[0].decode()
                        cid = int(topic[4:], 16)   # "CAN_363" -> 0x363
                        data = bytes.fromhex(json.loads(parts[1])["data_hex"])

                        if cid == self._id_src and len(data) >= 4:
                            was = self.tv_active
                            is_tv = (data[3] == self._tv_source_byte)
                            
                            if self.mock:
                                # In mock mode, we still track it but don't let it disable us
                                self.tv_active = True
                            else:
                                self.tv_active = is_tv

                            if self.tv_active and not was:
                                logger.info("TV source activated")
                                self._dis._no_media_shown = False
                                for ctrl in self._lines.values():
                                    if ctrl:
                                        ctrl.restart()
                                        ctrl._next_write = 0.0  # write immediately

                            elif not self.tv_active and was:
                                logger.info("TV source deactivated")
                                self._dis._no_media_shown = False
                                for ctrl in self._lines.values():
                                    if ctrl:
                                        ctrl.restart()

                        elif self.tv_active and cid in self._lines:
                            ctrl = self._lines[cid]
                            if not ctrl:
                                continue

                            now = time.monotonic()
                            last = self._last_oem.get(cid, 0.0)
                            if (now - last) < OEM_COOLDOWN:
                                continue
                            self._last_oem[cid] = now

                            snap = ctrl.snapshot()
                            logger.debug("[%s] OEM write — responding", ctrl.name)
                            for _ in range(OEM_RESPONSE_N):
                                self._isend(cid, snap)

                            # Reset periodic write timer so it fires immediately after
                            ctrl._next_write = 0.0

                except zmq.Again:
                    pass

            except Exception as e:
                logger.warning("CANWatcher: %s", e)
                time.sleep(0.1)


# ---------------------------------------------------------------------------
# DISController
# ---------------------------------------------------------------------------

class DISController:
    def __init__(self, mock=False):
        _nice()
        self.mock = mock
        logger.info("DISController initializing (mock=%s)", mock)
        cfg = self._load_config()
        self._setup_can(cfg)
        self._setup_lines(cfg)
        self._setup_zmq(cfg)
        self._setup_state(cfg)
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

    def _load_config(self) -> dict:
        config_path = CONFIG_PATH
        if self.mock and not os.path.exists(config_path):
            if os.path.exists("../config.json"):
                config_path = "../config.json"
            elif os.path.exists("config.json"):
                config_path = "config.json"
                
        with open(config_path) as f:
            cfg = json.load(f)
        
        display_cfg = cfg.get("display", {})
        feat = display_cfg.get("top_display", {})
        
        if not feat or not feat.get("enabled", False):
            sys.exit("top_display disabled in config.")
            
        self.running = True
        return cfg

    def _setup_can(self, cfg: dict):
        can_ids = cfg["can_ids"]
        source_cfg = cfg["input_mappings"]["source"]
        zmq_cfg = cfg["interfaces"]["zmq"]

        self._id_l1 = _hex(can_ids["fis_line1"], 0x363)
        self._id_l2 = _hex(can_ids["fis_line2"], 0x365)
        self._id_src = _hex(can_ids["source"], 0x661)
        self._tv_source_byte = _hex(source_cfg["tv_mode_identifier"], 0x37)

        self._zmq_ctx = zmq.Context()
        if self.mock:
            self._can_sub_addr = "tcp://127.0.0.1:5558"
            self._can_send_addr = "tcp://127.0.0.1:5557"
        else:
            self._can_sub_addr = zmq_cfg.get("can_raw_stream", "ipc:///run/rnse_control/can_stream.ipc")
            self._can_send_addr = zmq_cfg.get("send_address", "ipc:///run/rnse_control/can_send.ipc")

    def _setup_lines(self, cfg: dict):
        display_cfg = cfg.get("display", {})
        scroll_cfg = display_cfg.get("text_scrolling", {})
        feat = display_cfg.get("top_display", {})

        def speed_cfg(raw_cps):
            # Fallback to general speed_ms if CPS not provided or 0
            if not raw_cps:
                ms = _float(scroll_cfg.get("speed_ms"), 300)
                cps = 1000.0 / ms if ms > 0 else 3.333
            else:
                cps = max(0.0, min(10.0, _float(raw_cps, 3.333)))
            
            return (0.0, True) if cps == 0 else (round(1.0 / cps, 3), False)

        start_delay_ms = _float(feat.get("start_delay_ms"), _float(scroll_cfg.get("start_delay_ms"), 1000.0))
        end_delay_ms = _float(feat.get("end_delay_ms"), _float(scroll_cfg.get("end_delay_ms"), 250.0))
        start_delay = start_delay_ms / 1000.0
        end_delay = end_delay_ms / 1000.0
        
        # Use millisecond offset from config, fallback to seconds-based name or 1.0s
        ms_stagger = _float(scroll_cfg.get("line_offset_ms"), _float(scroll_cfg.get("line_start_offset"), 1000.0) * 1.0)
        stagger = ms_stagger / 1000.0 if ms_stagger > 10.0 else ms_stagger # Guard: handle if user put seconds in ms field
        
        # Unify continuous settings
        continuous = _bool(feat.get("continuous"), _bool(scroll_cfg.get("continuous"), False))
        continuous_gap = _int(feat.get("continuous_gap"), _int(scroll_cfg.get("continuous_gap"), 1))
        continuous_loop_delay = True # Always use delay for continuous to match dis_display

        l1_mode = str(feat.get("media_line1_mode", "0"))
        l2_mode = str(feat.get("media_line2_mode", "0"))

        l1_speed, l1_noscroll = speed_cfg(feat.get("media_line1_scroll_speed_cps"))
        l2_speed, l2_noscroll = speed_cfg(feat.get("media_line2_scroll_speed_cps"))

        # Create watcher first (controllers filled in after)
        self._watcher = CANWatcher(
            self._zmq_ctx, self._can_sub_addr, self._can_send_addr,
            self._id_src, self, self._tv_source_byte,
            mock=self.mock,
        )

        def make_ctrl(can_id, name, speed, line_stagger, mode, no_scroll):
            if mode == "0":
                return None
            return LineController(
                can_id=can_id,
                zmq_ctx=self._zmq_ctx,
                can_send_addr=self._can_send_addr,
                name=name,
                speed_seconds=speed,
                start_delay=start_delay,
                end_delay=end_delay,
                stagger=line_stagger,
                continuous=continuous,
                continuous_gap=continuous_gap,
                continuous_loop_delay=continuous_loop_delay,
                no_scroll=no_scroll,
                watcher=self._watcher,
                mock=self.mock,
            )

        self._ctrl_l1 = make_ctrl(self._id_l1, "L1", l1_speed, 0.0, l1_mode, l1_noscroll)
        self._ctrl_l2 = make_ctrl(self._id_l2, "L2", l2_speed, stagger, l2_mode, l2_noscroll)
        self._ctrls = [c for c in (self._ctrl_l1, self._ctrl_l2) if c]

        self._watcher._lines = {self._id_l1: self._ctrl_l1, self._id_l2: self._ctrl_l2}

        self._l1_mode = l1_mode
        self._l2_mode = l2_mode
        self._ph_l1_mode = str(feat.get("phone_line1_mode", "caller"))
        self._ph_l2_mode = str(feat.get("phone_line2_mode", "state"))
        self._nav_l1_mode = str(feat.get("nav_line1_mode", "description"))
        self._nav_l2_mode = str(feat.get("nav_line2_mode", "distance"))
        self._no_media = ("No Media", "")

    def _setup_zmq(self, cfg: dict):
        if self.mock:
            self._zmq_addr = "tcp://127.0.0.1:5559"
            self._display_status_addr = "tcp://127.0.0.1:5561"
        else:
            self._zmq_addr = cfg["interfaces"]["zmq"]["metric_stream"]
            self._display_status_addr = cfg["interfaces"]["zmq"].get("dis_display_status", "ipc:///run/rnse_control/dis_display_status.ipc")
        # socket created inside _listener thread for ZMQ thread-safety

    def _setup_state(self, cfg: dict):
        self._boot_delay = 3.0
        self._boot_time = time.monotonic()
        self._prio = PRIO_NONE
        self._media_texts = ("", "")
        self._call_active = False
        self._phone_texts = ("", "")
        self._last_media_msg = 0.0
        self._not_playing_t = 0.0
        self._no_media_grace = 0.0
        self._no_media_shown = False
        self._nav_active = False
        self._nav_texts = ("", "")
        
        # Center Display Awareness
        self._center_app = None
        self._center_ready = False

        for c, t in zip(self._ctrls, self._no_media):
            if t:
                c.set_text(t)

    def _make_sub(self, addr):
        sub = self._zmq_ctx.socket(zmq.SUB)
        sub.connect(addr)
        if hasattr(self, '_display_status_addr') and self._display_status_addr != addr:
            sub.connect(self._display_status_addr)
            
        for t in (b"HUDIY_MEDIA", b"HUDIY_PHONE", b"HUDIY_NAV", b"HUDIY_NAV_STATUS", b"DIS_DISPLAY_STATUS"):
            sub.setsockopt(zmq.SUBSCRIBE, t)
        return sub

    def _reconnect_zmq(self):
        logger.warning("ZMQ reconnecting")
        try:
            self._sub.close()
        except Exception:
            pass
        time.sleep(1.0)
        self._sub = self._make_sub(self._zmq_addr)

    def _shutdown(self, *_):
        self.running = False

    @staticmethod
    def _parse_mode(mode_str: str, fields: dict) -> str:
        if not mode_str or str(mode_str) == "0":
            return ""

        def clean(v):
            return str(v).strip() if v is not None else ""

        keys = [k.strip().lower() for k in mode_str.split("-")]
        parts = [v for v in (clean(fields.get(k, "")) for k in keys) if v]
        return " - ".join(parts) if len(parts) >= 2 else (parts[0] if parts else "")

    def _media_fields(self, d):
        f = {
            "title":  d.get("title") or "",
            "artist": d.get("artist", ""),
            "album":  d.get("album", ""),
            "source": d.get("source_label") or d.get("source", ""),
        }
        logger.info("Extracted Media Fields: %s", f)
        l1 = self._parse_mode(self._l1_mode, f) if self._ctrl_l1 else ""
        l2 = self._parse_mode(self._l2_mode, f) if self._ctrl_l2 else ""
        logger.info("Formatted Media Lines: L1='%s', L2='%s'", l1, l2)
        return l1, l2

    def _phone_fields(self, d):
        conn = d.get("connection_state", "")
        f = {
            "caller":     d.get("caller_name") or d.get("caller_id") or "Call",
            "state":      CALL_LABELS.get(d.get("state", ""), d.get("state", "")),
            "name":       d.get("name", ""),
            "connection": "Connected" if conn == "CONNECTED" else "Disconnected" if conn == "DISCONNECTED" else conn,
            "battery":    str(d.get("battery", "")),
            "signal":     str(d.get("signal", "")),
        }
        l1 = self._parse_mode(self._ph_l1_mode, f) if self._ctrl_l1 else ""
        l2 = self._parse_mode(self._ph_l2_mode, f) if self._ctrl_l2 else ""
        return l1, l2

    def _nav_fields(self, d):
        f = {
            "description": d.get("description", ""),
            "maneuver":    d.get("maneuver_text", ""),
            "distance":    d.get("distance", ""),
        }
        l1 = self._parse_mode(self._nav_l1_mode, f) if self._ctrl_l1 else ""
        l2 = self._parse_mode(self._nav_l2_mode, f) if self._ctrl_l2 else ""
        return l1, l2

    def _push(self, l1: str, l2: str):
        l1 = _normalize(l1)
        l2 = _normalize(l2)
        for ctrl, text in ((self._ctrl_l1, l1), (self._ctrl_l2, l2)):
            if not ctrl:
                continue
            changed = ctrl.set_text(text) if text else ctrl.clear()
            if changed and self._watcher.tv_active:
                ctrl._next_write = 0.0  # write new content immediately

    def _resolve(self):
        can_skip = (self._center_ready and self._center_app)
        logger.info("Resolving Priority: call=%s, nav=%s, media_msg=%s, center=%s (%s)", 
                    self._call_active, self._nav_active, self._last_media_msg > 0, self._center_app, self._center_ready)
        
        # Priority Order: Phone -> Nav -> Media -> None
        
        # 1. Phone
        if self._call_active:
            if not (can_skip and self._center_app == "app_phone"):
                if self._prio != PRIO_PHONE:
                    logger.info("Priority: PHONE")
                self._prio = PRIO_PHONE
                self._push(*self._phone_texts)
                return
            else:
                logger.info("Skipping PHONE (already on center display)")
                
        # 2. Nav
        if self._nav_active:
            if not (can_skip and self._center_app == "app_nav"):
                if self._prio != PRIO_NAV:
                    logger.info("Priority: NAV")
                self._prio = PRIO_NAV
                self._push(*self._nav_texts)
                return
            else:
                logger.info("Skipping NAV (already on center display)")
                
        # 3. Media
        now = time.monotonic()
        connected = (
            self._last_media_msg > 0 and
            (now - self._last_media_msg) < MEDIA_TIMEOUT
        )
        if connected:
            if not (can_skip and self._center_app == "app_media_player"):
                if self._prio != PRIO_MEDIA:
                    logger.info("Priority: MEDIA")
                self._prio = PRIO_MEDIA
                self._push(*self._media_texts)
                return
            else:
                logger.info("Skipping MEDIA (already on center display)")
                
        # 4. Fallback
        if self._prio != PRIO_NONE:
            logger.info("Priority: NONE")
        self._prio = PRIO_NONE
        if self._center_ready:
            # Center is active, but showing something else or we've skipped everything.
            # Show blank line as requested.
            self._push("", "")
        else:
            self._push(*self._no_media)
        
        self._no_media_shown = True

    def _listener(self):
        self._sub = self._make_sub(self._zmq_addr)
        pending = None
        deadline = None
        err_count = 0

        while self.running:
            now = time.monotonic()

            if pending is not None and now >= deadline:
                self._media_texts = pending
                self._resolve()
                pending = None
                deadline = None

            connected = (
                self._last_media_msg > 0 and
                (now - self._last_media_msg) < MEDIA_TIMEOUT
            )

            if (
                not self._call_active
                and not self._no_media_shown
                and not connected
                and self._prio < PRIO_MEDIA
                and (now - self._boot_time) >= self._boot_delay
                and now >= self._no_media_grace
            ):
                self._push(*self._no_media)
                self._no_media_shown = True

            try:
                parts = self._sub.recv_multipart(flags=zmq.NOBLOCK)
                topic, data = parts[0], json.loads(parts[1])
                err_count = 0
                
                logger.info("RX Topic: %s", topic.decode())
                if topic == b"HUDIY_MEDIA":
                    src = data.get("source_id", 0)
                    playing = data.get("playing", False)
                    title = (data.get("title") or "").strip()
                    logger.info("Media Msg: src=%s, playing=%s, title='%s'", src, playing, title)

                    # Allow src 0 in mock mode, otherwise ignore it
                    if (src != 0 or self.mock) and (playing or title):
                        self._last_media_msg = now
                        self._no_media_shown = False
                        self._no_media_grace = 0.0
                        new = self._media_fields(data)
                        if new != pending:
                            pending = new
                            recently_skipped = (
                                self._not_playing_t > 0
                                and (now - self._not_playing_t) < SKIP_WINDOW
                            )
                            deadline = now + (SKIP_DEBOUNCE if recently_skipped else DEBOUNCE)
                    else:
                        if src == 0 and not self.mock:
                            logger.debug("Ignoring media msg with src 0 (non-mock)")
                        pending = None
                        deadline = None
                        self._not_playing_t = now
                        self._last_media_msg = 0.0
                        self._no_media_shown = False
                        self._no_media_grace = now + NO_MEDIA_DEBOUNCE
                        self._resolve()

                elif topic == b"HUDIY_PHONE":
                    state = data.get("state", "IDLE")
                    was = self._call_active
                    self._call_active = state in CALL_ACTIVE

                    if self._call_active:
                        if not was:
                            logger.info("Call started (%s)", state)
                        self._phone_texts = self._phone_fields(data)
                        self._resolve()
                    elif was:
                        logger.info("Call ended — restoring display")
                        self._resolve()

                elif topic == b"HUDIY_NAV_STATUS":
                    self._nav_active = data.get("active", False)
                    self._resolve()

                elif topic == b"HUDIY_NAV":
                    self._nav_texts = self._nav_fields(data)
                    self._resolve()

                elif topic == b"DIS_DISPLAY_STATUS":
                    self._center_app = data.get("app")
                    self._center_ready = (data.get("state") == "READY")
                    self._resolve()

            except zmq.Again:
                err_count = 0
                sleep_for = max(0.0, min(0.05, deadline - now)) if deadline else 0.05
                time.sleep(sleep_for)
            except Exception as e:
                logger.warning("ZMQ: %s", e)
                err_count += 1
                if err_count >= 3:
                    self._reconnect_zmq()
                    err_count = 0
                else:
                    time.sleep(0.05)

    def run(self):
        threading.Thread(target=self._listener, daemon=True, name="meta").start()
        threading.Thread(target=self._watcher.run, daemon=True, name="rx").start()
        for c in self._ctrls:
            threading.Thread(target=c.run, daemon=True, name=f"tx-{c.name}").start()

        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.running = False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--mock', action='store_true', help='Connect to Emulator ports')
    args = parser.parse_args()
    
    DISController(mock=args.mock).run()
