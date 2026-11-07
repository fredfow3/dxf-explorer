"""Build "DXF Explorer.app" — a double-clickable launcher for explorer.py — and its icon.

    .venv/bin/python make_app.py                      # -> ~/Applications/DXF Explorer.app
    .venv/bin/python make_app.py --dest /Applications

The app runs this project's code and Python environment, so keep the project folder where it is
(or re-run this script after moving it). Drop a folder on the app's icon to open it.
"""
import argparse
import os
import plistlib
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAME = "DXF Explorer"


def draw_icon(png: Path, size=1024):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6 import QtCore as qc, QtGui as qg
    app = qg.QGuiApplication.instance() or qg.QGuiApplication([])
    img = qg.QImage(size, size, qg.QImage.Format_ARGB32); img.fill(qc.Qt.transparent)
    p = qg.QPainter(img); p.setRenderHint(qg.QPainter.Antialiasing)
    s = size / 1024
    # macOS-style rounded square with a blueprint gradient
    g = qg.QLinearGradient(0, 0, 0, size); g.setColorAt(0, qg.QColor("#1f6f8b")); g.setColorAt(1, qg.QColor("#0d3b4f"))
    p.setPen(qc.Qt.NoPen); p.setBrush(g); p.drawRoundedRect(qc.QRectF(100 * s, 100 * s, 824 * s, 824 * s), 185 * s, 185 * s)
    # faint grid
    p.setPen(qg.QPen(qg.QColor(255, 255, 255, 28), 3 * s))
    for i in range(1, 8):
        v = (100 + i * 103) * s
        p.drawLine(qc.QPointF(v, 130 * s), qc.QPointF(v, 894 * s)); p.drawLine(qc.QPointF(130 * s, v), qc.QPointF(894 * s, v))
    # a drawn gear outline + compass star, like the clip art
    import math
    c = qc.QPointF(512 * s, 470 * s)
    path = qg.QPainterPath()
    teeth, r1, r2 = 16, 250 * s, 290 * s
    for i in range(teeth * 4 + 1):
        a = i / (teeth * 4) * 2 * math.pi
        r = r2 if (i % 4) in (1, 2) else r1
        pt = qc.QPointF(c.x() + r * math.cos(a), c.y() + r * math.sin(a))
        path.moveTo(pt) if i == 0 else path.lineTo(pt)
    pen = qg.QPen(qg.QColor("#ffffff"), 16 * s); pen.setJoinStyle(qc.Qt.RoundJoin)
    p.setPen(pen); p.setBrush(qc.Qt.NoBrush); p.drawPath(path)
    star = qg.QPolygonF()
    for i in range(16):
        a = i / 16 * 2 * math.pi - math.pi / 2
        r = (190 if i % 4 == 0 else 120 if i % 2 == 0 else 45) * s
        star.append(qc.QPointF(c.x() + r * math.cos(a), c.y() + r * math.sin(a)))
    p.setBrush(qg.QColor(255, 255, 255, 60)); p.drawPolygon(star)
    # label
    f = qg.QFont("Helvetica Neue", int(118 * s)); f.setBold(True); f.setLetterSpacing(qg.QFont.AbsoluteSpacing, 10 * s)
    p.setFont(f); p.setPen(qg.QColor("#ffffff"))
    p.drawText(qc.QRectF(100 * s, 770 * s, 824 * s, 140 * s), qc.Qt.AlignCenter, "DXF")
    p.end()
    img.save(str(png))


def make_icns(png: Path, icns: Path):
    from PySide6 import QtCore as qc, QtGui as qg
    with tempfile.TemporaryDirectory() as td:
        iconset = Path(td) / "icon.iconset"; iconset.mkdir()
        src = qg.QImage(str(png))
        for base in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = base * scale
                name = f"icon_{base}x{base}{'@2x' if scale == 2 else ''}.png"
                src.scaled(px, px, qc.Qt.IgnoreAspectRatio, qc.Qt.SmoothTransformation).save(str(iconset / name))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(icns)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=str(Path.home() / "Applications"))
    a = ap.parse_args()
    dest = Path(a.dest).expanduser(); dest.mkdir(parents=True, exist_ok=True)
    app = dest / f"{NAME}.app"

    png = HERE / "icon.png"
    draw_icon(png)
    if app.exists():
        shutil.rmtree(app)
    (app / "Contents/MacOS").mkdir(parents=True)
    (app / "Contents/Resources").mkdir()
    make_icns(png, app / "Contents/Resources/AppIcon.icns")

    launcher = app / "Contents/MacOS" / NAME
    launcher.write_text(f"""#!/bin/bash
# Launcher for DXF Explorer: runs explorer.py from the project with its own Python.
PROJECT="{HERE}"
if [ ! -x "$PROJECT/.venv/bin/python" ]; then
  osascript -e 'display alert "DXF Explorer" message "The project folder {HERE} is missing. If you moved it, run make_app.py again from its new place."'
  exit 1
fi
exec "$PROJECT/.venv/bin/python" "$PROJECT/explorer.py" "$@" >> "$HOME/Library/Logs/DXF Explorer.log" 2>&1
""")
    launcher.chmod(0o755)

    plist = {
        "CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleExecutable": NAME,
        "CFBundleIdentifier": "local.dxf-explorer", "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0", "CFBundleVersion": "1", "CFBundleIconFile": "AppIcon",
        "LSMinimumSystemVersion": "12.0", "NSHighResolutionCapable": True,
        "CFBundleDocumentTypes": [
            {"CFBundleTypeName": "Folder", "CFBundleTypeRole": "Viewer", "LSItemContentTypes": ["public.folder"]},
            {"CFBundleTypeName": "Drawing", "CFBundleTypeRole": "Viewer", "LSHandlerRank": "Alternate",
             "CFBundleTypeExtensions": ["dxf", "DXF", "dwg", "DWG"]},
        ],
    }
    with open(app / "Contents/Info.plist", "wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["touch", str(app)])
    subprocess.run(["/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister",
                    "-f", str(app)], check=False)
    print(f"built {app}")


if __name__ == "__main__":
    main()
