"""Shared drawing code for DXF Explorer: load DXF/DWG, describe what's inside, prepare for display.

Used by explorer.py (the app) and inventory.py (the batch gallery). Nothing here writes to the
source files; every adjustment is made to the in-memory document only.
"""
from __future__ import annotations

import collections
import hashlib
import subprocess
from pathlib import Path

CADCRAFT = Path.home() / "Artcraft/CraftingApps/CADCraft/cli/cadcraft-cli"
DRAWING_SUFFIXES = (".dxf", ".dwg")

UNITS = {0: "unitless", 1: "inches", 2: "feet", 3: "miles", 4: "mm", 5: "cm", 6: "m",
         7: "km", 8: "microinches", 9: "mils", 10: "yards", 11: "ångströms",
         12: "nanometres", 13: "microns", 14: "decimetres", 15: "decametres",
         16: "hectometres", 17: "gigametres", 18: "AU", 19: "light years", 20: "parsecs"}
VERSIONS = {"AC1009": "R12", "AC1012": "R13", "AC1014": "R14", "AC1015": "2000",
            "AC1018": "2004", "AC1021": "2007", "AC1024": "2010", "AC1027": "2013",
            "AC1032": "2018"}
TEXT_TYPES = {"TEXT", "MTEXT", "ATTRIB", "ATTDEF"}
FLAT_TYPES = {"POLYLINE", "LWPOLYLINE", "CIRCLE", "ARC", "TEXT", "MTEXT", "INSERT", "HATCH", "SOLID", "TRACE"}

CREATORS = [  # substring in creator hints / app ids -> friendly name
    ("dxfrw", "LibreCAD"), ("librecad", "LibreCAD"), ("dxflib", "dxflib (QCAD or a converter)"),
    ("inkscape", "Inkscape"), ("vcarve", "Vectric"), ("vectric", "Vectric"), ("aspire", "Vectric"),
    ("corel", "CorelDRAW"), ("illustrator", "Illustrator"), ("rhino", "Rhino"), ("fusion", "Fusion 360"),
    ("solidworks", "SolidWorks"), ("sketchup", "SketchUp"), ("lightburn", "LightBurn"),
    ("ezdxf", "ezdxf"), ("draftsight", "DraftSight"), ("kompas", "KOMPAS-3D"),
    ("gear template generator", "Gear template generator"), ("bezarc", "BEZARC"),
    ("oda", "an ODA-based program (AutoCAD-compatible)"),
]


def file_id(rel: str) -> str:
    return hashlib.sha1(rel.encode()).hexdigest()[:10]


def find_drawings(root: Path) -> list[Path]:
    return sorted((p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in DRAWING_SUFFIXES
                   and not any(part.startswith(".") for part in p.relative_to(root).parts)),
                  key=lambda p: str(p.relative_to(root)).lower())


def sniff_creator(path: Path) -> list[str]:
    """'999' comment lines near the top of an ASCII DXF often name the exporter."""
    try:
        with open(path, "rb") as f:
            head = f.read(4096).decode("latin-1", "replace").splitlines()
    except OSError:
        return []
    return [head[i + 1].strip() for i, line in enumerate(head[:-1]) if line.strip() == "999"][:3]


def made_with(hints: list[str], app_ids: list[str]) -> str:
    words = [w.lower() for w in hints + app_ids]
    hay = " ".join(words)
    for key, name in CREATORS:
        if (key in words) if key == "oda" else (key in hay):   # 'oda' must be the whole app id
            return name
    return ""


def to_dxf(src: Path, cache: Path) -> tuple[Path, str | None]:
    """DWG -> DXF through CADCraft (ezdxf can't read DWG); DXF is used as is."""
    if src.suffix.lower() != ".dwg":
        return src, None
    if not CADCRAFT.exists():
        raise RuntimeError("DWG files can't be opened directly. Save this drawing as DXF from your CAD "
                           "program, or install CADCraft (its command-line tool is used to convert DWG).")
    cache.mkdir(parents=True, exist_ok=True)
    st = src.stat()
    dst = cache / (file_id(f"{src}|{st.st_size}|{st.st_mtime_ns}") + ".dxf")
    if not dst.exists():
        r = subprocess.run([str(CADCRAFT), "convert", str(src), str(dst)],
                           capture_output=True, text=True, timeout=180)
        if r.returncode != 0 or not dst.exists():
            raise RuntimeError("CADCraft could not convert this DWG: " + (r.stderr or r.stdout).strip()[:300])
    return dst, "converted from DWG by CADCraft"


def load(src: Path, cache: Path):
    """Read a drawing tolerantly. Returns (doc, info) where info holds what was learned while loading."""
    from ezdxf import recover
    info: dict = {"bytes": src.stat().st_size, "format": src.suffix.lower().lstrip(".")}
    if info["format"] == "dwg":
        with open(src, "rb") as f:
            info["dwgVersion"] = VERSIONS.get(f.read(6).decode("latin-1"), "unknown")
    dxf_path, note = to_dxf(src, cache)
    if note:
        info["note"] = note
    info["creatorHints"] = sniff_creator(dxf_path)
    try:                        # the normal reader is ~2x faster; audit afterwards for the same report
        import ezdxf
        doc = ezdxf.readfile(dxf_path)
        auditor = doc.audit()
    except Exception:           # damaged or non-standard file: the slower, tolerant reader
        doc, auditor = recover.readfile(dxf_path)
        info["recovered"] = True
    info["audit"] = {"errors": len(auditor.errors), "fixes": len(auditor.fixes),
                     "messages": [str(m.message) for m in (auditor.errors + auditor.fixes)[:8]]}
    return doc, info


