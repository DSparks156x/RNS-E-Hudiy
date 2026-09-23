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
DEFAULT_START = 0x5D000
DEFAULT_END = 0x5DFFF
END_MARKER_OFFSET = 0x5FFFC


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
    if file_off is not None and file_off != start:
        raise ValueError("PQ EPS images are CPU-linear; file offset must equal start address")
    data = _load(source)
    validate_image(data)
    validate_selection(start, end)
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
            "start_addr": start,
            "end_addr": end,
            "size": len(region),
            "checksum": sum(region) & 0xFFFF,
            "patches": [],
            "end_marker": marker,
            "selection_policy": "inclusive contiguous PQ EPS address range",
        },
    }


class UnsupportedFirmwarePatch(ValueError):
    pass


PATCH_MANIFESTS = ()


def require_patch_manifest(image: bytes, feature: str):
    raise UnsupportedFirmwarePatch(
        f"No exact PQ EPS firmware manifest supports {feature}; image was not modified")
