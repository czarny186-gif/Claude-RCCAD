"""Okno "Studio": układ, grafika i sposób modelowania/szkicowania odtworzone z wersji HTML (natywnie, bez przeglądarki)."""
from __future__ import annotations
from pathlib import Path
from PySide6.QtCore import QEvent, QObject, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QCursor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QMainWindow, QMenu, QMessageBox, QPushButton, QToolButton, QVBoxLayout, QWidget)
from . import kernel
from . import shell_ui as ui
from .document import Body, Document
from .viewport import CadView

NEED = {'rect': 2, 'centerRect': 2, 'rect3': 3, 'circle': 2, 'circle2': 2, 'circle3': 3, 'ellipse': 2, 'slot': 3, 'polygon': 2,
        'arc': 3, 'point': 1, 'construction': 2, 'measure': 2, 'text': 1, 'trim': 1, 'line': 2, 'circleTangent2': 3}
HINTS = {
    'rect': ['Kliknij pierwszy narożnik prostokąta.', 'Kliknij przeciwległy narożnik.'],
    'centerRect': ['Kliknij środek prostokąta.', 'Kliknij narożnik.'],
    'circle': ['Kliknij środek okręgu.', 'Kliknij punkt na okręgu (promień).'],
    'circle2': ['Kliknij pierwszy koniec średnicy.', 'Kliknij drugi koniec średnicy.'],
    'circle3': ['Kliknij pierwszy punkt okręgu.', 'Kliknij drugi punkt.', 'Kliknij trzeci punkt.'],
    'ellipse': ['Kliknij środek elipsy.', 'Kliknij narożnik opisanego prostokąta.'],
    'slot': ['Kliknij środek pierwszego końca.', 'Kliknij środek drugiego końca.', 'Kliknij punkt określający szerokość.'],
    'polygon': ['Kliknij środek wielokąta.', 'Kliknij wierzchołek.'],
    'rect3': ['Kliknij pierwszy punkt podstawy.', 'Kliknij drugi punkt podstawy.', 'Kliknij punkt określający wysokość.'],
    'arc': ['Kliknij początek łuku.', 'Kliknij punkt na łuku.', 'Kliknij koniec łuku.'],
    'point': ['Kliknij miejsce punktu.'],
    'construction': ['Kliknij początek linii konstrukcyjnej.', 'Kliknij koniec.'],
    'measure': ['Kliknij pierwszy punkt pomiaru.', 'Kliknij drugi punkt.'],
    'text': ['Wpisz treść w panelu i kliknij miejsce na szkicu.'],
    'trim': ['Nożyczki: kliknij fragment szkicu, który ma zniknąć.'],
    'line': ['Kliknij początek linii.', 'Kliknij kolejny punkt (Enter lub podwójne kliknięcie kończy, kliknięcie w pierwszy punkt zamyka obrys).'],
    'circleTangent2': ['Kliknij pierwszą linię.', 'Kliknij drugą linię.', 'Kliknij, aby wskazać wielkość okręgu.'],
}
LATER = set()
TINT_BASE = (.30, .55, .95, 1)
TINT_TOOL = (.95, .55, .20, 1)


def kernel_close(a, b, tol=1e-3):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


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


def _row(label, widget):
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    layout.addWidget(QLabel(label))
    layout.addWidget(widget)
    return box


def _spin(value, low=-1e6, high=1e6, suffix=' mm', decimals=3):
    box = QDoubleSpinBox()
    box.setRange(low, high)
    box.setDecimals(decimals)
    box.setValue(value)
    if suffix:
        box.setSuffix(suffix)
    return box


class StudioWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.document = Document()
        self.pool = QThreadPool.globalInstance()
        self.busy = False
        self.selected: list[str] = []
        self.edges: dict[str, set] = {}
        self.mode = None            # None | plane | sketch | extrude | bool | mod | mirror
        self.tool = 'rect'
        self.sides = 5
        self.points: list[tuple[float, float]] = []
        self.sketch_plane = None
        self.extrude_body_id = None
        self.extrude_src = None
        self._hv = None
        self.bool_ids: list[str] = []
        self.mirror_id = None
        self.mirror_face = None
        self.tangent_lines = []
        self._work = None
        self.resize(1400, 850)
        self.setStyleSheet(ui.STYLE)
        self.view = CadView(self)
        self.view.click_mode = True
        self.setCentralWidget(self.view)
        self.view.setStyleSheet('')
        self.view.planeClicked.connect(self.plane_picked)
        self.view.sketchMoved.connect(self.sketch_moved)
        self.view.sketchClicked.connect(self.sketch_clicked)
        self.view.viewClicked.connect(self.view_clicked)
        self.view.viewHover.connect(self.view_hover)
        self.view.contextRequested.connect(self.context_menu)
        self.view.handleDragged.connect(self.handle_dragged)
        self.view.handleReleased.connect(self.handle_released)
        self._build_overlays()
        self.view.installEventFilter(self)
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(120)
        self._preview_timer.timeout.connect(self.update_extrude_preview)
        self._mod_timer = QTimer(self)
        self._mod_timer.setSingleShot(True)
        self._mod_timer.setInterval(250)
        self._mod_timer.timeout.connect(self.update_mod_preview)
        for seq, fn in (('Ctrl+Z', self.undo), ('Ctrl+Y', self.redo), ('Ctrl+Shift+Z', self.redo), ('Ctrl+S', self.save_project),
                        ('Ctrl+O', self.open_project), ('Ctrl+N', self.new_project), ('Delete', self.delete_selected)):
            QShortcut(QKeySequence(seq), self, activated=fn)
        self.refresh(True)
        self._layout_overlays()
        self.hint('Wybierz narzędzie z paska u góry. „Szkic” zaczyna rysowanie na płaszczyźnie.')

    # ---------- budowa interfejsu ----------
    def _build_overlays(self):
        v = self.view
        icons = [('file', ui.svg_icon(ui.file_svg('fileTool.svg'), size=34), 'Plik'),
                 ('sketch', ui.png_icon('newSketch.png'), 'Nowy szkic'),
                 ('extrude', ui.png_icon('extrudeTool.png'), 'Wyciągnij'),
                 ('bool', ui.png_icon('boolTool.png'), 'Boolean — suma, różnica, część wspólna'),
                 ('mod', ui.png_icon('modTool.png'), 'Edytuj bryłę — zaokrąglenie i fazowanie'),
                 ('mirror', ui.png_icon('mirrorTool.png'), 'Lustro')]
        self.tools = {}
        for key, icon, tip in icons:
            button = ui.big_tool(icon, tip, checkable=key != 'file')
            button.setParent(v)
            self.tools[key] = button
        self.tools['file'].clicked.connect(self.file_menu)
        self.tools['sketch'].clicked.connect(lambda: self.set_mode('plane') if self.mode not in ('plane', 'sketch') else self.set_mode(None))
        self.tools['extrude'].clicked.connect(lambda: self.set_mode('extrude') if self.mode != 'extrude' else self.set_mode(None))
        self.tools['bool'].clicked.connect(lambda: self.set_mode('bool') if self.mode != 'bool' else self.set_mode(None))
        self.tools['mod'].clicked.connect(lambda: self.set_mode('mod') if self.mode != 'mod' else self.set_mode(None))
        self.tools['mirror'].clicked.connect(lambda: self.set_mode('mirror') if self.mode != 'mirror' else self.set_mode(None))

        # pasek kształtów szkicu (18,80)
        self.shape_bar = QFrame(v)
        self.shape_bar.setObjectName('toolbar')
        layout = QHBoxLayout(self.shape_bar)
        layout.setContentsMargins(7, 7, 7, 7)
        layout.setSpacing(5)
        self.shape_buttons = {}
        shapes = ui.load_shapes()
        groups: dict[str, list[dict]] = {}
        for item in shapes:
            if item['variant']:
                groups.setdefault(item['group'], []).append(item)
        for item in shapes:
            if item['variant']:
                continue
            button = QToolButton()
            button.setObjectName('shape')
            button.setCheckable(True)
            button.setFixedSize(40, 40)
            button.setIcon(ui.svg_icon(ui.stroked_shape_svg(item['svg']), size=26))
            button.setIconSize(QSize(26, 26))
            button.setToolTip(item['title'])
            button.clicked.connect(lambda _=False, name=item['shape']: self.choose_tool(name))
            layout.addWidget(button)
            self.shape_buttons[item['shape']] = button
            if item['group'] and groups.get(item['group']):
                more = QToolButton()
                more.setObjectName('expand')
                more.setText('▾')
                more.setFixedSize(16, 40)
                menu = QMenu(more)
                for variant in groups[item['group']]:
                    menu.addAction(variant['title'], lambda name=variant['shape'], b=button: self.choose_tool(name, b))
                more.setMenu(menu)
                more.setPopupMode(QToolButton.InstantPopup)
                layout.addWidget(more)
        done = QPushButton('Zakończ szkic')
        done.setObjectName('endsketch')
        done.setStyleSheet('QPushButton#endsketch{background:#f3f7fb;border:1px solid #9db8cf;border-radius:8px;padding:9px 14px;color:#254c71;font:13px "Segoe UI";}'
                           'QPushButton#endsketch:hover{background:#dcecff;}')
        done.clicked.connect(lambda: self.set_mode(None))
        layout.addWidget(done)
        self.shape_bar.adjustSize()
        self.shape_bar.hide()

        # historia, warstwy płaszczyzn, widok domowy (prawy górny róg)
        self.undo_button = self._round('↶', 'Cofnij (Ctrl+Z)', self.undo)
        self.redo_button = self._round('↷', 'Ponów (Ctrl+Y)', self.redo)
        self.layers = QToolButton(v)
        self.layers.setObjectName('layers')
        self.layers.setCheckable(True)
        self.layers.setFixedSize(40, 40)
        self.layers.setIcon(ui.svg_icon('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round">'
                                        '<path d="M16 5l11 6-11 6-11-6z"/><path d="M5 16l11 6 11-6"/><path d="M5 21l11 6 11-6"/></svg>', normal='#ffffff', active='#344e69', size=26))
        self.layers.setToolTip('Pokaż / ukryj płaszczyzny XY, XZ, YZ')
        self.layers.toggled.connect(lambda on: self.view.show_planes(on or self.mode in ('plane', 'sketch'), only=self.sketch_plane if self.mode == 'sketch' else None))
        self.home = QToolButton(v)
        self.home.setObjectName('home')
        self.home.setText('⌂')
        self.home.setFixedSize(36, 36)
        self.home.setToolTip('Widok domowy — dopasuj do modelu')
        self.home.clicked.connect(lambda: (self.view.set_view('iso'), self.view.fit_all()))

        # kostka widoku (138×138)
        self.cube = QFrame(v)
        self.cube.setObjectName('floating')
        self.cube.setFixedSize(138, 138)
        grid = [('Góra', 'Z', 0, 1), ('Dół', '-Z', 2, 1), ('Lewo', '-X', 1, 0), ('Przód', '-Y', 1, 1), ('Prawo', 'X', 1, 2),
                ('Tył', 'Y', 2, 2), ('Iso', 'iso', 0, 2), ('XY', 'XY', 2, 0), ('XZ', 'XZ', 0, 0)]
        shades = {'Z': '#8fb2d6', '-Z': '#5f7f9f', '-X': '#7897b6', '-Y': '#a3c1de', 'X': '#6d8cab', 'Y': '#6280a0', 'iso': '#3b6ea5', 'XY': '#3b82f6', 'XZ': '#22a06b'}
        for text, name, row, col in grid:
            button = QToolButton(self.cube)
            button.setObjectName('cube')
            button.setText(text)
            button.setFixedSize(38, 38)
            button.move(9 + col * 40, 9 + row * 40)
            button.setStyleSheet(f'QToolButton#cube{{background:{shades[name]};}}')
            button.clicked.connect(lambda _=False, n=name: self.view.set_view(n))
        self.cube.setToolTip('Widoki standardowe')

        # tryb myszy (dół, środek)
        self.pad = QFrame(v)
        self.pad.setObjectName('floating')
        pad_layout = QHBoxLayout(self.pad)
        pad_layout.setContentsMargins(8, 8, 8, 8)
        pad_layout.setSpacing(6)
        self.pad_buttons = {}
        for name, text, tip in (('select', '↖', 'Zaznaczanie'), ('orbit', '⟳', 'Obrót widoku'), ('pan', '✥', 'Przesuwanie widoku')):
            button = QToolButton()
            button.setObjectName('pad')
            button.setText(text)
            button.setCheckable(True)
            button.setFixedSize(40, 40)
            button.setToolTip(tip)
            button.clicked.connect(lambda _=False, n=name: self.set_mouse(n))
            pad_layout.addWidget(button)
            self.pad_buttons[name] = button
        self.pad.adjustSize()
        self.pad_buttons['select'].setChecked(True)

        self.hint_label = QLabel(v)
        self.hint_label.setObjectName('hint')
        self.notice = QLabel(v)
        self.notice.setObjectName('notice')
        self.notice.hide()
        self.notice_timer = QTimer(self)
        self.notice_timer.setSingleShot(True)
        self.notice_timer.timeout.connect(self.notice.hide)
        self.dim = QLabel(v)
        self.dim.setObjectName('dim')
        self.dim.hide()
        self.dim.setAttribute(Qt.WA_TransparentForMouseEvents)

        self._build_panels()

    def _round(self, text, tip, callback):
        button = QToolButton(self.view)
        button.setObjectName('round')
        button.setText(text)
        button.setFixedSize(40, 40)
        button.setToolTip(tip)
        button.setStyleSheet('QToolButton#round{font-size:20px;}')
        button.clicked.connect(callback)
        return button

    def _build_panels(self):
        v = self.view
        # --- Wyciągnięcie ---
        self.ex_panel = ui.panel(195)
        self.ex_panel.setParent(v)
        lay = QVBoxLayout(self.ex_panel)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)
        title = QLabel('Wyciągnięcie')
        title.setObjectName('title')
        lay.addWidget(title)
        self.ex_op = QComboBox()
        self.ex_op.addItem('Nowa bryła', 'new')
        self.ex_op.addItem('Połącz z bryłą', 'union')
        self.ex_op.addItem('Wytnij z bryły', 'subtract')
        lay.addWidget(_row('Operacja', self.ex_op))
        self.ex_target = QComboBox()
        self.ex_target_row = _row('Bryła docelowa', self.ex_target)
        lay.addWidget(self.ex_target_row)
        self.ex_sym = QCheckBox('Symetrycznie w obie strony')
        lay.addWidget(self.ex_sym)
        self.ex_two = QCheckBox('Dwie strony niezależnie')
        lay.addWidget(self.ex_two)
        self.ex_status = QLabel('Kliknij zamknięty profil szkicu.')
        self.ex_status.setObjectName('status')
        self.ex_status.setWordWrap(True)
        lay.addWidget(self.ex_status)
        self.ex_panel.hide()
        # górny pasek wyciągnięcia
        self.ex_bar = QFrame(v)
        self.ex_bar.setObjectName('panel')
        bar = QHBoxLayout(self.ex_bar)
        bar.setContentsMargins(13, 9, 13, 9)
        bar.setSpacing(9)
        bar.addWidget(QLabel('Odległość'))
        self.ex_distance = _spin(20, -1e5, 1e5)
        self.ex_distance.setFixedWidth(130)
        bar.addWidget(self.ex_distance)
        self.ex_dist2_label = QLabel('Odległość 2')
        bar.addWidget(self.ex_dist2_label)
        self.ex_distance2 = _spin(10, 0, 1e5)
        self.ex_distance2.setFixedWidth(120)
        bar.addWidget(self.ex_distance2)
        self.ex_apply = QPushButton('✓ Zastosuj')
        self.ex_apply.clicked.connect(self.apply_extrude)
        bar.addWidget(self.ex_apply)
        cancel = QPushButton('✕')
        cancel.clicked.connect(lambda: self.set_mode(None))
        bar.addWidget(cancel)
        self.ex_bar.adjustSize()
        self.ex_bar.hide()
        self.ex_distance.valueChanged.connect(lambda *_: self._preview_timer.start())
        self.ex_sym.toggled.connect(lambda on: (self.ex_two.setChecked(False) if on else None, self._preview_timer.start()))
        self.ex_two.toggled.connect(self._two_toggled)
        self.ex_distance2.valueChanged.connect(lambda *_: self._preview_timer.start())
        self.ex_op.currentIndexChanged.connect(self._extrude_options_changed)
        self.ex_target.currentIndexChanged.connect(lambda *_: self._preview_timer.start())

        # --- Boolean ---
        self.bool_panel = ui.panel(262)
        self.bool_panel.setParent(v)
        lay = QVBoxLayout(self.bool_panel)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)
        title = QLabel('Boolean')
        title.setObjectName('title')
        lay.addWidget(title)
        self.bool_op = QComboBox()
        self.bool_op.addItem('Suma (połącz)', 'union')
        self.bool_op.addItem('Różnica (wytnij narzędziami)', 'subtract')
        self.bool_op.addItem('Część wspólna', 'intersect')
        lay.addWidget(_row('Operacja', self.bool_op))
        self.bool_status = QLabel('')
        self.bool_status.setObjectName('status')
        self.bool_status.setWordWrap(True)
        lay.addWidget(self.bool_status)
        row = QHBoxLayout()
        apply_ = QPushButton('Zastosuj')
        apply_.clicked.connect(self.apply_bool)
        reset = QPushButton('Wyczyść wybór')
        reset.clicked.connect(self.reset_bool)
        row.addWidget(apply_)
        row.addWidget(reset)
        lay.addLayout(row)
        self.bool_panel.hide()

        # --- Edytuj bryłę (zaokrąglenie / fazowanie) ---
        self.mod_panel = ui.panel(262)
        self.mod_panel.setParent(v)
        lay = QVBoxLayout(self.mod_panel)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)
        title = QLabel('Edytuj bryłę')
        title.setObjectName('title')
        lay.addWidget(title)
        self.mod_kind = QComboBox()
        self.mod_kind.addItem('Zaokrąglenie krawędzi', 'fillet')
        self.mod_kind.addItem('Fazowanie krawędzi', 'chamfer')
        lay.addWidget(_row('Operacja', self.mod_kind))
        self.mod_size = _spin(2, .001, 1e5)
        lay.addWidget(_row('Promień / odległość', self.mod_size))
        self.mod_size.valueChanged.connect(lambda *_: self._mod_timer.start())
        self.mod_kind.currentIndexChanged.connect(lambda *_: self._mod_timer.start())
        self.mod_status = QLabel('')
        self.mod_status.setObjectName('status')
        self.mod_status.setWordWrap(True)
        lay.addWidget(self.mod_status)
        row = QHBoxLayout()
        apply_ = QPushButton('Zastosuj')
        apply_.clicked.connect(self.apply_mod)
        clear = QPushButton('Wyczyść')
        clear.clicked.connect(self.clear_edges)
        row.addWidget(apply_)
        row.addWidget(clear)
        lay.addLayout(row)
        self.mod_panel.hide()

        # --- Lustro ---
        self.mir_panel = ui.panel(262)
        self.mir_panel.setParent(v)
        lay = QVBoxLayout(self.mir_panel)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)
        title = QLabel('Lustro')
        title.setObjectName('title')
        lay.addWidget(title)
        self.mir_plane = QComboBox()
        for name in ('XY', 'XZ', 'YZ'):
            self.mir_plane.addItem(f'Płaszczyzna {name}', name)
        self.mir_plane.addItem('Wskazana ściana (kliknij w widoku)', 'face')
        lay.addWidget(_row('Płaszczyzna odbicia', self.mir_plane))
        self.mir_keep = QCheckBox('Zachowaj oryginał')
        self.mir_keep.setChecked(True)
        lay.addWidget(self.mir_keep)
        self.mir_status = QLabel('')
        self.mir_status.setObjectName('status')
        self.mir_status.setWordWrap(True)
        lay.addWidget(self.mir_status)
        apply_ = QPushButton('Zastosuj')
        apply_.clicked.connect(self.apply_mirror)
        lay.addWidget(apply_)
        self.mir_panel.hide()
        # --- panel tekstu (narzędzie Tekst) ---
        self.text_panel = ui.panel(262)
        self.text_panel.setParent(v)
        lay = QVBoxLayout(self.text_panel)
        lay.setContentsMargins(13, 13, 13, 13)
        lay.setSpacing(9)
        title = QLabel('Tekst')
        title.setObjectName('title')
        lay.addWidget(title)
        self.text_edit = QLineEdit('RCCAD')
        lay.addWidget(_row('Treść', self.text_edit))
        self.text_size = _spin(10, .5, 1000)
        lay.addWidget(_row('Wysokość liter', self.text_size))
        note = QLabel('Kliknij miejsce na szkicu, aby wstawić tekst.')
        note.setObjectName('small')
        note.setWordWrap(True)
        lay.addWidget(note)
        self.text_panel.hide()
        # --- wpisywanie wymiaru z klawiatury ---
        self.dim_edit = QLineEdit(v)
        self.dim_edit.setFixedWidth(130)
        self.dim_edit.setStyleSheet('QLineEdit{background:#fff;border:2px solid #2087d6;border-radius:6px;padding:5px;color:#1c5a8f;font:bold 13px "Segoe UI";}')
        self.dim_edit.hide()
        self.dim_edit.returnPressed.connect(self.apply_typed)
        # --- pasek transformacji (przesuń / obróć zaznaczone) ---
        self.tbar = QFrame(v)
        self.tbar.setObjectName('panel')
        tl = QHBoxLayout(self.tbar)
        tl.setContentsMargins(13, 9, 13, 9)
        tl.setSpacing(7)
        self.t_spins = {}
        for key, label in (('x', 'Przesuń X'), ('y', 'Y'), ('z', 'Z'), ('rx', 'Obrót X°'), ('ry', 'Y°'), ('rz', 'Z°')):
            tl.addWidget(QLabel(label))
            spin = _spin(0, -1e6, 1e6, suffix='', decimals=2)
            spin.setFixedWidth(82)
            tl.addWidget(spin)
            self.t_spins[key] = spin
        self.t_copy = QCheckBox('Kopia')
        tl.addWidget(self.t_copy)
        go = QPushButton('Zastosuj')
        go.clicked.connect(self.apply_transform)
        tl.addWidget(go)
        self.tbar.adjustSize()
        self.tbar.hide()
        self.panels = (self.ex_panel, self.ex_bar, self.bool_panel, self.mod_panel, self.mir_panel, self.text_panel)
        for p in self.panels:
            p.adjustSize()
        self.ex_dist2_label.hide()
        self.ex_distance2.hide()
        self.ex_bar.adjustSize()

    def _layout_overlays(self):
        W, H = self.view.width(), self.view.height()
        for i, key in enumerate(('file', 'sketch', 'extrude', 'bool', 'mod', 'mirror')):
            self.tools[key].move(18 + 60 * i, 18)
        self.shape_bar.move(18, 80)
        self.undo_button.move(W - 350, 20)
        self.redo_button.move(W - 302, 20)
        self.layers.move(W - 254, 20)
        self.home.move(W - 205, 22)
        self.cube.move(W - 160, 20)
        self.pad.move(max(18, W // 2 - self.pad.width() // 2), H - 170)
        top = 150 if self.shape_bar.isVisible() else 88
        self.ex_panel.move(18, 170)
        self.ex_bar.move(230, 170)
        for p in (self.bool_panel, self.mod_panel, self.mir_panel, self.text_panel):
            p.move(18, top)
        self.tbar.move(18, H - 130)
        self.tbar.raise_()
        self.hint_label.adjustSize()
        self.hint_label.move(18, H - 36)
        self.notice.adjustSize()
        self.notice.move(max(18, (W - self.notice.width()) // 2), 20 if W > 900 else 88)
        for w in (*self.tools.values(), self.shape_bar, self.undo_button, self.redo_button, self.layers, self.home,
                  self.cube, self.pad, self.hint_label, *self.panels):
            w.raise_()
        self.notice.raise_()
        self.dim.raise_()

    def eventFilter(self, obj, event):
        if obj is self.view and event.type() == QEvent.Resize:
            self._layout_overlays()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_overlays()

    # ---------- komunikaty ----------
    def hint(self, text):
        self.hint_label.setText(text)
        self.hint_label.adjustSize()
        self._layout_overlays()

    def toast(self, text, ms=4500):
        self.notice.setText(text)
        self.notice.adjustSize()
        self.notice.show()
        self._layout_overlays()
        self.notice_timer.start(ms)

    # ---------- tryby ----------
    def set_mouse(self, name):
        self.view.mouse_mode = name
        for key, button in self.pad_buttons.items():
            button.setChecked(key == name)
        self.view.setCursor(Qt.OpenHandCursor if name != 'select' else Qt.ArrowCursor)

    def set_mode(self, mode):
        """Przełącza tryb narzędzia; None = zwykłe zaznaczanie."""
        if self.busy:
            return
        self.mode = mode
        self.points = []
        self.tangent_lines = []
        self.dim.hide()
        self.dim_edit.hide()
        self.view.set_preview_mesh(None)
        self.view.sketch_plane = None
        self.view.sketch_tool = None
        self.view.plane_pick = False
        self.view.edge_mode = False
        self.view.tints = {}
        self.sketch_plane = None
        self.extrude_body_id = None
        self.extrude_src = None
        self.view.set_handle(None, None)
        self.bool_ids = []
        self.mirror_id = None
        self.mirror_face = None
        self.edges = {}
        for key, button in self.tools.items():
            if key != 'file':
                button.setChecked(key == ('sketch' if mode in ('plane', 'sketch') else mode))
        for p in (self.shape_bar, *self.panels):
            p.hide()
        self.view.show_planes(self.layers.isChecked())
        self.view.setCursor(Qt.ArrowCursor)
        if mode == 'plane':
            self.view.plane_pick = True
            self.view.show_planes(True)
            self.hint('Szkic: kliknij płaszczyznę XY, XZ lub YZ, na której chcesz rysować.')
        elif mode == 'extrude':
            self.fill_targets()
            self.ex_panel.show()
            self.ex_status.setText('Kliknij zamknięty profil szkicu, aby go wyciągnąć.')
            self.hint('Wyciągnięcie: kliknij profil szkicu. Odległość wpisz u góry; ujemna — w drugą stronę.')
            self.view.setCursor(Qt.PointingHandCursor)
        elif mode == 'bool':
            self.bool_panel.show()
            self.update_bool_status()
            self.hint('Boolean: kliknij bryłę bazową, potem kolejne bryły-narzędzia, i wybierz operację.')
        elif mode == 'mod':
            self.mod_panel.show()
            self.update_mod_status()
            self.hint('Edytuj bryłę: kliknij krawędź (Shift — cały łańcuch styczny, Ctrl — dodaj do wyboru).')
        elif mode == 'mirror':
            self.mir_panel.show()
            self.update_mirror_status()
            self.hint('Lustro: kliknij bryłę, wybierz płaszczyznę odbicia i zastosuj.')
        else:
            self.hint('Wybierz narzędzie z paska u góry. „Szkic” zaczyna rysowanie na płaszczyźnie.')
        self.refresh()
        self._layout_overlays()

    def choose_tool(self, name, button=None):
        self.tool = name
        self.points = []
        self.tangent_lines = []
        self.text_panel.setVisible(name == 'text')
        self.dim_edit.hide()
        self.dim.hide()
        self.view.set_preview_mesh(None)
        self.view.sketch_tool = name
        for key, b in self.shape_buttons.items():
            b.setChecked(b is (button or self.shape_buttons.get(self._group_button(name))))
        self.show_sketch_hint()

    @staticmethod
    def _group_button(name):
        return {'centerRect': 'rect', 'rect3': 'rect', 'circle2': 'circle', 'circle3': 'circle', 'circleTangent2': 'circle'}.get(name, name)

    def show_sketch_hint(self):
        texts = HINTS.get(self.tool, [''])
        self.hint(f'Płaszczyzna {self.sketch_plane}. ' + texts[min(len(self.points), len(texts) - 1)] + '  (Esc — przerwij, Alt — bez przyciągania)')

    # ---------- szkic ----------
    def plane_picked(self, name):
        if self.mode != 'plane':
            return
        self.mode = 'sketch'
        self.sketch_plane = name
        self.view.plane_pick = False
        self.view.sketch_plane = name
        self.view.show_planes(True, only=name)
        self.view.set_view(name)
        self.view.setCursor(Qt.CrossCursor)
        self.shape_bar.show()
        self.points = []
        self.choose_tool(self.tool)
        self._layout_overlays()

    def _wire(self, points, closed=False):
        t = self.tool
        if t in ('line', 'construction'):
            return kernel.polyline(self.sketch_plane, points, closed)
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
        if t in ('measure', 'text', 'trim', 'circleTangent2'):
            return kernel.polyline(self.sketch_plane, pts) if t == 'measure' and len(pts) == 2 else None
        if len(pts) == need:
            return self._wire(pts)
        if t == 'circle3' and len(pts) == 2:
            return kernel.sketch_shape('circle2', self.sketch_plane, pts)
        if t in ('arc', 'rect3', 'slot') and len(pts) == 2:
            return kernel.polyline(self.sketch_plane, pts)
        return None

    def sketch_moved(self, plane, u, v):
        if self.mode != 'sketch' or self.busy:
            return
        if self.tool == 'circleTangent2':
            if len(self.tangent_lines) == 2:
                try:
                    shape = kernel.circle_tangent2(self.sketch_plane, *self.tangent_lines, (u, v))
                    self.view.set_preview_mesh(kernel.display_mesh(shape), line_color=(1, .48, .05, 1), width=2.5)
                except kernel.CadError:
                    self.view.set_preview_mesh(None)
            return
        if not self.points:
            return
        pts = [*self.points, (u, v)]
        try:
            shape = self._preview_points(pts)
            self.view.set_preview_mesh(kernel.display_mesh(shape) if shape is not None else None, line_color=(1, .48, .05, 1), width=2.5)
        except Exception:
            self.view.set_preview_mesh(None)
        self.show_dimension(pts)

    def show_dimension(self, pts):
        import math
        a = self.points[0]
        b = pts[-1]
        if self.tool == 'line' and len(pts) > 2:
            a = pts[-2]
        du, dv = abs(b[0] - a[0]), abs(b[1] - a[1])
        if self.tool in ('rect', 'ellipse'):
            text = f'{du:.2f} × {dv:.2f} mm'
        elif self.tool == 'centerRect':
            text = f'{2 * du:.2f} × {2 * dv:.2f} mm'
        elif self.tool in ('circle', 'polygon'):
            text = f'R {math.hypot(du, dv):.2f} mm'
        elif self.tool == 'circle2':
            text = f'Ø {math.hypot(b[0] - a[0], b[1] - a[1]):.2f} mm'
        else:
            text = f'{math.hypot(b[0] - a[0], b[1] - a[1]):.2f} mm'
        self.dim.setText(text)
        self.dim.adjustSize()
        pos = self.view.mapFromGlobal(QCursor.pos())
        self.dim.move(pos.x() + 16, pos.y() + 14)
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
        return kernel._line_uv(edge, body.plane)

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
                    self.hint(f'Płaszczyzna {self.sketch_plane}. ' + HINTS[t][len(self.tangent_lines)])
                    return
                shape = kernel.circle_tangent2(plane, *self.tangent_lines, (u, v))
                self.tangent_lines = []
                self.view.set_preview_mesh(None)
                self.create_sketch([shape])
                return
            if t == 'text':
                shapes = kernel.text_shape(plane, self.text_edit.text(), u, v, self.text_size.value())
                self.create_sketch(shapes, 'Tekst')
                return
        except kernel.CadError as exc:
            self.toast(str(exc))
            return
        if t == 'line':
            if self.points and kernel_close(self.points[0], (u, v)) and len(self.points) >= 3:
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
        self.view.set_preview_mesh(None)
        if len(points) < 2:
            self.show_sketch_hint()
            return
        try:
            self.create_sketch([kernel.polyline(self.sketch_plane, points, closed)])
        except kernel.CadError as exc:
            self.toast(str(exc))

    def complete(self, points):
        """Zebrane punkty tworzą gotowy element szkicu (lub pomiar)."""
        self.dim.hide()
        self.view.set_preview_mesh(None)
        try:
            if self.tool == 'measure':
                (a, b) = points[:2]
                import math
                self.toast(f'Odległość: {math.hypot(b[0] - a[0], b[1] - a[1]):.3f} mm   (ΔU {abs(b[0] - a[0]):.3f}, ΔV {abs(b[1] - a[1]):.3f})', 8000)
                self.show_sketch_hint()
                return
            shape = self._wire(points)
        except kernel.CadError as exc:
            self.toast(str(exc))
            self.show_sketch_hint()
            return
        self.create_sketch([shape], 'Konstrukcja' if self.tool == 'construction' else ('Punkt' if self.tool == 'point' else None))

    def create_sketch(self, shapes, label=None):
        plane = self.sketch_plane
        name = f'{label or "Szkic"} {plane}'
        self.run_operation('Tworzenie szkicu', lambda: [Body(name, sh, 'sketch', plane).prepared() for sh in shapes], self.add_prepared_many)
        self.show_sketch_hint()

    def add_prepared_many(self, bodies):
        self.document.commit((*self.document.bodies, *bodies))
        if self.mode != 'sketch':
            self.selected = [b.id for b in bodies]

    def trim_at_cursor(self):
        hit = self._cursor_edge()
        body = self.document.get(hit[0]) if hit else None
        if body is None or body.kind != 'sketch':
            raise kernel.CadError('Kliknij fragment szkicu.')
        index = hit[1]

        def build():
            wires = kernel.remove_edge(body.shape, index)
            made = [Body(body.name, w, 'sketch', body.plane).prepared() for w in wires]
            out = []
            for b in self.document.bodies:
                out.extend(made if b.id == body.id else [b])
            return out

        self.run_operation('Nożyczki', build, lambda bodies: self.document.commit(bodies))

    # ---------- wpisywanie wymiarów z klawiatury ----------
    def open_dim_input(self, first=''):
        if self.mode != 'sketch' or not self.points or self.tool in ('arc', 'rect3', 'circle3', 'slot', 'text', 'trim', 'circleTangent2', 'point'):
            return False
        self.dim_edit.setText(first)
        pos = self.view.mapFromGlobal(QCursor.pos())
        self.dim_edit.move(pos.x() + 16, pos.y() + 14)
        self.dim_edit.show()
        self.dim_edit.raise_()
        self.dim_edit.setFocus()
        self.dim_edit.setPlaceholderText({'rect': 'szer wys', 'centerRect': 'szer wys', 'ellipse': 'rx ry'}.get(self.tool, 'długość  kąt°' if self.tool in ('line', 'construction', 'measure') else 'promień'))
        return True

    def apply_typed(self):
        import re, math
        text = self.dim_edit.text()
        self.dim_edit.hide()
        self.view.setFocus()
        nums = [float(x) for x in re.findall(r'[-+]?\d+(?:[.,]\d+)?', text.replace(',', '.'))]
        if not nums:
            return
        u0, v0 = self.points[-1] if self.tool == 'line' else self.points[0]
        t = self.tool
        if t in ('rect', 'ellipse', 'centerRect'):
            w, h = nums[0], nums[1] if len(nums) > 1 else nums[0]
            end = (u0 + (w / 2 if t == 'centerRect' else w), v0 + (h / 2 if t == 'centerRect' else h))
        elif t in ('circle', 'polygon', 'circle2'):
            end = (u0 + nums[0], v0)
        else:
            ang = math.radians(nums[1]) if len(nums) > 1 else 0.0
            end = (u0 + nums[0] * math.cos(ang), v0 + nums[0] * math.sin(ang))
        if t == 'line':
            self.points.append(end)
            self.show_sketch_hint()
            return
        points, self.points = [*self.points, end], []
        self.complete(points)

    # ---------- klikanie w widoku ----------
    def view_hover(self, x, y):
        if self.mode == 'mod':
            self.view._set_hover_edge(self.view.nearest_edge(x, y))

    def view_clicked(self, x, y, shift, ctrl):
        if self.busy:
            return
        if self.mode == 'extrude':
            self.pick_profile(x, y)
        elif self.mode == 'bool':
            self.pick_bool(x, y)
        elif self.mode == 'mod':
            self.pick_edge(x, y, shift, ctrl)
        elif self.mode == 'mirror':
            self.pick_mirror(x, y)
        elif self.mode is None:
            bid = self.view.pick_body(x, y)
            if bid is None:
                if not (shift or ctrl):
                    self.selected = []
            elif shift or ctrl:
                self.selected = [i for i in self.selected if i != bid] if bid in self.selected else [*self.selected, bid]
            else:
                self.selected = [bid]
            self.refresh()

    # ---------- wyciąganie ----------
    def fill_targets(self):
        self.ex_target.blockSignals(True)
        self.ex_target.clear()
        for body in self.document.bodies:
            if body.kind == 'solid':
                self.ex_target.addItem(body.name, body.id)
        self.ex_target.blockSignals(False)
        has = self.ex_target.count() > 0
        for index in (1, 2):
            item = self.ex_op.model().item(index)
            item.setEnabled(has)
        if not has:
            self.ex_op.setCurrentIndex(0)
        self._extrude_options_changed()

    def _two_toggled(self, on):
        if on:
            self.ex_sym.setChecked(False)
        self.ex_dist2_label.setVisible(on)
        self.ex_distance2.setVisible(on)
        self.ex_bar.adjustSize()
        self._preview_timer.start()

    def _extrude_options_changed(self, *_):
        self.ex_target_row.setVisible(self.ex_op.currentData() != 'new')
        self.ex_panel.adjustSize()
        self._preview_timer.start()

    def pick_profile(self, x, y):
        bid = self.view.pick_profile(x, y)
        src = None
        if bid is not None:
            body = self.document.get(bid)
            src = dict(kind='sketch', id=bid, wire=body.shape, normal=kernel.NORMALS[body.plane], center=body.shape.Center().toTuple())
        else:
            hit = self.view.pick_face(x, y)
            body = self.document.get(hit[0]) if hit else None
            if body is not None and body.kind == 'solid':
                try:
                    face, normal = kernel.face_at(body.shape, hit[1], hit[2])
                    src = dict(kind='face', id=body.id, wire=face.outerWire(), normal=tuple(float(c) for c in normal), center=face.Center().toTuple())
                except kernel.CadError as exc:
                    self.toast(str(exc))
                    return
        if src is None:
            self.toast('Kliknij zamknięty profil szkicu albo płaską ścianę bryły.')
            return
        self.extrude_body_id = src['id']
        self.extrude_src = src
        if src['kind'] == 'face':
            self.fill_targets()
            index = self.ex_target.findData(src['id'])
            if index >= 0:
                self.ex_target.setCurrentIndex(index)
                self.ex_op.setCurrentIndex(1)
        self.ex_bar.show()
        self.ex_status.setText('Wybrano ' + ('profil szkicu' if src['kind'] == 'sketch' else 'ścianę bryły') + '. Przeciągnij strzałkę albo wpisz odległość u góry.')
        self.hint('Wyciągnięcie: przeciągnij pomarańczową strzałkę lub wpisz odległość, potem ✓ Zastosuj.')
        self.ex_distance.setFocus()
        self.update_extrude_preview()
        self.place_handle()
        self._layout_overlays()

    def place_handle(self):
        src = self.extrude_src
        if src is None:
            self.view.set_handle(None, None)
            return
        n = src['normal']
        d = self.ex_distance.value()
        tip = [src['center'][i] + n[i] * d for i in range(3)]
        self.view.set_handle(tip, n)

    def handle_dragged(self, delta):
        if self.mode != 'extrude' or self.extrude_src is None:
            return
        if self._hv is None:
            self._hv = self.ex_distance.value()
        self.ex_distance.setValue(round(self._hv + delta, 1) or .1)

    def handle_released(self):
        self._hv = None
        self.place_handle()

    def _make_tool(self):
        """Funkcja budująca narzędzie wyciągnięcia z bieżących ustawień (bezpieczna do wywołania w wątku roboczym)."""
        src = self.extrude_src
        if src is None:
            raise kernel.CadError('Wybierz profil szkicu lub ścianę.')
        d1, d2 = self.ex_distance.value(), self.ex_distance2.value()
        sym, two = self.ex_sym.isChecked(), self.ex_two.isChecked()
        wire, normal = src['wire'], src['normal']
        if src['kind'] == 'sketch':
            plane = self.document.get(src['id']).plane
            return lambda: kernel.extrude2(wire, plane, d1, d2) if two else kernel.extrude(wire, plane, d1, sym)
        return lambda: kernel.extrude_dir(wire, normal, d1, d2 if two else 0.0, sym)

    def update_extrude_preview(self):
        if self.mode != 'extrude' or self.extrude_src is None:
            return
        src = self.extrude_src
        if src['kind'] == 'face' and self.ex_op.currentData() != 'new':
            want = 'union' if self.ex_distance.value() >= 0 else 'subtract'
            if self.ex_op.currentData() != want:
                self.ex_op.blockSignals(True)
                self.ex_op.setCurrentIndex(1 if want == 'union' else 2)
                self.ex_op.blockSignals(False)
                self.ex_target_row.setVisible(True)
                self.ex_panel.adjustSize()
        try:
            mesh = kernel.display_mesh(self._make_tool()())
        except Exception as exc:
            self.view.set_preview_mesh(None)
            self.ex_status.setText(str(exc))
            return
        color = (.95, .30, .25, .55) if self.ex_op.currentData() == 'subtract' else (.25, .55, .95, .55)
        self.view.set_preview_mesh(mesh, color=color)
        if self._hv is None:
            self.place_handle()

    def apply_extrude(self):
        if self.busy or self.extrude_src is None:
            return
        op = self.ex_op.currentData()
        base = self.document.get(self.ex_target.currentData()) if op != 'new' else None
        if op != 'new' and base is None:
            self.toast('Wybierz bryłę docelową.')
            return
        make = self._make_tool()

        def build():
            tool = make()
            if base is None:
                return [*self.document.bodies, Body('Wyciągnięcie', tool).prepared()]
            result = base.changed(kernel.boolean(op, base.shape, [tool]))
            return [result if b.id == base.id else b for b in self.document.bodies]

        def apply(bodies):
            self.document.commit(bodies)
            self.selected = [bodies[-1].id] if base is None else [base.id]

        self.view.set_preview_mesh(None)
        self.view.set_handle(None, None)
        self.run_operation('Wyciąganie', build, apply, after=lambda: self.set_mode(None))

    # ---------- boolean ----------
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
        self.view.tints = {}
        for index, bid in enumerate(self.bool_ids):
            self.view.tints[bid] = TINT_BASE if index == 0 else TINT_TOOL
        names = [self.document.get(i).name for i in self.bool_ids if self.document.get(i)]
        if not names:
            text = 'Kliknij bryłę bazową.'
        elif len(names) == 1:
            text = f'Baza: {names[0]}\nKliknij bryłę-narzędzie.'
        else:
            text = f'Baza: {names[0]}\nNarzędzia: {", ".join(names[1:])}'
        self.bool_status.setText(text)
        self.refresh()

    def reset_bool(self):
        self.bool_ids = []
        self.update_bool_status()

    def apply_bool(self):
        if self.busy:
            return
        if len(self.bool_ids) < 2:
            self.toast('Wybierz bryłę bazową i co najmniej jedną bryłę-narzędzie.')
            return
        bodies = [self.document.get(i) for i in self.bool_ids]
        base, tools = bodies[0], bodies[1:]
        ids = set(self.bool_ids)
        op = self.bool_op.currentData()

        def build():
            result = base.changed(kernel.boolean(op, base.shape, [b.shape for b in tools]))
            return [result if b.id == base.id else b for b in self.document.bodies if b.id == base.id or b.id not in ids]

        def apply(new):
            self.document.commit(new)
            self.selected = [base.id]

        self.run_operation('Operacja na bryłach', build, apply, after=lambda: self.set_mode(None))

    # ---------- zaokrąglenia ----------
    def pick_edge(self, x, y, shift, ctrl):
        hit = self.view.nearest_edge(x, y)
        if hit is None:
            if not ctrl:
                self.edges = {}
            self.update_mod_status()
            return
        bid, index = hit[0], hit[1]
        body = self.document.get(bid)
        if body is None or body.kind != 'solid':
            return
        ids = set(kernel.edge_chain(body.shape, index)) if shift else {index}
        if not ctrl or bid not in self.edges:
            current = set() if not ctrl else self.edges.get(bid, set())
            self.edges = {bid: current}
        current = self.edges[bid]
        if ids <= current:
            current -= ids
        else:
            current |= ids
        self.update_mod_status()

    def update_mod_status(self):
        count = sum(len(v) for v in self.edges.values())
        self.mod_status.setText(f'Zaznaczone krawędzie: {count}' if count else 'Kliknij krawędź bryły w widoku 3D.')
        self.refresh()
        self._mod_timer.start()

    def update_mod_preview(self):
        if self.mode != 'mod':
            return
        if len(self.edges) != 1 or not next(iter(self.edges.values()), None):
            self.view.set_preview_mesh(None)
            return
        bid, ids = next(iter(self.edges.items()))
        body = self.document.get(bid)
        if body is None or len(body.shape.Faces()) > 300:
            return
        try:
            mesh = kernel.display_mesh(kernel.blend(body.shape, set(ids), self.mod_size.value(), self.mod_kind.currentData()))
            self.view.set_preview_mesh(mesh, color=(.2, .75, .45, .55), line_color=(.05, .4, .2, 1))
        except Exception:
            self.view.set_preview_mesh(None)
            self.mod_status.setText(self.mod_status.text().split('\n')[0] + '\nTa wartość jest za duża dla wybranych krawędzi.')

    def clear_edges(self):
        self.edges = {}
        self.update_mod_status()

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

        self.run_operation('Zaokrąglanie' if kind == 'fillet' else 'Fazowanie', lambda: body.changed(kernel.blend(body.shape, ids, size, kind)), apply,
                           after=lambda: self.set_mode(None))

    # ---------- lustro ----------
    def pick_mirror(self, x, y):
        if self.mir_plane.currentData() == 'face':
            hit = self.view.pick_face(x, y)
            if hit is None:
                self.toast('Kliknij ścianę bryły, względem której ma być odbicie.')
                return
            self.mirror_face = (hit[1], hit[2])
            if self.mirror_id is None:
                self.mirror_id = hit[0]
        else:
            bid = self.view.pick_body(x, y)
            if bid is None or self.document.get(bid).kind == 'sketch':
                self.toast('Kliknij bryłę do odbicia.')
                return
            self.mirror_id = bid
        self.view.tints = {self.mirror_id: TINT_BASE}
        self.update_mirror_status()

    def update_mirror_status(self):
        body = self.document.get(self.mirror_id) if self.mirror_id else None
        text = f'Obiekt: {body.name}' if body else 'Kliknij obiekt do odbicia.'
        if self.mir_plane.currentData() == 'face':
            text += '\nŚciana: wskazana' if self.mirror_face else '\nKliknij ścianę jako płaszczyznę odbicia.'
        self.mir_status.setText(text)
        self.refresh()

    def apply_mirror(self):
        if self.busy:
            return
        body = self.document.get(self.mirror_id) if self.mirror_id else None
        if body is None:
            self.toast('Kliknij obiekt do odbicia.')
            return
        which = self.mir_plane.currentData()
        face = self.mirror_face
        if which == 'face' and face is None:
            self.toast('Kliknij ścianę jako płaszczyznę odbicia.')
            return
        keep = self.mir_keep.isChecked()

        def build():
            if which == 'face':
                shape = kernel.mirror_plane(body.shape, face[0], face[1])
            else:
                shape = kernel.mirror(body.shape, which)
            mirrored = Body(body.name + ' — odbicie', shape, body.kind, body.plane).prepared()
            if keep:
                return [*self.document.bodies, mirrored]
            return [mirrored if b.id == body.id else b for b in self.document.bodies]

        def apply(new):
            self.document.commit(new)
            self.selected = [new[-1].id if keep else body.id]

        self.run_operation('Odbicie lustrzane', build, apply, after=lambda: self.set_mode(None))

    # ---------- model i odświeżanie ----------
    def refresh(self, fit=False):
        live = {b.id for b in self.document.bodies}
        self.selected = [i for i in self.selected if i in live]
        self.edges = {i: es for i, es in self.edges.items() if i in live}
        self.view.set_models(self.document.bodies, self.selected, self.edges)
        if fit:
            self.view.fit_all()
        self.tbar.setVisible(self.mode is None and any(self.document.get(i) for i in self.selected))
        self.undo_button.setEnabled(self.document.can_undo and not self.busy)
        self.redo_button.setEnabled(self.document.can_redo and not self.busy)
        name = self.document.path.name if self.document.path else 'Nowy projekt'
        self.setWindowTitle(f"{'● ' if self.document.dirty else ''}{name} — RCCAD")

    def run_operation(self, label, function, apply, fit=False, after=None):
        if self.busy:
            return
        self.busy = True
        self.hint(label + '…')
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

    def add_prepared(self, body):
        self.document.commit((*self.document.bodies, body))
        if self.mode != 'sketch':
            self.selected = [body.id]

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

    # ---------- transformacja i menu kontekstowe ----------
    def apply_transform(self):
        if self.busy:
            return
        targets = [self.document.get(i) for i in self.selected if self.document.get(i)]
        if not targets:
            return
        v = {k: spin.value() for k, spin in self.t_spins.items()}
        copy = self.t_copy.isChecked()

        def build():
            out = []
            for b in targets:
                moved = kernel.transform(b.shape, (v['x'], v['y'], v['z']), (v['rx'], v['ry'], v['rz']))
                out.append(Body(b.name + (' — kopia' if copy else ''), moved, b.kind, b.plane).prepared() if copy else b.changed(moved))
            return out

        def apply(new):
            if copy:
                self.document.commit((*self.document.bodies, *new))
                self.selected = [b.id for b in new]
            else:
                mapping = {t.id: n for t, n in zip(targets, new)}
                self.document.commit([mapping.get(b.id, b) for b in self.document.bodies])

        self.run_operation('Transformacja', build, apply)

    def duplicate_selected(self):
        if self.busy or not self.selected:
            return
        targets = [self.document.get(i) for i in self.selected if self.document.get(i)]

        def build():
            return [Body(b.name + ' — kopia', kernel.transform(b.shape, (10, 10, 0)), b.kind, b.plane).prepared() for b in targets]

        def apply(new):
            self.document.commit((*self.document.bodies, *new))
            self.selected = [b.id for b in new]

        self.run_operation('Duplikowanie', build, apply)

    def hide_selected(self):
        if self.busy or not self.selected:
            return
        from dataclasses import replace
        self.document.commit([replace(b, visible=False) if b.id in self.selected else b for b in self.document.bodies])
        self.selected = []
        self.refresh()

    def show_all(self):
        from dataclasses import replace
        if self.busy:
            return
        self.document.commit([replace(b, visible=True) for b in self.document.bodies])
        self.refresh()

    def context_menu(self, x, y):
        if self.busy or self.mode is not None:
            return
        bid = self.view.pick_body(x, y)
        if bid and bid not in self.selected:
            self.selected = [bid]
            self.refresh()
        menu = QMenu(self)
        has = bool(self.selected)
        for text, fn, on in (('Duplikuj', self.duplicate_selected, has), ('Ukryj', self.hide_selected, has), ('Pokaż wszystko', self.show_all, True),
                             ('Usuń\tDelete', self.delete_selected, has), ('Eksportuj zaznaczone…', self.export_model, has)):
            action = menu.addAction(text, fn)
            action.setEnabled(on)
        menu.exec(QCursor.pos())

    def import_svg(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importuj SVG jako szkice na płaszczyźnie XY', '', 'SVG (*.svg)')
        if not path:
            return

        def build():
            return [Body(f'{Path(path).stem} {i + 1}', w, 'sketch', 'XY').prepared() for i, w in enumerate(kernel.svg_profiles(path, 'XY'))]

        self.run_operation('Importowanie SVG', build, self.add_prepared_many, True)

    # ---------- plik ----------
    def file_menu(self):
        menu = QMenu(self)
        for text, fn in (('Nowy projekt\tCtrl+N', self.new_project), ('Otwórz…\tCtrl+O', self.open_project), ('Zapisz\tCtrl+S', self.save_project),
                         ('Zapisz jako…', lambda: self.save_project(True)), None, ('Importuj model (STEP, BREP, STL, DXF)…', self.import_model), ('Importuj SVG jako szkice…', self.import_svg),
                         ('Eksportuj (STEP, STL, BREP, DXF)…', self.export_model), None, ('Dopasuj widok do modelu', lambda: self.view.fit_all())):
            if fn is None:
                menu.addSeparator()
            else:
                menu.addAction(text, fn)
        menu.exec(self.tools['file'].mapToGlobal(self.tools['file'].rect().bottomLeft()))

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
        if save_as or path is None:
            value, _ = QFileDialog.getSaveFileName(self, 'Zapisz projekt', str(path or 'Projekt.rccadx'), 'RCCAD (*.rccadx)')
            if not value:
                return
            path = Path(value)
            if path.suffix.lower() != '.rccadx':
                path = path.with_suffix('.rccadx')
        self.run_operation('Zapisywanie projektu', lambda: self.document.save(path), lambda _: None)

    def import_model(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Importuj model', '', 'Modele CAD (*.step *.stp *.brep *.brp *.stl *.dxf)')
        if not path:
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

    def export_model(self):
        bodies = [b for b in self.document.bodies if b.id in self.selected] if self.selected else [b for b in self.document.bodies if b.visible]
        if not bodies:
            self.toast('Brak geometrii do eksportu.')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Eksportuj zaznaczone lub widoczne obiekty', 'Model.step',
                                              'STEP (*.step);;STL (*.stl);;BREP (*.brep);;DXF — szkice (*.dxf)')
        if path:
            self.run_operation('Eksportowanie', lambda: kernel.export_shapes([b.shape for b in bodies], path), lambda _: None)

    def keyPressEvent(self, event):
        key = event.key()
        if self.mode == 'sketch' and not self.busy:
            if key in (Qt.Key_Return, Qt.Key_Enter) and self.tool == 'line' and self.points:
                self.finish_line()
                event.accept()
                return
            text = event.text()
            if text and text in '0123456789.-,' and self.points and not self.dim_edit.isVisible():
                if self.open_dim_input(text):
                    event.accept()
                    return
        if key == Qt.Key_Escape and self.dim_edit.isVisible():
            self.dim_edit.hide()
            event.accept()
            return
        if event.key() == Qt.Key_Escape and not self.busy:
            if self.mode == 'sketch' and (self.points or self.tangent_lines):
                self.tangent_lines = []
                self.points = []
                self.dim.hide()
                self.view.set_preview_mesh(None)
                self.show_sketch_hint()
            elif self.mode is not None:
                self.set_mode(None)
            else:
                self.selected = []
                self.refresh()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if self.confirm_discard():
            event.accept()
        else:
            event.ignore()
