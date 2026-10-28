"""Okno „Studio”: układ, grafika i sposób modelowania / szkicowania odtworzone z wersji HTML (natywnie, bez przeglądarki)."""
from __future__ import annotations
import math
from dataclasses import replace
from pathlib import Path
import numpy as np
from PySide6.QtCore import QEvent, QObject, QPoint, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QMatrix4x4, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QToolButton, QVBoxLayout, QWidget)
from . import kernel
from . import shell_ui as ui
from . import snap as snapping
icons_green = '#2fa56d'
icons_orange = '#f09a22'
from .document import Body, Document
from .viewcube import ViewCube
from . import sketchmeta as sm
from .viewport import CadView

NEED = {'rect': 2, 'centerRect': 2, 'rect3': 3, 'circle': 2, 'circle2': 2, 'circle3': 3, 'ellipse': 2, 'slot': 3, 'polygon': 2,
        'arc': 3, 'point': 1, 'construction': 2, 'measure': 2, 'text': 1, 'trim': 1, 'line': 2, 'circleTangent2': 3}
HINTS = {
    'rect': ['Kliknij pierwszy narożnik prostokąta.', 'Kliknij przeciwległy narożnik.'],
    'centerRect': ['Kliknij środek prostokąta.', 'Kliknij narożnik.'],
    'rect3': ['Kliknij pierwszy punkt podstawy.', 'Kliknij drugi punkt podstawy.', 'Kliknij punkt określający wysokość.'],
    'circle': ['Kliknij środek okręgu.', 'Kliknij punkt na okręgu (promień).'],
    'circle2': ['Kliknij pierwszy koniec średnicy.', 'Kliknij drugi koniec średnicy.'],
    'circle3': ['Kliknij pierwszy punkt okręgu.', 'Kliknij drugi punkt.', 'Kliknij trzeci punkt.'],
    'circleTangent2': ['Kliknij pierwszą linię.', 'Kliknij drugą linię.', 'Kliknij, aby wskazać wielkość okręgu.'],
    'ellipse': ['Kliknij środek elipsy.', 'Kliknij narożnik opisanego prostokąta.'],
    'slot': ['Kliknij środek pierwszego końca.', 'Kliknij środek drugiego końca.', 'Kliknij punkt określający szerokość.'],
    'polygon': ['Kliknij środek wielokąta.', 'Kliknij wierzchołek.'],
    'arc': ['Kliknij początek łuku.', 'Kliknij punkt na łuku.', 'Kliknij koniec łuku.'],
    'point': ['Kliknij miejsce punktu.'],
    'construction': ['Kliknij początek linii konstrukcyjnej.', 'Kliknij koniec.'],
    'measure': ['Kliknij pierwszy punkt pomiaru.', 'Kliknij drugi punkt.'],
    'text': ['Wpisz treść w panelu i kliknij miejsce na szkicu.'],
    'trim': ['Nożyczki: kliknij fragment szkicu, który ma zniknąć.'],
    'line': ['Kliknij początek linii.', 'Kliknij kolejny punkt. Enter lub ponowne kliknięcie kończy, kliknięcie w pierwszy punkt zamyka obrys.'],
}
VARIANT_LABELS = {'rect': '2 narożniki', 'centerRect': 'Od środka', 'rect3': '3 punkty', 'circle': 'Środek + promień',
                  'circleTangent2': 'Styczny do 2 elementów', 'circle2': 'Od 2 punktów', 'circle3': 'Od 3 punktów'}
DIM_LABELS = {'rect': ('Szerokość (mm)', 'Wysokość (mm)'), 'centerRect': ('Szerokość (mm)', 'Wysokość (mm)'), 'ellipse': ('Szerokość (mm)', 'Wysokość (mm)'),
              'circle': ('Promień (mm)',), 'polygon': ('Promień (mm)', 'Ilość kątów'), 'circle2': ('Średnica (mm)',),
              'line': ('Długość (mm)', 'Kąt (°)'), 'construction': ('Długość (mm)', 'Kąt (°)'), 'measure': ('Długość (mm)', 'Kąt (°)')}
AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
AXIS_COLORS = ((.89, .31, .33, 1), (.14, .64, .42, 1), (.2, .5, .9, 1))
TINT_BASE = (.30, .55, .95, 1)
TINT_TOOL = (.95, .55, .20, 1)
PREVIEW_BLUE = (.30, .62, .91, .73)
PREVIEW_TOL = .3
SKETCH_ORANGE = (.95, .55, .1, 1)


def fmt(value, digits=3):
    return f'{value:.{digits}f}'.replace('.', ',')


def kernel_close(a, b, tol=1e-3):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _merge_meshes(meshes):
    """Łączy kilka siatek podglądu w jedną."""
    if len(meshes) == 1:
        return meshes[0]
    vertices, triangles, edges, offset, key = [], [], {}, 0, 0
    for m in meshes:
        vertices.append(m.vertices)
        triangles.append(m.triangles + offset)
        offset += len(m.vertices)
        for points in m.edges.values():
            edges[key] = points
            key += 1
    return kernel.DisplayMesh(np.vstack(vertices), np.vstack(triangles), edges, meshes[0].center, meshes[0].size)


def profile_face(wire):
    """Powierzchnia ograniczona zamkniętym drutem (do podświetlania profilu)."""
    import cadquery as cq
    try:
        return cq.Face.makeFromWires(wire)
    except Exception:
        return None


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class _Work(QRunnable):
    def __init__(self, function):
        super().__init__()
        self.function = function
        self.signals = _Signals()

    def run(self):
        try:
            self.signals.done.emit(self.function())
        except Exception as exc:
            self.signals.failed.emit(str(exc) if isinstance(exc, kernel.CadError) else f'Operacja nie powiodła się: {exc}')


def _spin(value, low=-1e6, high=1e6, decimals=3, step=1.0):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setSingleStep(step)
    box.setValue(value)
    box.setButtonSymbols(QDoubleSpinBox.NoButtons)
    return box


