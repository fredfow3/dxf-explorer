# DXF Explorer

Look inside a folder of DXF/DWG drawings with [ezdxf](https://ezdxf.readthedocs.io): what each file
contains, what made it, and a clean picture of it. The source folder is only read, never changed.

## The app

Double-click **DXF Explorer** in `~/Applications` (or Launchpad/Spotlight). It reopens the last folder;
**File ▸ Open Folder… (⌘O)** picks another, or drop a folder on its Dock icon.

- **Left:** every DXF/DWG in the folder and its sub-folders. Type in the filter box to narrow it;
  ↑/↓ moves through files; right-click for Reveal in Finder / Open in Default App / Copy Path.
- **Middle:** the drawing. Two-finger scroll moves around, pinch zooms (or ⌘-scroll, or a mouse wheel),
  drag pans, double-click or ⌘0 fits it back to the window. ⌘= / ⌘- zoom. The status bar shows the
  cursor's drawing coordinates and the zoom level.
- **Right:** layer checkboxes (double-click a layer to show only that one; All / None buttons), and the
  info panel: format, units, size, what made it, entity counts, blocks, text, audit, identical copies.
- **⌘D** switches between a light and a dark background. Lines that would vanish (black on dark,
  white on light) are flipped so they stay visible; the info panel says when that happened.
- **⌘I** hides/shows the right-hand panel.

Run it from Terminal instead with `.venv/bin/python explorer.py [FOLDER]`. Problems are logged to
`~/Library/Logs/DXF Explorer.log`. If you move this project folder, rebuild the app with
`.venv/bin/python make_app.py`.

## The web gallery (batch)

```sh
cd ~/projects/dxf-explorer
.venv/bin/python inventory.py ~/Dropbox/"Clip Art"     # scan + render everything  (~1–2 min for 164 files)
open out/index.html                                     # browse the results
```

- `--only TEXT` scans just the files whose path contains TEXT; `--out DIR` writes somewhere else.
- `.venv/bin/python gallery.py` rebuilds `out/index.html` from `out/data.json` without rescanning.
- Look at a single drawing interactively (pan, zoom, layers):

  ```sh
  .venv/bin/ezdxf view ~/Dropbox/"Clip Art"/compass.dxf
  ```

## What it records per drawing

Format and version, units, drawing size, file size, a guess at the program that made it (from
`999` comments and app IDs), entity counts by type, layers (colour, on/off, how many entities),
blocks used, any real text (TEXT/MTEXT — lettering that was converted to outlines doesn't count),
ezdxf's audit of the file's structure, identical copies elsewhere in the folder, and a PNG render.

## Notes

- **DWG**: ezdxf can't read DWG, so `inventory.py` converts each one to DXF with CADCraft's CLI
  (`~/Artcraft/CraftingApps/CADCraft/cli/cadcraft-cli`) into `out/dwg-cache/` first.
- **Audit "fixed on load"**: most of these are harmless internal bookkeeping (dictionary owner
  handles, leftover AutoCAD proxy objects). The geometry is not changed.
- Renders keep the drawing's colours on white; AutoCAD "white" (colour 7) draws as black.
- Files: `explorer.py` (the app), `dxfcore.py` (shared loading/info code), `inventory.py` + `gallery.py`
  (batch gallery), `make_app.py` (builds the .app and icon).
- Folders: `.venv/` (Python 3.12 with ezdxf, matplotlib, PySide6, pyobjc), `out/` (generated; safe to
  delete). DWG conversions are cached in `~/Library/Caches/DXF Explorer`.
