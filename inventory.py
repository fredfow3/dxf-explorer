"""Inventory a folder of DXF/DWG drawings with ezdxf and build a browsable web gallery.

For every drawing: version, units, size, the program that made it, layers, entity counts,
blocks, any text it contains, an audit of problems, and a PNG render on a white background.

    .venv/bin/python inventory.py "~/Dropbox/Clip Art"            # -> out/
    .venv/bin/python inventory.py FOLDER --out other-out --jobs 4
    .venv/bin/python inventory.py FOLDER --only "Celtic"           # filename filter

Writes out/data.json and out/png/<id>.png, then builds out/index.html.
The source folder is only read, never changed. (For browsing interactively, use explorer.py.)
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import dxfcore

HERE = Path(__file__).resolve().parent


def analyse(src: str, root: str, cache: str, png_dir: str, size_px: int) -> dict:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    srcp = Path(src)
    rel = str(srcp.relative_to(root))
    base = {"id": dxfcore.file_id(rel), "path": rel, "name": srcp.name,
            "folder": str(Path(rel).parent) if str(Path(rel).parent) != "." else ""}
    t0 = time.time()
    try:
        sha1 = hashlib.sha1(srcp.read_bytes()).hexdigest()
        doc, info = dxfcore.load(srcp, Path(cache))
        rec = {**base, **dxfcore.describe(doc, info), "sha1": sha1}
        rec["whiteLines"] = dxfcore.Contrast(doc).apply(dark=False)   # white lines would vanish on white

        t1 = time.time()
        fig = plt.figure()
        ax = fig.add_axes([0, 0, 1, 1])
        cfg = Configuration(background_policy=BackgroundPolicy.WHITE, color_policy=ColorPolicy.COLOR)
        Frontend(RenderContext(doc), MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=True)
        w, h = fig.get_size_inches()          # finalize reshapes the figure to the drawing; longest side -> size_px
        fig.savefig(Path(png_dir) / f"{rec['id']}.png", dpi=size_px / max(w, h, 0.01), facecolor="white")
        plt.close(fig)
        rec["renderSeconds"] = round(time.time() - t1, 2)
        rec["png"] = f"png/{rec['id']}.png"
        rec["ok"] = True
    except Exception as ex:  # keep going; record why this file failed
        rec = {**base, "bytes": srcp.stat().st_size, "format": srcp.suffix.lower().lstrip("."),
               "ok": False, "error": f"{type(ex).__name__}: {ex}"[:400]}
    rec["seconds"] = round(time.time() - t0, 2)
    return rec


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder")
    ap.add_argument("--out", default=str(HERE / "out"))
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument("--size", type=int, default=1600, help="longest side of each render, in pixels")
    ap.add_argument("--only", default="", help="only files whose path contains this text")
    a = ap.parse_args()

    root = Path(os.path.expanduser(a.folder)).resolve()
    out = Path(a.out).resolve()
    (out / "png").mkdir(parents=True, exist_ok=True)
    files = [p for p in dxfcore.find_drawings(root) if a.only.lower() in str(p.relative_to(root)).lower()]
    print(f"{len(files)} drawings in {root}  ->  {out}  ({a.jobs} at a time)")

    results = []
    with ProcessPoolExecutor(max_workers=a.jobs) as pool:
        futs = [pool.submit(analyse, str(f), str(root), str(out / "dwg-cache"), str(out / "png"), a.size)
                for f in files]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            results.append(r)
            flag = "ok " if r["ok"] else "ERR"
            print(f"[{i:3}/{len(files)}] {flag} {r['seconds']:6.1f}s  {r['path']}"
                  + ("" if r["ok"] else f"  — {r['error']}"), flush=True)
    results.sort(key=lambda r: r["path"].lower())
    by_hash = collections.defaultdict(list)
    for r in results:
        if r.get("sha1"):
            by_hash[r["sha1"]].append(r["path"])
    for r in results:
        r["duplicates"] = [p for p in by_hash.get(r.get("sha1"), []) if p != r["path"]]
    (out / "data.json").write_text(json.dumps({"root": str(root), "generated": time.strftime("%Y-%m-%d %H:%M"),
                                               "drawings": results}, indent=1))
    subprocess.run([sys.executable, str(HERE / "gallery.py"), str(out)], check=False)
    bad = [r for r in results if not r["ok"]]
    print(f"done: {len(results) - len(bad)} ok, {len(bad)} failed. Open {out / 'index.html'}")


if __name__ == "__main__":
    main()
