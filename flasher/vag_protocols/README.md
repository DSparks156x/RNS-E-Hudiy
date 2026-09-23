# Shared VAG Protocol Stack

This package is the single implementation point for TP2 framing and KWP2000
request/response behavior in this project.

## Layering

- `tp2.py` owns timing decoding, sequence numbers, segmentation, ACK creation,
  length-prefixed reassembly, dynamic diagnostic channel setup, keepalives, and
  retransmission handling.
- `kwp.py` owns positive/negative response handling, response-pending behavior,
  bounded busy retries, reusable KWP service helpers, and the generic profile
  schema. Concrete ECU profiles remain with their consuming application.
- `dis_client/ddp_protocol.py` remains the one DDP application/session library.
  It uses the TP2 frame primitives here but retains its fixed channel IDs,
  active/passive cluster handshake, display state machine, and empirical cluster
  limits.

Consumers import this package directly. Higher-level applications such as
`tp2/tp2_protocol.py` may compose these primitives, but no forwarding protocol
module is maintained.

The current controller bindings use this same RNS-E-Hudiy-derived stack for
both Haldex and PQ EPS programming. EPS programming is policy-gated by
`controllers/pq_eps`: OBD ranges are restricted to `0x00A000..0x05FFFF`, while
the shared transport supplies negotiated TP2 timing, segmentation, KWP pending
handling, and reconnect behavior.

## DDP compatibility profile

The currently known-good cluster behavior is deliberately preserved:

- fixed rather than dynamically allocated CAN IDs;
- end-delimited TP2-style payloads rather than KWP's two-byte length prefix;
- at most 42 application bytes per acknowledged DDP message;
- a 2 ms local CAN pacing delay;
- an optional 20 ms post-message processing delay on white clusters.

The DDP service accepts matching `ddp_frame_gap_s`,
`ddp_max_message_bytes`, `ddp_max_unacked_frames`, and
`ddp_white_post_message_delay_s` configuration keys, so cluster experiments do
not require changes to the shared TP2 implementation.

These represent observed behavior, not assumed protocol requirements. Bench
testing should vary the following independently:

1. maximum unacknowledged frames;
2. maximum logical TP2/DDP message size;
3. inter-frame timing;
4. post-message application processing delay.

That distinction matters: a true TP2 block boundary uses opcode `0x0` (ACK,
more frames follow), whereas the current 42-byte DDP compatibility behavior
ends the logical message with opcode `0x1` and starts a new one.

## Migration rule

New transport behavior belongs here and must have offline frame-level tests.
Application-specific validation belongs in KWP profiles or the DDP application
layer; it must not be reimplemented in service loops.
