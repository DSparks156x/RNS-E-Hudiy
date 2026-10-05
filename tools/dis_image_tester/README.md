## DIS Image & GIF Tester

This is the DIS image and animated GIF tester, a React webapp for experimenting with the DIS image processing settings to turn full-color album art and animated GIFs into pixelated 2-color DIS message screen graphics.

### Features

- **Static Album Art & Animated GIFs**: Full support for `.png`, `.jpg`, `.jpeg`, `.webp`, `.bmp`, and animated `.gif` files.
- **Real-Time Frame Processing**: GIFs are processed frame-by-frame using the DIS pipeline (`dis_client/dis_image.py`), rendered as animated 1-bit / 2-color previews.
- **Playback & Scrubber**: Play/pause animations, scrub through frames with a frame slider, step frame-by-frame (`⏮` / `⏭`), and peek at original color art.
- **Compare Originals**: Side-by-side comparison mode to inspect dithering, edge smear, and thresholding against the original art.
- **1-Click Config Generation**:
  - Easter Egg definition for `eggs.json` (auto-detects non-default parameters)
  - Python call for `egg_app.load_gif()` or `dis_image.process_image()`
  - Display config snippet for `config.json`
- **File Upload**: Drop or upload images and GIFs directly in the browser UI.

### How to use

1. Run `npm start` in the `tools/dis_image_tester` directory.
2. Open `http://localhost:5173` in your browser.
3. Drop or add additional images to `tools/dis_image_tester/albumcovers` and GIFs to `tools/dis_image_tester/gifs` (or use the "+ Upload File" button in the UI).
4. Tune contrast, sharpen, dither algorithms (Floyd-Steinberg vs Atkinson), black floor, boldness, and copy the config directly into your project.
