# Native navigation source artwork

These 44 mapped SVGs are Google's actual Maps maneuver vectors, extracted from
`com.google.android.apps.maps` version `26.39.04.984891338`. The original artwork
is credited to Google. `manifest.json` records the base APK hash, decoded source
resource, source byte hash, curated SVG hash and approved packed-mask hash for
each existing navigation key. No APK, full raster dump or phone tooling is needed
to regenerate the runtime assets.

Android vector path data, viewport, fill colors and alpha were preserved in SVG
conversion; the two ferry resources were already SVG. The complete source
viewport is contained in 72x72 physical pixels with phase (0,0). There is no
occupied-shape crop, per-glyph repair, synthetic mirror, or image dithering.
Eight-times coverage is BOX-averaged and thresholded at 128/255. Active routes
are solid. Separately authored half-opacity context routes use a fixed (x+y even)
checker, with active pixels taking priority. The checker is anchored to the
output grid; it is not mirror-invariant on an even 72px canvas.

The existing 44 NavApp keys, road-side circulation, angle mapping and (6,2)
placement on the 128x96 canvas are preserved. CCW U-turn uses the authored left
return; CW uses right. Roundabout entry/default is an authored alias of the
enter-and-exit generic source; exit and named macro exit variants are distinct.
Authored aliases are retained: normal on-ramp matches normal turn, and all
three MERGE sources have the same image. Other ramp variants remain available
in the complete research export; they are not substituted for current semantics.

`reference72/` holds the exact approved mode1 review masks (648 packed bytes each)
so unit tests do not need an SVG renderer. Runtime loads only the pre-generated
standard-library `nav_icons_data.py`; SVG/Pillow/Node dependencies are development
tools, not new device service requirements.

From the repository root, regenerate/check using:

```sh
python -m pip install -r tools/native_nav_icons/requirements-dev.txt
npm install --prefix tools/native_nav_icons
python tools/generate_native_nav_icons.py --check --previews /tmp/nav-icons
python tools/generate_native_nav_icons.py --previews /tmp/nav-icons
```

The generator accepts `--node` and `--sharp-module` for an existing alternative
development installation. Update reference masks deliberately with
`--update-reference` after a source/raster change has been reviewed. Installing
or using the service does not run this generator or install Node dependencies.
