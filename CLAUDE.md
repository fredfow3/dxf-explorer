# DXF Explorer

A Mac app (PySide6 + ezdxf) for browsing a folder of DXF/DWG drawings, plus a batch web gallery.
User-facing docs are in `README.md`. Source files are only ever read, never written.

## Layout
- `explorer.py` — the app: file tree (left), `DrawingView` canvas (middle), layers + info panel (right).
- `dxfcore.py` — shared: `load()` (DWG→DXF via CADCraft CLI, normal reader then audit, tolerant
  `recover` fallback), `describe()` (info dict; also adds undefined layers and flattens tilted 2D
  entities in memory), `Contrast` (swaps near-white/near-black true colours per background).
- `inventory.py` + `gallery.py` — batch scan → `out/data.json`, `out/png/`, `out/index.html`.
- `make_app.py` — builds `~/Applications/DXF Explorer.app` (bash launcher + icon). Rebuild if the
  project folder moves. App log: `~/Library/Logs/DXF Explorer.log`. Settings: QSettings
  `com.dxf-explorer.DXF Explorer` (folder, file, dark, geometry).

## Run / test
- Python env: `.venv/bin/python` (3.12; ezdxf 1.4.5, PySide6, matplotlib, pyobjc-framework-Cocoa).
- App: `.venv/bin/python explorer.py [FOLDER]`; restart the installed app after code changes
  (`pkill -f dxf-explorer/explorer.py; open ~/Applications/"DXF Explorer.app"`).
- Headless UI test: `QT_QPA_PLATFORM=offscreen`, create `explorer.Explorer`, drive it, `w.grab()`.
  Wait for loads by checking that `w.status_label` no longer starts with "Loading".
- Test data: `~/Dropbox/Clip Art` (164 drawings incl. 5 DWG). Big/slow ones: `Angry Birds Star Wars
  Aztec Calendar.dxf` (23 MB), `screen.dxf`, `groovy.dxf` (656 layers). Edge cases: `Scrollsaw Clock/big_gear.dxf`
  (undefined layer), `Middle East - Islamic/Setvectorpanels1.*.dxf` (pure-white lines),
  `Scrollwork/Pickguard Graphics/strat_pg_hb.dxf` (tilted planes), `herbs_legs.dxf` (real 3D).

## Gotchas (learned the hard way)
- Keep a reference to every `QRunnable` job until its signal fires (`self.jobs`, `setAutoDelete(False)`);
  otherwise PySide can garbage-collect the signal object and the result is silently lost.
- ezdxf's Qt backend ignores `Configuration.min_lineweight`; minimum line width is enforced in
  `SolidLineBackend._get_pen` (cosmetic pens, screen points).
- ezdxf won't draw entities on layers missing from the layer table — `describe()` adds them.
- The process runs as `org.python.python` (Homebrew framework Python); the menu-bar name is patched
  to "DXF Explorer" via pyobjc in `main()`.
