#!/usr/bin/env python3
"""
Haldex Gen4 Firmware Patcher & Anti-Brick Safeguard Engine.

Performs:
1. Comprehensive application checksum calculation (Blocks 4, 5, 6, 7).
2. Anti-Brick Safety Hook at 0x020364 (redirects panic/assert to 0x02027C).
3. Anti-Brick Reset Routine at 0x02027C (sets RAM[0x00F9FC]=0x001119AB and fires SRST).
4. Scenario C Trap Table Hardening: Converts all 120 dummy self-loop traps at
   0x020002..0x020200 to jmps 0x02027C so hardware traps (illegal opcodes,
   stack underflow/overflow, bus errors) boot immediately into permanent CAN mode.
5. Routine 0xC5 Additive Flash Checksum calculation for bootloader transfer.
"""
import argparse
import hashlib
import struct
import sys
import os
from dataclasses import dataclass
from pathlib import Path

CPU_RAM_FLAG_ADDR = 0x00F9FC
BOOTLOADER_STAY_FLAG = 0x001119AB

# Hook: calla cc_UC, 0x02027C [da 02 7c 02]; rets [db 00]
HOOK_BYTES = bytes.fromhex("da027c02db00")

# Anti-Brick Routine:
# mov r12, #0x19AB       [e6 fc ab 19]
# mov r13, #0x0011       [e6 fd 11 00]
# mov r14, #0xF9FC       [e6 fe fc f9]
# mov [r14+2], r13       [c4 de 02 00]  -> RAM[0x00F9FE] = 0x0011
# mov [r14], r12         [b8 ce]        -> RAM[0x00F9FC] = 0x19AB
# srst                   [b7 48 b7 b7]  -> Trigger hardware CPU reset!
# jmpr cc_UC, -2         [0d fe]        -> (safety trap if srst returns)
ROUTINE_BYTES = bytes.fromhex("e6fcab19e6fd1100e6fefcf9c4de0200b8ceb748b7b70dfe")

# JMPS 0x02, 0x027C: [fa 02 7c 02]
TRAP_ESCAPE_OPCODE = bytes.fromhex("fa027c02")


# Layer-1 checksummed application blocks, from the descriptor table at Controller
# 0x024000. Mask 0xF0 -> blocks 4..7. (start, size) in Controller read-space addresses.
APP_BLOCKS = [
    (0x018000, 0x08000),   # B0F4  core OS, drivers, diag dispatcher
    (0x020000, 0x10000),   # B0F5  vectors, crt0, anti-brick net, valve duty map
    (0x030000, 0x10000),   # B0F6  *** the 65 tuning tables + 37 vehicle constants ***
    (0x040000, 0x10000),   # B0F7  CAN I/O, DTC memory
]


IMAGE_SIZE = 0x50000


def validate_image(data):
    if len(data) != IMAGE_SIZE:
        raise ValueError(f"Expected exactly 320 KiB ({IMAGE_SIZE} bytes), got {len(data)} bytes")


def selected_blocks(start=0x18000, end=0x4ffff):
    """Require inclusive boundaries of contiguous complete application sectors."""
    if start not in {a for a, _ in APP_BLOCKS} or end not in {a+n-1 for a, n in APP_BLOCKS} or end < start:
        raise ValueError("Select whole application sectors: 0x18000..0x1ffff, "
                         "0x20000..0x2ffff, 0x30000..0x3ffff, 0x40000..0x4ffff")
    return [(a, n) for a, n in APP_BLOCKS if start <= a and a+n-1 <= end]


def calculate_app_checksum(data_slice: bytes) -> int:
    """
    Computes ST10 application checksum (~sum(16-bit little endian words) & 0xFFFF)
    across a memory slice excluding the last 2 bytes.
    """
    words = struct.unpack(f"<{len(data_slice[:-2])//2}H", data_slice[:-2])
    return (~sum(words)) & 0xFFFF


def calculate_c5_sum(data_slice: bytes) -> int:
    """Computes Routine 0xC5 additive 16-bit byte sum."""
    return sum(data_slice) & 0xFFFF


