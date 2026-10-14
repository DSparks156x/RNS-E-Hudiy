#!/usr/bin/env python3
"""Interrogate every KWP service a module answers, old-style and new-style.

Read-only. For each target module and each diagnostic session, it tries a
matrix of identification, DTC, measuring-block, coding and security-seed
requests and records, per request, whether the module answered positively, with
which bytes, or with which negative-response code (NRC). The goal is to
establish, across the whole car, which modules speak the legacy KWP service set
(1A ReadECUIdentification, 13 ClearDTC) and which speak the newer set (22
ReadDataByIdentifier, 14 Clear, 18 02 ReadDTCByStatus) -- so the TP2 worker can
pick the right requests per module instead of assuming one dialect.

Nothing here writes, flashes, resets or unlocks anything:
  * it never sends 2E/34/35/36/37 (write/download), 11 (ECUReset),
    14 (clear DTCs), 31 (RoutineControl, may actuate), or a 27 key;
  * 27 seed requests (03/01) only READ a seed; no key is ever computed or sent,
    so the module's attempt counter/lockout is never touched;
  * session 0x85 (programming pre-state, which on some modules arms a delayed
    reset) is refused unless --allow-programming-session is passed explicitly.

    python3 tp2/module_probe.py 20 09 0A 01 ...
    python3 tp2/module_probe.py --all-found          # sweep, then probe responders
    python3 tp2/module_probe.py 20 --subsystems      # also LIN/K-line sub-bus DIDs
"""
import argparse
import json
import os
import sys
import time

from tp2_protocol import TP2Protocol, TP2Error
from module_survey import ServicePause, load_config, TESTER_ID, sweep

# Sessions to open before the request matrix. None = no explicit session (the
# channel's power-on default). 0x89 is the generic diagnostic session almost
# every VAG module accepts; 0x86 is the elevated/engineering session (usually
# gated on security, so it typically returns an NRC here -- which is itself
# informative). 0x85 is deliberately excluded by default (see module docstring).
DEFAULT_SESSIONS = [None, 0x89, 0x86]
PROGRAMMING_SESSION = 0x85

# ---- Request matrix -------------------------------------------------------
# Each entry: (label, request-bytes, category). Everything here is read-only.
OLD_STYLE = [
    ("ident 1A 9B  (part/sw/coding/text)", [0x1A, 0x9B], "ident"),
    ("ident 1A 91  (hw/part)",             [0x1A, 0x91], "ident"),
    ("ident 1A 80",                        [0x1A, 0x80], "ident"),
    ("ident 1A 86",                        [0x1A, 0x86], "ident"),
    ("ident 1A 9A",                        [0x1A, 0x9A], "ident"),
    ("install 1A 9F (gateway only)",       [0x1A, 0x9F], "ident"),
    ("DTC 13      (legacy clear-read)",    [0x13],       "dtc"),
    ("meas 21 01  (local id grp 1)",       [0x21, 0x01], "meas"),
    ("meas 21 02",                         [0x21, 0x02], "meas"),
    ("meas 21 03",                         [0x21, 0x03], "meas"),
]
NEW_STYLE = [
    ("ident 22 F187 (part number)",        [0x22, 0xF1, 0x87], "ident"),
    ("ident 22 F189 (sw version)",         [0x22, 0xF1, 0x89], "ident"),
    ("ident 22 F18A (supplier)",           [0x22, 0xF1, 0x8A], "ident"),
    ("ident 22 F191 (hw part)",            [0x22, 0xF1, 0x91], "ident"),
    ("ident 22 F197 (system name)",        [0x22, 0xF1, 0x97], "ident"),
    ("ident 22 F19E (asam)",               [0x22, 0xF1, 0x9E], "ident"),
    ("coding 22 0600",                     [0x22, 0x06, 0x00], "ident"),
    ("DTC 18 02 FF 00 (by status)",        [0x18, 0x02, 0xFF, 0x00], "dtc"),
    ("DTC 18 00 FF 00 (by status, sub00)", [0x18, 0x00, 0xFF, 0x00], "dtc"),
]
# Always safe, both dialects.
COMMON = [
    ("tester present 3E",                  [0x3E],       "common"),
    ("security seed 27 01",                [0x27, 0x01], "seed"),
    ("security seed 27 03",                [0x27, 0x03], "seed"),
]

