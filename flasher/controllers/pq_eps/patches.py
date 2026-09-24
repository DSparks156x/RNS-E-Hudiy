"""PQ EPS image validation and transfer preparation.

This module deliberately does not patch firmware. It accepts a complete
CPU-linear rack image, selects an inclusive flash range, and calculates the
additive checksum consumed by loader routine 0xC5. Both the stock ``Ende``
trailer and an erased ``ff ff ff ff`` trailer are valid inputs.
"""
import hashlib
from pathlib import Path


IMAGE_SIZE = 0x60000
FLASH_START = 0x0A000
DATASET_START = 0x5E000
DATASET_END = 0x5EFFF
DATASET_SIZE = DATASET_END - DATASET_START + 1
DEFAULT_START = 0x5D000
DEFAULT_END = 0x5DFFF
END_MARKER_OFFSET = 0x5FFFC

# The resident loader in the user's full TT 3001 rack dump requires exact
# partition bounds for CPU-flash RequestDownload (0x9A10, flag bit 0). This
# fingerprint limits the extra check to images retaining that loader bank;
# SGO-derived application images do not identify the target's resident loader.
TT3001_LOADER_SHA256 = "432B7F6C46DCED5A19A63D22C26E6B8987184996033404B586DB54D9714E1D93"
TT3001_PARTITIONS = frozenset({
    (0x0A000, 0x5FFFF),
    (0x0A000, 0x5BFFF),
    (0x0A000, 0x5DFFF),
    (0x5F000, 0x5FFFF),
    (0x5C000, 0x5DFFF),
    (0x5C000, 0x5CFFF),
    (0x5D000, 0x5DFFF),
    (0x5E000, 0x5EFFF),
    (0x57000, 0x5FFFF),
})


def _load(source) -> bytes:
    if isinstance(source, (bytes, bytearray, memoryview)):
        return bytes(source)
    return Path(source).read_bytes()


def validate_image(data: bytes) -> None:
    if len(data) != IMAGE_SIZE:
        raise ValueError(
            f"Expected exactly 384 KiB ({IMAGE_SIZE} bytes), got {len(data)} bytes")


def validate_selection(start: int, end: int) -> None:
    if not FLASH_START <= start <= end < IMAGE_SIZE:
        raise ValueError("PQ EPS OBD flash range must be within 0x00A000..0x05FFFF")


def prepare_image(source, start=DEFAULT_START, end=DEFAULT_END, file_off=None,
                  simulator_mode=False) -> dict:
    """Prepare an unmodified inclusive range for the common PQ flash engine."""
    if simulator_mode:
        raise ValueError("PQ EPS has no simulator-mode firmware patch set")
    data = _load(source)
    if len(data) == DATASET_SIZE:
        if (start, end) != (DATASET_START, DATASET_END):
            raise ValueError(
                "A 4 KiB EPS block image can only be flashed as the 0x5E steer dataset")
        if file_off not in (None, 0):
            raise ValueError("A 4 KiB EPS steer dataset starts at file offset zero")
        return {
            "image": data,
            "region": data,
            "metadata": {
                "image_size": len(data),
                "image_sha256": hashlib.sha256(data).hexdigest().upper(),
                "source_kind": "4 KiB steer dataset block (0x5E)",
                "start_addr": start,
                "end_addr": end,
                "size": len(data),
                "checksum": sum(data) & 0xFFFF,
                "patches": [],
                "end_marker": None,
                "selection_policy": "exact 0x5E steer-dataset block",
            },
        }
    if file_off is not None and file_off != start:
        raise ValueError("PQ EPS images are CPU-linear; file offset must equal start address")
    validate_image(data)
    validate_selection(start, end)
    tt3001_loader = hashlib.sha256(data[:FLASH_START]).hexdigest().upper() == TT3001_LOADER_SHA256
    if tt3001_loader and (start, end) not in TT3001_PARTITIONS:
        raise ValueError(
            "TT 3001 resident loader requires exact partition bounds; "
            f"0x{start:05X}..0x{end:05X} is not in its RequestDownload table")
    region = data[start:end + 1]
    trailer = data[END_MARKER_OFFSET:END_MARKER_OFFSET + 4]
    marker = ("Ende" if trailer == b"Ende" else
              "erased" if trailer == b"\xFF" * 4 else trailer.hex())
    return {
        "image": data,
        "region": region,
        "metadata": {
            "image_size": len(data),
            "image_sha256": hashlib.sha256(data).hexdigest().upper(),
            "source_kind": "384 KiB CPU-linear EPS firmware",
            "start_addr": start,
            "end_addr": end,
            "size": len(region),
            "checksum": sum(region) & 0xFFFF,
            "patches": [],
            "end_marker": marker,
            "selection_policy": (
                "exact TT 3001 resident-loader partition" if tt3001_loader else
                "local PQ EPS range only; target loader partition unverified"),
        },
    }


class UnsupportedFirmwarePatch(ValueError):
    pass


PATCH_MANIFESTS = ()


def require_patch_manifest(image: bytes, feature: str):
    raise UnsupportedFirmwarePatch(
        f"No exact PQ EPS firmware manifest supports {feature}; image was not modified")