# CONSUMER AUDIT 2026-09-05 (live Ghidra). Each patch was classified as either
# FUNCTIONAL (it changes what the controller does) or REPORTING-ONLY (it only
# changes what the Controller says about itself on CAN). Reporting-only patches are
# WORSE THAN USELESS on a diagnostic bench: they make the 0x2C0 flags lie while
# the underlying behaviour is unchanged, which has already cost this project one
# wrong conclusion ("Controller healthy" read off patched flags while it sat at 0 Nm).
#
#   FUN_03114C @0x03114C is the 0x2C0 Allrad_1 FRAME BUILDER (callers:
#   CtrlOutputAllradFrameThread / CtrlOutputIdleThread / CtrlOutputThread). Its
#   body is FUN_02CD22(bit, value) calls -- pure TX signal packing. Anything
#   whose ONLY consumer is FUN_03114C is reporting-only by definition.
#
# REMOVED as reporting-only:
#   * Notlauf bypass (Controller 0x032880, FUN_032880). Sole caller FUN_03114C, and
#     the return goes straight into FUN_02CD22(0x34, ...) -- one TX bit, no
#     control path. Removing it makes the bench tell the truth about limp state.
#     (A second reporting-only patch, Fehler_Allrad_Kupplung @0x021168, was
#     already removed by the user before this audit.)
#
# KEPT as functional (verified each has a non-FUN_03114C consumer):
#   2 StrategicControlThread  - pins DAT_00E57E to State 1; suppresses a real
#                               state machine. The heaviest patch here.
#   3 StartUpThread           - boots into State 1 instead of State 3.
#   4 FUN_03BD68              - stops CtrlHLSCThread forcing ValveOff.
#   5 FUN_03DE7E              - stops ValveOff gating ValveSetDemand.
#   6 FUN_03FF5E              - returns DAT_0F1B9C; consumed by FUN_03FF7C,
#                               which selects CtrlRefGenThread STATE 6 when it
#                               reads 3. Functional: it suppresses the fault
#                               branch. (Also read by FUN_032880, but that is
#                               the reporting path.)
#   7 FUN_030E68              - returns DAT_0F13CA; sole caller CtrlHLSCThread,
#                               a control thread, so functional.
SIMULATOR_PATCHES = [
    # 2. Force State 1 Normal Operation in StrategicControlThread (Controller 0x01B942)
    # Replaces the entry of StrategicControlThread with:
    #   mov r13, #1           (e0 1d)
    #   mov 0xe57e, r13       (f6 fd 7e e5) -> DAT_00e57e = 1 (State 1 Normal Operation)
    #   movb rl2, #1          (e1 12)
    #   movb DAT_00e572, rl2  (f7 f2 72 e5) -> DAT_00e572 = 1 (Thread success flag)
    #   rets                  (db 00)
    # This prevents ANY state machine transition out of State 1 (to State 2, 3, 4, 5, 0).
    # The Controller is permanently locked into State 1 (Normal Operation).
    # The 0x2C0 Allrad_1 status message is NOT patched; it truthfully reads DAT_00e57e == 1 (No Fault).
    (0x01B942, bytes.fromhex("da018abada01f8baf0c4f3f27de5"), bytes.fromhex("e01df6fd7ee5e112f7f272e5db00"), "Force State 1 Normal Operation (StrategicControlThread)"),

    # 3. Emergency fault bypass in StrategicControlSystemStartUpThread (Controller 0x01B932)
    # Redirects 'calls FUN_01bd5a' (fault entry) to 'calls FUN_01bd02' (normal entry):
    # If conditions are missing at boot/cold start, boot directly into State 1 instead of State 3.
    (0x01B932, bytes.fromhex("da015abd"), bytes.fromhex("da0102bd"), "Boot into State 1 (StartUpThread)"),

    # 4. Kupplung_komplett_offen control bypass in FUN_03bd68 (Controller 0x03BD68)
    # Replaces comparison 'DAT_0f1a78 == 1' with 'movb rl4, #0; rets; nop; nop'
    # Prevents CtrlHLSCThread and CtrlHLSCLimitedThread from forcing ValveOff.
    (0x03BD68, bytes.fromhex("f2fc789a48c13d02"), bytes.fromhex("e108db00cc00cc00"), "Kupplung_komplett_offen control bypass (FUN_03bd68)"),

    # 5. ValveOff bypass in FUN_03de7e (Controller 0x03DE7E)
    # Replaces 'movb rl4, DAT_0f1af9; rets' with 'movb rl4, #0; rets; nop' -> ValveSetDemand always called
    (0x03DE7E, bytes.fromhex("f3f8f99adb00"), bytes.fromhex("e1c8db00cc00"), "ValveOff bypass (FUN_03de7e)"),

    # 6. Control error bypass in FUN_03ff5e (Controller 0x03FF5E)
    # Replaces 'mov r4, DAT_0f1b9c; rets' with 'mov r4, #0; rets' -> error count forced to 0
    (0x03FF5E, bytes.fromhex("f2f49c9bdb00"), bytes.fromhex("e6f40000db00"), "Control error bypass (FUN_03ff5e)"),

    # 7. Strategic fault flag bypass in FUN_030e68 (Controller 0x030E68)
    # Replaces 'movb rl4, DAT_0f13ca; rets' with 'movb rl4, #0; rets; nop' -> pipeline fault flag forced to 0
    (0x030E68, bytes.fromhex("f3f8ca93db00"), bytes.fromhex("e108db00cc00"), "Strategic fault flag bypass (FUN_030e68)"),
]