def _label(text, name='label'):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.document = Document()
        self.pool = QThreadPool.globalInstance()
        self.busy = False
        self.selected: list[str] = []
        self.edges: dict[str, set] = {}
        self.mode = None            # None | plane | sketch | extrude | bool | mod | mirror | move | rotate
        self.tool = 'rect'
        self.sides = 5
        self.points: list[tuple[float, float]] = []
        self.last_uv = (0.0, 0.0)
        self.sketch_plane = None
        self.tangent_lines = []
        self.ex_profiles: list[dict] = []
        self._hv = None
        self.bool_ids: list[str] = []
        self.mirror_id = None
        self.mirror_frame = None
        self.override: dict[str, Body] = {}
        self.t_target = None
        self.t_center = np.zeros(3)
        self.t_mass = np.zeros(3)
        self.t_radius = 10.0
        self.clipboard: list[tuple] = []
        self._hover_key = None
        self._work = None
        self._popup = None
        self._planes_visible = True
        self._pv = {}
        self._region_cache = {}
        self._trim_cache = None
        self._snap_cache = None
        self.resize(1400, 850)
        self.setStyleSheet(ui.style())
        self.view = CadView(self)
        self.view.click_mode = True
        self.setCentralWidget(self.view)
        self.view.sketchMoved.connect(self.sketch_moved)
        self.view.sketchClicked.connect(self.sketch_clicked)
        self.view.viewClicked.connect(self.view_clicked)
        self.view.viewHover.connect(self.view_hover)
        self.view.contextRequested.connect(self.context_menu)
        self.view.handleDragged.connect(self.handle_dragged)
        self.view.handleReleased.connect(self.handle_released)
        self.view.pointDragged.connect(self.handle_point_dragged)
        self._build_overlays()
        self.view.installEventFilter(self)
        QApplication.instance().installEventFilter(self)
        self._timers = {}
        for name, slot in (('extrude', self.update_extrude_preview), ('mod', self.update_mod_preview), ('bool', self.update_bool_preview),
                           ('mirror', self.update_mirror_preview), ('transform', self.update_transform_preview), ('dim', self.update_dim_preview),
                           ('gizmo', self._place_gizmo)):
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(16 if name in ('extrude', 'mod') else 40)
            timer.timeout.connect(slot)
            self._timers[name] = timer
        for seq, fn in (('Ctrl+Z', self.undo), ('Ctrl+Y', self.redo), ('Ctrl+Shift+Z', self.redo), ('Ctrl+S', self.save_project),
                        ('Ctrl+O', self.open_project), ('Ctrl+N', self.new_project), ('Delete', self.delete_selected),
                        ('Ctrl+C', self.copy_selected), ('Ctrl+X', self.cut_selected), ('Ctrl+V', self.paste_clipboard)):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self.refresh(True)
        self.view.show_planes(True)
        self._layout_overlays()
        self.set_origin_text()

    # =====================================================================
    # budowa interfejsu (wymiary i kolory z CSS wersji HTML)
    # =====================================================================
    def _panel(self, width, title, kind='sketch', subtitle='', color=None):
        frame = QFrame(self.view)
        frame.setObjectName('panel')
        frame.setFixedWidth(width)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(16, 15, 16, 15)
        lay.setSpacing(11)
        lay.addWidget(ui.panel_header(kind, title, subtitle, color or ui.icons.BLUE))
        ui.shadow(frame, 26, 7, 46)
        frame.hide()
        return frame, lay

    @staticmethod
    def _field(layout, text, widget):
        layout.addWidget(_label(text))
        layout.addWidget(widget)
        return widget

    @staticmethod
    def _buttons(layout, first, second, on_first, on_second):
        row = QHBoxLayout()
        row.setSpacing(6)
        a, b = QPushButton(first), QPushButton(second)
        a.setObjectName('primary')
        a.clicked.connect(lambda _=False: on_first())
        b.clicked.connect(lambda _=False: on_second())
        row.addWidget(a)
        row.addWidget(b)
        layout.addLayout(row)
        return a, b

    def _build_overlays(self):
        v = self.view
        icons = [('file', ui.style_icon('file', 38), 'Plik'),
                 ('sketch', ui.style_icon('sketch', 38), 'Nowy szkic'),
                 ('extrude', ui.style_icon('extrude', 38), 'Wyciągnij'),
                 ('bool', ui.style_icon('bool', 38), 'Boolean / CSG'),
                 ('mod', ui.style_icon('mod', 38), 'Edytuj bryłę — zaokrąglenie i fazowanie'),
                 ('mirror', ui.style_icon('mirror', 38), 'Odbicie lustrzane')]
        self.tools = {}
        for key, icon, tip in icons:
            button = ui.big_tool(icon, tip, checkable=key != 'file')
            button.setParent(v)
            ui.shadow(button, 12, 3, 36)
            self.tools[key] = button
            if key != 'file':
                button.clicked.connect(lambda _=False, k=key: self.toggle_mode(k))
        self.tools['file'].clicked.connect(self.file_menu)

        self._build_shape_bar()

        undo_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path d="M11 8L5 14l6 6" fill="none" stroke="currentColor" stroke-width="2.6" '
                    'stroke-linecap="round" stroke-linejoin="round"/><path d="M5 14h13a7 7 0 0 1 0 14h-4" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>')
        redo_svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><path d="M21 8l6 6-6 6" fill="none" stroke="currentColor" stroke-width="2.6" '
                    'stroke-linecap="round" stroke-linejoin="round"/><path d="M27 14H14a7 7 0 0 0 0 14h4" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round"/></svg>')
        self.clear_button = self._round(ui.style_icon('trash', 24), 'Wyczyść całe pole', self.clear_all)
        self.undo_button = self._round(ui.style_icon('undo', 24), 'Cofnij (Ctrl+Z)', self.undo)
        self.redo_button = self._round(ui.style_icon('redo', 24), 'Ponów (Ctrl+Y)', self.redo)
        self.layers = QToolButton(v)
        self.layers.setObjectName('layers')
        self.layers.setCheckable(True)
        self.layers.setChecked(True)
        self.layers.setFixedSize(40, 40)
        self.layers.setIcon(ui.style_icon('layers', 26))
        self.layers.setIconSize(QSize(26, 26))
        self.layers.setToolTip('Pokaż / ukryj płaszczyzny')
        self.layers.toggled.connect(self._planes_toggled)
        ui.shadow(self.layers, 12, 3, 28)
        self.xray = QToolButton(v)
        self.xray.setObjectName('layers')
        self.xray.setCheckable(True)
        self.xray.setFixedSize(40, 40)
        xicon = QIcon()
        xicon.addPixmap(ui.icons.pixmap('xray', 26), QIcon.Normal, QIcon.Off)
        xicon.addPixmap(ui.icons.pixmap('xray_w', 26), QIcon.Normal, QIcon.On)
        xicon.addPixmap(ui.icons.pixmap('xray_w', 26), QIcon.Active, QIcon.On)
        self.xray.setIcon(xicon)
        self.xray.setIconSize(QSize(26, 26))
        self.xray.setToolTip('Przezroczyste bryły (podgląd ukrytych krawędzi)')
        self.xray.toggled.connect(self._xray_toggled)
        ui.shadow(self.xray, 12, 3, 28)
        self.home = QToolButton(v)
        self.home.setObjectName('home')
        self.home.setIcon(ui.style_icon('home', 24))
        self.home.setIconSize(QSize(24, 24))
        self.home.setFixedSize(36, 36)
        self.home.setToolTip('Widok domowy')
        self.home.clicked.connect(lambda: (self.view.set_view('iso'), self.view.fit_all(), self._mark_view('iso')))
        ui.shadow(self.home, 12, 3, 28)

        # kostka orientacji (jak ViewCube w Fusion 360): obraca się z kamerą, ściana / narożnik = widok
        self.cube = ViewCube(self.view, v)
        ui.shadow(self.cube, 22, 5, 32)
        self.cube_buttons = {}
        self.cube.faceClicked.connect(self._cube_clicked)
        self.cube.directionClicked.connect(lambda az, el: (self.view.setCameraPosition(azimuth=az, elevation=el), self.view.update()))
        self.cube.rotateClicked.connect(self._cube_rotate)
        self.view.cameraMoved.connect(self.cube.update)
        self.view.cameraMoved.connect(self._camera_changed)

        # pasek transformacji (przesuń / obróć)
        self.pad = QFrame(v)
        self.pad.setObjectName('bar')
        pl = QHBoxLayout(self.pad)
        pl.setContentsMargins(7, 7, 7, 7)
        pl.setSpacing(7)
        self.pad_buttons = {}
        for name, text, tip in (('move', 'Przesuń', 'Przesuń zaznaczony element w osiach X, Y, Z'), ('rotate', 'Obróć', 'Obróć zaznaczony element')):
            button = QToolButton()
            button.setObjectName('padTool')
            button.setIcon(ui.style_icon(name, 26))
            button.setIconSize(QSize(26, 26))
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setText(' ' + text)
            button.setCheckable(True)
            button.setFixedSize(112, 44)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, n=name: self.toggle_mode(n))
            pl.addWidget(button)
            self.pad_buttons[name] = button
        ui.shadow(self.pad, 19, 5, 43)
        self.pad.adjustSize()

        # edytor transformacji nad paskiem
        self.t_editor = QFrame(v)
        self.t_editor.setObjectName('bar')
        tl = QHBoxLayout(self.t_editor)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.setSpacing(8)
        self.t_status = QLabel('Kliknij obiekt, aby go zaznaczyć')
        self.t_status.setMinimumWidth(175)
        tl.addWidget(self.t_status)
        self.t_spins = []
        self.t_axis_labels = []
        for axis in 'XYZ':
            label = QLabel(axis)
            spin = _spin(0, -1e6, 1e6, 3, 1.0)
            spin.setFixedWidth(78)
            spin.valueChanged.connect(lambda *_: self._transform_changed())
            tl.addWidget(label)
            tl.addWidget(spin)
            self.t_axis_labels.append(label)
            self.t_spins.append(spin)
        for text, cb in (('Zastosuj', self.apply_transform), ('Anuluj', lambda: self.set_mode(None))):
            b = QPushButton(text)
            b.setObjectName('primary' if text == 'Zastosuj' else 'ghost')
            b.clicked.connect(lambda _=False, f=cb: f())
            tl.addWidget(b)
        ui.shadow(self.t_editor, 20, 5, 45)
        self.t_editor.hide()
        self.t_editor.adjustSize()

        # pasek szkicu (jak 'Finish Sketch' w Fusion 360)
        self.sk_bar = QFrame(v)
        self.sk_bar.setObjectName('skbar')
        sl = QHBoxLayout(self.sk_bar)
        sl.setContentsMargins(12, 9, 12, 9)
        sl.setSpacing(10)
        self.sk_badge = QLabel()
        self.sk_badge.setPixmap(ui.icons.badge('sketch', ui.icons.BLUE, 42))
        self.sk_title = QLabel('Szkic')
        self.sk_title.setStyleSheet('font-weight:700;font-size:13px;')
        self.sk_hint = QLabel('')
        self.sk_hint.setStyleSheet('color:#6c869b;')
        finish = QPushButton('✓  Zakończ szkic')
        finish.setObjectName('primary')
        finish.clicked.connect(lambda _=False: self.set_mode(None))
        for w in (self.sk_badge, self.sk_title, self.sk_hint, finish):
            sl.addWidget(w)
        ui.shadow(self.sk_bar, 22, 6, 44)
        self.sk_bar.hide()

        self.origin_label = QLabel(v)
        self.origin_label.setObjectName('origin')
        self.notice = QLabel(v)
        self.notice.setObjectName('notice')
        self.notice.hide()
        ui.shadow(self.notice, 18, 5, 32)
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.notice.hide)
        self.dim = QLabel(v)
        self.dim.setObjectName('dim')
        self.dim.hide()
        self.dim.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._build_dim_panel()
        self._build_panels()

    def _round(self, icon, tip, callback):
        button = QToolButton(self.view)
        button.setObjectName('round')
        button.setIcon(icon)
        button.setIconSize(QSize(24, 24))
        button.setFixedSize(40, 40)
        button.setToolTip(tip)
        button.clicked.connect(lambda _=False: callback())
        ui.shadow(button, 12, 3, 36)
        return button

    def _build_shape_bar(self):
        self.shape_bar = QFrame(self.view)
        self.shape_bar.setObjectName('toolbar')
        lay = QVBoxLayout(self.shape_bar)
        lay.setContentsMargins(7, 7, 7, 7)
        lay.setSpacing(8)
        self.shape_buttons = {}
        shapes = ui.load_shapes()
        variants: dict[str, list] = {}
        for item in shapes:
            if item['variant']:
                variants.setdefault(item['group'], []).append(item)
        for item in shapes:
            if item['variant']:
                continue
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(0)
            grouped = bool(item['group'] and variants.get(item['group']))
            button = QToolButton()
            button.setObjectName('shapeMain')
            button.setProperty('grouped', 'true' if grouped else 'false')
            button.setCheckable(True)
            button.setFixedSize(34 if grouped else 42, 42)
            button.setIcon(ui.style_icon('s_' + item['shape'], 28))
            button.setIconSize(QSize(28, 28))
            button.setToolTip(item['title'])
            button.clicked.connect(lambda _=False, name=item['shape']: self._tool_clicked(name))
            hl.addWidget(button)
            self.shape_buttons[item['shape']] = button
            if grouped:
                more = QToolButton()
                more.setObjectName('shapeExpand')
                more.setText('▾')
                more.setFixedSize(15, 42)
                more.setToolTip('Warianty')
                more.clicked.connect(lambda _=False, g=item['group'], b=more, main=button: self._variants_menu(variants[g], b, main))
                hl.addWidget(more)
            lay.addWidget(row)
        ui.shadow(self.shape_bar, 15, 4, 36)
        self.shape_bar.adjustSize()
        self.shape_bar.hide()

    VARIANT_HINTS = {'rect': 'Przeciągnij przekątną', 'centerRect': 'Środek i narożnik', 'rect3': 'Podstawa i wysokość',
                     'circle': 'Środek i punkt na okręgu', 'circleTangent2': 'Kliknij dwie linie i wielkość', 'circle2': 'Końce średnicy',
                     'circle3': 'Trzy punkty na okręgu'}

    VARIANT_ICONS = {'rect': 'v_rect2', 'centerRect': 'v_rectC', 'rect3': 'v_rect3', 'circle': 'v_circle', 'circle2': 'v_circle2', 'circle3': 'v_circle3',
                     'circleTangent2': 'v_tan'}

    def _variants_menu(self, items, anchor, main):
        entries = []
        for item in items:
            name = item['shape']
            icon = ui.icons.pixmap(self.VARIANT_ICONS.get(name, 'v_rect2'), 34)
            entries.append((icon, VARIANT_LABELS.get(name, item['title']), self.VARIANT_HINTS.get(name, ''), lambda n=name: self.choose_tool(n, main)))
        menu = ui.RichMenu(self, entries, 'Sposób rysowania', 290)
        self._popup = menu
        menu.popup_at(anchor.mapToGlobal(QPoint(anchor.width() + 8, 0)))

    def _build_dim_panel(self):
        self.dim_panel = QFrame(self.view)
        self.dim_panel.setObjectName('dimpanel')
        lay = QHBoxLayout(self.dim_panel)
        lay.setContentsMargins(13, 11, 13, 11)
        lay.setSpacing(8)
        self.dim_labels, self.dim_edits = [], []
        for _ in range(3):
            col = QVBoxLayout()
            col.setSpacing(4)
            label = QLabel('')
            edit = QLineEdit()
            edit.textChanged.connect(lambda *_: self._timers['dim'].start())
            edit.returnPressed.connect(self.apply_typed)
            col.addWidget(label)
            col.addWidget(edit)
            lay.addLayout(col)
            self.dim_labels.append(label)
            self.dim_edits.append(edit)
        help_ = QLabel('Tab: kolejne pole\nEnter: zatwierdź\nEsc: anuluj')
        help_.setObjectName('help')
        lay.addWidget(help_)
        ui.shadow(self.dim_panel, 20, 5, 37)
        self.dim_panel.hide()
        self.dim_edit = self.dim_edits[0]   # zgodność wsteczna
        self._dim_target = None
        self.dim_panel.installEventFilter(self)

    def _build_panels(self):
        # --- wyciągnięcie: panel opcji + górny pasek ---
        self.ex_panel, lay = self._panel(312, 'Wyciągnięcie', 'extrude' if False else 'one', 'Profil lub ściana → bryła')
        lay.setSpacing(11)
        self.ex_op = ui.Segmented([('Nowa', 'new', 'new'), ('Połącz', 'join', 'join'), ('Wytnij', 'cut', 'cut'), ('Wspólna', 'intersect', 'intersect')], 32)
        self._field(lay, 'Operacja', self.ex_op)
        self.ex_dir = ui.Segmented([('Jedna strona', 'one', 'one'), ('Symetrycznie', 'symmetric', 'sym'), ('Dwie strony', 'two', 'two')], 32)
        self._field(lay, 'Kierunek', self.ex_dir)
        self.ex_status = _label('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.', 'status')
        lay.addWidget(self.ex_status)
        self.ex_bar = QFrame(self.view)
        self.ex_bar.setObjectName('bar')
        bar = QHBoxLayout(self.ex_bar)
        bar.setContentsMargins(12, 10, 12, 10)
        bar.setSpacing(8)
        strong = QLabel('Wyciągnięcie')
        strong.setStyleSheet('font-weight:700;font-size:13px;color:#000;')
        bar.addWidget(strong)
        bar.addWidget(QLabel('Odległość (mm)'))
        self.ex_value = _spin(10, -1e5, 1e5, 3, 1.0)
        self.ex_value.setFixedWidth(105)
        bar.addWidget(self.ex_value)
        self.ex_second_label = QLabel('Druga strona (mm)')
        bar.addWidget(self.ex_second_label)
        self.ex_second = _spin(10, 0, 1e5, 3, 1.0)
        self.ex_second.setFixedWidth(105)
        bar.addWidget(self.ex_second)
        for text, cb in (('Zastosuj', self.apply_extrude), ('Anuluj', lambda: self.set_mode(None))):
            b = QPushButton(text)
            b.setObjectName('primary' if text == 'Zastosuj' else 'ghost')
            b.clicked.connect(lambda _=False, f=cb: f())
            bar.addWidget(b)
        ui.shadow(self.ex_bar, 24, 7, 64)
        self.ex_bar.hide()
        for w in (self.ex_value, self.ex_second):
            w.valueChanged.connect(lambda *_: self._ex_value_changed())
        self.ex_dir.currentIndexChanged.connect(self._ex_dir_changed)
        self.ex_op.currentIndexChanged.connect(lambda *_: (self._ex_op_user_changed(), self._timers['extrude'].start()))
        self.ex_second_label.hide()
        self.ex_second.hide()

        # --- boolean ---
        self.bool_panel, lay = self._panel(312, 'Boolean / CSG', 'union', 'Łączenie, odejmowanie, część wspólna', icons_green)
        self.bool_op = ui.Segmented([('Suma', 'union', 'union'), ('Różnica', 'subtract', 'subtract'), ('Część wspólna', 'intersect', 'common')], 36)
        self._field(lay, 'Operacja', self.bool_op)
        self.bool_status = _label('', 'status')
        lay.addWidget(self.bool_status)
        self.bool_keep = QCheckBox('Zachowaj bryły-narzędzia')
        lay.addWidget(self.bool_keep)
        self._buttons(lay, 'Zastosuj', 'Anuluj', self.apply_bool, lambda: self.set_mode(None))
        self.bool_op.currentIndexChanged.connect(lambda *_: self._timers['bool'].start())

        # --- edytuj bryłę ---
        self.mod_panel, lay = self._panel(312, 'Edytuj bryłę', 'fillet', 'Zaokrąglenie i fazowanie krawędzi', icons_orange)
        self.mod_kind = ui.Segmented([('Zaokrąglij', 'fillet', 'fillet'), ('Fazuj', 'chamfer', 'chamfer')], 36)
        self._field(lay, 'Operacja', self.mod_kind)
        self.mod_label = _label('Promień zaokrąglenia (mm)')
        self.mod_size = _spin(3, .01, 1e5, 3, .5)
        lay.addWidget(self.mod_label)
        lay.addWidget(self.mod_size)
        self.mod_status = _label('Kliknij krawędź (lub kilka krawędzi) bryły.', 'status')
        lay.addWidget(self.mod_status)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_mod, lambda: self.set_mode(None))
        self.mod_size.valueChanged.connect(lambda *_: self._mod_value_changed())
        self.mod_kind.currentIndexChanged.connect(self._mod_kind_changed)

        # --- odbicie lustrzane ---
        self.mir_panel, lay = self._panel(312, 'Odbicie lustrzane', 'mirror', 'Obiekt → ściana-lustro', icons_green)
        self.mir_step1 = ui.StepRow(1, 'mirror', 'Obiekt do odbicia')
        self.mir_step2 = ui.StepRow(2, 'sym', 'Ściana-lustro')
        lay.addWidget(self.mir_step1)
        lay.addWidget(self.mir_step2)
        self.mir_keep = QCheckBox('Zachowaj oryginał (kopia)')
        self.mir_keep.setChecked(True)
        lay.addWidget(self.mir_keep)
        self.mir_join = QCheckBox('Połącz z oryginałem w jedną bryłę')
        lay.addWidget(self.mir_join)
        reset = QPushButton('Zmień obiekt')
        reset.clicked.connect(lambda _=False: self.reset_mirror())
        lay.addWidget(reset)
        self._buttons(lay, 'Zastosuj', 'Zamknij', self.apply_mirror, lambda: self.set_mode(None))
        self.mir_keep.toggled.connect(lambda *_: self._timers['mirror'].start())
        self.mir_join.toggled.connect(lambda *_: self._timers['mirror'].start())

        # --- tekst ---
        self.text_panel, lay = self._panel(300, 'Tekst', 'sketch', 'Kontury liter jako profile')
        self.text_edit = QPlainTextEdit('Tekst')
        self.text_edit.setFixedHeight(54)
        self._field(lay, 'Treść', self.text_edit)
        row = QHBoxLayout()
        row.setSpacing(8)
        col1, col2 = QVBoxLayout(), QVBoxLayout()
        self.text_size = _spin(10, .1, 1000, 2, 1)
        self.text_angle = _spin(0, -360, 360, 1, 5)
        col1.addWidget(_label('Wysokość liter (mm)'))
        col1.addWidget(self.text_size)
        col2.addWidget(_label('Obrót (°)'))
        col2.addWidget(self.text_angle)
        row.addLayout(col1)
        row.addLayout(col2)
        lay.addLayout(row)
        self.text_font = QComboBox()
        for label, key in (('Sans (DejaVu)', 'sans'), ('Sans pogrubiona', 'bold'), ('Szeryfowa', 'serif')):
            self.text_font.addItem(label, key)
        self._field(lay, 'Czcionka', self.text_font)
        self.text_align = QComboBox()
        for label, key in (('Do lewej', 'left'), ('Do środka', 'center'), ('Do prawej', 'right')):
            self.text_align.addItem(label, key)
        self._field(lay, 'Wyrównanie względem klikniętego punktu', self.text_align)
        close = QPushButton('Zamknij narzędzie')
        close.clicked.connect(lambda _=False: self.choose_tool('rect'))
        lay.addWidget(close)

        self.panels = (self.ex_panel, self.ex_bar, self.bool_panel, self.mod_panel, self.mir_panel, self.text_panel)
        for p in self.panels:
            p.adjustSize()

    def _layout_overlays(self):
        W, H = self.view.width(), self.view.height()
        for i, key in enumerate(('file', 'sketch', 'extrude', 'bool', 'mod', 'mirror')):
            self.tools[key].move(18 + 60 * i, 18)
        self.shape_bar.move(18, 80)
        self.clear_button.move(W - 446, 20)
        self.undo_button.move(W - 398, 20)
        self.redo_button.move(W - 350, 20)
        self.layers.move(W - 302, 20)
        self.xray.move(W - 254, 20)
        self.home.move(W - 205, 20)
        self.cube.move(W - 160, 20)
        self.pad.adjustSize()
        self.pad.move((W - self.pad.width()) // 2, H - 113 - self.pad.height())
        self.t_editor.adjustSize()
        self.t_editor.move(max(10, (W - self.t_editor.width()) // 2), H - 166 - self.t_editor.height())
        self.sk_bar.adjustSize()
        self.sk_bar.move(max(400, (W - self.sk_bar.width()) // 2), 18)
        self.origin_label.adjustSize()
        self.origin_label.move(W - 18 - self.origin_label.width(), H - 15 - self.origin_label.height())
        self.notice.adjustSize()
        self.notice.move(W - 18 - self.notice.width(), H - 22 - self.notice.height())
        for p in (self.bool_panel, self.mod_panel, self.mir_panel):
            p.adjustSize()
            p.move(18, 88)
        self.text_panel.adjustSize()
        self.text_panel.move(92, 88)
        self.ex_panel.adjustSize()
        self.ex_panel.move(18, 170)
        self.ex_bar.adjustSize()
        self.ex_bar.move(346, 170)
        for w in (*self.tools.values(), self.shape_bar, self.clear_button, self.undo_button, self.redo_button, self.layers, self.xray, self.home, self.cube, self.pad,
                  self.t_editor, self.sk_bar, self.origin_label, *self.panels, self.dim_panel, self.dim, self.notice):
            w.raise_()

    def eventFilter(self, obj, event):
        if not hasattr(self, '_dim_target'):
            return super().eventFilter(obj, event)
        if obj is self.dim_panel and event.type() == QEvent.Hide and self._dim_target is not None:
            self._dim_target = None
            self.view.set_preview_mesh(None)
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Tab and self.isActiveWindow() and not self.busy and not isinstance(QApplication.focusWidget(), QPlainTextEdit):
            if self.dim_panel.isVisible():
                edits = [e for e in self.dim_edits if e.isVisible()]
                if len(edits) > 1:
                    index = next((i for i, e in enumerate(edits) if e.hasFocus()), -1)
                    edits[(index + 1) % len(edits)].setFocus()
                    edits[(index + 1) % len(edits)].selectAll()
                return True
            if self.mode == 'sketch' and self.points and self.open_dim_input():
                return True
            if self.mode in (None, 'sketch') and not self.points and not self.tangent_lines and self.tool not in ('trim',):
                if self.mode is None and not self.selected and self._sketch_edit_target() is None:
                    return super().eventFilter(obj, event)
                if self.open_dim_edit():
                    return True
        if event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.isActiveWindow() and not self.busy:
            action = {'extrude': self.apply_extrude, 'bool': self.apply_bool, 'mod': self.apply_mod, 'mirror': self.apply_mirror,
                      'move': self.apply_transform, 'rotate': self.apply_transform}.get(self.mode)
            focus = QApplication.focusWidget()
            if action and not isinstance(focus, QPlainTextEdit) and (focus is None or self.isAncestorOf(focus) or focus is self):
                action()
                return True
        if obj is self.view and event.type() == QEvent.Resize:
            self._layout_overlays()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_overlays()

    # =====================================================================
    # komunikaty
    # =====================================================================
    def hint(self, text):
        pass  # podpowiedzi przeniesione do samouczka (Plik → Pomoc)

    def toast(self, text, ms=4500):
        self.notice.setText(text)
        self.notice.adjustSize()
        self.notice.show()
        self._layout_overlays()
        self.notice_timer.start(ms)

    def set_origin_text(self, text=None):
        self.origin_label.setText(text or 'Płaszczyzny XY · XZ · YZ')
        self._layout_overlays()

    # =====================================================================
    # widok: kostka, płaszczyzny
    # =====================================================================
    def _mark_view(self, name):
        pass

    CUBE_PLANES = {'Z': 'XY', '-Z': 'XY', 'X': 'YZ', '-X': 'YZ', 'Y': 'XZ', '-Y': 'XZ'}

    def _cube_clicked(self, name):
        if self.mode == 'plane' and name in self.CUBE_PLANES and not self.busy:
            # przy wyborze płaszczyzny ściana kostki wybiera płaszczyznę szkicu (kamera patrzy na nią z wybranej strony)
            self.enter_sketch(self.CUBE_PLANES[name])
            self.view.set_view(name)
            self._mark_view(name)
            return
        self.view.set_view(name)
        self._mark_view(name)

    def _planes_toggled(self, on):
        self._planes_visible = on
        if self.mode == 'sketch':
            # zmiana płaszczyzny w trakcie szkicu: kliknij płaszczyznę lub ścianę
            self.view.show_planes(on)
            self.view.plane_pick = bool(on)
            self.view.setCursor(Qt.PointingHandCursor if on else Qt.ArrowCursor)
            if on:
                self.toast('Kliknij płaszczyznę lub płaską ścianę, aby szkicować gdzie indziej.', 3500)
        elif self.mode != 'plane':
            self.view.show_planes(on)

    def _xray_toggled(self, on):
        self.view.set_xray(on)

    def _camera_changed(self):
        """Uchwyty przesuwania / obrotu skalują się z odległością kamery, żeby były zawsze wygodne do złapania."""
        if self.mode in ('move', 'rotate') and self.t_target is not None and self._hv is None and not self.view._handle_drag:
            if not self._timers['gizmo'].isActive():
                self._timers['gizmo'].start()

    # =====================================================================
    # tryby
    # =====================================================================
    def toggle_mode(self, key):
        if self.busy:
            return
        target = 'plane' if key == 'sketch' else key
        current = 'plane' if self.mode == 'sketch' else self.mode
        if current == target:
            self.set_mode(None)
            return
        self.set_mode(target)
        # płaszczyznę wybieramy tylko na początku szkicowania; potem szkic wraca na ostatnią (zmiana: kostka, przycisk płaszczyzn albo ściana)
        last = getattr(self, '_last_sketch_plane', None)
        if target == 'plane' and last is not None:
            self.enter_sketch(last)
            self.layers.setChecked(True)   # włącza wybór: klik w płaszczyznę lub ścianę bryły zmienia powierzchnię szkicu
            self.toast('Kliknij ścianę bryły lub płaszczyznę, by szkicować gdzie indziej – albo zacznij rysować na bieżącej.', 4500)

    def set_mode(self, mode):
        """Przełącza narzędzie; None = zwykłe zaznaczanie."""
        if self.busy:
            return
        self.override = {}
        self.view.clear_body_matrices()
        self.cancel_previews()
        self.view.snapper = None
        self.view.hover_gate = None
        self.view.free_drag = None
        self.mode = mode
        self.points = []
        self.tangent_lines = []
        self._hv = None
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        self.view.set_selection_meshes(None)
        self.view.drag_hook = None
        self.view.sketch_grips = []
        self.view.set_handles([])
        self.view.set_marker(None)
        self.view.sketch_plane = None
        self.view.sketch_tool = None
        self.view.plane_pick = False
        self.view.edge_mode = False
        self.view.tints = {}
        self.view.show_custom_plane(None)
        self.view.set_grid_frame(None)
        self.sketch_plane = None
        self.ex_profiles = []
        self.bool_ids = []
        self.mirror_id = None
        self.mirror_frame = None
        self.t_target = None
        self.edges = {}
        self._hover_key = None
        for key, button in self.tools.items():
            if key != 'file':
                button.setChecked(key == ('sketch' if mode == 'plane' else mode))
        for key, button in self.pad_buttons.items():
            button.setChecked(key == mode)
        for p in (self.shape_bar, self.t_editor, self.sk_bar, *self.panels):
            p.hide()
        self.view.show_planes(self._planes_visible)
        self.view.setCursor(Qt.ArrowCursor)
        self.set_origin_text()
        if mode == 'plane':
            self.view.plane_pick = True
            self.view.show_planes(True)
            self.view.setCursor(Qt.PointingHandCursor)
            self.shape_bar.show()
            self.hint('Wybierz płaszczyznę XY, XZ lub YZ albo kliknij ścianę bryły, aby rozpocząć szkic.')
        elif mode == 'extrude':
            self.ex_panel.show()
            self.ex_status.setText('Kliknij zamknięty profil szkicu lub płaską ścianę bryły.')
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Wyciągnięcie: kliknij profil szkicu lub ścianę bryły.')
        elif mode == 'bool':
            self.bool_panel.show()
            self.update_bool_status()
            self.hint('Boolean: kliknij bryłę bazową, potem bryły-narzędzia.')
        elif mode == 'mod':
            self.mod_panel.show()
            self.view.edge_mode = True
            self.mod_size.blockSignals(True)
            self.mod_size.setValue(2.0)
            self.mod_size.blockSignals(False)
            self._mod_kind_changed()
            self.update_mod_status()
            self.hint('Edytuj bryłę: kliknij krawędź. Shift + klik dodaje kolejne.')
        elif mode == 'mirror':
            self.mir_panel.show()
            self.update_mirror_status()
            self.hint('Lustro: kliknij bryłę, a potem ścianę, względem której ma nastąpić odbicie.')
        elif mode in ('move', 'rotate'):
            self.t_editor.show()
            self.t_status.setText('Kliknij obiekt, aby go zaznaczyć')
            for label, axis in zip(self.t_axis_labels, 'XYZ'):
                label.setText(axis + ('°' if mode == 'rotate' else ''))
            for spin in self.t_spins:
                spin.blockSignals(True)
                spin.setValue(0)
                spin.blockSignals(False)
            self.view.setCursor(Qt.PointingHandCursor)
            self.hint('Kliknij bryłę lub szkic, który chcesz ' + ('przesunąć.' if mode == 'move' else 'obrócić.'))
            if self.selected:
                body = self.document.get(self.selected[0])
                if body is not None:
                    self.select_transform_target(body)
        self.refresh()
        self._layout_overlays()

    # =====================================================================
    # szkic
    # =====================================================================
    def _tool_clicked(self, name):
        """Ponowne kliknięcie aktywnego narzędzia wyłącza je (zostaje sam szkic: zaznaczanie i skalowanie kształtów)."""
        self._end_plane_pick()
        if self.tool is not None and (self.tool == name or self._group_button(self.tool) == name):
            self.choose_tool(None)
        else:
            self.choose_tool(name)

    def _end_plane_pick(self):
        if self.mode == 'sketch' and self.view.plane_pick:
            self.layers.setChecked(False)

    def choose_tool(self, name, button=None):
        if name is not None and self.mode == 'sketch' and self.selected:
            self.selected = []
            self.refresh()
        self.tool = name
        self.points = []
        self.tangent_lines = []
        self.text_panel.setVisible(name == 'text')
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        self.view.sketch_tool = name
        main = button or self.shape_buttons.get(self._group_button(name))
        for b in self.shape_buttons.values():
            b.setChecked(b is main)
        if self.mode == 'sketch':
            self.show_sketch_hint()
            self.sk_hint.setText('Wybierz kształt do rysowania' if name is None and not self.selected else
                                 ('Tab – wymiary · przeciągnij krawędź – skaluj' if name is None else 'Rysuj na płaszczyźnie; Esc kończy kształt'))
        self._update_grips()
        self._layout_overlays()

    @staticmethod
    def _group_button(name):
        return {'centerRect': 'rect', 'rect3': 'rect', 'circle2': 'circle', 'circle3': 'circle', 'circleTangent2': 'circle'}.get(name, name)

    def show_sketch_hint(self):
        texts = HINTS.get(self.tool, [''])
        self.hint(texts[min(len(self.points) + len(self.tangent_lines), len(texts) - 1)])

    def _plane_label(self):
        return self.sketch_plane if isinstance(self.sketch_plane, str) else 'ściana'

    def pick_surface(self, x, y):
        """Płaszczyzna szkicu spod kursora: płaska ściana bryły (Frame) albo jedna z płaszczyzn XY / XZ / YZ."""
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is not None and body.kind == 'solid':
            try:
                face, normal = kernel.face_at(body.shape, hit[1], hit[2])
                return kernel.face_frame(face.Center().toTuple(), normal), face
            except kernel.CadError:
                return None, None
        return self.view.plane_at(x, y), None

    def enter_sketch(self, plane):
        self.mode = 'sketch'
        self._last_sketch_plane = plane
        self.sketch_plane = plane
        self.view.plane_pick = False
        self.view.sketch_plane = plane
        self.view.snapper = self._snapper
        self.view.hover_gate = self.sketch_hover_wanted
        self.view.drag_hook = self._sketch_hook
        self._sk_drag = None
        self.view.show_planes(False)
        self.layers.blockSignals(True)
        self.layers.setChecked(False)
        self.layers.blockSignals(False)
        self._planes_visible = False
        self.view.set_preview_mesh(None)
        self.view.look_along(plane)
        self.view.set_grid_frame(plane)
        self._mark_view(None)
        self.view.setCursor(Qt.ArrowCursor)
        self.points = []
        self.shape_bar.show()
        self.sk_bar.show()
        self.sk_title.setText(f'Szkic · płaszczyzna {self._plane_label()}')
        self.sk_hint.setText('Rysuj na płaszczyźnie; Esc kończy kształt')
        self.set_origin_text(f'Szkic · płaszczyzna {self._plane_label()}')
        self.choose_tool(self.tool)

    def plane_picked(self, name):
        self.enter_sketch(name)

    def _snapper(self, x, y, raw):
        key = (self.sketch_plane if isinstance(self.sketch_plane, str) else id(self.sketch_plane),
               tuple((b.id, id(b.mesh)) for b in self.document.bodies if b.kind == 'sketch'))
        if self._snap_cache is None or self._snap_cache[0] != key:
            self._snap_cache = (key, snapping.SketchGeometry(self.document.bodies, self.sketch_plane))
        return snapping.snap(self.view, self.sketch_plane, self._snap_cache[1], x, y, raw)

    def _wire(self, points):
        t = self.tool
        if t in ('line', 'construction'):
            return kernel.polyline(self.sketch_plane, points, False)
        if t == 'arc':
            return kernel.arc3(self.sketch_plane, points)
        if t == 'rect3':
            return kernel.rect3(self.sketch_plane, points)
        if t == 'point':
            return kernel.point_marker(self.sketch_plane, points[0])
        return kernel.sketch_shape(t, self.sketch_plane, points, self.sides)

    def _preview_points(self, pts):
        t, need = self.tool, NEED.get(self.tool, 2)
        if t == 'line':
            return kernel.polyline(self.sketch_plane, pts) if len(pts) >= 2 else None
        if t == 'measure':
            return kernel.polyline(self.sketch_plane, pts) if len(pts) == 2 else None
        if t in ('text', 'trim', 'circleTangent2', 'point'):
            return None
        if len(pts) == need:
            return self._wire(pts)
        if t == 'circle3' and len(pts) == 2:
            return kernel.sketch_shape('circle2', self.sketch_plane, pts)
        if t in ('arc', 'rect3', 'slot') and len(pts) == 2:
            return kernel.polyline(self.sketch_plane, pts)
        return None

    def _show_sketch_preview(self, pts):
        try:
            shape = self._preview_points(pts)
            mesh = kernel.display_mesh(shape) if shape is not None else None
        except Exception:
            mesh = None
        self.view.set_preview_mesh(mesh, line_color=SKETCH_ORANGE, width=2, dashed=True)

    def sketch_moved(self, plane, u, v):
        if self.mode != 'sketch' or self.busy:
            return
        self.last_uv = (u, v)
        drawing = bool(self.points) or (self.tool == 'circleTangent2' and bool(self.tangent_lines))
        self.view.set_marker(kernel.to_world(self.sketch_plane, u, v), label=self.view.snap_label)
        if self.tool == 'trim':
            self.trim_preview()
            return
        if self.tool == 'circleTangent2':
            if len(self.tangent_lines) == 2:
                try:
                    shape = kernel.circle_tangent2(self.sketch_plane, *self.tangent_lines, (u, v))
                    self.view.set_preview_mesh(kernel.display_mesh(shape), line_color=SKETCH_ORANGE, width=2, dashed=True)
                except kernel.CadError:
                    self.view.set_preview_mesh(None)
            return
        if not self.points or self.dim_panel.isVisible():
            return          # wartości wpisane z klawiatury mają pierwszeństwo przed kursorem
        pts = [*self.points, (u, v)]
        self._show_sketch_preview(pts)
        self.show_dimension(pts)

    def show_dimension(self, pts):
        a, b = self.points[0], pts[-1]
        if self.tool == 'line' and len(pts) > 2:
            a = pts[-2]
        du, dv = abs(b[0] - a[0]), abs(b[1] - a[1])
        dist = math.hypot(b[0] - a[0], b[1] - a[1])
        if self.tool in ('rect', 'ellipse'):
            text = f'{fmt(du)} × {fmt(dv)} mm'
        elif self.tool == 'centerRect':
            text = f'{fmt(2 * du)} × {fmt(2 * dv)} mm'
        elif self.tool in ('circle', 'polygon'):
            text = f'R {fmt(dist)} mm'
        elif self.tool == 'circle2':
            text = f'Ø {fmt(dist)} mm'
        else:
            text = f'{fmt(dist)} mm'
        self.dim.setText(text)
        self.dim.adjustSize()
        pos = self.view.mapFromGlobal(QCursor.pos())
        self.dim.move(pos.x() + 14, pos.y() + 12)
        self.dim.show()
        self.dim.raise_()

    def _cursor_edge(self):
        pos = self.view.mapFromGlobal(QCursor.pos())
        return self.view.nearest_edge(pos.x(), pos.y())

    def _edge_line(self):
        hit = self._cursor_edge()
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'sketch':
            raise kernel.CadError('Kliknij prostą linię narysowanego szkicu.')
        edge = body.shape.Edges()[hit[1]]
        if edge.geomType() != 'LINE':
            raise kernel.CadError('Wybierz prostą linię (nie łuk ani okrąg).')
        return kernel.uv_of(self.sketch_plane, edge.startPoint().toTuple()), kernel.uv_of(self.sketch_plane, edge.endPoint().toTuple())

    def sketch_clicked(self, plane, u, v):
        if self.mode != 'sketch' or self.busy:
            return
        t = self.tool
        try:
            if t == 'trim':
                self.trim_at_cursor()
                return
            if t == 'circleTangent2':
                if len(self.tangent_lines) < 2:
                    self.tangent_lines.append(self._edge_line())
                    self.show_sketch_hint()
                    return
                shape = kernel.circle_tangent2(self.sketch_plane, *self.tangent_lines, (u, v))
                self.tangent_lines = []
                self.view.set_preview_mesh(None)
                self.create_sketch([shape])
                return
            if t == 'text':
                font = self.text_font.currentData()
                shapes = kernel.text_shape(self.sketch_plane, self.text_edit.toPlainText().replace('\n', ' '), u, v, self.text_size.value(),
                                           font='Serif' if font == 'serif' else 'Sans', bold=font == 'bold',
                                           halign=self.text_align.currentData(), angle=self.text_angle.value())
                self.create_sketch(shapes, 'Tekst')
                return
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if t == 'line':
            if len(self.points) >= 3 and kernel_close(self.points[0], (u, v)):
                self.finish_line(closed=True)
                return
            if self.points and kernel_close(self.points[-1], (u, v)):
                self.finish_line()
                return
            self.points.append((u, v))
            self.show_sketch_hint()
            return
        self.points.append((u, v))
        if len(self.points) < NEED[t]:
            self.show_sketch_hint()
            return
        points, self.points = list(self.points), []
        self.complete(points)

    def finish_line(self, closed=False):
        points, self.points = list(self.points), []
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        if len(points) < 2:
            self.show_sketch_hint()
            return
        try:
            meta = dict(tool='line', points=[list(p) for p in points], sides=self.sides) if len(points) == 2 and not closed else None
            self.create_sketch([kernel.polyline(self.sketch_plane, points, closed)], None, meta)
        except kernel.CadError as exc:
            self.toast(str(exc))

    def complete(self, points):
        """Zebrane punkty tworzą gotowy element szkicu (lub pomiar)."""
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        try:
            if self.tool == 'measure':
                (a, b) = points[:2]
                self.toast(f'Odległość: {fmt(math.hypot(b[0] - a[0], b[1] - a[1]))} mm   (ΔU {fmt(abs(b[0] - a[0]))}, ΔV {fmt(abs(b[1] - a[1]))})', 8000)
                return
            shape = self._wire(points)
        except kernel.CadError as exc:
            self.toast(str(exc))
            self.show_sketch_hint()
            return
        meta = dict(tool=self.tool, points=[list(p) for p in points], sides=self.sides) if self.tool in self.EDITABLE and self.tool not in ('line', 'text') else None
        self.create_sketch([shape], 'Konstrukcja' if self.tool == 'construction' else ('Punkt' if self.tool == 'point' else None), meta)

    def create_sketch(self, shapes, label=None, meta=None, select=False):
        plane = self.sketch_plane
        name = f'{label or "Szkic"} {self._plane_label()}'
        made = [replace(Body(name, sh, 'sketch', plane).prepared(), meta=meta) for sh in shapes] if select else None

        def after():
            if select and made:
                self.choose_tool(None)
                self.selected = [made[-1].id]
                self.refresh()
                self._update_grips()
                self.sk_hint.setText('Tekst: przesuń, skaluj lub obróć uchwytami · Tab – wysokość i kąt')

        self.run_operation('Tworzenie szkicu', (lambda: made) if select else (lambda: [replace(Body(name, sh, 'sketch', plane).prepared(), meta=meta) for sh in shapes]),
                           self.add_prepared_many, after=after if select else None)
        self.show_sketch_hint()

    def add_prepared_many(self, bodies):
        self.document.commit((*self.document.bodies, *bodies))
        if bodies and bodies[-1].meta:
            self._last_sketch_id = bodies[-1].id
        if self.mode != 'sketch':
            self.selected = [b.id for b in bodies]

    def _trim_target(self):
        """Szkic i kawałek jego krawędzi (między przecięciami z innymi szkicami) najbliższy kursorowi."""
        pos = self.view.mapFromGlobal(QCursor.pos())
        hit = self.view.nearest_edge(pos.x(), pos.y())
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'sketch':
            return None
        key = self._plane_key(body.plane)
        plane, bodies = self._drawn_sketches().get(key, (None, []))
        if body not in bodies:
            return None
        sig = (key, tuple((b.id, id(b.shape)) for b in bodies), body.id)
        if self._trim_cache is None or self._trim_cache[0] != sig:
            self._trim_cache = (sig, kernel.trim_pieces([b.shape.Edges() for b in bodies], bodies.index(body)))
        pieces = self._trim_cache[1]
        uv = self.view.plane_point(body.plane, pos.x(), pos.y())
        if not pieces or uv is None:
            return None
        import cadquery as cq
        vertex = cq.Vertex.makeVertex(*[float(c) for c in kernel.to_world(body.plane, *uv)])
        index = min(range(len(pieces)), key=lambda i: pieces[i].distance(vertex))
        return body, pieces, index

    def trim_preview(self):
        try:
            target = self._trim_target()
            mesh = kernel.display_mesh(target[1][target[2]], PREVIEW_TOL) if target else None
        except Exception:
            mesh = None
        self.view.set_preview_mesh(mesh, line_color=(.9, .18, .18, 1), width=5)

    def trim_at_cursor(self):
        target = self._trim_target()
        if target is None:
            raise kernel.CadError('Kliknij fragment szkicu.')
        body, pieces, index = target

        def build():
            made = [Body(body.name, w, 'sketch', body.plane).prepared() for w in kernel.trim_result(pieces, index)]
            out = []
            for b in self.document.bodies:
                out.extend(made if b.id == body.id else [b])
            return out

        self.view.set_preview_mesh(None)
        self.run_operation('Nożyczki', build, lambda bodies: self.document.commit(bodies))
    # ---------- wymiary z klawiatury (panel jak #dimensionPanel, podgląd na żywo) ----------
    def open_dim_input(self, first=''):
        labels = DIM_LABELS.get(self.tool)
        if self.mode != 'sketch' or not self.points or not labels:
            return False
        self._dim_target = None
        for i in range(len(self.dim_edits)):
            visible = i < len(labels)
            self.dim_labels[i].setVisible(visible)
            self.dim_edits[i].setVisible(visible)
            if visible:
                self.dim_labels[i].setText(labels[i])
                self.dim_edits[i].blockSignals(True)
                self.dim_edits[i].setText(first if i == 0 else (str(self.sides) if labels[i].startswith('Ilość') else ''))
                self.dim_edits[i].blockSignals(False)
        pos = self.view.mapFromGlobal(QCursor.pos())
        self.dim_panel.adjustSize()
        self.dim_panel.move(max(0, min(pos.x() + 16, self.view.width() - self.dim_panel.width() - 10)),
                            max(0, min(pos.y() + 14, self.view.height() - self.dim_panel.height() - 10)))
        self.dim_panel.show()
        self.dim_panel.raise_()
        self.dim_edits[0].setFocus()
        self.dim_edits[0].setCursorPosition(len(first))
        self.dim.hide()
        self.update_dim_preview()
        return True

    def _typed_values(self):
        values = []
        for edit in self.dim_edits:
            if edit.isVisible():
                try:
                    values.append(float(edit.text().replace(',', '.')))
                except ValueError:
                    values.append(None)
        return values

    def typed_end(self):
        v = self._typed_values()
        if not v or v[0] is None:
            return None
        self._apply_typed_sides(v)
        p0 = self.points[-1] if self.tool == 'line' else self.points[0]
        return self._dim_end(self.tool, p0, self.last_uv, v)

    def _apply_typed_sides(self, v):
        if self.tool == 'polygon' and len(v) > 1 and v[1] is not None and 3 <= int(v[1]) <= 64:
            self.sides = int(v[1])

    @staticmethod
    def _dim_end(t, p0, ref, v, direction=None):
        """Punkt końcowy figury z wpisanych wymiarów; ref wyznacza stronę (znaki), direction - kierunek promienia."""
        u0, v0 = p0
        sx = 1 if ref[0] >= u0 else -1
        sy = 1 if ref[1] >= v0 else -1
        if t in ('rect', 'ellipse', 'centerRect'):
            w = v[0]
            h = v[1] if len(v) > 1 and v[1] is not None else v[0]
            k = .5 if t in ('centerRect', 'ellipse') else 1
            return (u0 + sx * w * k, v0 + sy * h * k)
        if t in ('circle', 'polygon', 'circle2'):
            d = direction or (1.0, 0.0)
            return (u0 + v[0] * d[0], v0 + v[0] * d[1])
        ang = math.radians(v[1]) if len(v) > 1 and v[1] is not None else 0.0
        return (u0 + v[0] * math.cos(ang), v0 + v[0] * math.sin(ang))

    # ---------- edycja wymiarów istniejącego szkicu (Tab po zaznaczeniu) ----------
    EDITABLE = sm.EDITABLE

    def _sketch_edit_target(self):
        chosen = [b for b in (self.document.get(i) for i in self.selected) if b is not None and b.kind == 'sketch' and b.meta]
        if len(chosen) == 1:
            return chosen[0]
        last = self.document.get(getattr(self, '_last_sketch_id', None)) if getattr(self, '_last_sketch_id', None) else None
        return last if last is not None and last.meta else None

    @staticmethod
    def _meta_shape(plane, meta):
        t = meta['tool']
        pts = [tuple(p) for p in meta['points']]
        if t == 'line':
            return kernel.polyline(plane, pts, False)
        if t == 'arc':
            return kernel.arc3(plane, pts)
        if t == 'rect3':
            return kernel.rect3(plane, pts)
        return kernel.sketch_shape(t, plane, pts, meta.get('sides', 5))

    def open_dim_edit(self):
        body = self._sketch_edit_target()
        if body is None or body.meta.get('tool') not in self.EDITABLE:
            self.toast('Zaznacz szkic narysowany z wymiarami (prostokąt, okrąg, wielokąt, elipsa, łuk, linia, tekst…).')
            return False
        self.selected = [body.id]
        self.refresh()
        self._update_grips()
        meta = body.meta
        tool = meta['tool']
        labels = sm.LABELS[tool]
        values = sm.values(meta)
        for i in range(len(self.dim_edits)):
            visible = i < len(labels)
            self.dim_labels[i].setVisible(visible)
            self.dim_edits[i].setVisible(visible)
            if visible:
                self.dim_labels[i].setText(labels[i])
                self.dim_edits[i].blockSignals(True)
                self.dim_edits[i].setText(values[i])
                self.dim_edits[i].blockSignals(False)
        self.dim_panel.adjustSize()
        self.dim_panel.move(max(0, (self.view.width() - self.dim_panel.width()) // 2), 90)
        self.dim_panel.show()
        self._dim_target = dict(body=body, meta=meta)
        self.dim_panel.raise_()
        self.dim_edits[0].setFocus()
        self.dim_edits[0].selectAll()
        self.dim.hide()
        self._dim_edit_shape()
        return True

    def _dim_edit_shape(self):
        """(kształt, nowe meta) z wpisanych wartości albo None."""
        t = self._dim_target
        v = self._typed_values()
        if t is None or not v or v[0] is None:
            return None
        try:
            meta = sm.apply_values(t['meta'], v)
            return self._meta_shape(t['body'].plane, meta), meta
        except Exception:
            return None

    def apply_dim_edit(self):
        result = self._dim_edit_shape()
        target = self._dim_target
        self.dim_panel.hide()
        self.view.setFocus()
        self.view.set_preview_mesh(None)
        if result is None or target is None:
            return
        self._commit_sketch_edit(target['body'], result[0], result[1])

    def _commit_sketch_edit(self, old, shape, meta):
        def build():
            return replace(old, shape=shape, mesh=kernel.display_mesh(shape), meta=meta)

        def apply(body):
            self.override = {}
            self.document.commit([body if b.id == body.id else b for b in self.document.bodies])
            self._last_sketch_id = body.id
            self.selected = [body.id]
            self._update_grips()

        self.run_operation('Zmiana wymiarów szkicu', build, apply)

    # ---------- zaznaczanie i skalowanie kształtów myszą (szkic bez wybranego narzędzia) ----------
    def _update_grips(self, body=None, meta=None, mesh=None):
        grips, box = [], None
        if self.mode == 'sketch' and self.tool is None and len(self.selected) == 1:
            body = body or self.document.get(self.selected[0])
            if body is not None and body.meta and body.meta.get('tool') in self.EDITABLE:
                meta = meta or body.meta
                grips = [kernel.to_world(body.plane, *g) for g in sm.grip_points(meta)]
        self.view.sketch_grips = grips
        self.view.sketch_box = box
        self.view.update()

    def _drag_label(self, meta, x, y):
        text = ' × '.join(sm.values(meta)[:2]) + ' mm'
        self.dim.setText(text)
        self.dim.adjustSize()
        self.dim.move(int(x) + 14, int(y) + 12)
        self.dim.show()

    def _sketch_hook(self, kind, x, y):
        if self.mode != 'sketch' or self.tool is not None or self.busy or self.view.plane_pick:
            return False
        if kind == 'press':
            self._sk_drag = None
            hit = self.view.nearest_edge(x, y, kinds=('sketch',))
            body = self.document.get(hit[0]) if hit else None
            if body is None:
                return False
            self.selected = [body.id]
            self.refresh()
            self._update_grips()
            if not body.meta or body.meta.get('tool') not in self.EDITABLE:
                self.sk_hint.setText('Zaznaczono szkic (brak wymiarów do edycji)')
                return True
            self.sk_hint.setText('Zaznaczono · Tab – wymiary · przeciągnij uchwyt lub krawędź')
            uv = self.view.plane_point(body.plane, x, y)
            if uv is None:
                return True
            pts = [tuple(p) for p in body.meta['points']]
            ppm = max(self.view._cam_ppm(), 1e-6)
            self._sk_drag = dict(kind='shape', body=body, meta=body.meta, new=None,
                                 grab=sm.grab_info(body.meta['tool'], pts, uv, 14.0 / ppm, body.meta))
            return True
        drag = getattr(self, '_sk_drag', None)
        if drag is None:
            return True
        body = drag['body']
        if kind == 'move':
            uv = self.view.plane_point(body.plane, x, y)
            if uv is None:
                return True
            meta2 = sm.grab_apply(drag['meta'], drag['grab'], uv)
            if meta2 is None:
                return True
            try:
                shape = self._meta_shape(body.plane, meta2)
                mesh = kernel.display_mesh(shape)
            except Exception:
                return True
            drag['new'] = (shape, meta2)
            self.override = {body.id: replace(body, shape=shape, mesh=mesh, meta=meta2)}
            self.refresh()
            self._update_grips(body, meta2, mesh)
            self._drag_label(meta2, x, y)
            return True
        if kind == 'release':
            self._sk_drag = None
            self.dim.hide()
            if drag['new'] is not None:
                self._commit_sketch_edit(body, drag['new'][0], drag['new'][1])
            else:
                self.override = {}
            return True
        return True

    def update_dim_preview(self):
        if self._dim_target is not None:
            result = self._dim_edit_shape()
            if self.dim_panel.isVisible() and result is not None:
                self.view.set_preview_mesh(kernel.display_mesh(result[0]), line_color=SKETCH_ORANGE, width=2.4)
            return
        if not self.dim_panel.isVisible() or not self.points:
            return
        end = self.typed_end()
        if end is None:
            return
        self._show_sketch_preview([*self.points, end])
        self.view.set_marker(kernel.to_world(self.sketch_plane, *end), label='Wymiar')

    def apply_typed(self):
        if self._dim_target is not None:
            self.apply_dim_edit()
            return
        end = self.typed_end()
        self.dim_panel.hide()
        self.view.setFocus()
        if end is None:
            return
        if self.tool == 'line':
            self.points.append(end)
            self.show_sketch_hint()
            self._show_sketch_preview(list(self.points))
            return
        points, self.points = [*self.points, end], []
        self.complete(points)

    # =====================================================================
    # klikanie i najeżdżanie w widoku
    # =====================================================================
    def view_hover(self, x, y):
        if self.busy:
            return
        try:
            if self.mode == 'plane':
                frame, face = self.pick_surface(x, y)
                key = ('f', face.hashCode()) if face is not None else ('p', frame if isinstance(frame, str) else None)
                if key != self._hover_key:
                    self._hover_key = key
                    self.view.set_preview_mesh(kernel.display_mesh(face) if face is not None else None,
                                               color=(1, .55, .1, .35), line_color=SKETCH_ORANGE, width=2)
            elif self.mode == 'sketch' and self.tool is None:
                hit = self.view.nearest_edge(x, y, kinds=('sketch',))
                self.view._set_hover_edge(hit)
                self.view.setCursor(Qt.SizeAllCursor if hit else Qt.ArrowCursor)
            elif self.mode == 'mirror' and self.mirror_id and self.mirror_frame is None:
                self._hover_face_only(x, y)
            elif self.mode == 'mod':
                self.view._set_hover_edge(self.view.nearest_edge(x, y, True))
            elif self.mode is None and self._planes_visible:
                name = self.view.plane_at(x, y)
                self.view._highlight_plane(name)
                self.view.setCursor(Qt.PointingHandCursor if name else Qt.ArrowCursor)
            elif self.mode == 'extrude' and not self.ex_profiles:
                self._hover_extrude(x, y)
        except Exception:
            self._hover_key = None

    def _hover_face_only(self, x, y):
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        face = None
        if body is not None and body.kind == 'solid':
            try:
                face, _ = kernel.face_at(body.shape, hit[1], hit[2])
            except kernel.CadError:
                face = None
        key = ('mf', face.hashCode()) if face is not None else None
        if key != self._hover_key:
            self._hover_key = key
            self.view.set_preview_mesh(kernel.display_mesh(face) if face is not None else None, color=(1, .55, .1, .35), line_color=SKETCH_ORANGE, width=2)

    def _hover_extrude(self, x, y):
        blue = dict(color=(.35, .65, .94, .45), line_color=(.1, .3, .6, 1), width=2)
        try:
            src = self._profile_at(x, y)
        except kernel.CadError:
            src = None
        if src is None:
            if self._hover_key is not None:
                self._hover_key = None
                self.view.set_preview_mesh(None)
            return
        face = src.get('face') or profile_face(src['wire'])
        key = (src['kind'], src.get('id'), tuple(round(c, 3) for c in src['center']))
        if key != self._hover_key:
            self._hover_key = key
            self.view.set_preview_mesh(kernel.display_mesh(face) if face is not None else None, **blue)
    def view_clicked(self, x, y, shift, ctrl):
        if self.busy:
            return
        if self.mode == 'sketch' and self.view.plane_pick:
            plane, _ = self.pick_surface(x, y)
            if plane is not None:
                self.enter_sketch(plane)
                return
            self._end_plane_pick()   # kliknięcie w pustkę = zostajemy na bieżącej powierzchni i rysujemy
        if self.mode == 'sketch':
            if self.tool is None and self.selected:
                self.selected = []
                self.refresh()
                self._update_grips()
                self.sk_hint.setText('Wybierz kształt do rysowania')
            return
        if self.mode == 'plane':
            plane, _ = self.pick_surface(x, y)
            if plane is None:
                self.toast('Kliknij płaszczyznę lub płaską ścianę bryły.')
                return
            self.enter_sketch(plane)
        elif self.mode == 'extrude':
            self.pick_profile(x, y, shift)
        elif self.mode == 'bool':
            self.pick_bool(x, y)
        elif self.mode == 'mod':
            self.pick_edge(x, y, shift, ctrl)
        elif self.mode == 'mirror':
            self.pick_mirror(x, y)
        elif self.mode in ('move', 'rotate'):
            self.pick_transform_target(x, y)
        elif self.mode is None:
            bid = self.pick_object(x, y)
            if bid is None and self._planes_visible and not (shift or ctrl):
                name = self.view.plane_at(x, y)
                if name:
                    self.enter_sketch(name)
                    return
            if bid is None:
                if not (shift or ctrl):
                    self.selected = []
            elif shift or ctrl:
                self.selected = [i for i in self.selected if i != bid] if bid in self.selected else [*self.selected, bid]
            else:
                self.selected = [bid]
            self.refresh()

    def pick_object(self, x, y):
        bid = self.view.pick_body(x, y)
        if bid is None:
            hit = self.view.nearest_edge(x, y)
            bid = hit[0] if hit else None
        return bid

    # =====================================================================
    # wyciąganie: profil szkicu albo ściana bryły, strzałka, podgląd na żywo
    # =====================================================================
    @staticmethod
    def _plane_key(plane):
        return plane if isinstance(plane, str) else (plane.origin, plane.xdir, plane.normal)

    def _drawn_sketches(self):
        """Szkice (bez konstrukcji i punktów) pogrupowane według płaszczyzn: klucz -> (płaszczyzna, [bryły])."""
        groups = {}
        for b in self.document.bodies:
            if b.kind == 'sketch' and b.visible and not b.name.startswith(('Konstrukcja', 'Punkt')):
                groups.setdefault(self._plane_key(b.plane), (b.plane, []))[1].append(b)
        return groups

    def _regions_for(self, key, plane, bodies):
        sig = tuple((b.id, id(b.shape)) for b in bodies)
        cached = self._region_cache.get(key)
        if cached and cached[0] == sig:
            return cached[1]
        try:
            faces = kernel.regions(plane, [e for b in bodies for e in b.shape.Edges()], [b.shape for b in bodies if b.shape.IsClosed()])
        except Exception:
            faces = [f for f in (profile_face(b.shape) for b in bodies if b.shape.IsClosed()) if f is not None]
        self._region_cache[key] = (sig, faces)
        return faces

    def _region_at(self, x, y):
        """Obszar szkicu pod kursorem (nakładające się kształty tną się nawzajem): (odległość, płaszczyzna, ściana)."""
        best = None
        for key, (plane, bodies) in self._drawn_sketches().items():
            hit = self.view._plane_hit(plane, x, y)
            if hit is None:
                continue
            for face in self._regions_for(key, plane, bodies):
                if kernel.face_contains(face, hit[1]):
                    if best is None or hit[0] < best[0]:
                        best = (hit[0], plane, face)
                    break
        return best

    def _profile_at(self, x, y):
        region = self._region_at(x, y)
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        solid = None
        if body is not None and body.kind == 'solid':
            face, normal = kernel.face_at(body.shape, hit[1], hit[2])
            ray = self.view._ray(x, y)
            t = float(np.linalg.norm(np.asarray(hit[2], float) - ray[0])) if ray else 0.0
            solid = (t, dict(kind='face', id=body.id, face=face, wire=face.outerWire(), plane=None, normal=tuple(float(c) for c in normal),
                             center=face.Center().toTuple()))
        if region is not None and (solid is None or region[0] <= solid[0] + max(5e-3, 1e-4 * solid[0])):
            frame = kernel.frame_of(region[1])
            face = region[2]
            return dict(kind='region', id=None, face=face, wire=face.outerWire(), plane=region[1], normal=tuple(frame.normal), center=face.Center().toTuple())
        if solid is not None:
            return solid[1]
        bid = self.view.pick_profile(x, y)
        if bid is not None:
            body = self.document.get(bid)
            frame = kernel.frame_of(body.plane)
            return dict(kind='sketch', id=bid, face=None, wire=body.shape, plane=body.plane, normal=tuple(frame.normal), center=body.shape.Center().toTuple())
        return None
    def pick_profile(self, x, y, shift=False):
        try:
            src = self._profile_at(x, y)
        except Exception as exc:
            self.toast(str(exc) or 'Nie udało się wybrać profilu.')
            return
        if src is None:
            self.toast('Kliknij zamknięty profil szkicu albo płaską ścianę bryły.')
            return
        if shift:
            dup = [p for p in self.ex_profiles if p['id'] == src['id'] and p['kind'] == src['kind'] and np.allclose(p['center'], src['center'], atol=1e-6)]
            self.ex_profiles = [p for p in self.ex_profiles if p not in dup] if dup else [*self.ex_profiles, src]
        else:
            self.ex_profiles = [src]
        self._hover_key = None
        if not shift:
            self._ex_op_manual = False
            for spin in (self.ex_value, self.ex_second):
                spin.blockSignals(True)
                spin.setValue(10.0)
                spin.blockSignals(False)
        self._auto_extrude_op()
        if not self.ex_profiles:
            self.view.set_selection_meshes(None)
            self.ex_bar.hide()
            self.view.set_preview_mesh(None)
            self.view.set_handles([])
            return
        self._mark_profiles()
        self.ex_bar.show()
        self.ex_status.setText(f'Wybrano profili: {len(self.ex_profiles)}. Przeciągnij strzałkę albo wpisz odległość u góry.')
        self.hint('Przeciągnij pomarańczową strzałkę lub wpisz odległość, potem Zastosuj (Enter).')
        self.ex_value.setFocus()
        self._layout_overlays()
        self.update_extrude_preview()

    def _mark_profiles(self):
        meshes = []
        for src in self.ex_profiles:
            try:
                face = src.get('face') or profile_face(src['wire'])
                meshes.append(kernel.display_mesh(face) if face is not None else None)
            except Exception:
                pass
        self.view.set_selection_meshes(meshes)

    def _ex_dir_changed(self, *_):
        two = self.ex_dir.currentData() == 'two'
        self.ex_second_label.setVisible(two)
        self.ex_second.setVisible(two)
        self.ex_bar.adjustSize()
        self._timers['extrude'].start()

    def _cube_rotate(self, daz, delev):
        """Strzałki kostki: obrót widoku o 90° (przerzucenie kostki na niewidoczną ścianę)."""
        az = float(self.view.opts['azimuth'])
        el = float(self.view.opts['elevation'])
        if daz:
            az = round(az / 90.0) * 90.0 + daz
        if delev:
            el = max(-90.0, min(90.0, round(el / 90.0) * 90.0 + delev))
        self.view.setCameraPosition(azimuth=az, elevation=el)
        self.view.update()

    def _auto_extrude_op(self):
        """Wciąganie w bryłę = wycinanie, na zewnątrz = połączenie (dopóki użytkownik sam nie wybrał operacji)."""
        if getattr(self, '_ex_op_manual', False) or len(self.ex_profiles) != 1 or self.ex_dir.currentData() != 'one':
            return
        src = self.ex_profiles[0]
        value = self.ex_value.value()
        if abs(value) < 1e-6:
            return
        n = np.array(src['normal'], float)
        c = np.array(src['center'], float)
        solids = [b for b in self.document.bodies if b.kind == 'solid']
        touching = src.get('kind') == 'face'
        sample = c + n * (.05 if value > 0 else -.05)
        inside = False
        try:
            if not touching:
                touching = any(kernel.point_state(b.shape, c) != 'out' for b in solids)
            inside = touching and any(kernel.point_state(b.shape, sample) == 'in' for b in solids)
        except Exception:
            return
        want = 'new' if not touching else ('cut' if inside else 'join')
        if self.ex_op.currentData() != want:
            self._ex_auto = True
            try:
                self.ex_op.setCurrentIndex(self.ex_op._data.index(want))
            finally:
                self._ex_auto = False

    def _ex_op_user_changed(self):
        if not getattr(self, '_ex_auto', False):
            self._ex_op_manual = True

    def _ex_value_changed(self):
        self._auto_extrude_op()
        self._timers['extrude'].start()
        if self._hv is None:
            self._place_extrude_handle()

    def _place_extrude_handle(self):
        if self.mode != 'extrude' or not self.ex_profiles:
            self.view.set_handles([])
            return
        src = self.ex_profiles[0]
        n = np.array(src['normal'], float)
        c = np.array(src['center'], float)
        d = self.ex_value.value()
        mode = self.ex_dir.currentData()
        sign = 1.0 if d >= 0 else -1.0
        handles = [dict(id='ex', start=c, tip=c + n * (d / 2 if mode == 'symmetric' else d), dir=n, color=(.94, .6, .13, 1), label='+')]
        if mode == 'two':
            d2 = self.ex_second.value()
            handles.append(dict(id='ex2', start=c, tip=c - n * d2, dir=-n, color=(.11, .51, .81, 1), label='−'))
        self.view.set_handles(handles)
    def _make_tools(self):
        """Funkcje budujące bryły-narzędzia (po jednej na profil); bezpieczne dla wątku roboczego."""
        if not self.ex_profiles:
            raise kernel.CadError('Wybierz profil szkicu lub ścianę.')
        d1, d2 = self.ex_value.value(), self.ex_second.value()
        mode = self.ex_dir.currentData()
        out = []
        for src in self.ex_profiles:
            wire, normal, plane, face = src['wire'], src['normal'], src['plane'], src.get('face')
            if face is not None:
                out.append(lambda f=face, n=normal, a=d1, b=d2 if mode == 'two' else 0.0, s=mode == 'symmetric': kernel.extrude_face(f, n, a, b, s))
            elif mode == 'two':
                out.append(lambda w=wire, n=normal, a=d1, b=d2: kernel.extrude_dir(w, n, a, b))
            elif plane is not None:
                out.append(lambda w=wire, p=plane, a=d1, s=mode == 'symmetric': kernel.extrude(w, p, a, s))
            else:
                out.append(lambda w=wire, n=normal, a=d1, s=mode == 'symmetric': kernel.extrude_dir(w, n, a, 0.0, s))
        return out

    def update_extrude_preview(self):
        if self.mode != 'extrude' or not self.ex_profiles:
            return
        makers = self._make_tools()
        op = self.ex_op.currentData()
        value_now = self.ex_value.value()

        def compute():
            return _merge_meshes([kernel.display_mesh(make(), PREVIEW_TOL) for make in makers])

        def show(mesh, error):
            if self.mode != 'extrude' or not self.ex_profiles:
                return
            if error:
                self.view.set_preview_mesh(None)
                self.ex_status.setText(error)
                self.toast(error)
                return
            self._ex_mesh_value = value_now
            red = op == 'cut'
            color = (.9, .2, .2, .7) if red else ((.3, .75, .5, .72) if op == 'intersect' else PREVIEW_BLUE)
            self.view.set_preview_mesh(mesh, color=color, line_color=(.56, .07, .07, 1) if red else (.14, .3, .45, 1), width=2)
            self.ex_status.setText(f'Wybrano profili: {len(self.ex_profiles)}.')
            if self._hv is not None:
                self._stretch_extrude()

        self.run_preview('extrude', compute, show)
        if self._hv is None:
            self._place_extrude_handle()
    def apply_extrude(self):
        if self.busy or not self.ex_profiles:
            return
        op = self.ex_op.currentData()
        makers = self._make_tools()
        existing = list(self.document.bodies)

        def build():
            tools = [m() for m in makers]
            if op == 'new':
                return [*existing, *[Body('Wyciągnięcie', t).prepared() for t in tools]]
            bodies = list(existing)
            used = False
            for tool in tools:
                box = kernel.bounds(tool)
                for i, b in enumerate(bodies):
                    if b.kind != 'solid':
                        continue
                    other = kernel.bounds(b.shape)
                    if (box.xmin > other.xmax + 1e-3 or box.xmax < other.xmin - 1e-3 or box.ymin > other.ymax + 1e-3 or
                            box.ymax < other.ymin - 1e-3 or box.zmin > other.zmax + 1e-3 or box.zmax < other.zmin - 1e-3):
                        continue
                    key = {'join': 'union', 'cut': 'subtract', 'intersect': 'intersect'}[op]
                    try:
                        bodies[i] = b.changed(kernel.boolean(key, b.shape, [tool]))
                        used = True
                    except kernel.CadError:
                        continue
            if not used:
                raise kernel.CadError('Nie ma bryły, z którą można wykonać tę operację. Profil musi dotykać bryły lub ją przecinać.')
            return bodies

        def apply(bodies):
            self.document.commit(bodies)
            self.selected = [bodies[-1].id] if op == 'new' else []

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.run_operation('Wyciąganie', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # boolean
    # =====================================================================
    def pick_bool(self, x, y):
        bid = self.view.pick_body(x, y)
        body = self.document.get(bid) if bid else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij bryłę (nie szkic).')
            return
        if bid in self.bool_ids:
            self.bool_ids.remove(bid)
        else:
            self.bool_ids.append(bid)
        self.update_bool_status()

    def update_bool_status(self):
        self.view.tints = {bid: (TINT_BASE if i == 0 else TINT_TOOL) for i, bid in enumerate(self.bool_ids)}
        names = [self.document.get(i).name for i in self.bool_ids if self.document.get(i)]
        if not names:
            text = 'Kliknij bryłę bazową.'
        elif len(names) == 1:
            text = f'Baza: {names[0]}\nKliknij bryłę-narzędzie.'
        else:
            text = f'Baza: {names[0]}\nNarzędzia: {", ".join(names[1:])}'
        self.bool_status.setText(text)
        self.refresh()
        self._timers['bool'].start()

    def update_bool_preview(self):
        if self.mode != 'bool':
            return
        if len(self.bool_ids) < 2:
            self.cancel_previews()
            self.view.set_preview_mesh(None)
            return
        base, *tools = [self.document.get(i) for i in self.bool_ids]
        op = self.bool_op.currentData()
        ids = tuple(self.bool_ids)

        def compute():
            return kernel.display_mesh(kernel.boolean(op, base.shape, [t.shape for t in tools]), PREVIEW_TOL)

        def show(mesh, error):
            if self.mode != 'bool' or tuple(self.bool_ids) != ids:
                return
            if error:
                self.view.set_preview_mesh(None)
                self.bool_status.setText(self.bool_status.text().split('\n\n')[0] + '\n\n' + error)
                return
            self.view.set_preview_mesh(mesh, color=(.3, .8, .5, .55), line_color=(.05, .4, .2, 1), width=2)

        self.run_preview('bool', compute, show)
    def apply_bool(self):
        if self.busy:
            return
        if len(self.bool_ids) < 2:
            self.toast('Do operacji Boolean potrzebne są co najmniej dwie bryły.')
            return
        bodies = [self.document.get(i) for i in self.bool_ids]
        base, tools = bodies[0], bodies[1:]
        ids = {b.id for b in tools}
        op = self.bool_op.currentData()
        keep = self.bool_keep.isChecked()

        def build():
            result = base.changed(kernel.boolean(op, base.shape, [b.shape for b in tools]))
            return [result if b.id == base.id else b for b in self.document.bodies if keep or b.id not in ids]

        def apply(new):
            self.document.commit(new)
            self.selected = [base.id]

        self.view.set_preview_mesh(None)
        self.run_operation('Operacja na bryłach', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # edytuj bryłę: zaokrąglenia i fazy z uchwytem-strzałką
    # =====================================================================
    def _mod_kind_changed(self, *_):
        self.mod_label.setText('Promień zaokrąglenia (mm)' if self.mod_kind.currentData() == 'fillet' else 'Odległość fazy (mm)')
        self._timers['mod'].start()

    def _mod_value_changed(self):
        self._timers['mod'].start()
        if self._hv is None:
            self._place_mod_handle()

    def pick_edge(self, x, y, shift, ctrl):
        hit = self.view.nearest_edge(x, y, True)
        if hit is None:
            if not (shift or ctrl):
                self.edges = {}
            self.update_mod_status()
            return
        bid, index = hit[0], hit[1]
        body = self.document.get(bid)
        if body is None or body.kind != 'solid':
            return
        ids = set(kernel.edge_chain(body.shape, index)) if ctrl else {index}
        if not (shift or ctrl) or bid not in self.edges:
            if not any(self.edges.values()):
                self.mod_size.blockSignals(True)
                self.mod_size.setValue(2.0)
                self.mod_size.blockSignals(False)
            self.edges = {bid: set()}
        current = self.edges[bid]
        if (shift or ctrl) and ids <= current:
            current -= ids
        else:
            current |= ids
        self.update_mod_status()

    def update_mod_status(self):
        count = sum(len(v) for v in self.edges.values())
        self.mod_status.setText(f'Zaznaczone krawędzie: {count}' if count else 'Kliknij krawędź (lub kilka krawędzi) bryły.')
        self.refresh()
        self._place_mod_handle()
        self._timers['mod'].start()

    def _place_mod_handle(self):
        if self.mode != 'mod' or len(self.edges) != 1 or not next(iter(self.edges.values()), None):
            self.view.set_handles([])
            return
        bid, ids = next(iter(self.edges.items()))
        body = self.document.get(bid)
        try:
            mid, direction = kernel.edge_handle(body.shape, max(ids))
        except Exception:
            self.view.set_handles([])
            return
        mid, d = np.array(mid, float), np.array(direction, float)
        self.view.set_handles([dict(id='mod', start=mid, tip=mid + d * self.mod_size.value(), dir=d, color=(.94, .6, .13, 1))])
    def update_mod_preview(self):
        if self.mode != 'mod':
            return
        if len(self.edges) != 1 or not next(iter(self.edges.values()), None):
            self.cancel_previews()
            self.view.set_preview_mesh(None)
            return
        bid, ids = next(iter(self.edges.items()))
        body = self.document.get(bid)
        if body is None:
            return
        size, kind, ids = self.mod_size.value(), self.mod_kind.currentData(), set(ids)

        def compute():
            result = kernel.blend(body.shape, ids, size, kind)
            return kernel.display_mesh(result, PREVIEW_TOL), result.Volume() > body.shape.Volume() + 1e-6

        def show(value, error):
            if self.mode != 'mod' or self.edges.get(bid) != ids:
                return
            if error or value is None:
                self.view.set_preview_mesh(None)
                self.mod_status.setText(f'Zaznaczone krawędzie: {len(ids)}\nTa wartość jest za duża dla wybranych krawędzi.')
                return
            mesh, adds = value
            self.view.set_preview_mesh(mesh, color=(.25, .8, .45, .6) if adds else (.95, .55, .2, .6),
                                       line_color=(.1, .4, .2, 1) if adds else (.55, .3, .05, 1), width=2)
            self.mod_status.setText(f'Zaznaczone krawędzie: {len(ids)}\n' + ('Zielony podgląd: dodaje materiał.' if adds else 'Pomarańczowy podgląd: usuwa materiał.'))

        self.run_preview('mod', compute, show)
    def apply_mod(self):
        if self.busy:
            return
        if len(self.edges) != 1 or not next(iter(self.edges.values()), None):
            self.toast('Zaznacz krawędzie jednej bryły.')
            return
        bid, ids = next(iter(self.edges.items()))
        body = self.document.get(bid)
        size, kind = self.mod_size.value(), self.mod_kind.currentData()
        ids = set(ids)

        def apply(new):
            self.document.commit([new if b.id == body.id else b for b in self.document.bodies])
            self.selected = [body.id]

        self.view.set_preview_mesh(None)
        self.view.set_handles([])
        self.run_operation('Zaokrąglanie' if kind == 'fillet' else 'Fazowanie', lambda: body.changed(kernel.blend(body.shape, ids, size, kind)), apply,
                           after=lambda: self.set_mode(None))

    # =====================================================================
    # lustro
    # =====================================================================
    def reset_mirror(self):
        self.mirror_id = None
        self.mirror_frame = None
        self.view.tints = {}
        self.view.set_preview_mesh(None)
        self.update_mirror_status()

    def pick_mirror(self, x, y):
        if self.mirror_id is None:
            bid = self.pick_object(x, y)
            if bid is None:
                self.toast('Kliknij bryłę lub element szkicu do odbicia.')
                return
            self.mirror_id = bid
            self.view.tints = {bid: TINT_BASE}
            self.update_mirror_status()
            return
        hit = self.view.pick_face(x, y)
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'solid':
            self.toast('Kliknij ścianę, względem której ma nastąpić odbicie.')
            return
        try:
            face, normal = kernel.face_at(body.shape, hit[1], hit[2])
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        self.mirror_frame = (tuple(float(c) for c in normal), tuple(float(c) for c in face.Center().toTuple()))
        self.view.set_selection_meshes([kernel.display_mesh(face)], color=(.25, .75, .45, .55), line_color=(.1, .55, .3, 1))
        self.update_mirror_status()

    def update_mirror_status(self):
        body = self.document.get(self.mirror_id) if self.mirror_id else None
        if body is None:
            self.mir_step1.set_state('active', 'Kliknij bryłę lub szkic')
            self.mir_step2.set_state('pending', 'Najpierw wybierz obiekt')
        elif self.mirror_frame is None:
            self.mir_step1.set_state('done', body.name)
            self.mir_step2.set_state('active', 'Kliknij ścianę bryły')
        else:
            self.mir_step1.set_state('done', body.name)
            self.mir_step2.set_state('done', 'Wskazana')
        self.mir_join.setEnabled(body is not None and body.kind == 'solid')
        self.refresh()
        self._timers['mirror'].start()

    def update_mirror_preview(self):
        if self.mode != 'mirror':
            return
        if self.mirror_id is None or self.mirror_frame is None:
            self.cancel_previews()
            self.view.set_preview_mesh(None)
            return
        body = self.document.get(self.mirror_id)
        frame = self.mirror_frame

        def compute():
            return kernel.display_mesh(kernel.mirror_plane(body.shape, *frame), PREVIEW_TOL)

        def show(mesh, error):
            if self.mode == 'mirror' and self.mirror_frame == frame:
                self.view.set_preview_mesh(None if error else mesh, color=(.3, .8, .5, .55), line_color=(.05, .4, .2, 1), width=2)

        self.run_preview('mirror', compute, show)
    def apply_mirror(self):
        if self.busy:
            return
        if self.mirror_id is None or self.mirror_frame is None:
            self.toast('Kliknij obiekt, a potem ścianę jako płaszczyznę odbicia.')
            return
        body = self.document.get(self.mirror_id)
        normal, origin = self.mirror_frame
        keep, join = self.mir_keep.isChecked(), self.mir_join.isChecked() and body.kind == 'solid'

        def build():
            shape = kernel.mirror_plane(body.shape, normal, origin)
            if join:
                merged = kernel.boolean('union', body.shape, [shape])
                return [body.changed(merged) if b.id == body.id else b for b in self.document.bodies]
            mirrored = Body(body.name + ' — odbicie', shape, body.kind, body.plane).prepared()
            if keep:
                return [*self.document.bodies, mirrored]
            return [mirrored if b.id == body.id else b for b in self.document.bodies]

        def apply(new):
            self.document.commit(new)
            self.selected = [new[-1].id if keep and not join else body.id]

        self.view.set_preview_mesh(None)
        self.run_operation('Odbicie lustrzane', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # przesuwanie i obracanie zaznaczonych szkiców / brył z uchwytami 3D
    # =====================================================================
    def pick_transform_target(self, x, y):
        bid = self.pick_object(x, y)
        body = self.document.get(bid) if bid else None
        if body is None:
            self.toast('Kliknij bryłę lub szkic.')
            return
        self.select_transform_target(body)

    def select_transform_target(self, body):
        self.override = {}
        self.t_target = body
        box = kernel.bounds(body.shape)
        self.t_center = np.array(box.center.toTuple(), float)
        self.t_mass = np.array(body.shape.Center().toTuple(), float)
        self.view.clear_body_matrices()
        self.t_radius = max(8.0, max(box.xlen, box.ylen, box.zlen) * .75)
        self.t_status.setText(f'Zaznaczono: {body.name}')
        for spin in self.t_spins:
            spin.blockSignals(True)
            spin.setValue(0)
            spin.blockSignals(False)
        self.selected = [body.id]
        self.view.free_drag = (body.id, self.t_center) if self.mode == 'move' else None
        self.refresh()
        self._place_gizmo()

    def _place_gizmo(self):
        """Uchwyty w stylu Fusion 360: przesuwanie = kolorowe strzałki osi + kwadraty płaszczyzn; obrót = kolorowe pierścienie."""
        if self.t_target is None or self.mode not in ('move', 'rotate'):
            self.view.set_handles([])
            return
        c, r = self.t_center, self.t_radius
        axes = [np.array(a) for a in AXES]
        handles = []
        if self.mode == 'move':
            base = c + np.array([s.value() for s in self.t_spins])
            length = max(r, float(self.view.opts['distance']) * .13)
            for i, a in enumerate(axes):
                handles.append(dict(id='xyz'[i], kind='axis', start=base, tip=base + a * length, dir=a, color=AXIS_COLORS[i], label='XYZ'[i], min_px=46))
            for i, j, k in ((0, 1, 2), (0, 2, 1), (1, 2, 0)):
                a, b = axes[i], axes[j]
                q0 = base + (a + b) * .2 * length
                quad = [q0, q0 + a * .26 * length, q0 + (a + b) * .26 * length, q0 + b * .26 * length]
                handles.append(dict(id='p' + 'xyz'[i] + 'xyz'[j], kind='plane', quad=quad, plane_origin=base, normal=axes[k], color=AXIS_COLORS[k]))
        else:
            for i, a in enumerate(axes):
                e1 = np.cross(a, (0, 0, 1.0) if abs(a[2]) < .9 else (1.0, 0, 0))
                e1 /= np.linalg.norm(e1)
                handles.append(dict(id='xyz'[i], kind='ring', ring=(c, a, r), tip=c + e1 * r, dir=np.cross(a, e1), color=AXIS_COLORS[i], label='XYZ'[i]))
        self.view.set_handles(handles)

    def handle_point_dragged(self, hid, vec):
        """Przeciąganie kwadratu płaszczyzny lub samej bryły (lewy przycisk): przesunięcie w płaszczyźnie."""
        if self.mode != 'move' or self.t_target is None:
            return
        if self._hv is None or self._hv[0] != 'pt':
            self._hv = ('pt', np.array([s.value() for s in self.t_spins], float))
        mask = {'pxy': (0, 1), 'pxz': (0, 2), 'pyz': (1, 2)}.get(hid, (0, 1, 2))
        values = self._hv[1].copy()
        for i in mask:
            values[i] += float(vec[i])
        for spin, value in zip(self.t_spins, values):
            spin.blockSignals(True)
            spin.setValue(round(float(value), 2))
            spin.blockSignals(False)
        self.update_transform_preview()
        self._place_gizmo()
    def _transform_changed(self):
        self.update_transform_preview()
        if self._hv is None:
            self._place_gizmo()

    def handle_dragged(self, hid, delta):
        if hid == 'ex':
            if self._hv is None:
                self._hv = self.ex_value.value()
            self.ex_value.setValue(round(self._hv + delta, 1))
            self._stretch_extrude()
        elif hid == 'ex2':
            if self._hv is None:
                self._hv = self.ex_second.value()
            self.ex_second.setValue(max(0.0, round(self._hv + delta, 1)))
        elif hid == 'mod':
            if self._hv is None:
                self._hv = self.mod_size.value()
            self.mod_size.setValue(max(.1, round(self._hv + delta, 1)))
        elif hid in ('x', 'y', 'z') and self.t_target is not None:
            index = 'xyz'.index(hid)
            if self._hv is None or self._hv[0] != hid:
                self._hv = (hid, self.t_spins[index].value())
            value = self._hv[1] + (delta if self.mode == 'move' else math.degrees(delta / max(self.t_radius, 1e-6)))
            self.t_spins[index].setValue(round(value, 1))

    def _stretch_extrude(self):
        """Natychmiastowa reakcja podglądu na przeciąganie strzałki (jednostronne wyciągnięcie jednego profilu)."""
        base = getattr(self, '_ex_mesh_value', 0.0)
        if len(self.ex_profiles) != 1 or self.ex_dir.currentData() != 'one' or abs(base) < 1e-6:
            return
        factor = self.ex_value.value() / base
        if factor > .02:
            src = self.ex_profiles[0]
            self.view.stretch_preview(src['center'], src['normal'], factor)

    def handle_released(self, hid):
        self._hv = None
        if hid in ('ex', 'ex2'):
            self._place_extrude_handle()
        elif hid == 'mod':
            self._place_mod_handle()
        else:
            self._place_gizmo()

    def update_transform_preview(self):
        """Podgląd przesunięcia / obrotu bez liczenia geometrii: macierz nakładana na elementy GL (natychmiast, nawet dla dużych brył)."""
        if self.mode not in ('move', 'rotate') or self.t_target is None:
            return
        v = [s.value() for s in self.t_spins]
        m = QMatrix4x4()
        if self.mode == 'move':
            m.translate(*v)
        else:
            c = self.t_mass
            m.translate(*c)
            for axis, angle in ((2, v[2]), (1, v[1]), (0, v[0])):
                if angle:
                    m.rotate(float(angle), *[1.0 if i == axis else 0.0 for i in range(3)])
            m.translate(*(-c))
        self.view.set_body_matrix(self.t_target.id, m)
    def apply_transform(self):
        if self.busy or self.t_target is None:
            self.toast('Kliknij obiekt, aby go zaznaczyć.')
            return
        self._timers['transform'].stop()
        v = tuple(s.value() for s in self.t_spins)
        target, mode = self.t_target, self.mode
        self.override = {}

        def build():
            shape = kernel.transform(target.shape, v, (0, 0, 0)) if mode == 'move' else kernel.transform(target.shape, (0, 0, 0), v)
            return target.changed(shape)

        def apply(body):
            self.view.clear_body_matrices()
            self.document.commit([body if b.id == body.id else b for b in self.document.bodies])
            self.selected = [body.id]

        self.view.set_handles([])
        self.run_operation('Przekształcenie', build, apply, after=lambda: self.set_mode(None))

    # =====================================================================
    # model, odświeżanie
    # =====================================================================
    def refresh(self, fit=False):
        live = {b.id for b in self.document.bodies}
        self.selected = [i for i in self.selected if i in live]
        self.edges = {i: es for i, es in self.edges.items() if i in live}
        bodies = [self.override.get(b.id, b) for b in self.document.bodies]
        self.view.set_models(bodies, self.selected, self.edges)
        if fit:
            self.view.fit_all()
        self.undo_button.setEnabled(self.document.can_undo and not self.busy)
        self.redo_button.setEnabled(self.document.can_redo and not self.busy)
        name = self.document.path.name if self.document.path else 'Nowy projekt'
        self.setWindowTitle(f"{'● ' if self.document.dirty else ''}{name} — RCCAD")

    def run_operation(self, label, function, apply, fit=False, after=None):
        if self.busy:
            return
        self.busy = True
        work = _Work(function)
        self._work = work

        def finish():
            self.busy = False
            self._work = None

        def done(value):
            try:
                apply(value)
            except Exception as exc:
                self.toast(str(exc))
            finally:
                finish()
                self.refresh(fit)
                if after:
                    after()

        def failed(message):
            finish()
            self.toast(message + ' Dotychczasowy model pozostał bez zmian.', 7000)
            self.refresh()

        work.signals.done.connect(done)
        work.signals.failed.connect(failed)
        self.pool.start(work)

    # ---------- podglądy liczone w tle (GUI nigdy nie czeka na OpenCascade) ----------
    def run_preview(self, key, compute, show):
        """Ostatnie żądanie wygrywa: przy szybkim przeciąganiu pośrednie wyniki są pomijane, a interfejs nie zamarza."""
        st = self._pv.setdefault(key, dict(running=False, pending=None, gen=0))
        st['gen'] += 1
        st['pending'] = (st['gen'], compute, show)
        if not st['running']:
            self._pv_next(key)

    def _pv_next(self, key):
        st = self._pv[key]
        if st['pending'] is None:
            st['running'] = False
            return
        gen, compute, show = st['pending']
        st['pending'] = None
        st['running'] = True
        work = _Work(compute)
        st['work'] = work
        work.signals.done.connect(lambda value, g=gen: self._pv_done(key, g, show, value, None))
        work.signals.failed.connect(lambda message, g=gen: self._pv_done(key, g, show, None, message))
        self.pool.start(work)

    def _pv_done(self, key, gen, show, value, error):
        st = self._pv[key]
        st['running'] = False
        if st['gen'] == gen:
            try:
                show(value, error)
            except Exception:
                pass
        self._pv_next(key)

    def cancel_previews(self):
        for st in self._pv.values():
            st['gen'] += 1
            st['pending'] = None

    def add_prepared(self, body):
        self.document.commit((*self.document.bodies, body))
        if self.mode != 'sketch':
            self.selected = [body.id]

    def clear_all(self):
        if self.busy:
            return
        if not self.document.bodies:
            self.toast('Pole robocze jest już puste.')
            return
        answer = QMessageBox.question(self, 'Wyczyścić pole', 'Na pewno wyczyścić całe pole?\nWszystkie bryły i szkice zostaną usunięte (można cofnąć Ctrl+Z).',
                                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.set_mode(None)
        self.document.commit(())
        self.selected = []
        self.edges = {}
        self.refresh()

    def undo(self):
        if not self.busy:
            self.document.undo()
            self.edges = {}
            self.refresh()

    def redo(self):
        if not self.busy:
            self.document.redo()
            self.edges = {}
            self.refresh()

    def delete_selected(self):
        if not self.busy and self.selected and self.mode is None:
            self.document.commit([b for b in self.document.bodies if b.id not in self.selected])
            self.selected = []
            self.refresh()

    def copy_selected(self):
        self.clipboard = [(b.name, b.shape, b.kind, b.plane) for b in self.document.bodies if b.id in self.selected]
        if self.clipboard:
            self.toast('Skopiowano zaznaczone obiekty.', 2500)

    def cut_selected(self):
        if self.selected and self.mode is None and not self.busy:
            self.copy_selected()
            self.delete_selected()

    def paste_clipboard(self):
        if self.busy or not self.clipboard or self.mode is not None:
            return
        items = list(self.clipboard)

        def build():
            return [Body(n + ' — kopia', kernel.transform(sh, (10, 10, 0)), k, p).prepared() for n, sh, k, p in items]

        def apply(new):
            self.document.commit((*self.document.bodies, *new))
            self.selected = [b.id for b in new]

        self.run_operation('Wklejanie', build, apply)

    def end_current_shape(self):
        """Prawy przycisk / Esc w trakcie rysowania: linia zostaje (jeśli ma ≥ 2 punkty) i rysowanie linii się kończy; inne kształty są porzucane."""
        if self.tool == 'line' and len(self.points) >= 2:
            self.finish_line()
            return
        self.points = []
        self.tangent_lines = []
        self.dim.hide()
        self.dim_panel.hide()
        self.view.set_preview_mesh(None)
        self.view.set_marker(None)
        self.show_sketch_hint()

    def sketch_hover_wanted(self):
        """Kursor ze znacznikiem i przyciąganiem działa dopiero po wybraniu miejsca rysowania (pierwszy klik) — bez ciągłego liczenia."""
        return bool(self.points) or self.tool == 'trim' or (self.tool == 'circleTangent2' and len(self.tangent_lines) == 2)

    def context_menu(self, x, y):
        if self.busy:
            return
        if self.mode == 'sketch':
            if self.points or self.tangent_lines:
                self.end_current_shape()
            return
        if self.mode is not None:
            return
        bid = self.pick_object(x, y)
        if bid and bid not in self.selected:
            self.selected = [bid]
            self.refresh()
        has = bool(self.selected)
        items = [('Kopiuj', 'Ctrl+C', self.copy_selected, has), ('Wytnij', 'Ctrl+X', self.cut_selected, has),
                 ('Wklej', 'Ctrl+V', self.paste_clipboard, bool(self.clipboard)), ('Usuń', 'Del', self.delete_selected, has)]
        menu = ui.PopupMenu(self, items, min_width=170)
        self._popup = menu
        menu.popup_at(QCursor.pos())

    # =====================================================================
    # plik
    # =====================================================================
    def file_menu(self):
        px = lambda kind: ui.icons.pixmap(kind, 34)
        entries = [(px('f_new'), 'Nowy projekt', 'Czysta przestrzeń robocza  ·  Ctrl+N', self.new_project),
                   (px('f_open'), 'Otwórz projekt…', 'Plik .rccadx  ·  Ctrl+O', self.open_project),
                   None,
                   (px('f_save'), 'Zapisz projekt', 'Zapis w bieżącym pliku  ·  Ctrl+S', self.save_project),
                   (px('f_saveas'), 'Zapisz jako…', 'Zapis pod nową nazwą', lambda: self.save_project(True)),
                   None,
                   (px('f_import'), 'Importuj…', 'STEP · STL · BREP · DXF · SVG', self.import_model),
                   (px('f_export'), 'Eksportuj…', 'STEP · STL · BREP · DXF', self.export_model),
                   None,
                   (px('f_help'), 'Pomoc', 'Samouczek: jak korzystać z programu', self.show_help)]
        menu = ui.RichMenu(self, entries, 'Plik', 330)
        self._popup = menu
        button = self.tools['file']
        menu.popup_at(button.mapToGlobal(QPoint(0, button.height() + 10)))

    def show_help(self):
        from .help import HelpDialog
        HelpDialog(self).exec()

    def confirm_discard(self):
        if self.busy:
            self.toast('Trwa operacja — poczekaj na jej zakończenie.')
            return False
        if not self.document.dirty:
            return True
        return QMessageBox.question(self, 'Niezapisane zmiany', 'Odrzucić niezapisane zmiany?', QMessageBox.Discard | QMessageBox.Cancel,
                                    QMessageBox.Cancel) == QMessageBox.Discard

    def new_project(self):
        if self.confirm_discard():
            self.set_mode(None)
            self.document = Document()
            self.selected = []
            self.refresh(True)

    def open_project(self):
        if not self.confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Otwórz projekt', '', 'RCCAD (*.rccadx)')
        if path:
            self.set_mode(None)

            def loaded(doc):
                self.document = doc
                self.selected = []

            self.run_operation('Otwieranie projektu', lambda: Document.load(path), loaded, True)

    def save_project(self, save_as=False):
        path = self.document.path
        if save_as is True or path is None:
            value, _ = QFileDialog.getSaveFileName(self, 'Zapisz projekt', str(path or 'Projekt.rccadx'), 'RCCAD (*.rccadx)')
            if not value:
                return
            path = Path(value)
            if path.suffix.lower() != '.rccadx':
                path = path.with_suffix('.rccadx')
        self.run_operation('Zapisywanie projektu', lambda: self.document.save(path), lambda _: self.toast('Projekt zapisany.', 2500))

    def import_model(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importuj', '', 'Modele CAD i SVG (*.step *.stp *.brep *.brp *.stl *.dxf *.svg)')
        if not path:
            return
        if path.lower().endswith('.svg'):
            def build_svg():
                return [Body(f'{Path(path).stem} {i + 1}', w, 'sketch', 'XY').prepared() for i, w in enumerate(kernel.svg_profiles(path, 'XY'))]
            self.run_operation('Importowanie SVG', build_svg, self.add_prepared_many, True)
            return

        def build():
            return [Body(Path(path).stem if i == 0 else f'{Path(path).stem} {i + 1}', s, kind).prepared()
                    for i, (s, kind) in enumerate(kernel.import_shapes(path))]

        def add(bodies):
            if not bodies:
                raise kernel.CadError('Plik nie zawiera obsługiwanej geometrii.')
            self.document.commit((*self.document.bodies, *bodies))
            self.selected = [b.id for b in bodies]

        self.run_operation('Importowanie modelu', build, add, True)

    def import_svg(self):
        self.import_model()

    def export_model(self):
        bodies = [b for b in self.document.bodies if b.id in self.selected] if self.selected else [b for b in self.document.bodies if b.visible]
        if not bodies:
            self.toast('Brak geometrii do eksportu.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Eksportuj zaznaczone lub widoczne obiekty', 'Model.step',
                                              'STEP (*.step);;STL (*.stl);;BREP (*.brep);;DXF — szkice (*.dxf)')
        if path:
            self.run_operation('Eksportowanie', lambda: kernel.export_shapes([b.shape for b in bodies], path), lambda _: None)

    # =====================================================================
    # klawiatura
    # =====================================================================
    def keyPressEvent(self, event):
        key = event.key()
        if self.busy:
            super().keyPressEvent(event)
            return
        if self.mode == 'sketch':
            if key in (Qt.Key_Return, Qt.Key_Enter) and self.tool == 'line' and self.points and not self.dim_panel.isVisible():
                self.finish_line()
                event.accept()
                return
            text = event.text()
            if text and text in '0123456789.,-' and self.points and not self.dim_panel.isVisible() and self.open_dim_input(text):
                event.accept()
                return
        if key == Qt.Key_Tab and self.dim_panel.isVisible():
            edits = [e for e in self.dim_edits if e.isVisible()]
            if len(edits) > 1:
                (edits[1] if edits[0].hasFocus() else edits[0]).setFocus()
            event.accept()
            return
        if key in (Qt.Key_Return, Qt.Key_Enter):
            action = {'extrude': self.apply_extrude, 'bool': self.apply_bool, 'mod': self.apply_mod, 'mirror': self.apply_mirror,
                      'move': self.apply_transform, 'rotate': self.apply_transform}.get(self.mode)
            if action:
                action()
                event.accept()
                return
        if key == Qt.Key_Escape:
            if self.dim_panel.isVisible():
                self.dim_panel.hide()
                self.view.setFocus()
            elif self.mode == 'sketch' and (self.points or self.tangent_lines):
                self.end_current_shape()
            elif self.mode == 'sketch' and self.tool is None and self.selected:
                self.selected = []
                self.refresh()
                self._update_grips()
            elif self.mode == 'sketch' and self.tool == 'text':
                self.choose_tool('rect')
            elif self.mode is not None:
                self.set_mode(None)
            else:
                self.selected = []
                self.refresh()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.busy:
            self.toast('Trwa operacja — poczekaj na jej zakończenie.')
            event.ignore()
            return
        if not self.document.dirty:
            QApplication.instance().removeEventFilter(self)
            event.accept()
            return
        answer = QMessageBox.question(self, 'Niezapisane zmiany', 'Projekt ma niezapisane zmiany. Zapisać przed zamknięciem?',
                                      QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if answer == QMessageBox.Discard:
            event.accept()
        elif answer == QMessageBox.Save:
            path = self.document.path
            if path is None:
                value, _ = QFileDialog.getSaveFileName(self, 'Zapisz projekt', 'Projekt.rccadx', 'RCCAD (*.rccadx)')
                if not value:
                    event.ignore()
                    return
                path = Path(value)
                if path.suffix.lower() != '.rccadx':
                    path = path.with_suffix('.rccadx')
            try:
                self.document.save(path)
            except Exception as exc:
                QMessageBox.warning(self, 'Zapis nie powiódł się', str(exc))
                event.ignore()
                return
            event.accept()
        else:
            event.ignore()