# LIN/K-line sub-bus masters (such as the PQ BCM) expose their sub-controllers
# through outer service-22 identifiers. Reading these is how VCDS shows a
# sub-controller's coding and part number. Two channels are known on the PQ BCM:
# channel 0 (NAD 1/2) and channel 1 (NAD 5/6/7). All reads, no writes.
SUBSYSTEM_DIDS = [
    ("sub coding  22 0610 (ch0 NAD1)",     [0x22, 0x06, 0x10], "subsys"),
    ("sub coding  22 0611 (ch0 NAD2)",     [0x22, 0x06, 0x11], "subsys"),
    ("sub part    22 0640 (ch0 NAD1)",     [0x22, 0x06, 0x40], "subsys"),
    ("sub part    22 0641 (ch0 NAD2)",     [0x22, 0x06, 0x41], "subsys"),
    ("sub ver     22 0670 (ch0 NAD1)",     [0x22, 0x06, 0x70], "subsys"),
    ("sub ver     22 0671 (ch0 NAD2)",     [0x22, 0x06, 0x71], "subsys"),
    ("sub part    22 064F (ch1 NAD5)",     [0x22, 0x06, 0x4F], "subsys"),
    ("sub part    22 0655 (ch1 NAD6)",     [0x22, 0x06, 0x55], "subsys"),
    ("sub part    22 0651 (ch1 NAD7)",     [0x22, 0x06, 0x51], "subsys"),
]

NRC_NAMES = {
    0x10: "generalReject", 0x11: "serviceNotSupported",
    0x12: "subFunctionNotSupported/invalidFormat", 0x21: "busy-repeatRequest",
    0x22: "conditionsNotCorrect", 0x23: "routineNotComplete",
    0x31: "requestOutOfRange", 0x33: "securityAccessDenied",
    0x35: "invalidKey", 0x36: "exceedAttempts", 0x37: "timeDelayNotExpired",
    0x78: "responsePending(timeout)", 0x80: "notSupportedInSession",
}

# Requests we will never emit regardless of flags: writes/resets/actuation.
FORBIDDEN_FIRST_BYTES = {0x2E, 0x34, 0x35, 0x36, 0x37, 0x11, 0x14, 0x31}


def ascii_of(data):
    return "".join(chr(b) if 32 <= b <= 126 else "." for b in data).strip(". ")


def classify(resp):
    """Turn a raw response list into a compact result dict."""
    if not resp:
        return {"result": "none"}
    if resp[0] == 0x7F:
        nrc = resp[2] if len(resp) > 2 else None
        return {"result": "nrc", "nrc": f"{nrc:02X}" if nrc is not None else "??",
                "nrc_name": NRC_NAMES.get(nrc, "")}
    body = bytes(resp)
    out = {"result": "ok", "sid": f"{resp[0]:02X}", "hex": body.hex(" ")}
    text = ascii_of(body[1:] if len(body) > 1 else b"")
    if text:
        out["ascii"] = text
    return out


def build_matrix(style, with_subsystems):
    matrix = []
    if style in ("old", "all", "min"):
        matrix += OLD_STYLE if style != "min" else OLD_STYLE[:1]
    if style in ("new", "all", "min"):
        matrix += NEW_STYLE if style != "min" else NEW_STYLE[:3]
    matrix += COMMON
    if with_subsystems:
        matrix += SUBSYSTEM_DIDS
    # Safety: strip anything that would mutate the module.
    return [(label, req, cat) for (label, req, cat) in matrix
            if req[0] not in FORBIDDEN_FIRST_BYTES
            and not (req[0] == 0x27 and len(req) > 2)]  # seed only, never a key


def probe_session(proto, mod, session, matrix, verbose):
    """Open one session and run the whole matrix. Returns a dict of rows."""
    rows = {}
    if session is not None:
        try:
            resp = proto.send_kwp_request([0x10, session])
            rows[f"start 10 {session:02X}"] = classify(resp)
            if resp and resp[0] == 0x7F:
                rows[f"start 10 {session:02X}"]["note"] = "session refused; matrix run in current session"
        except TP2Error as e:
            rows[f"start 10 {session:02X}"] = {"result": "error", "error": str(e)}
            if not proto.connected:
                return rows
    for label, req, _cat in matrix:
        if not proto.connected:
            rows[label] = {"result": "channel_closed"}
            continue
        try:
            rows[label] = classify(proto.send_kwp_request(req))
        except TP2Error as e:
            rows[label] = {"result": "error", "error": str(e)}
        if verbose:
            print(f"      {label:<36} {rows[label]}")
    return rows