def patch_firmware(data: bytearray, harden_traps: bool = True, simulator_mode: bool = False,
                   start: int = 0x18000, end: int = 0x4ffff) -> dict:
    """
    Applies the complete Anti-Brick Safety Suite (and optional Simulator Mode) to a 320 KB ST10 CPU firmware image:
    1. Installs Anti-Brick Reset Routine at Controller 0x02027C.
    2. Installs Anti-Brick Panic Hook at Controller 0x020364.
    3. Replaces all 120 dummy self-loops in Vector Table with TRAP_ESCAPE_OPCODE (0x020002..0x020200).
    4. If simulator_mode is True: bypasses pump/valve faults, Notlauf, and clutch open flags.
    5. Recalculates Layer-1 checksums for selected blocks only.
    Other sectors remain byte-identical. Anti-brick code lives entirely in block5.
    """
    validate_image(data)
    blocks = selected_blocks(start, end)
    patch_antibrick = any(address == 0x20000 for address, _ in blocks)
    if simulator_mode:
        # Feature patches are firmware-layout specific even though the flash
        # protocol and checksum scheme are shared across the controller family.
        SIMULATOR_MANIFEST.validate(data)

    # Validate fixed-address preimages before making any changes.
    if patch_antibrick and (
            bytes(data[0x2027c:0x2027c+len(ROUTINE_BYTES)]) not in
            (b'\xff' * len(ROUTINE_BYTES), ROUTINE_BYTES)
            or bytes(data[0x20364:0x20364+len(HOOK_BYTES)]) not in
            (bytes.fromhex('da026e030dff'), HOOK_BYTES)):
        raise ValueError('Recovery hook/routine preimage mismatch')
    if simulator_mode:
        for addr, orig, rep, desc in SIMULATOR_PATCHES:
            if start <= addr <= addr+len(rep)-1 <= end and bytes(data[addr:addr+len(orig)]) not in (orig, rep):
                raise ValueError(f'Simulator patch preimage mismatch: {desc}')

    # 1. Install Reset Routine at Controller 0x02027C
    routine_off = 0x02027C
    if patch_antibrick:
        data[routine_off:routine_off + len(ROUTINE_BYTES)] = ROUTINE_BYTES

    # 2. Install Panic Hook at Controller 0x020364
    hook_off = 0x020364
    if patch_antibrick:
        data[hook_off:hook_off + len(HOOK_BYTES)] = HOOK_BYTES

    # 3. Harden Vector Table (0x020002..0x020200)
    traps_patched = 0
    if harden_traps and patch_antibrick:
        vec_base = 0x020002
        for idx in range(128):
            p = vec_base + idx * 4
            inst = data[p:p+4]
            if inst[0] == 0xFA:
                seg = inst[1]
                addr = inst[2] | (inst[3] << 8)
                target = (seg << 16) | addr
                # If vector is a dummy self-loop, redirect it to our escape routine!
                if target == p:
                    data[p:p+4] = TRAP_ESCAPE_OPCODE
                    traps_patched += 1

    # 4. Optional Bench Simulator Mode (bypasses pump/valve open-circuit faults & Notlauf)
    sim_patches_applied = 0
    if simulator_mode:
        for addr, orig, rep, desc in SIMULATOR_PATCHES:
            if not start <= addr <= addr+len(rep)-1 <= end:
                continue
            if data[addr:addr + len(orig)] == orig:
                data[addr:addr + len(rep)] = rep
                sim_patches_applied += 1
            elif data[addr:addr + len(rep)] == rep:
                sim_patches_applied += 1
            else:
                print(f"[!] Warning: Simulator patch '{desc}' mismatch at Controller address 0x{addr:06X}")

    # 5. Recalculate Layer-1 checksums only for the selected complete blocks.
    #    FUN_018534 is called with mask 0xF0 -> blocks 4,5,6,7 are ALL verified at
    #    startup, and any one of them failing lands in the 0x020364 panic.
    csums = {}
    c5 = {}
    for ecu_start, size in blocks:
        csum = calculate_app_checksum(bytes(data[ecu_start:ecu_start + size]))
        struct.pack_into("<H", data, ecu_start + size - 2, csum)
        csums[ecu_start] = csum
        c5[ecu_start] = calculate_c5_sum(data[ecu_start:ecu_start + size])

    return {
        "routine_installed": patch_antibrick,
        "hook_installed": patch_antibrick,
        "traps_hardened": traps_patched,
        "simulator_mode": simulator_mode,
        "sim_patches_applied": sim_patches_applied,
        "block5_csum": csums.get(0x020000),
        "block6_csum": csums.get(0x030000),
        "csums": csums,
        "c5_sums": c5,
        "c5_sum": c5.get(0x020000),
    }


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(description="Haldex Gen4 Firmware Patcher & Anti-Brick Safeguard Engine.")
    parser.add_argument("input_bin", help="Input 320 KiB CPU firmware image")
    parser.add_argument("output_bin", nargs="?", default=None, help="Output patched binary (optional)")
    parser.add_argument("--simulator-mode", action="store_true",
                        help="Bypass pump/valve open-circuit faults, Notlauf limp mode, and clutch open flags for bench testing")
    parser.add_argument("--verify", action="store_true", help="Verify checksums only; do not apply patches")
    parser.add_argument("--fix", type=lambda value: int(value, 0),
                        help="Fix only the Layer-1 checksum of this sector (CPU start address)")
    parser.add_argument("--out", help="Output for --fix (default: input file)")
    args = parser.parse_args(argv)
    if args.verify or args.fix is not None:
        if args.simulator_mode or args.output_bin:
            parser.error("checksum-only mode cannot be combined with patching options")
        return checksum_image(args.input_bin, args.verify, args.fix, args.out)
    if args.out:
        parser.error("--out requires --fix")

    in_file = args.input_bin
    out_file = args.output_bin if args.output_bin else in_file.replace(".bin", "_sim.bin" if args.simulator_mode else "_patched.bin")

    with open(in_file, "rb") as f:
        data = bytearray(f.read())

    validate_image(data)

    print(f"[*] Reading '{in_file}' ({len(data)} bytes, 320 KB CPU memory space)...")
    res = patch_firmware(data, harden_traps=True, simulator_mode=args.simulator_mode)

    print(f"[+] Anti-Brick Routine installed at Controller 0x02027C ({len(ROUTINE_BYTES)} bytes)")
    print(f"[+] Anti-Brick Panic Hook installed at Controller 0x020364 ({len(HOOK_BYTES)} bytes)")
    print(f"[+] Hardened {res['traps_hardened']} dummy trap vectors (Scenario C protection active)")
    if args.simulator_mode:
        print(f"[+] Bench Simulator Mode: Applied {res['sim_patches_applied']} bypass patches (Notlauf & valve/pump faults defeated)")
    print("[+] Layer-1 startup checksums (all four are verified by FUN_018534 mask 0xF0):")
    for ecu_start, size in APP_BLOCKS:
        tag = "  <- tuning tables" if ecu_start == 0x030000 else ""
        print(f"      B0F@0x{ecu_start:06X}  stored 0x{res['csums'][ecu_start]:04X} "
              f"@0x{ecu_start + size - 2:06X}   0xC5 sum 0x{res['c5_sums'][ecu_start]:04X}{tag}")

    with open(out_file, "wb") as f:
        f.write(data)

    print(f"\n[*** SUCCESS ***] Saved patched binary to: '{out_file}'")



