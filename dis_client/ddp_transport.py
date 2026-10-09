"""Fixed-channel TP negotiation fields verified in native193PU 80633E78.

Session identification remains in DDPProtocol: long records identify its white
profile, and the existing short red profile has its own handshake. This parser
does not interpret opaque session bytes or convert scheduler ticks to seconds.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class PeerTransportParameters:
    raw: tuple
    block_size_raw: int
    native_block_size: int
    legacy: bool
    pacing_raw: object
    pacing_counter_ticks: int

    @classmethod
    def parse(cls, record):
        raw = tuple(record)
        if (not 2 <= len(raw) <= 8 or raw[0] not in (0xA0, 0xA1)
                or any(type(value) is not int or not 0 <= value <= 255 for value in raw)):
            raise ValueError('Malformed fixed-channel session parameter record')
        legacy = len(raw) < 6
        pacing = None if legacy else raw[4]
        if legacy:
            ticks = 1
        else:
            magnitude, unit = pacing & 63, pacing >> 6
            ticks = ((magnitude + 99) // 100 if unit == 0 else
                     (magnitude * (1 if unit == 1 else 10 if unit == 2 else 100) + 9) // 10)
        return cls(raw, raw[1], min(raw[1], 15), legacy, pacing, ticks)

    @property
    def host_ack_block_cap(self):
        # Actual80633ABC sets (nextSequence+BS-1)&15.80634F6C reaches a
        #zero-BS boundary after16 frames. The driver independently retains its
        #configured safety cap and at-most15 pending frames for ACK disambiguation.
        return 16 if self.native_block_size == 0 else self.native_block_size
