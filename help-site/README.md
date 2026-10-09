# RNS-E Hudiy field guide

Live guide: [rns-e-hudiy.netlify.app](https://rns-e-hudiy.netlify.app/). [Netlify deploy dashboard](https://app.netlify.com/projects/rns-e-hudiy/deploys).

Production follows `codex/help-site`; branch deploys are disabled. Commits changing `help-site/` build and publish automatically. Runtime work on `testing` stays independent.

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

Publish **`help-site/dist/`**, not the source folder. The build uses versioned copies of the config, bitmap, AUDSCII and theme helpers in `tool-snapshots/` and faceplate mappings in `data/control-defaults.json`. It needs only this folder. Generated `public/tools/` copies and `dist/` are ignored.

When changing a canonical helper or button defaults in the runtime checkout, run `npm run sync-tools` from `help-site`, review the snapshot changes and carry them to the site branch. The refresh command requires the runtime repository; ordinary builds do not. It saves only the faceplate mappings, not a copy of your installed config.

The config launcher defaults to `DSparks156x/RNS-E-Hudiy` → `testing`. It passes `repo`, `branch` and `load=1` to the local standalone helper, which fetches that branch's latest public `config.json`. Related-setting links use that same selection and add `search=<setting path>`; the helper retains the filter after loading. The full settings reference lives in the helper. Selecting another source does not replace this guide's prose. Private repositories need a locally imported config; no token is collected or stored.

## Netlify

Import `DSparks156x/RNS-E-Hudiy`, select **`codex/help-site`** as the production branch and set **`help-site`** as the base directory. The included `netlify.toml` runs `npm run check && npm run build`, publishes `dist` relative to that base and pins Node 22. Netlify installs the locked dependencies automatically. Alternatively, build locally and upload the contents of `dist`.

The dedicated branch contains the site without the Pi runtime. Runtime commits on `testing` do not deploy it. The ignore command additionally compares `help-site/` between Netlify's last successful commit and the incoming commit, skipping changes outside the folder. First builds and unavailable history build normally. Netlify build hooks and manually forced builds can bypass this check. Automatic builds should remain enabled for the production branch; branch deploys can be disabled if you only want production.

See [Netlify's ignore command](https://docs.netlify.com/build/configure-builds/ignore-builds/) and [configuration discovery](https://docs.netlify.com/build/configure-builds/file-based-configuration/). Account connection and granting access to the repository happen in Netlify; no credentials belong in this folder.

## GitHub Pages

The repository includes `.github/workflows/help-site-pages.yml`, triggered manually. After these files are committed and pushed:

1. In repository **Settings → Pages**, choose **GitHub Actions** as the source.
2. In **Actions**, choose **Publish help site**, select the branch containing the guide, and run it.
3. Open the URL reported by the deployment job.

The workflow builds only this guide, copies its browser helpers, and publishes `help-site/dist`. It does not deploy the Pi services. Hash routes need no rewrite/404 workaround. See [GitHub's custom Pages workflow guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Demonstration assets

DIS PNGs/GIFs use the production app render commands, real navigation/readings assets, and captured native font masks. Values and phone/media metadata are synthetic. Rebuild from the runtime repository checkout (the rendering scripts import its production apps), then carry the generated media to the site branch:

```sh
python help-site/scripts/render_dis.py
python help-site/scripts/render_navigation_showcase.py
```

Requires Pillow and NumPy. `public/media/provenance.json` records sample inputs, render details and source hashes. This renders the 128×96 center area at 4× nearest-neighbor scale; it is not footage of physical hardware.

`navigation-showcase.json` records the matched stock/bitmap maneuver inputs and source hashes. Its 26 examples include distant straight guidance, approaching turns, ramps, forks, roundabout exits and bitmap fallback for maneuvers without a reviewed stock mapping. GIFs and stills are black/white production renders, with separate 500 m switching and 300 m bar ranges explained in the guide.

`python help-site/scripts/render_wheel.py` renders the wheel-control states for Readings and Phone through the production views. `wheel-provenance.json` records the sources and synthetic inputs. The interactive guide switches between those images and highlights the actual wheel glyph. The RNS-E faceplate is rendered in HTML/CSS using `data/control-defaults.json`.

DataView images use the actual Engine, Transmission, AWD, Data & Logs and Diagnostics React components, CSS, and DataStore with synthetic values and a sample Hudiy palette. The full canonical catalog comes from the production API. The capture-only fixture has its own Vite config, in-memory APIs and socket replacement: it makes no controller connection. See `scripts/CAPTURE-DATAVIEW.md` for scenes and commands. Capture at 800×480 into `public/media`; Engine animation frames go under `.capture-frames/`. After `python scripts/assemble-dataview.py`, run `python scripts/update-dataview-provenance.py` to include all current scenes. The capture fixture is excluded from the production entry.

The file portal captures mount the production component with synthetic file catalogs and in-memory upload APIs. See `scripts/CAPTURE-FILE-PORTAL.md`. Capture the recordings, debug and upload scenes at 1280×720, then run `python help-site/scripts/update-file-portal-provenance.py` from the repository root. The optional PIN is off in the guide screenshots, matching the default config. Browser tests cover desktop and phone layouts; capture uploads do not validate or write real firmware.

## Maintaining content

`src/HowToGuides.jsx` contains applying config/updating, building DIS pages, recording/interpreting a run and symptom-based troubleshooting. `src/NavigationShowcase.jsx` and `src/navigation-examples.json` connect the animated comparisons and inspectable stills.

Edit `src/guide.jsx` for topics, groups and feature prose; `src/ui.jsx` holds shared content components and the config launcher. `src/main.jsx` handles routing, navigation and search; `src/style.css` holds shared visual tokens. The navigation separates cluster features, vehicle data, controls and setup. Feature pages put demonstrations next to their explanation, followed by concrete workflows, relevant settings and related tasks. Review runtime code when changing behavior claims. Current README sections have some older descriptions; the guide was checked against the current implementations by separate feature and config review agents.

The guide distinguishes native/legacy displays, named/raw logging, source quality, disabled Openpilot transport, and offline-tested controller workflows. Do not promote sample renders into hardware-validation claims. Rebuild the media after relevant rendering changes.