BLOCKS = dict(APP_BLOCKS)
APP_SECTORS = tuple((start, start+size) for start, size in APP_BLOCKS)

def layer1(img, start, size):
    return calculate_app_checksum(img[start:start+size])

def layer2(img, start, size):
    return calculate_c5_sum(img[start:start+size])

def application_checksums(data, start):
    """Verify Layer-1 one's-complement LE word sums for complete captured sectors."""
    rows = []
    end = start+len(data)
    for low, high in APP_SECTORS:
        if start >= high or end <= low:
            continue
        complete = start <= low and end >= high
        row = {'start': low, 'end_exclusive': high, 'complete': complete}
        if complete:
            block = data[low-start:high-start]
            stored = int.from_bytes(block[-2:], 'little')
            computed = calculate_app_checksum(block)
            row.update(stored=stored, computed=computed, valid=stored == computed)
        else:
            row.update(valid=None, reason='Requested capture does not include this entire sector')
        rows.append(row)
    return rows


def checksum_image(path, verify=False, fix=None, out=None):
    """Checksum-only operation; never installs anti-brick or simulator patches."""
    with open(path, "rb") as source:
        img = bytearray(source.read())
    validate_image(img)

    valid = True
    if verify or fix is None:
        print("block      stored     computed   0xC5 sum   state")
        for start, size in BLOCKS.items():
            stored = struct.unpack_from("<H", img, start + size - 2)[0]
            calc = layer1(img, start, size)
            c5 = layer2(img, start, size)
            valid = valid and stored == calc
            ok = "OK" if stored == calc else "*** MISMATCH ***"
            print(f"  0x{start:06X}  0x{stored:04X}     0x{calc:04X}     0x{c5:04X}     {ok}")

    if fix is not None:
        start = fix
        if start not in BLOCKS:
            sys.exit(f"0x{start:06X} is not a checksummed block start {[hex(b) for b in BLOCKS]}")
        size = BLOCKS[start]
        calc = layer1(img, start, size)
        off = start + size - 2
        old = struct.unpack_from("<H", img, off)[0]
        struct.pack_into("<H", img, off, calc)
        c5 = layer2(img, start, size)
        outp = out or path
        with open(outp, "wb") as output:
            output.write(img)
        print(f"B0F@0x{start:06X}: Layer-1 checksum 0x{old:04X} -> 0x{calc:04X} written to "
              f"0x{off:06X}")
        print(f"  0xC5 additive transfer sum for this block = 0x{c5:04X}")
        print(f"  wrote {outp}")
        print(f"  FLASH THE WHOLE BLOCK: --start 0x{start:06X} --end 0x{start+size-1:06X}")



    return 0 if valid else 1




