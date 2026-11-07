"""Build the standalone, shareable DXF Explorer: dist/DXF Explorer.app and dist/DXF-Explorer-<version>.dmg.

    .venv/bin/python build_dist.py              # build app + DMG
    .venv/bin/python build_dist.py --no-dmg     # app only

Unlike make_app.py (a launcher that runs this project's code), this bundles Python, Qt and ezdxf
into the app with PyInstaller, so it runs on any Mac with the same CPU type (this build machine's).
The app is ad-hoc signed, not notarized: on first open macOS asks the user to allow it
(see "Read Me First.txt" in the DMG). With a Developer ID certificate, pass --sign "Developer ID
Application: …" and then notarize the DMG with `xcrun notarytool submit … --wait` and staple it.
"""
import argparse
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from importlib import metadata
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "DXF Explorer"
BUNDLE_ID = "com.fredfowler.dxf-explorer"
BUILD, DIST = HERE / "build", HERE / "dist"

# Bundled third-party packages and what they're licensed under (the full texts are copied in below).
PACKAGES = ["ezdxf", "PySide6_Essentials", "shiboken6", "numpy", "pillow", "pyparsing", "fonttools", "typing_extensions"]
# Big pieces of PySide6 / the venv the viewer never uses; leaving them out keeps the app small.
EXCLUDES = ["matplotlib", "tkinter", "contourpy", "kiwisolver", "dateutil", "Foundation", "AppKit", "objc",
            "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
            "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
            "PySide6.Qt3DCore", "PySide6.QtMultimedia", "PySide6.QtNetwork", "PySide6.QtCharts", "PySide6.QtDataVisualization",
            "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtBluetooth", "PySide6.QtPositioning", "PySide6.QtSensors"]


def version() -> str:
    return re.search(r'^VERSION = "([^"]+)"', (HERE / "explorer.py").read_text(), re.M).group(1)


def third_party_notices(out: Path):
    """One text file: what's inside the app, each component's licence, and the full licence texts."""
    parts = [f"{NAME} — third-party software notices\n",
             f"{NAME} is © 2026 Fred Fowler (see LICENSE). It is built from the open-source components\n"
             "below, each used under its own licence.\n",
             "Qt and Qt for Python (PySide6, shiboken6) are used under the GNU Lesser General Public License\n"
             "version 3 (LGPLv3), which builds on the GNU GPL version 3; both texts are at the end of this file.\n"
             "They are included as separate, unmodified shared libraries inside the app\n"
             f"({NAME}.app/Contents/Frameworks), so you can replace them with your own builds of the same\n"
             "versions. Their source code is available from https://download.qt.io/official_releases/ and\n"
             "https://download.qt.io/official_releases/QtForPython/ ; the author will also send it on request.\n",
             f"Python {platform.python_version()} is used under the PSF License Agreement.\n",
             "=" * 78]
    for pkg in PACKAGES:
        dist = metadata.distribution(pkg)
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or "see below"
        parts.append(f"\n{dist.metadata['Name']} {dist.version}  —  {lic.splitlines()[0]}\n"
                     f"{dist.metadata.get('Home-page') or ''}".rstrip())
        for f in dist.files or []:
            if "licenses/" in str(f) and Path(f.locate()).is_file():
                parts += [f"\n--- {Path(f).name} ({dist.metadata['Name']}) ---\n", Path(f.locate()).read_text(errors="replace")]
    for name in ("Python.txt", "LGPL-3.0.txt", "GPL-3.0.txt"):
        parts += ["\n" + "=" * 78, f"\n--- {name[:-4]} ---\n", (HERE / "licenses" / name).read_text()]
    out.write_text("\n".join(parts))


