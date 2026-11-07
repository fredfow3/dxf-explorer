"""DXF Explorer — point it at a folder and browse the DXF/DWG drawings inside.

    .venv/bin/python explorer.py [FOLDER]

Left: every drawing in the folder (and sub-folders), with a filter box.
Middle: the drawing. Scroll/two-finger drag to move, pinch or Cmd+scroll (mouse wheel) to zoom,
drag with the mouse to pan. Right: layer checkboxes and an information panel.
Files are only read; nothing is ever written back to them.
"""
from __future__ import annotations

import hashlib
import html
import math
import os
import subprocess
import sys
import time
import traceback
from collections import OrderedDict, defaultdict
from pathlib import Path

from PySide6 import QtCore as qc, QtGui as qg, QtWidgets as qw

from ezdxf.addons.drawing import Frontend, RenderContext
from ezdxf.addons.drawing.config import BackgroundPolicy, ColorPolicy, Configuration
from ezdxf.addons.drawing.properties import layer_key
from ezdxf.addons.drawing.pyqt import PyQtBackend, _get_x_scale

import dxfcore

APP = "DXF Explorer"
CACHE = Path.home() / "Library/Caches/DXF Explorer"
BG = {False: "#ffffff", True: "#20262e"}          # light / dark drawing background


# ----------------------------------------------------------------------------- drawing view
class DrawingView(qw.QGraphicsView):
    """Zoom and pan like a Mac app: trackpad scroll pans, pinch or ⌘-scroll zooms, a mouse wheel zooms."""
    mouse_at = qc.Signal(float, float)
    zoom_changed = qc.Signal(float)

    def __init__(self):
        super().__init__()
        self._fit_scale = 1.0
        self.setTransformationAnchor(qw.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(qw.QGraphicsView.AnchorViewCenter)
        self.setDragMode(qw.QGraphicsView.ScrollHandDrag)
        self.setFrameShape(qw.QFrame.NoFrame)
        self.setRenderHints(qg.QPainter.Antialiasing | qg.QPainter.TextAntialiasing | qg.QPainter.SmoothPixmapTransform)
        self.setViewportUpdateMode(qw.QGraphicsView.SmartViewportUpdate)
        self.setMouseTracking(True)
        self.setScene(qw.QGraphicsScene())
        self._message = ""
        self.scale(1, -1)                                   # drawing +Y is up

    # -- scene handling
    def show_scene(self, scene: qw.QGraphicsScene, keep_view: bool):
        saved = (self.transform(), self.horizontalScrollBar().value(), self.verticalScrollBar().value())
        r = scene.itemsBoundingRect()
        if r.isNull():
            r = qc.QRectF(-1, -1, 2, 2)
        # generous margin so the drawing can be scrolled past its edges when zoomed in
        m = max(r.width(), r.height()) * 0.5
        scene.setSceneRect(r.adjusted(-m, -m, m, m))
        self._content = r
        old = self.scene()
        self.setScene(scene)
        if old is not None:
            old.deleteLater()
        if keep_view:
            self.setTransform(saved[0])
            self.horizontalScrollBar().setValue(saved[1])
            self.verticalScrollBar().setValue(saved[2])
        else:
            self.fit()

    def fit(self):
        r = getattr(self, "_content", self.sceneRect())
        pad = max(r.width(), r.height()) * 0.04
        self.fitInView(r.adjusted(-pad, -pad, pad, pad), qc.Qt.KeepAspectRatio)
        self._fit_scale = _get_x_scale(self.transform()) or 1.0
        self.zoom_changed.emit(1.0)

    def zoom_by(self, factor: float, anchor_mouse=True):
        current = _get_x_scale(self.transform()) / self._fit_scale
        target = min(max(current * factor, 0.05), 5000)
        factor = target / current
        if not anchor_mouse:
            self.setTransformationAnchor(qw.QGraphicsView.AnchorViewCenter)
        self.scale(factor, factor)
        self.setTransformationAnchor(qw.QGraphicsView.AnchorUnderMouse)
        self.zoom_changed.emit(target)

    def set_message(self, text: str):
        self._message = text
        self.viewport().update()

    # -- input
    def wheelEvent(self, ev: qg.QWheelEvent):
        mods = ev.modifiers()
        trackpad = not ev.pixelDelta().isNull()
        if trackpad and not (mods & (qc.Qt.ControlModifier | qc.Qt.MetaModifier)):
            super().wheelEvent(ev)                          # two-finger scroll pans
            return
        dy = ev.angleDelta().y() or ev.angleDelta().x()
        self.zoom_by(1.0015 ** dy)                          # mouse wheel / ⌘-scroll zooms
        ev.accept()

    def viewportEvent(self, ev: qc.QEvent) -> bool:
        if ev.type() == qc.QEvent.NativeGesture and ev.gestureType() == qc.Qt.ZoomNativeGesture:
            self.zoom_by(1.0 + ev.value())                  # trackpad pinch
            return True
        return super().viewportEvent(ev)

    def mouseMoveEvent(self, ev: qg.QMouseEvent):
        p = self.mapToScene(ev.position().toPoint())
        self.mouse_at.emit(p.x(), p.y())
        super().mouseMoveEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        self.fit()

    def drawForeground(self, painter: qg.QPainter, rect: qc.QRectF):
        if not self._message:
            return
        painter.save()
        painter.setWorldMatrixEnabled(False)
        r = self.viewport().rect()
        f = painter.font(); f.setPointSize(15); painter.setFont(f)
        dark = self.backgroundBrush().color().lightness() < 128
        painter.setPen(qg.QColor("#c9cdd2" if dark else "#555b62"))
        painter.drawText(r.adjusted(30, 30, -30, -30), qc.Qt.AlignCenter | qc.Qt.TextWordWrap, self._message)
        painter.restore()


class SolidLineBackend(PyQtBackend):
    """ezdxf's Qt renderer draws default lines ~0.7 screen points wide, which a Retina screen shows
    as faint grey hairlines (and it ignores Configuration.min_lineweight). Enforce a minimum width."""
    MIN_WIDTH = 1.25          # screen points; lines stay this width at any zoom (cosmetic pens)

    def _get_pen(self, properties):
        pen = super()._get_pen(properties)
        if pen.widthF() < self.MIN_WIDTH:
            pen.setWidthF(self.MIN_WIDTH)
        return pen


# ----------------------------------------------------------------------------- background loading
class LoadSignals(qc.QObject):
    done = qc.Signal(int, object, object, str)          # token, doc, info, error


class LoadJob(qc.QRunnable):
    def __init__(self, token: int, path: Path):
        super().__init__()
        self.token, self.path, self.signals = token, path, LoadSignals()

    def run(self):
        try:
            doc, info = dxfcore.load(self.path, CACHE / "dwg")
            info = dxfcore.describe(doc, info)
            contrast = dxfcore.Contrast(doc)
            self.signals.done.emit(self.token, (doc, contrast), info, "")
        except Exception as ex:
            self.signals.done.emit(self.token, None, None, f"{type(ex).__name__}: {ex}")


class HashSignals(qc.QObject):
    done = qc.Signal(object)


class HashJob(qc.QRunnable):
    """Fingerprint every file once per folder so the info panel can list identical copies."""
    def __init__(self, files: list[Path]):
        super().__init__()
        self.files, self.signals = files, HashSignals()

    def run(self):
        out = {}
        for p in self.files:
            try:
                out[p] = hashlib.sha1(p.read_bytes()).hexdigest()
            except OSError:
                pass
        self.signals.done.emit(out)


# ----------------------------------------------------------------------------- main window
class Explorer(qw.QMainWindow):
    def __init__(self, folder: Path | None):
        super().__init__()
        self.settings = qc.QSettings("dxf-explorer", "DXF Explorer")
        self.root: Path | None = None
        self.current: Path | None = None
        self.doc = self.contrast = self.info = None
        self.hidden_layers: set[str] = set()
        self.token = 0
        self.pool = qc.QThreadPool.globalInstance()
        self.loaded: OrderedDict[Path, tuple] = OrderedDict()   # small cache: path -> (doc, contrast, info)
        self.hashes: dict[Path, str] = {}
        # Background jobs must stay referenced until they report back: otherwise Python can
        # garbage-collect their signal object mid-run and the result is silently lost.
        self.jobs: set = set()
        self.dark = self.settings.value("dark", False, type=bool)

        self.setWindowTitle(APP)
        self.resize(1400, 860)
        self._build_ui()
        self._build_actions()
        geo = self.settings.value("geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        st = self.settings.value("splitter")
        if st is not None:
            self.split.restoreState(st)
        self._apply_background()

        start = folder or (Path(self.settings.value("folder")) if self.settings.value("folder") else None)
        if start and start.is_dir():
            qc.QTimer.singleShot(0, lambda: self.open_folder(start))
        else:
            self.view.set_message("Open a folder of DXF/DWG drawings  —  File ▸ Open Folder… (⌘O)")

    # -- layout
    def _build_ui(self):
        # left: filter + file tree
        left = qw.QWidget(); ll = qw.QVBoxLayout(left); ll.setContentsMargins(6, 6, 0, 6); ll.setSpacing(6)
        self.folder_label = qw.QLabel("No folder"); self.folder_label.setStyleSheet("font-weight:600")
        self.folder_label.setTextInteractionFlags(qc.Qt.TextSelectableByMouse)
        self.filter = qw.QLineEdit(); self.filter.setPlaceholderText("Filter by name…"); self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.tree = qw.QTreeWidget(); self.tree.setHeaderLabels(["Drawing", "Size"])
        self.tree.setUniformRowHeights(True); self.tree.setAlternatingRowColors(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, qw.QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, qw.QHeaderView.ResizeToContents)
        self.tree.currentItemChanged.connect(self._on_select)
        self.tree.setContextMenuPolicy(qc.Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_menu)
        self.count_label = qw.QLabel(""); self.count_label.setStyleSheet("color:gray")
        for w in (self.folder_label, self.filter, self.tree, self.count_label):
            ll.addWidget(w)

        # middle: drawing
        self.view = DrawingView()
        self.view.mouse_at.connect(lambda x, y: self.coord_label.setText(f"x {x:,.3f}   y {y:,.3f}"))
        self.view.zoom_changed.connect(lambda z: self.zoom_label.setText(f"{z * 100:,.0f}%"))

        # right: layers + info
        right = qw.QSplitter(qc.Qt.Vertical)
        lay_box = qw.QWidget(); lb = qw.QVBoxLayout(lay_box); lb.setContentsMargins(0, 6, 6, 0); lb.setSpacing(4)
        head = qw.QHBoxLayout(); t = qw.QLabel("Layers"); t.setStyleSheet("font-weight:600")
        b_all = qw.QPushButton("All"); b_none = qw.QPushButton("None")
        for b in (b_all, b_none):
            b.setFixedWidth(52)
        b_all.clicked.connect(lambda: self._set_all_layers(True)); b_none.clicked.connect(lambda: self._set_all_layers(False))
        head.addWidget(t); head.addStretch(1); head.addWidget(b_all); head.addWidget(b_none)
        self.layers = qw.QListWidget(); self.layers.itemChanged.connect(self._on_layer_toggled)
        self.layers.itemDoubleClicked.connect(self._solo_layer)
        self.layers.setToolTip("Tick to show, untick to hide. Double-click a layer to show only that layer.")
        lb.addLayout(head); lb.addWidget(self.layers)
        self.info_view = qw.QTextBrowser(); self.info_view.setOpenExternalLinks(False)
        self.info_view.setFrameShape(qw.QFrame.NoFrame)
        info_box = qw.QWidget(); ib = qw.QVBoxLayout(info_box); ib.setContentsMargins(0, 0, 6, 6)
        ib.addWidget(self.info_view)
        right.addWidget(lay_box); right.addWidget(info_box); right.setSizes([260, 520])
        self.right_panel = right

        self.split = qw.QSplitter(); self.split.addWidget(left); self.split.addWidget(self.view); self.split.addWidget(right)
        self.split.setStretchFactor(1, 1); self.split.setSizes([300, 800, 320])
        self.setCentralWidget(self.split)

        sb = self.statusBar()
        self.status_label = qw.QLabel(""); self.coord_label = qw.QLabel(""); self.zoom_label = qw.QLabel("")
        sb.addWidget(self.status_label, 1); sb.addPermanentWidget(self.coord_label); sb.addPermanentWidget(self.zoom_label)

    def _build_actions(self):
        def act(text, slot, key=None, checkable=False, tip=None):
            a = qg.QAction(text, self)
            if key:
                a.setShortcut(qg.QKeySequence(key))
            a.setCheckable(checkable)
            if tip:
                a.setToolTip(tip)
            a.triggered.connect(slot)
            return a

        self.a_open = act("Open Folder…", self.choose_folder, "Ctrl+O")
        self.a_reload = act("Rescan Folder", lambda: self.root and self.open_folder(self.root, keep=True), "Ctrl+Shift+R")
        self.a_reveal = act("Reveal in Finder", self.reveal, "Ctrl+R")
        self.a_default = act("Open in Default App", self.open_default, "Ctrl+Shift+O")
        self.a_dark = act("Dark Background", self.toggle_dark, "Ctrl+D", checkable=True,
                          tip="Switch the drawing background between light and dark (⌘D)")
        self.a_dark.setChecked(self.dark)
        self.a_fit = act("Fit to Window", self.view.fit, "Ctrl+0")
        self.a_in = act("Zoom In", lambda: self.view.zoom_by(1.25, False), "Ctrl+=")
        self.a_out = act("Zoom Out", lambda: self.view.zoom_by(0.8, False), "Ctrl+-")
        self.a_panel = act("Show Layers && Info", lambda on: self.right_panel.setVisible(on), "Ctrl+I", checkable=True)
        self.a_panel.setChecked(True)
        self.a_next = act("Next Drawing", lambda: self._step(1), "Ctrl+Down")
        self.a_prev = act("Previous Drawing", lambda: self._step(-1), "Ctrl+Up")

        m = self.menuBar().addMenu("&File")
        for a in (self.a_open, self.a_reload, None, self.a_reveal, self.a_default):
            m.addSeparator() if a is None else m.addAction(a)
        m = self.menuBar().addMenu("&View")
        for a in (self.a_dark, None, self.a_fit, self.a_in, self.a_out, None, self.a_panel, None, self.a_next, self.a_prev):
            m.addSeparator() if a is None else m.addAction(a)

        tb = self.addToolBar("Main"); tb.setMovable(False); tb.setToolButtonStyle(qc.Qt.ToolButtonTextOnly)
        for a in (self.a_open, None, self.a_fit, self.a_in, self.a_out, None, self.a_dark, None, self.a_reveal):
            tb.addSeparator() if a is None else tb.addAction(a)

    # -- folder & list
    def choose_folder(self):
        start = str(self.root or Path.home())
        d = qw.QFileDialog.getExistingDirectory(self, "Choose a folder of drawings", start)
        if d:
            self.open_folder(Path(d))

    def open_folder(self, folder: Path, keep: bool = False):
        folder = folder.expanduser().resolve()
        self.root = folder
        self.settings.setValue("folder", str(folder))
        self.folder_label.setText(folder.name); self.folder_label.setToolTip(str(folder))
        self.setWindowTitle(f"{APP} — {folder.name}")
        qw.QApplication.setOverrideCursor(qc.Qt.WaitCursor)
        try:
            files = dxfcore.find_drawings(folder)
        finally:
            qw.QApplication.restoreOverrideCursor()
        self.files = files
        self.loaded.clear(); self.hashes = {}
        last = self.settings.value("file")             # reopen on the drawing viewed last time
        prev = self.current if keep else (Path(last) if last else None)

        self.tree.blockSignals(True); self.tree.clear()
        folders: dict[str, qw.QTreeWidgetItem] = {}

        def folder_item(rel: Path) -> qw.QTreeWidgetItem | None:
            if str(rel) in (".", ""):
                return None
            key = str(rel)
            if key not in folders:
                parent = folder_item(rel.parent)
                it = qw.QTreeWidgetItem([rel.name, ""])
                it.setIcon(0, self.style().standardIcon(qw.QStyle.SP_DirIcon))
                it.setFlags(it.flags() & ~qc.Qt.ItemIsSelectable)
                (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
                folders[key] = it
            return folders[key]

        select_item = None
        for p in files:
            rel = p.relative_to(folder)
            it = qw.QTreeWidgetItem([p.name, human(p.stat().st_size)])
            it.setData(0, qc.Qt.UserRole, str(p))
            it.setToolTip(0, str(rel))
            it.setTextAlignment(1, qc.Qt.AlignRight | qc.Qt.AlignVCenter)
            parent = folder_item(rel.parent)
            (parent.addChild(it) if parent else self.tree.addTopLevelItem(it))
            if prev and p == prev:
                select_item = it
        # folders first, then files, alphabetically
        self.tree.sortItems(0, qc.Qt.AscendingOrder)
        self.tree.blockSignals(False)
        self.count_label.setText(f"{len(files)} drawings" + ("" if files else " — none found here"))
        self.status_label.setText(str(folder))
        if not files:
            self._clear_drawing("No DXF or DWG files in this folder.")
            return
        first = select_item or self._first_file_item()
        self.tree.setCurrentItem(first)
        job = HashJob(files)
        job.setAutoDelete(False)
        self.jobs.add(job)
        job.signals.done.connect(lambda h, j=job: (self.jobs.discard(j), self._hashes_ready(h)))
        self.pool.start(job)

    def _first_file_item(self):
        it = qw.QTreeWidgetItemIterator(self.tree)
        while it.value():
            if it.value().data(0, qc.Qt.UserRole):
                return it.value()
            it += 1
        return None

    def _apply_filter(self, text: str):
        words = text.lower().split()

        def visit(item: qw.QTreeWidgetItem) -> bool:
            path = item.data(0, qc.Qt.UserRole)
            if path:
                show = all(w in path.lower() for w in words)
            else:
                show = any([visit(item.child(i)) for i in range(item.childCount())])
                if words and show:
                    item.setExpanded(True)
            item.setHidden(not show)
            return show

        shown = sum(visit(self.tree.topLevelItem(i)) for i in range(self.tree.topLevelItemCount()))
        n = sum(1 for p in getattr(self, "files", []) if all(w in str(p).lower() for w in words))
        self.count_label.setText(f"{n} of {len(getattr(self, 'files', []))} drawings" if words else f"{len(self.files)} drawings")

    def _step(self, d: int):
        items, it = [], qw.QTreeWidgetItemIterator(self.tree)
        while it.value():
            v = it.value()
            if v.data(0, qc.Qt.UserRole) and not v.isHidden():
                items.append(v)
            it += 1
        if not items:
            return
        cur = self.tree.currentItem()
        i = items.index(cur) if cur in items else -1
        self.tree.setCurrentItem(items[max(0, min(len(items) - 1, i + d))])

    def _tree_menu(self, pos):
        it = self.tree.itemAt(pos)
        if not it or not it.data(0, qc.Qt.UserRole):
            return
        p = Path(it.data(0, qc.Qt.UserRole))
        m = qw.QMenu(self)
        m.addAction("Reveal in Finder", lambda: subprocess.run(["open", "-R", str(p)]))
        m.addAction("Open in Default App", lambda: subprocess.run(["open", str(p)]))
        m.addAction("Copy Path", lambda: qw.QApplication.clipboard().setText(str(p)))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _hashes_ready(self, hashes: dict):
        self.hashes = hashes
        if self.info:
            self._show_info()

    # -- loading & drawing
    def _on_select(self, item, _prev=None):
        if not item or not item.data(0, qc.Qt.UserRole):
            return
        path = Path(item.data(0, qc.Qt.UserRole))
        if path == self.current and self.doc is not None:
            return
        self.current = path
        self.settings.setValue("file", str(path))
        self.token += 1
        if path in self.loaded:
            self.loaded.move_to_end(path)
            doc, contrast, info = self.loaded[path]
            self._loaded(self.token, (doc, contrast), info, "")
            return
        self.status_label.setText(f"Loading {path.name}  ({human(path.stat().st_size)})…")
        self.view.set_message(f"Loading {path.name}…")
        job = LoadJob(self.token, path)
        job.setAutoDelete(False)
        self.jobs.add(job)
        job.signals.done.connect(lambda *a, j=job: (self.jobs.discard(j), self._loaded(*a)))
        self.pool.start(job)

    def _loaded(self, token: int, payload, info, error: str):
        if token != self.token:
            return                                          # the user has moved on to another file
        if error:
            self.doc = self.info = None
            self._clear_drawing(f"Couldn't open {self.current.name}\n\n{error}")
            self.info = {"bytes": self.current.stat().st_size, "format": self.current.suffix[1:], "error": error}
            self._show_info(); self._fill_layers()
            self.status_label.setText(f"Couldn't open {self.current.name}")
            return
        doc, contrast = payload
        self.loaded[self.current] = (doc, contrast, info)
        while len(self.loaded) > 6:
            self.loaded.popitem(last=False)
        self.doc, self.contrast, self.info = doc, contrast, info
        self.hidden_layers = {layer_key(l.dxf.name) for l in doc.layers if not l.is_on() or l.is_frozen()}
        self._fill_layers()
        self._draw(keep_view=False)
        self._show_info()

    def _draw(self, keep_view: bool):
        if self.doc is None:
            return
        t0 = time.time()
        qw.QApplication.setOverrideCursor(qc.Qt.WaitCursor)
        try:
            self.info["contrastFixed"] = self.contrast.apply(self.dark)
            cfg = Configuration(background_policy=BackgroundPolicy.CUSTOM, custom_bg_color=BG[self.dark],
                                color_policy=ColorPolicy.COLOR)
            ctx = RenderContext(self.doc)
            hidden = set(self.hidden_layers)

            def layer_override(layers):
                for lp in layers:
                    lp.is_visible = layer_key(lp.layer) not in hidden
            ctx.set_layer_properties_override(layer_override)
            scene = qw.QGraphicsScene()
            backend = SolidLineBackend()
            backend.set_scene(scene)
            try:
                Frontend(ctx, backend, config=cfg).draw_layout(self.doc.modelspace(), finalize=True)
            finally:
                backend.finalize()
            self.view.set_message("" if scene.items() else "Nothing visible — every layer with content is hidden, or the drawing is empty.")
            self.view.show_scene(scene, keep_view)
            self._apply_background()
        except Exception as ex:
            traceback.print_exc()
            self._clear_drawing(f"Couldn't draw {self.current.name}\n\n{type(ex).__name__}: {ex}")
        finally:
            qw.QApplication.restoreOverrideCursor()
        self.status_label.setText(f"{self.current.relative_to(self.root) if self.root else self.current}"
                                  f"   ·   drawn in {time.time() - t0:.2f}s")

    def _clear_drawing(self, message: str):
        self.view.show_scene(qw.QGraphicsScene(), keep_view=False)
        self.view.set_message(message)
        self.layers.clear()

    def _apply_background(self):
        self.view.setBackgroundBrush(qg.QColor(BG[self.dark]))

    def toggle_dark(self, on: bool):
        self.dark = on
        self.settings.setValue("dark", on)
        self._apply_background()
        self._fill_layers()                                 # swatch contrast
        self._draw(keep_view=True)
        if self.info:
            self._show_info()

    # -- layers
    def _fill_layers(self):
        self.layers.blockSignals(True)
        self.layers.clear()
        if self.info and self.doc is not None:
            ctx = RenderContext(self.doc)
            for l in self.info.get("layers", []):
                lp = ctx.layers.get(layer_key(l["name"]))
                color = lp.color[:7].lower() if lp else "#888888"
                if color in ("#ffffff", "#000000"):          # AutoCAD colour 7: drawn white on dark, black on light
                    color = "#ffffff" if self.dark else "#000000"
                it = qw.QListWidgetItem(f"{l['name']}   ({l['entities']:,})" if l["entities"] else l["name"])
                it.setData(qc.Qt.UserRole, l["name"])
                it.setFlags(it.flags() | qc.Qt.ItemIsUserCheckable)
                it.setCheckState(qc.Qt.Unchecked if layer_key(l["name"]) in self.hidden_layers else qc.Qt.Checked)
                it.setIcon(swatch(color))
                if not l["entities"]:
                    it.setForeground(qg.QColor("gray"))
                    it.setToolTip("Empty layer")
                self.layers.addItem(it)
        self.layers.blockSignals(False)

    def _on_layer_toggled(self, item: qw.QListWidgetItem):
        key = layer_key(item.data(qc.Qt.UserRole))
        if item.checkState() == qc.Qt.Checked:
            self.hidden_layers.discard(key)
        else:
            self.hidden_layers.add(key)
        self._draw(keep_view=True)

    def _set_all_layers(self, on: bool):
        if not self.info:
            return
        self.hidden_layers = set() if on else {layer_key(l["name"]) for l in self.info.get("layers", [])}
        self._fill_layers(); self._draw(keep_view=True)

    def _solo_layer(self, item: qw.QListWidgetItem):
        keep = layer_key(item.data(qc.Qt.UserRole))
        self.hidden_layers = {layer_key(l["name"]) for l in self.info.get("layers", [])} - {keep}
        self._fill_layers(); self._draw(keep_view=True)

    # -- info panel
    def _show_info(self):
        r, p = self.info or {}, self.current
        if not p:
            return
        e = html.escape
        rows = []

        def row(k, v):
            if v not in (None, "", []):
                rows.append(f"<tr><td class=k>{e(k)}</td><td>{v}</td></tr>")

        row("Folder", e(str(p.parent.relative_to(self.root))) if self.root and p.parent != self.root else "")
        row("Format", e(f"{r.get('format', '').upper()} {r.get('dxfVersion', '')}") + (f" <span class=m>({e(r['note'])})</span>" if r.get("note") else ""))
        row("File size", human(r.get("bytes", 0)))
        if r.get("size"):
            u = "" if r.get("units") == "unitless" else " " + r["units"]
            row("Drawing size", e(f"{r['size'][0]:,.3g} × {r['size'][1]:,.3g}{u}"))
        row("Units", e(f"{r.get('units', '')} ({r.get('measurement', '')})") if r.get("units") else "")
        mw = r.get("madeWith") or ("unknown" if "madeWith" in r else "")
        row("Made with", e(mw) + (f"<br><span class=m>{e('; '.join(r['creatorHints']))}</span>" if r.get("creatorHints") else ""))
        row("App IDs", e(", ".join(r.get("appIds", []))))
        if "entityTotal" in r:
            row("Entities", f"{r['entityTotal']:,}" + (f" <span class=m>· paper layouts: {e(', '.join(r['paperLayouts']))}</span>" if r.get("paperLayouts") else ""))
        a = r.get("audit")
        if a:
            row("Audit", "clean" if not (a["errors"] or a["fixes"]) else f"{a['errors']} errors, {a['fixes']} fixed on load <span class=m>(usually harmless bookkeeping)</span>")
        if r.get("missingLayers"):
            row("Undefined layers", e(", ".join(r["missingLayers"])) + " <span class=m>(used but not defined; drawn anyway)</span>")
        if r.get("contrastFixed"):
            bg = "dark" if self.dark else "light"
            row("Recoloured", f"{r['contrastFixed']:,} objects would be invisible on a {bg} background; shown {'white' if self.dark else 'black'}")
        if r.get("tiltedEntities"):
            row("Tilted", f"{r['tiltedEntities']:,} flat shapes sit on upright planes; laid flat to show them")
        if r.get("error"):
            row("Error", f"<span class=bad>{e(r['error'])}</span>")

        dups = []
        h = self.hashes.get(p)
        if h:
            dups = [q for q, hh in self.hashes.items() if hh == h and q != p]

        parts = [f"<h2>{e(p.name)}</h2>", f"<table>{''.join(rows)}</table>"]
        if dups:
            parts.append("<h3>Identical copies</h3>" + "<br>".join(e(str(q.relative_to(self.root))) for q in dups))
        if r.get("text"):
            parts.append("<h3>Text in the drawing</h3><div class=box>" + "<br>".join(e(t) for t in r["text"]) + "</div>")
        if r.get("entities"):
            parts.append("<h3>Entity types</h3><table>" + "".join(
                f"<tr><td>{e(k)}</td><td class=n>{v:,}</td></tr>" for k, v in r["entities"].items()) + "</table>")
        if r.get("blocks"):
            parts.append(f"<h3>Blocks used ({r.get('blockDefs', 0)} defined)</h3><table>" + "".join(
                f"<tr><td>{e(b['name'])}</td><td class=n>×{b['inserts']}</td></tr>" for b in r["blocks"]) + "</table>")
        if a and a.get("messages"):
            parts.append("<h3>Audit messages</h3><div class=box>" + "<br>".join(e(m) for m in a["messages"]) + "</div>")

        pal = self.palette()
        muted = pal.color(qg.QPalette.PlaceholderText).name()
        base = pal.color(qg.QPalette.Base)
        box = (base.lighter(150) if base.lightness() < 128 else base.darker(106)).name()   # readable in both themes
        css = (f"<style>body{{font-size:12.5px}} h2{{font-size:15px;margin:2px 0 8px}} "
               f"h3{{font-size:11px;color:{muted};text-transform:uppercase;margin:12px 0 3px}} "
               f"td{{padding:1px 8px 1px 0;vertical-align:top}} td.k{{color:{muted};white-space:nowrap}} td.n{{text-align:right;color:{muted}}} "
               f".m{{color:{muted}}} .bad{{color:#d33}} .box{{background:{box};padding:4px 6px}}</style>")
        self.info_view.setHtml(css + "".join(parts))

    # -- misc
    def reveal(self):
        if self.current:
            subprocess.run(["open", "-R", str(self.current)])

    def open_default(self):
        if self.current:
            subprocess.run(["open", str(self.current)])

    def closeEvent(self, ev):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("splitter", self.split.saveState())
        super().closeEvent(ev)


def human(n: int) -> str:
    return f"{n / 1e6:.1f} MB" if n >= 1e6 else f"{max(1, round(n / 1e3))} KB"


def swatch(color: str) -> qg.QIcon:
    pm = qg.QPixmap(14, 14); pm.fill(qc.Qt.transparent)
    p = qg.QPainter(pm); p.setRenderHint(qg.QPainter.Antialiasing)
    p.setPen(qg.QColor("#888")); p.setBrush(qg.QColor(color)); p.drawRoundedRect(1, 1, 12, 12, 3, 3); p.end()
    return qg.QIcon(pm)


class App(qw.QApplication):
    """Also accepts a folder dropped on the app's Dock icon."""
    folder_opened = qc.Signal(str)

    def event(self, ev):
        if ev.type() == qc.QEvent.FileOpen:
            self.folder_opened.emit(ev.file())
            return True
        return super().event(ev)


def main():
    try:   # make the macOS menu bar say "DXF Explorer" instead of "Python"
        from Foundation import NSBundle
        b = NSBundle.mainBundle()
        info = b.localizedInfoDictionary() or b.infoDictionary()
        if info is not None:
            info["CFBundleName"] = APP
    except Exception:
        pass
    app = App(sys.argv)
    app.setApplicationName(APP); app.setApplicationDisplayName(APP)
    icon = Path(__file__).with_name("icon.png")
    if icon.exists():
        app.setWindowIcon(qg.QIcon(str(icon)))
    args = [a for a in sys.argv[1:] if not a.startswith("-psn")]
    folder = Path(args[0]).expanduser() if args else None
    if folder and folder.is_file():
        folder = folder.parent
    w = Explorer(folder)
    app.folder_opened.connect(lambda f: w.open_folder(Path(f) if Path(f).is_dir() else Path(f).parent))
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
