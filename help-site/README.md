# RNS-E Hudiy field guide

Static React documentation for the current working-tree features. All routes use URL hashes, and Vite emits relative asset URLs, so the same build works at a Netlify domain or a GitHub Pages repository subpath. No application backend is required.

## Run and build

From `help-site`, with Node 22 or newer:

```sh
npm ci
npm run dev
npm run check
npm run build
npm run preview
```

Publish **`help-site/dist/`**, not the source folder. `build` copies the current standalone config, bitmap, AUDSCII and theme helpers from `../tools/` before bundling the guide. It must run from this repository checkout. Those generated helper copies and `dist/` are ignored; canonical changes belong in `tools/`.

The config launcher defaults to `DSparks156x/RNS-E-Hudiy` → `testing`. It passes `repo`, `branch` and `load=1` to the local standalone helper, which fetches that branch's latest public `config.json`. Related-setting links use that same selection and add `search=<setting path>`; the helper retains the filter after loading. The full settings reference lives in the helper. Selecting another source does not replace this guide's prose. Private repositories need a locally imported config; no token is collected or stored.

## Netlify

Import this repository and select `help-site` as the base directory. The included `netlify.toml` sets the build command to `npm run build` and publish directory to `dist` relative to that base. Netlify installs the locked dependencies automatically. Alternatively, build locally and upload the contents of `dist`.

See [Netlify build settings](https://docs.netlify.com/build/configure-builds/overview/) and [configuration discovery](https://docs.netlify.com/build/configure-builds/file-based-configuration/) for a repository with several projects.

## GitHub Pages

The repository includes `.github/workflows/help-site-pages.yml`, triggered manually. After these files are committed and pushed:

1. In repository **Settings → Pages**, choose **GitHub Actions** as the source.
2. In **Actions**, choose **Publish help site**, select the branch containing the guide, and run it.
3. Open the URL reported by the deployment job.

The workflow builds only this guide, copies its browser helpers, and publishes `help-site/dist`. It does not deploy the Pi services. Hash routes need no rewrite/404 workaround. See [GitHub's custom Pages workflow guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Demonstration assets

DIS PNGs/GIFs use the production app render commands, real navigation/readings assets, and captured native font masks. Values and phone/media metadata are synthetic. Rebuild from repository root with:

```sh
python help-site/scripts/render_dis.py
```

Requires Pillow and NumPy. `public/media/provenance.json` records sample inputs, render details and source hashes. This renders the 128×96 center area at 4× nearest-neighbor scale; it is not footage of physical hardware.

`python help-site/scripts/render_wheel.py` renders the wheel-control states for Readings and Phone through the production views. `wheel-provenance.json` records the sources and synthetic inputs. The interactive guide switches between those images and highlights the actual wheel glyph. The RNS-E faceplate is rendered in HTML/CSS and takes its key mappings from the bundled `config.json`.

DataView images use the actual Engine, Transmission, AWD, Data & Logs and Diagnostics React components, CSS, and DataStore with synthetic values and a sample Hudiy palette. The full canonical catalog comes from the production API. The capture-only fixture has its own Vite config, in-memory APIs and socket replacement: it makes no controller connection. See `scripts/CAPTURE-DATAVIEW.md` for scenes and commands. Capture at 800×480 into `public/media`; Engine animation frames go under `.capture-frames/`. After `python scripts/assemble-dataview.py`, run `python scripts/update-dataview-provenance.py` to include all current scenes. The capture fixture is excluded from the production entry.

The file portal captures mount the production component with synthetic file catalogs and in-memory upload APIs. See `scripts/CAPTURE-FILE-PORTAL.md`. Capture the recordings, debug and upload scenes at 1280×720, then run `python help-site/scripts/update-file-portal-provenance.py` from the repository root. The optional PIN is off in the guide screenshots, matching the default config. Browser tests cover desktop and phone layouts; capture uploads do not validate or write real firmware.

## Maintaining content

Edit `src/guide.jsx` for topics, groups and feature prose; `src/ui.jsx` holds shared content components and the config launcher. `src/main.jsx` handles routing, navigation and search; `src/style.css` holds shared visual tokens. The navigation separates cluster features, vehicle data, controls and setup. Feature pages put demonstrations next to their explanation, followed by concrete workflows, relevant settings and related tasks. Review runtime code when changing behavior claims. Current README sections have some older descriptions; the guide was checked against the current implementations by separate feature and config review agents.

The guide distinguishes native/legacy displays, named/raw logging, source quality, disabled Openpilot transport, and offline-tested controller workflows. Do not promote sample renders into hardware-validation claims. Rebuild the media after relevant rendering changes.
