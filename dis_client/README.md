To fix:
- bitmap drawing on A4 red dis clusters

To do:
- implement car data from CAN data
- adding icons for phone menu
- adding more navigation bitmaps
- adding dis top radio lines

````markdown

NEW: ADDED BETA VERSION FOR COLOR DIS IN COLOR_DIS_BETA BRANCH


````


```bash
ddp_protocol.py and dis_service.py are compatible with all cluster versions in the COLOR_DIS_BETA branch.
To use dis_display.py with color DIS, add to config.json  "dis_type": "color"
The dis_display.py in COLOR_DIS_BETA is at the moment only compatible with color DIS clusters.
```


## Measured text layout

`display.center_display.high_resolution` selects the white-cluster fonts and
high-resolution graphics when enabled, or the red-cluster fonts and legacy graphics
when disabled. The same setting chooses the eight-value or five-line Car Info
layout. Legacy tables are available, but have not been verified on red hardware in
this session.

`font_metrics.py` measures the actual encoded AUDSCII bytes in physical pixels.
Both profiles use that unit, while graphics coordinates remain logical pixels
(two physical pixels per coordinate). Measured advances include trailing
spacing. Unknown native advances conservatively reserve the maximum 12-pixel
cell; an unknown bitmap can still have a verified advance.

Media title/artist/album scrolling fits each whole-character window within 128
physical pixels. Navigation streets use their measured viewport, reserve the
approach bar and margins, and center fitting text within that viewport. Distance
values choose a complete rounded representation that fits the 38/44-pixel slot.
Dictionary text updates clear the bounded line before drawing, including
same-character-count changes from wide to narrow text. Scrolling resets when
the text, available width, font, profile, or looping mode changes.

The generated metrics asset is reproducible from the same capture export and
legacy font tables as the emulator:

```sh
python tools/import_native_fonts.py --source /path/to/native_fonts.json
```
