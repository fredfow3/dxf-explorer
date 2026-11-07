"""Build out/index.html: a browsable gallery of the inventory in out/data.json.

    .venv/bin/python gallery.py [OUT_DIR]

The page is self-contained (data embedded), so it opens straight from Finder.
"""
import html
import json
import sys
from pathlib import Path

out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent / "out")
data = json.loads((out / "data.json").read_text())

CREATORS = [  # substring in creator hints / app ids -> friendly name
    ("dxfrw", "LibreCAD"), ("librecad", "LibreCAD"), ("dxflib", "dxflib (QCAD or a converter)"),
    ("inkscape", "Inkscape"), ("vcarve", "Vectric"), ("vectric", "Vectric"), ("aspire", "Vectric"),
    ("corel", "CorelDRAW"), ("illustrator", "Illustrator"), ("rhino", "Rhino"), ("fusion", "Fusion 360"),
    ("solidworks", "SolidWorks"), ("sketchup", "SketchUp"), ("lightburn", "LightBurn"),
    ("ezdxf", "ezdxf"), ("draftsight", "DraftSight"), ("kompas", "KOMPAS-3D"),
    ("gear template generator", "Gear template generator"), ("bezarc", "BEZARC"),
    ("oda", "an ODA-based program (AutoCAD-compatible)"),
]


def made_with(r):
    words = [w.lower() for w in r.get("creatorHints", []) + r.get("appIds", [])]
    hay = " ".join(words)
    for key, name in CREATORS:
        if (key in words) if key == "oda" else (key in hay):   # 'oda' must be the whole app id
            return name
    return ""


for r in data["drawings"]:
    r["madeWith"] = made_with(r)

