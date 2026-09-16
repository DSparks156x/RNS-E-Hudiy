"""Vehicle artifact authority. Preparation is entirely offline and fail closed."""
import hashlib
import struct
from pathlib import Path
from .haldex_patcher import APP_BLOCKS, patch_firmware, layer1

DEFAULT_START, DEFAULT_END = 0x18000, 0x4ffff

def prepare_image(source, start_addr=DEFAULT_START, end_addr=DEFAULT_END,
                  file_off=None, simulator_mode=False):
    if simulator_mode is not False:
        raise ValueError('Simulator bypasses are forbidden in the vehicle workflow')
    if type(start_addr) is not int or type(end_addr) is not int:
        raise ValueError('Addresses must be integers')
    if (start_addr not in {a for a, _ in APP_BLOCKS}
            or end_addr not in {a+s-1 for a, s in APP_BLOCKS} or end_addr < start_addr):
        raise ValueError('Select complete application sectors within 0x18000..0x4ffff')
    if file_off is not None and (type(file_off) is not int or file_off != start_addr):
        raise ValueError('Source offset must match CPU linear application address')
    image = Path(source).read_bytes() if isinstance(source, (str, Path)) else bytes(source)
    if len(image) != 0x50000:
        raise ValueError('Only validated 320KiB CPU linear images are supported; 64KiB calibration files and raw dumps are unsupported')
    digest = hashlib.sha256(image).hexdigest()
    original = image
    prepared = bytearray(original)
    patch_result = patch_firmware(prepared, harden_traps=True, simulator_mode=False,
                                  start=start_addr, end=end_addr)
    image = bytes(prepared)
    # Record exact byte changes, including checksum repairs, without modifying
    # the source file. Selection still controls which prepared sectors are sent.
    patches = []
    offset = 0
    while offset < len(image):
        if image[offset] == original[offset]:
            offset += 1
            continue
        first = offset
        while offset < len(image) and image[offset] != original[offset]:
            offset += 1
        patches.append({'address': first, 'before': original[first:offset].hex(),
                        'after': image[first:offset].hex(),
                        'transferred': start_addr <= first and offset-1 <= end_addr})
    sectors = []
    for addr, size in APP_BLOCKS:
        stored = struct.unpack_from('<H', image, addr+size-2)[0]
        if start_addr <= addr and addr+size-1 <= end_addr and stored != layer1(image, addr, size):
            raise ValueError(f'Application checksum mismatch at {addr:#x}')
        if start_addr <= addr and addr+size-1 <= end_addr:
            sectors.append({'start': addr, 'end': addr+size-1, 'source_offset': addr,
                        'size': size, 'layer1_checksum': stored,
                        'transfer_checksum': sum(image[addr:addr+size]) & 0xffff})
    region = image[start_addr:end_addr+1]
    metadata = {'original_sha256': digest, 'prepared_sha256': hashlib.sha256(image).hexdigest(), 'patches': patches,
                'patch_policy': 'automatic recovery patches, trap hardening and checksum repairs in selected sectors',
                'patch_result': patch_result,
                'sectors': sectors, 'start_addr': start_addr, 'end_addr': end_addr,
                'size': len(region), 'checksum': sum(region) & 0xffff,
                'selection_policy': 'user-selected whole application sectors'}
    return {'image': image, 'region': region, 'metadata': metadata}
