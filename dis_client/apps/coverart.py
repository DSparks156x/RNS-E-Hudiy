import io
import logging
from PIL import Image
import dis_image
from .base import BaseApp

logger = logging.getLogger(__name__)


class CoverArtApp(BaseApp):
    # Decode cover art once on receipt, never inside the recurring draw loop.
    MAX_ENCODED_BYTES = 4 * 1024 * 1024
    MAX_SOURCE_PIXELS = 8_000_000

    def __init__(self, config=None):
        super().__init__(config)
        self.bitmap_hex = ''
        self.native_bitmap_hex = ''
        self.title = 'Now Playing'
        settings = self.config.get('display', {}).get('center_display', {}).get('coverart', {})
        self.native_resolution = settings.get('native_resolution', False)
        if not isinstance(self.native_resolution, bool):
            raise ValueError('coverart.native_resolution must be a boolean')
        self.native_preset = settings.get('native_preset', 'legacy')
        self.native_args = settings.get('native_args', {})
        if not isinstance(self.native_args, dict):
            raise ValueError('coverart.native_args must be an object')
        if self.native_preset == 'legacy':
            legacy_args = settings.get('args', {})
            if not isinstance(legacy_args, dict):
                raise ValueError('coverart.args must be an object')
            # Existing64x48 controls carry through exactly, but geometry is
            # always native128x96. Explicit native_args override those controls.
            self.native_args = {**{key: value for key, value in legacy_args.items() if key != 'target_size'},
                                **self.native_args}
        else:
            self.native_args = dict(self.native_args)
        dis_image.native_image_options(self.native_preset, **self.native_args)
        self.native_render_order = settings.get('native_render_order', 'tiles')
        if self.native_render_order not in ('tiles', 'planes', 'bands'):
            raise ValueError('coverart.native_render_order must be tiles, planes or bands')
        self.native_delta = settings.get('native_delta', False)
        if not isinstance(self.native_delta, bool):
            raise ValueError('coverart.native_delta must be a boolean')
        if self.native_delta and self.native_render_order != 'tiles':
            raise ValueError('coverart.native_delta requires native_render_order tiles')
        self._last_native_source = None

    def _process_native_cover(self, image_hex, native_hex):
        if image_hex:
            if not isinstance(image_hex, str) or len(image_hex) > self.MAX_ENCODED_BYTES * 2:
                raise ValueError('Encoded cover exceeds4 MiB or is not hex text')
            encoded = bytes.fromhex(image_hex)
            with Image.open(io.BytesIO(encoded)) as source:
                if source.width * source.height > self.MAX_SOURCE_PIXELS:
                    raise ValueError('Decoded cover exceeds8 million pixels')
                processed = dis_image.process_native_image(source, self.native_preset, **self.native_args)
            return processed.tobytes().hex()
        if native_hex:
            if not isinstance(native_hex, str) or len(native_hex) > 1536 * 2:
                raise ValueError('Native cover must contain exactly1536 packed bytes')
            packed = bytes.fromhex(native_hex)
            if len(packed) != 1536:
                raise ValueError('Native cover must contain exactly1536 packed bytes')
            return packed.hex()
        return ''

    def update_hudiy(self, topic, data):
        if topic != b'HUDIY_COVERART':
            return
        self.bitmap_hex = data.get('bitmap_hex', '')
        if not self.native_resolution:
            return
        image_hex = data.get('image_hex', '')
        native_hex = data.get('native_bitmap_hex', '')
        source_key = (image_hex, native_hex)
        # The active app can receive the same event twice; avoid repeat decode.
        if source_key == self._last_native_source:
            return
        self._last_native_source = source_key
        self.native_bitmap_hex = ''
        try:
            self.native_bitmap_hex = self._process_native_cover(image_hex, native_hex)
        except (ValueError, TypeError, OSError, Image.DecompressionBombError) as exc:
            logger.warning('Native cover unavailable; using legacy cover: %s', exc)

    def get_view(self):
        if self.native_resolution and self.native_bitmap_hex:
            # Descriptor is separate: DisplayEngine skips all items with type.
            command = {'cmd': 'native_bitmap', 'data_hex': self.native_bitmap_hex,
                       'render_order': self.native_render_order}
            if self.native_delta:
                command['delta'] = True
            return [{'type': 'cover_art'}, command]
        if not self.bitmap_hex:
            return [
                {'type': 'cover_art'},
                {'cmd': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48},
                {'cmd': 'draw_text', 'text': 'No Cover Art', 'x': 0, 'y': 20,
                 'flags': self.FLAG_ITEM_CENTERED}
            ]
        return [
            {'type': 'cover_art', 'cmd': 'clear_area', 'x': 0, 'y': 0, 'w': 64, 'h': 48},
            {'cmd': 'draw_raw_bitmap', 'data_hex': self.bitmap_hex,
             'w': 64, 'h': 48, 'x': 0, 'y': 0, 'mode_flag': 0x02}
        ]