def summarize(module_result):
    """One-line dialect verdict per module from its collected rows."""
    flat = {}
    for sess in module_result.values():
        if isinstance(sess, dict):
            flat.update(sess)

    def ok(label_substr):
        return any(lbl.startswith(label_substr) and r.get("result") == "ok"
                   for lbl, r in flat.items())

    verdict = []
    if ok("ident 1A 9B") or ok("ident 1A 91"):
        verdict.append("old-ident(1A)")
    if ok("ident 22 F187") or ok("ident 22 F189"):
        verdict.append("new-ident(22)")
    if ok("DTC 18 02"):
        verdict.append("dtc(18-02)")
    if ok("DTC 18 00"):
        verdict.append("dtc(18-00)")
    if ok("DTC 13"):
        verdict.append("dtc(13)")
    if ok("meas 21"):
        verdict.append("meas(21)")
    if ok("sub coding 22 0610") or ok("sub part 22 0640") or ok("sub part 22 064F"):
        verdict.append("lin-subbus(22)")
    return " ".join(verdict) if verdict else "no positive reads"


def probe_module(proto, mod, sessions, matrix, verbose):
    result = {}
    for session in sessions:
        label = f"session {session:02X}" if session is not None else "no session"
        if not proto.connect(mod):
            result[label] = {"__connect__": {"result": "connect_failed"}}
            continue
        try:
            result[label] = probe_session(proto, mod, session, matrix, verbose)
        finally:
            proto.disconnect()
            time.sleep(0.2)
    return result


def _parse_id(token):
    """Accept raw hex (20, 0x20) or, if the flasher registry is importable, aliases."""
    token = str(token).strip()
    try:
        return int(token, 16)
    except ValueError:
        pass
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(__file__)))), "HaldexRE"))
        from flasher.controllers.registry import parse_module  # type: ignore
        return parse_module(token)
    except Exception as exc:
        raise SystemExit(f"Unknown module id/alias {token!r}: {exc}")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ids", nargs="*", help="TP2 IDs/aliases in hex, e.g. 20 09 0A 01")
    ap.add_argument("--all-found", action="store_true",
                    help="sweep 01..7F first and probe every responder")
    ap.add_argument("--style", choices=("old", "new", "all", "min"), default="all",
                    help="which request matrix to run (default: all)")
    ap.add_argument("--subsystems", action="store_true",
                    help="also read LIN/K-line sub-bus DIDs (22 06xx); for sub-bus masters like the BCM")
    ap.add_argument("--sessions", help="comma hex session list, e.g. 89,86 (default 'none',89,86)")
    ap.add_argument("--allow-programming-session", action="store_true",
                    help="permit session 0x85 (DANGEROUS: may arm a delayed reset)")
    ap.add_argument("--no-pause", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                  "module_probe.json"))
    args = ap.parse_args()

    if args.sessions:
        sessions = []
        for tok in args.sessions.split(","):
            tok = tok.strip().lower()
            sessions.append(None if tok in ("none", "") else int(tok, 16))
    else:
        sessions = list(DEFAULT_SESSIONS)
    if PROGRAMMING_SESSION in sessions and not args.allow_programming_session:
        sys.exit("Refusing session 0x85 without --allow-programming-session")

    matrix = build_matrix(args.style, args.subsystems)

    cfg = load_config()
    channel = cfg.get("interfaces", {}).get("can", {}).get("diagnostic", "can0")
    pause = None if args.no_pause else ServicePause(cfg)
    proto = TP2Protocol(channel=channel, tester_id=TESTER_ID)
    result = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "channel": channel,
              "style": args.style,
              "sessions": [None if s is None else f"{s:02X}" for s in sessions],
              "modules": {}}
    try:
        if pause:
            pause.__enter__()
        proto.open()

        if args.all_found:
            print(f"[ ] Sweeping 01..7F on {channel} ...")
            found = sweep(proto, list(range(0x01, 0x80)), 0.25, "Sweep")
            ids = [m for m, v in sorted(found.items()) if v.get("status") == "D0"]
            print(f"[+] probing {len(ids)} responders: " + " ".join(f"{m:02X}" for m in ids))
        else:
            ids = [_parse_id(x) for x in args.ids]
        if not ids:
            sys.exit("No module IDs given (use positional IDs or --all-found)")

        for n, mod in enumerate(ids, 1):
            print(f"\n[{n}/{len(ids)}] module 0x{mod:02X}")
            rows = probe_module(proto, mod, sessions, matrix, args.verbose)
            result["modules"][f"{mod:02X}"] = rows
            print(f"    => {summarize(rows)}")
    finally:
        proto.close()
        if pause:
            pause.__exit__()

    with open(args.out, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\n{'ID':<5} verdict")
    print("-" * 70)
    for key, rows in result["modules"].items():
        print(f"{key:<5} {summarize(rows)}")
    print(f"\nSaved {args.out}")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, TP2Error) as e:
        print(f"[-] {e}")
        sys.exit(1)
