"""PQ EPS image validation and transfer preparation.

This module deliberately does not patch firmware. It accepts either a complete
CPU-linear rack image or the exact 4 KiB 0x5E steering dataset, selects an
inclusive flash range, and calculates the additive checksum consumed by loader
routine 0xC5. Both the stock ``Ende`` trailer and an erased ``ff ff ff ff``
trailer are valid for complete images.
"""
import hashlib
from pathlib import Path


IMAGE_SIZE = 0x60000
FLASH_START = 0x0A000
DEFAULT_START = 0x5D000
DEFAULT_END = 0x5DFFF
STEER_DATASET_START = 0x5E000
STEER_DATASET_END = 0x5EFFF
STEER_DATASET_SIZE = 0x1000
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


def prepare_image(source, start_addr=DEFAULT_START, end_addr=DEFAULT_END, file_off=None,
                  simulator_mode=False) -> dict:
    """Prepare a full CPU-linear image or the exact 0x5E steer dataset."""
    if simulator_mode:
        raise ValueError("PQ EPS has no simulator-mode firmware patch set")
    data = _load(source)
    validate_selection(start_addr, end_addr)
    if len(data) == IMAGE_SIZE:
        if file_off is not None and file_off != start_addr:
            raise ValueError("PQ EPS full images are CPU-linear; file offset must equal start address")
        region = data[start_addr:end_addr + 1]
        trailer = data[END_MARKER_OFFSET:END_MARKER_OFFSET + 4]
        marker = ("Ende" if trailer == b"Ende" else
                  "erased" if trailer == b"\xFF" * 4 else trailer.hex())
        source_kind = "384 KiB CPU-linear PQ EPS image"
    elif len(data) == STEER_DATASET_SIZE:
        if (start_addr, end_addr) != (STEER_DATASET_START, STEER_DATASET_END):
            raise ValueError(
                "A 4 KiB PQ EPS dataset is valid only for 0x05E000..0x05EFFF")
        if file_off is not None and file_off != STEER_DATASET_START:
            raise ValueError("PQ EPS steer dataset file offset must be 0x05E000")
        region = data
        marker = "not-present"
        source_kind = "4 KiB 0x5E steering dataset"
    else:
        raise ValueError(
            f"Expected a 384 KiB full PQ EPS image or 4 KiB 0x5E steer dataset, got {len(data)} bytes")
    return {
        "image": data,
        "region": region,
        "metadata": {
            "image_size": len(data),
            "image_sha256": hashlib.sha256(data).hexdigest().upper(),
            "start_addr": start_addr,
            "end_addr": end_addr,
            "size": len(region),
            "checksum": sum(region) & 0xFFFF,
            "patches": [],
            "end_marker": marker,
            "source_kind": source_kind,
            "selection_policy": "inclusive contiguous PQ EPS address range",
        },
    }


class UnsupportedFirmwarePatch(ValueError):
    pass


PATCH_MANIFESTS = ()


def require_patch_manifest(image: bytes, feature: str):
    raise UnsupportedFirmwarePatch(
        f"No exact PQ EPS firmware manifest supports {feature}; image was not modified")