page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>DXF Explorer</title>
<style>
:root{--bg:#f6f6f4;--card:#fff;--ink:#1d1f22;--muted:#6b7077;--line:#e2e2de;--accent:#0b6f88;--warn:#b45309;--bad:#b91c1c;--chip:#eef2f3}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#16181b;--card:#1f2226;--ink:#e8e8e6;--muted:#9aa0a6;--line:#2e3237;--accent:#4fb3cc;--warn:#f59e0b;--bad:#f87171;--chip:#262b30}}
:root[data-theme="dark"]{--bg:#16181b;--card:#1f2226;--ink:#e8e8e6;--muted:#9aa0a6;--line:#2e3237;--accent:#4fb3cc;--warn:#f59e0b;--bad:#f87171;--chip:#262b30}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;flex-wrap:wrap;gap:8px;align-items:center}
h1{font-size:17px;margin:0 12px 0 0}input,select,button{font:inherit;color:var(--ink);background:var(--card);border:1px solid var(--line);border-radius:6px;padding:5px 8px}
input[type=search]{flex:1;min-width:180px}.stat{color:var(--muted);font-size:13px}
main{padding:16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;overflow:hidden;cursor:pointer;display:flex;flex-direction:column}
.card:hover{border-color:var(--accent)}.card img{width:100%;aspect-ratio:4/3;object-fit:contain;background:#fff;display:block;border-bottom:1px solid var(--line)}
.card .t{padding:7px 9px 9px}.name{font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.sub{color:var(--muted);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.flags{display:flex;gap:4px;flex-wrap:wrap;margin-top:4px}.chip{background:var(--chip);border-radius:4px;padding:0 5px;font-size:11px;color:var(--muted)}
.chip.warn{color:var(--warn)}.chip.bad{color:var(--bad)}
dialog{border:1px solid var(--line);border-radius:10px;background:var(--card);color:var(--ink);padding:0;width:min(1100px,96vw);max-height:92vh}
dialog::backdrop{background:rgba(0,0,0,.5)}.dl{display:grid;grid-template-columns:minmax(0,3fr) minmax(260px,2fr);max-height:92vh}
.dl .img{background:#fff;display:flex;align-items:center;justify-content:center;min-height:300px}.dl .img img{max-width:100%;max-height:88vh;cursor:zoom-in}
.dl .info{padding:14px 16px;overflow:auto;max-height:92vh;border-left:1px solid var(--line)}
.dl h2{font-size:16px;margin:0 0 2px;word-break:break-word}.kv{display:grid;grid-template-columns:auto 1fr;gap:2px 10px;font-size:13px;margin:10px 0}.kv dt{color:var(--muted)}.kv dd{margin:0;word-break:break-word}
h3{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);margin:14px 0 4px}
table{border-collapse:collapse;width:100%;font-size:12.5px}td{padding:2px 4px;border-bottom:1px solid var(--line)}td.n{text-align:right;color:var(--muted)}
.txt{font-size:12.5px;white-space:pre-wrap;background:var(--chip);border-radius:6px;padding:6px 8px;max-height:200px;overflow:auto}
.close{position:absolute;top:8px;right:10px}.err{color:var(--bad);font-size:12.5px}
@media (max-width:760px){.dl{grid-template-columns:1fr}.dl .info{border-left:0;border-top:1px solid var(--line)}}
</style></head><body>
<header>
 <h1>DXF Explorer</h1>
 <input type="search" id="q" placeholder="Search names, folders, text in drawings, layers, entity types…">
 <select id="folder"><option value="">All folders</option></select>
 <select id="sort"><option value="name">Sort: name</option><option value="entities">Most entities</option><option value="bytes">Largest file</option><option value="size">Biggest drawing</option></select>
 <select id="flag"><option value="">All drawings</option><option value="text">Has text</option><option value="dup">Duplicates</option><option value="audit">Audit problems</option><option value="dwg">DWG only</option><option value="fail">Failed</option></select>
 <button id="theme" title="Light / dark">◐</button>
 <span class="stat" id="stat"></span>
</header>
<main id="grid"></main>
<dialog id="dlg"><button class="close" onclick="dlg.close()">✕</button><div class="dl" id="det"></div></dialog>
<script>
const DATA = __DATA__;
const D = DATA.drawings;
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const kb = b => b > 1e6 ? (b/1e6).toFixed(1)+" MB" : Math.round(b/1e3)+" KB";
const dims = r => r.size ? `${+r.size[0].toFixed(2)} × ${+r.size[1].toFixed(2)} ${r.units==="unitless"?"":r.units}` : "—";
const area = r => r.size ? r.size[0]*r.size[1] : 0;
const hay = r => [r.path, r.madeWith, ...(r.text||[]), ...(r.layers||[]).map(l=>l.name), ...Object.keys(r.entities||{})].join(" ").toLowerCase();
D.forEach(r => r._h = hay(r));
[...new Set(D.map(r => r.folder))].sort().forEach(f => $("#folder").insertAdjacentHTML("beforeend", `<option value="${f ? esc(f) : "__top"}">${f ? esc(f) : "(top level)"}</option>`));
try { const t = localStorage.getItem("dxfx-theme"); if (t) document.documentElement.dataset.theme = t; } catch(e) {}
$("#theme").onclick = () => { const r = document.documentElement, dark = matchMedia("(prefers-color-scheme: dark)").matches;
  const cur = r.dataset.theme || (dark ? "dark" : "light"); r.dataset.theme = cur === "dark" ? "light" : "dark";
  try { localStorage.setItem("dxfx-theme", r.dataset.theme); } catch(e) {} };

function flags(r){
  const f = [];
  if (!r.ok) return `<span class="chip bad">failed</span>`;
  f.push(`<span class="chip">${esc(r.format.toUpperCase())} ${esc(r.dxfVersion)}</span>`);
  if (r.units && r.units !== "unitless") f.push(`<span class="chip">${esc(r.units)}</span>`);
  if (r.text?.length) f.push(`<span class="chip">text</span>`);
  if (r.duplicates?.length) f.push(`<span class="chip warn">duplicate</span>`);
  if (r.audit?.errors) f.push(`<span class="chip warn">${r.audit.errors} audit</span>`);
  if (r.missingLayers?.length) f.push(`<span class="chip warn">undefined layer</span>`);
  if (r.whiteLines) f.push(`<span class="chip warn">white lines</span>`);
  if (r.tiltedEntities) f.push(`<span class="chip warn">tilted</span>`);
  return f.join("");
}
function render(){
  const q = $("#q").value.trim().toLowerCase().split(/\\s+/).filter(Boolean), fo = $("#folder").value, fl = $("#flag").value, so = $("#sort").value;
  let rows = D.filter(r => (!fo || r.folder === (fo === "__top" ? "" : fo)) && q.every(w => r._h.includes(w)));
  if (fl === "text") rows = rows.filter(r => r.text?.length);
  if (fl === "dup") rows = rows.filter(r => r.duplicates?.length);
  if (fl === "audit") rows = rows.filter(r => r.audit?.errors || r.audit?.fixes || r.missingLayers?.length || r.whiteLines || r.tiltedEntities);
  if (fl === "dwg") rows = rows.filter(r => r.format === "dwg");
  if (fl === "fail") rows = rows.filter(r => !r.ok);
  const key = {name: r => r.path.toLowerCase(), entities: r => -(r.entityTotal||0), bytes: r => -r.bytes, size: r => -area(r)}[so];
  rows.sort((a,b) => { const x = key(a), y = key(b); return x < y ? -1 : x > y ? 1 : 0; });
  $("#stat").textContent = `${rows.length} of ${D.length} drawings · scanned ${DATA.generated}`;
  $("#grid").innerHTML = rows.map(r => `<div class="card" data-id="${r.id}">
    ${r.png ? `<img loading="lazy" src="${r.png}" alt="">` : `<div style="aspect-ratio:4/3;display:flex;align-items:center;justify-content:center" class="err">no render</div>`}
    <div class="t"><div class="name" title="${esc(r.name)}">${esc(r.name)}</div>
    <div class="sub">${esc(r.folder || "")}${r.folder ? " · " : ""}${(r.entityTotal ?? 0).toLocaleString()} entities · ${kb(r.bytes)}</div>
    <div class="flags">${flags(r)}</div></div></div>`).join("");
}
function detail(id){
  const r = D.find(x => x.id === id);
  const ents = Object.entries(r.entities||{}).map(([k,v]) => `<tr><td>${esc(k)}</td><td class="n">${v.toLocaleString()}</td></tr>`).join("");
  const lays = (r.layers||[]).map(l => `<tr><td>${esc(l.name)}${l.on ? "" : " <span class='chip'>off</span>"}${l.frozen ? " <span class='chip'>frozen</span>" : ""}</td><td class="n">ACI ${l.aci}</td><td class="n">${l.entities.toLocaleString()}</td></tr>`).join("");
  const blks = (r.blocks||[]).map(b => `<tr><td>${esc(b.name)}</td><td class="n">×${b.inserts}</td></tr>`).join("");
  $("#det").innerHTML = `<div class="img">${r.png ? `<a href="${r.png}" target="_blank"><img src="${r.png}" alt=""></a>` : ""}</div>
  <div class="info"><h2>${esc(r.name)}</h2><div class="sub">${esc(DATA.root)}/${esc(r.path)}</div>
  ${r.ok ? "" : `<p class="err">${esc(r.error)}</p>`}
  <dl class="kv">
   <dt>Format</dt><dd>${esc(r.format.toUpperCase())} ${esc(r.dxfVersion || "")}${r.note ? ` (${esc(r.note)})` : ""}</dd>
   <dt>File</dt><dd>${kb(r.bytes)}</dd>
   <dt>Drawing size</dt><dd>${dims(r)}</dd>
   <dt>Units</dt><dd>${esc(r.units || "—")} (${esc(r.measurement || "")})</dd>
   <dt>Made with</dt><dd>${esc(r.madeWith || "unknown")}${r.creatorHints?.length ? ` <span class="sub">${esc(r.creatorHints.join("; "))}</span>` : ""}</dd>
   ${r.appIds?.length ? `<dt>App IDs</dt><dd>${esc(r.appIds.join(", "))}</dd>` : ""}
   <dt>Entities</dt><dd>${(r.entityTotal ?? 0).toLocaleString()} in model space${r.paperLayouts?.length ? `; paper layouts: ${esc(r.paperLayouts.join(", "))}` : ""}</dd>
   <dt>Audit</dt><dd>${r.audit ? (r.audit.errors || r.audit.fixes ? `${r.audit.errors} errors, ${r.audit.fixes} fixed on load` : "clean") : "—"}</dd>
   ${r.missingLayers?.length ? `<dt>Undefined layers</dt><dd>${esc(r.missingLayers.join(", "))} <span class="sub">(used but not in the layer table)</span></dd>` : ""}
   ${r.whiteLines ? `<dt>White lines</dt><dd>${r.whiteLines.toLocaleString()} objects are coloured white; shown black in the picture</dd>` : ""}
   ${r.tiltedEntities ? `<dt>Tilted</dt><dd>${r.tiltedEntities.toLocaleString()} 2D objects sit on upright/tilted planes; laid flat for the picture</dd>` : ""}
   <dt>Render</dt><dd>${r.renderSeconds ?? "—"} s</dd>
  </dl>
  ${r.duplicates?.length ? `<h3>Identical copies</h3><div class="txt">${r.duplicates.map(esc).join("\\n")}</div>` : ""}
  ${r.audit?.messages?.length ? `<h3>Audit messages</h3><div class="txt">${r.audit.messages.map(esc).join("\\n")}</div>` : ""}
  ${r.text?.length ? `<h3>Text in the drawing</h3><div class="txt">${r.text.map(esc).join("\\n")}</div>` : ""}
  ${ents ? `<h3>Entity types</h3><table>${ents}</table>` : ""}
  ${lays ? `<h3>Layers</h3><table>${lays}</table>` : ""}
  ${blks ? `<h3>Blocks used (${r.blockDefs} defined)</h3><table>${blks}</table>` : ""}
  </div>`;
  $("#dlg").showModal();
}
$("#grid").onclick = e => { const c = e.target.closest(".card"); if (c) detail(c.dataset.id); };
["#q","#folder","#sort","#flag"].forEach(s => $(s).addEventListener("input", render));
render();
</script></body></html>"""

payload = json.dumps(data).replace("</", "<\\/")
(out / "index.html").write_text(page.replace("__DATA__", payload))
print(f"wrote {out / 'index.html'}  ({len(data['drawings'])} drawings)")
