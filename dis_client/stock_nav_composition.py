"""Bounded stock193 hicolor maneuver composition from raw ROM selectors.

This preserves8055E3A4 records, including auxiliary81 symbols and raw83 frame
records. It neither assigns visual names nor performs ownership/CAN operations.
The glyph-only native_nav_glyphs API retains its existing meaning.
"""
from native_nav_glyphs import StockNavGlyphCatalog


class StockNavComposition:
    def __init__(self, catalog=None):
        self.catalog = catalog if catalog is not None else StockNavGlyphCatalog()

    def object_records(self, capability, source_object):
        """Exact serialized header/count/triples for proved paired/special domains.

        This separate entry preserves records()/glyph-only semantics. Header
        selection is not inferred from directions: the canonical leading0D
        in special objects is essential to native80555B12/80559DAE selection.
        Unknown keys/neighbor-ROM rows and unproved source permutations refuse.
        Caller owns initial frame0, ownership,128-byte packing and distinct39.
        """
        if (not isinstance(source_object, (list, tuple, bytes, bytearray))
                or any(type(v) is not int or not 0 <= v <= 255 for v in source_object)):
            raise ValueError('Stock source object must contain exact byte integers')
        raw = bytes(source_object)
        if (len(raw) < 12 or raw[0] != 0 or not 3 <= raw[2] <= 5
                or len(raw) != 3 + 3 * raw[2]):
            raise ValueError('Stock source header/count/extent is not verified')
        elements = [raw[i:i+3] for i in range(3, len(raw), 3)]
        if any(row[2] != 0 for row in elements):
            raise ValueError('Only zero third element bytes are verified')
        kinds = tuple(row[0] for row in elements)
        primary = [row for row in elements if row[0] != 0x81]
        if (raw[1] == 2 and len(primary) == 2
                and all(row[0] == 0x0D for row in primary)):
            patterns = ((0x81,0x0D,0x0D), (0x0D,0x81,0x0D), (0x0D,0x0D,0x81),
                        (0x0D,0x81,0x0D,0x81), (0x0D,0x81,0x81,0x81,0x0D),
                        (0x0D,0x0D,0x81,0x81,0x81))
            keys = [row[1] for row in elements if row[0] == 0x81]
            if kinds not in patterns or len(set(keys)) != 1:
                raise ValueError('Paired supplement arrangement is not verified')
            # Exact catalog lookup rejects every pair outside40/C0 x00/80.
            # The four paired auxiliary pointers are null: keys do not draw.
            return self.records(capability, 0x0D, [row[1] for row in primary])
        if (raw[1] != 1 or len(primary) != 2 or elements[0] != b'\x0d\x00\x00'
                or primary[1][0] not in (0x7D,0x7E,0x7F)):
            raise ValueError('Special source selection/header is not verified')
        selected = primary[1]
        count = raw[2] - 2
        if kinds not in ((0x0D, selected[0]) + (0x81,) * count,
                         (0x0D,) + (0x81,) * count + (selected[0],)):
            raise ValueError('Special supplement placement is not verified')
        keys = [row[1] for row in elements if row[0] == 0x81]
        if selected[0] == 0x7D:
            if (any(key not in range(0,256,32) for key in keys)
                    or not (len(set(keys)) == 1
                            or keys == [(keys[0] + 32 * n) % 256 for n in range(count)])):
                raise ValueError('Special7D auxiliary key/sequence is not verified')
        elif len(set(keys)) != 1:
            raise ValueError('Special ignored-key sequence is not verified')
        # records() verifies capability and exact main ROM row without enabling
        # the old API's refused special/supplement compounds.
        bare = self.records(capability, selected[0], [selected[1]])
        units = bytearray()
        for supplied in keys:
            key = supplied if selected[0] == 0x7D else selected[1]
            units.extend(b''.join(record[2:] for record in self.catalog.auxiliary_records(
                capability, selected[0], [selected[1]], key, clear=False, position=0)))
        if len(units) > 124 or len(units) % 4:
            raise ValueError('One special69 record exceeds native128-byte bounds')
        return bare[:-1] + ((bytes((0x69,len(units))) + units,) if units else ()) + bare[-1:]

    def records(self, capability, maneuver_type, directions, auxiliary_keys=(),
                auxiliary_position='after'):
        """Exact bounded full7A objects; every input remains a raw source value.

        Bare catalog objects are covered by129 native vectors. Supplements
        cover one0D/15/16/0F/10 primary plus one to three81 keys. Before-primary
        placement is proved only for0F/10 or0D direction0. Other compounds are
        refused before a record is returned. Caller owns the initial frame0,
        whole-record128 message packing, ownership and separate39 commit.
        """
        if (getattr(capability, 'command_family', None) != 0x7A
                or getattr(capability, 'format_code', None) != 0x10
                or getattr(capability, 'company_code', None) != 3):
            raise ValueError('Stock composition requires negotiated7A hicolor capability')
        if (not isinstance(directions, (list, tuple)) or len(directions) not in (1,2)
                or any(type(value) is not int or not 0 <= value <= 255 for value in directions)):
            raise ValueError('Stock composition requires one or two raw direction bytes')
        if (not isinstance(auxiliary_keys, (list, tuple))
                or len(auxiliary_keys) > 3
                or any(type(k) is not int or not 0 <= k <= 255 for k in auxiliary_keys)):
            raise ValueError('Stock composition accepts zero to three raw81 byte keys')
        if auxiliary_position not in ('after', 'before'):
            raise ValueError('Auxiliary position must be before or after')
        # The existing catalog performs exact-int/raw-direction validation;
        # all selected rows must be backed by recovered stock ROM tables.
        row, pair = self.catalog._lookup('hicolor', maneuver_type, directions)
        if auxiliary_keys and (pair is not None or maneuver_type not in (0x0D,0x15,0x16,0x0F,0x10)):
            raise ValueError('This stock primary/supplement compound is not verified')
        if (auxiliary_keys and auxiliary_position == 'before'
                and not (maneuver_type in (0x0F,0x10)
                         or maneuver_type == 0x0D and directions[0] == 0)):
            raise ValueError('Before-primary81 placement is not verified for this primary')

        result = list(self.catalog.frame_records(capability, 12))
        units = bytearray()
        if maneuver_type in (0x0D,0x15,0x16):
            # Bare paired0D selects the second row's clear auxiliary pointer;
            # one-primary paths select position1. Empty tables emit no units.
            position = 2 if pair is not None else 1
            units.extend(b''.join(r[2:] for r in self.catalog.auxiliary_records(
                capability, maneuver_type, directions, directions[-1], clear=True, position=position)))
        if auxiliary_keys:
            clear = maneuver_type not in (0x0F,0x10)
            position = 1 if clear else 0
            _, _, pointer = self.catalog.auxiliary_descriptor(
                capability, maneuver_type, directions, clear=clear, position=position)
            known = {entry['key'] for entry in
                     self.catalog.catalog['auxiliary']['hicolor'].get(pointer, ())}
            if any(key not in known for key in auxiliary_keys):
                raise ValueError('Auxiliary key has no verified stock table row')
            for key in auxiliary_keys:
                units.extend(b''.join(r[2:] for r in self.catalog.auxiliary_records(
                    capability, maneuver_type, directions, key, clear=clear, position=position)))
        if units:
            if len(units) > 124 or len(units) % 4:
                raise ValueError('One composed69 record exceeds the native128 message limit')
            result.append(bytes((0x69,len(units)))+units)
            if maneuver_type in (0x15,0x16) and 0x67 < directions[-1] < 0x98:
                result.extend(self.catalog.frame_records(capability, 15))
        # Stock writes a two-byte zero69 record for a known empty primary row;
        # glyph-only absolute_records deliberately returns no records instead.
        primary = bytes.fromhex(row['payload_hex']) or bytes((0x69,0))
        result.append(primary)
        if any(len(record) > 128 for record in result):
            raise ValueError('One stock record exceeds the native128 message limit')
        return tuple(result)
