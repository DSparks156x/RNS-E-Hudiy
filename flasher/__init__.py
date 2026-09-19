"""PQ flasher engine, shared VAG protocols, and controller-family policies."""

from .controllers import FAMILIES, family_for_module, get_family, parse_module

__all__ = ["FAMILIES", "family_for_module", "get_family", "parse_module"]
