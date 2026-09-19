"""PQ EPS firmware-specific patch catalog.

No patch set has been validated yet. Keeping this module intentionally empty
prevents a family match or a same-sized image from authorizing mutation.
"""


class UnsupportedFirmwarePatch(ValueError):
    pass


PATCH_MANIFESTS = ()


def require_patch_manifest(image: bytes, feature: str):
    raise UnsupportedFirmwarePatch(
        f"No exact PQ EPS firmware manifest supports {feature}; image was not modified")