def build_app(sign: str) -> Path:
    sys.path.insert(0, str(HERE))
    import make_app                                   # reuse its icon drawing
    shutil.rmtree(BUILD, ignore_errors=True); BUILD.mkdir()
    make_app.draw_icon(HERE / "icon.png")
    make_app.make_icns(HERE / "icon.png", BUILD / "AppIcon.icns")
    third_party_notices(BUILD / "THIRD_PARTY_LICENSES.txt")
    shutil.copy(HERE / "LICENSE", BUILD / "LICENSE.txt")

    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--windowed", "--name", NAME,
           "--icon", str(BUILD / "AppIcon.icns"), "--osx-bundle-identifier", BUNDLE_ID,
           "--distpath", str(DIST), "--workpath", str(BUILD / "pyi"), "--specpath", str(BUILD),
           "--add-data", f"{HERE / 'icon.png'}:.",
           "--add-data", f"{BUILD / 'THIRD_PARTY_LICENSES.txt'}:.",
           "--add-data", f"{BUILD / 'LICENSE.txt'}:."]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    subprocess.run(cmd + [str(HERE / "explorer.py")], check=True)

    app = DIST / f"{NAME}.app"
    shutil.rmtree(DIST / NAME, ignore_errors=True)   # PyInstaller's loose folder; only the .app is shipped
    plist_path = app / "Contents/Info.plist"
    plist = plistlib.loads(plist_path.read_bytes())
    v = version()
    plist.update({
        "CFBundleDisplayName": NAME, "CFBundleShortVersionString": v, "CFBundleVersion": v,
        "NSHumanReadableCopyright": "© 2026 Fred Fowler. Free to use and share.",
        "LSMinimumSystemVersion": "12.0", "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.graphics-design",
        "CFBundleDocumentTypes": [
            {"CFBundleTypeName": "Folder", "CFBundleTypeRole": "Viewer", "LSItemContentTypes": ["public.folder"]},
            {"CFBundleTypeName": "Drawing", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
             "CFBundleTypeExtensions": ["dxf", "DXF", "dwg", "DWG"]},
        ],
    })
    plist_path.write_bytes(plistlib.dumps(plist))
    # Editing Info.plist invalidates PyInstaller's signature, so sign the whole bundle again.
    opts = ["--options", "runtime", "--timestamp"] if sign != "-" else []
    subprocess.run(["codesign", "--force", "--deep", "--sign", sign, *opts, str(app)], check=True)
    subprocess.run(["codesign", "--verify", "--deep", "--strict", str(app)], check=True)
    return app


READ_ME = """DXF Explorer {v}
================

Install: drag "DXF Explorer" onto the Applications folder next to it.

Opening it the first time
-------------------------
DXF Explorer is free software from an independent developer and isn't notarized by Apple,
so the first time you open it macOS says it "can't be opened" or "can't verify" it.
To allow it (you only do this once):

  macOS 15 Sequoia and later:
    1. Double-click DXF Explorer and click "Done" (or "OK") on the warning.
    2. Open System Settings ▸ Privacy & Security and scroll down.
    3. Next to "DXF Explorer was blocked…", click "Open Anyway", then confirm.

  macOS 12–14:
    Right-click (or Control-click) DXF Explorer in Applications, choose "Open",
    then click "Open" in the dialog.

Using it
--------
File ▸ Open Folder… (⌘O) and pick a folder of DXF drawings, or drop a folder on the app's
icon. Your drawings are only read, never changed. ⌘D switches light/dark background,
⌘I hides the layers & info panel, double-click the drawing to fit it to the window.

DWG files: DXF Explorer opens DXF directly. For DWG, save the drawing as DXF from your CAD
program first.

Requires a Mac with Apple silicon (M1 or later) running macOS 12 or later.

Licence: free to use and share; see LICENSE.txt. Third-party notices: Help ▸ Licenses.
"""


def build_dmg(app: Path) -> Path:
    v = version()
    dmg = DIST / f"DXF-Explorer-{v}.dmg"
    dmg.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as td:
        stage = Path(td) / NAME
        stage.mkdir()
        subprocess.run(["ditto", str(app), str(stage / app.name)], check=True)   # ditto keeps signatures intact
        (stage / "Applications").symlink_to("/Applications")
        (stage / "Read Me First.txt").write_text(READ_ME.format(v=v))
        shutil.copy(HERE / "LICENSE", stage / "LICENSE.txt")
        subprocess.run(["hdiutil", "create", "-volname", f"{NAME} {v}", "-srcfolder", str(stage),
                        "-fs", "HFS+", "-format", "UDZO", "-imagekey", "zlib-level=9", "-ov", str(dmg)], check=True)
    return dmg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-dmg", action="store_true")
    ap.add_argument("--sign", default="-", help='codesign identity; "-" (default) = ad-hoc')
    a = ap.parse_args()
    app = build_app(a.sign)
    size = subprocess.run(["du", "-sh", str(app)], capture_output=True, text=True).stdout.split()[0]
    print(f"built {app}  ({size})")
    if not a.no_dmg:
        dmg = build_dmg(app)
        print(f"built {dmg}  ({dmg.stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