def describe(doc, info: dict) -> dict:
    """What's in the drawing. Also adds any undefined layers to the in-memory doc (so they draw)."""
    from ezdxf import bbox
    rec = dict(info)
    h = doc.header
    rec["dxfVersion"] = rec.get("dwgVersion") or VERSIONS.get(doc.dxfversion, doc.dxfversion)
    rec["units"] = UNITS.get(h.get("$INSUNITS", 0), str(h.get("$INSUNITS")))
    rec["measurement"] = "metric" if h.get("$MEASUREMENT", 0) == 1 else "imperial"
    skip = {"ACAD"} | ({"CADCRAFT"} if rec.get("note") else set())   # CADCRAFT is added by DWG conversion
    rec["appIds"] = sorted(a.dxf.name for a in doc.appids if a.dxf.name.upper() not in skip)[:12]
    rec["madeWith"] = made_with(rec.get("creatorHints", []), rec["appIds"])

    msp = doc.modelspace()
    counts = collections.Counter(e.dxftype() for e in msp)
    rec["entities"] = dict(counts.most_common())
    rec["entityTotal"] = sum(counts.values())

    per_layer = collections.Counter(e.dxf.get("layer", "0") for e in msp)
    missing = sorted(set(per_layer) - {l.dxf.name for l in doc.layers})
    rec["missingLayers"] = missing
    for n in missing:                       # ezdxf won't draw entities on undefined layers; CAD apps do
        doc.layers.add(n)
    rec["layers"] = sorted(({"name": l.dxf.name, "aci": l.dxf.get("color", 7), "on": l.is_on(),
                             "frozen": l.is_frozen(), "entities": per_layer.get(l.dxf.name, 0)}
                            for l in doc.layers), key=lambda l: (-l["entities"], l["name"].lower()))

    used_blocks = collections.Counter(e.dxf.name for e in msp.query("INSERT"))
    rec["blocks"] = [{"name": b, "inserts": c} for b, c in used_blocks.most_common(20)]
    rec["blockDefs"] = sum(1 for b in doc.blocks if not b.name.startswith("*"))

    texts = [text_of(e) for e in msp if e.dxftype() in TEXT_TYPES]
    for b in doc.blocks:                    # text inside blocks that are actually used
        if not b.name.startswith("*") and b.name in used_blocks:
            texts += [text_of(e) for e in b if e.dxftype() in TEXT_TYPES]
    rec["text"] = list(dict.fromkeys(t for t in texts if t))[:60]

    rec["tiltedEntities"] = flatten_tilted(doc)      # before measuring, so the size matches the picture
    ext = bbox.extents(msp, fast=True)
    if ext.has_data:
        rec["extents"] = [[round(ext.extmin.x, 3), round(ext.extmin.y, 3)],
                          [round(ext.extmax.x, 3), round(ext.extmax.y, 3)]]
        rec["size"] = [round(ext.size.x, 3), round(ext.size.y, 3)]
    rec["paperLayouts"] = [l.name for l in doc.layouts if l.name != "Model" and len(l) > 0]
    return rec


def text_of(e) -> str:
    try:
        if e.dxftype() == "MTEXT":
            return e.plain_text().strip()
        return (e.dxf.get("text") or "").strip()
    except Exception:
        return ""


def flatten_tilted(doc) -> int:
    """2D objects placed on upright/tilted planes show edge-on from above; lay them flat. Returns count."""
    n = 0
    for e in doc.entitydb.values():
        if e.dxftype() in FLAT_TYPES and hasattr(e, "dxf") and e.dxf.hasattr("extrusion"):
            x, y, z = e.dxf.extrusion
            if abs(abs(z) - 1) > 1e-6:          # +Z and -Z (mirrored) are fine
                e.dxf.extrusion = (0, 0, 1)
                n += 1
    return n


def _luma(tc: int) -> float:
    return 0.2126 * ((tc >> 16) & 255) + 0.7152 * ((tc >> 8) & 255) + 0.0722 * (tc & 255)


class Contrast:
    """Swap explicit near-white / near-black colours that would vanish on the chosen background.

    ezdxf already flips AutoCAD colour 7; this handles true colours (RGB) such as pure white
    or pure black lines from vector converters. Originals are remembered so it can switch back.
    """
    LIGHT, DARK = 225, 40

    def __init__(self, doc):
        self.items = []   # (dxf namespace, original true colour)
        for obj in list(doc.layers) + list(doc.entitydb.values()):
            if hasattr(obj, "dxf") and obj.dxf.hasattr("true_color"):
                self.items.append((obj, obj.dxf.true_color))

    def apply(self, dark: bool) -> int:
        """Returns how many drawing objects (not polyline points) had their colour changed."""
        changed = 0
        for obj, tc in self.items:
            lum = _luma(tc)
            if dark and lum < self.DARK:
                obj.dxf.true_color = 0xFFFFFF - tc        # invert: black -> white
            elif not dark and lum > self.LIGHT:
                obj.dxf.true_color = 0xFFFFFF - tc        # invert: white -> black
            else:
                obj.dxf.true_color = tc
                continue
            changed += obj.dxftype() not in ("VERTEX", "SEQEND", "LAYER")
        return changed