DEFAULT_START, DEFAULT_END = 0x18000, 0x4FFFF


@dataclass(frozen=True)
class PatchSite:
    address: int
    expected: bytes
    replacement: bytes
    description: str

    def state(self, image: bytes) -> str:
        actual = image[self.address:self.address + len(self.expected)]
        if actual == self.expected:
            return "stock"
        if actual == self.replacement:
            return "applied"
        return "mismatch"


@dataclass(frozen=True)
class PatchManifest:
    name: str
    feature: str
    sites: tuple[PatchSite, ...]

    def validate(self, image: bytes) -> dict:
        validate_image(image)
        states = {site.address: site.state(image) for site in self.sites}
        mismatches = [site for site in self.sites if states[site.address] == "mismatch"]
        if mismatches:
            details = ", ".join(
                f"0x{site.address:06X} {site.description}" for site in mismatches)
            raise ValueError(f"{self.feature} patch manifest does not match image: {details}")
        return {"manifest": self.name, "feature": self.feature, "states": states}


SIMULATOR_MANIFEST = PatchManifest(
    name="haldex-gen4-simulator-known-layout",
    feature="simulator-mode",
    sites=tuple(PatchSite(*site) for site in SIMULATOR_PATCHES),
)


def prepare_image(source, start_addr=DEFAULT_START, end_addr=DEFAULT_END,
                  file_off=None, simulator_mode=False):
    """Prepare a Haldex image using only this controller family's patch policy."""
    if type(simulator_mode) is not bool:
        raise ValueError("simulator_mode must be a boolean")
    if type(start_addr) is not int or type(end_addr) is not int:
        raise ValueError("Addresses must be integers")
    selected_blocks(start_addr, end_addr)
    if file_off is not None and (type(file_off) is not int or file_off != start_addr):
        raise ValueError("Source offset must match CPU linear application address")

    image = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
    if len(image) != IMAGE_SIZE:
        raise ValueError(
            "Only validated 320KiB CPU linear images are supported; "
            "64KiB calibration files and raw dumps are unsupported")
    validate_image(image)
    digest = hashlib.sha256(image).hexdigest()
    original = image
    if simulator_mode:
        SIMULATOR_MANIFEST.validate(original)

    prepared = bytearray(original)
    patch_result = patch_firmware(
        prepared, harden_traps=True, simulator_mode=simulator_mode,
        start=start_addr, end=end_addr)
    image = bytes(prepared)

    changes = []
    offset = 0
    while offset < len(image):
        if image[offset] == original[offset]:
            offset += 1
            continue
        first = offset
        while offset < len(image) and image[offset] != original[offset]:
            offset += 1
        changes.append({
            "address": first,
            "before": original[first:offset].hex(),
            "after": image[first:offset].hex(),
            "transferred": start_addr <= first and offset - 1 <= end_addr,
        })

    sectors = []
    for address, size in APP_BLOCKS:
        stored = struct.unpack_from("<H", image, address + size - 2)[0]
        if start_addr <= address and address + size - 1 <= end_addr:
            if stored != layer1(image, address, size):
                raise ValueError(f"Application checksum mismatch at {address:#x}")
            sectors.append({
                "start": address,
                "end": address + size - 1,
                "source_offset": address,
                "size": size,
                "layer1_checksum": stored,
                "transfer_checksum": sum(image[address:address + size]) & 0xFFFF,
            })

    region = image[start_addr:end_addr + 1]
    metadata = {
        "original_sha256": digest,
        "prepared_sha256": hashlib.sha256(image).hexdigest(),
        "patches": changes,
        "patch_policy": (
            "Haldex Gen4 recovery patches, trap hardening, optional exact-manifest "
            "simulator patches, and checksum repairs in selected sectors"
        ),
        "patch_result": patch_result,
        "patch_manifest": SIMULATOR_MANIFEST.name if simulator_mode else None,
        "sectors": sectors,
        "start_addr": start_addr,
        "end_addr": end_addr,
        "size": len(region),
        "checksum": sum(region) & 0xFFFF,
        "selection_policy": "user-selected whole application sectors",
        "simulator_mode": simulator_mode,
        "bench_only": simulator_mode,
    }
    return {"image": image, "region": region, "metadata": metadata}


if __name__ == "__main__":
    raise SystemExit(main())
