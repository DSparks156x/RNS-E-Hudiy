# File portal capture fixture

The fixture renders the production `FilePortal` and `FilesTab` components, including the normal DataView fonts and Hudiy color roles. File names, timestamps, content and palettes are sample data. It does not connect to a device, read actual logs or flash any controller.

Use the existing capture server from `help-site`:

```sh
npm run dev -- --config scripts/capture-vite.config.js --port 5190
```

Open `/scripts/capture-file-portal.html?scene=recordings`. Scenes are `recordings`, `debug` and `upload`. Add `&theme=light` to check the light Hudiy palette or `&pin=1` to test the optional upload PIN. Guide captures use 1280 × 720 with the PIN off, matching the default config. Check a narrow phone viewport as well.

The fixture injects an in-memory catalog and upload function through the production component's props. Search, sorting, group selection and validation use production code. Downloads use `data:` URLs; collection ZIPs are empty sample archives. Uploads update only the fixture's in-memory catalog.

Production entry `hudiy_dataview/src/portal.tsx` supplies no fixture props. It uses `/api/files`, the existing upload API, native `window.hudiy` theme callbacks and the read-only `/api/files/theme` cache for standalone browsers.
