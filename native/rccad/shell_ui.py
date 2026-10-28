"""Elementy interfejsu w stylu wersji HTML: ikony, pływające przyciski i panele (QSS odpowiada CSS z RCCAD.html)."""
from __future__ import annotations
import json
from pathlib import Path
import re
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget, QApplication

ASSETS = Path(__file__).resolve().parent / 'assets'

INK = '#344e69'
PANEL_TEXT = '#29475e'

def style():
    chev = (ASSETS / 'chev.svg').as_posix()
    check = (ASSETS / 'check_w.png').as_posix()
    return """
* { font-family: "Segoe UI", Arial, sans-serif; }
QToolTip { background:#fff; color:#29475e; border:1px solid #b2c7db; padding:4px 7px; }
QToolButton#tool { background:#fff; border:1px solid #bdcbd8; border-radius:11px; }
QToolButton#tool:hover { background:#eef8ff; border:1px solid #2087d6; }
QToolButton#tool:checked, QToolButton#tool:checked:hover { background:#080808; border:2px solid #080808; }
QToolButton#round { background:#fff; border:1px solid #bdcbd8; border-radius:20px; color:#344e69; }
QToolButton#round:hover:enabled { background:#080808; color:#fff; border-color:#080808; }
QToolButton#round:disabled { background:#fff; border:1px solid #d7dfe8; color:#b9c4d0; }
QToolButton#layers { background:#fff; border:1px solid #e4b9b9; border-radius:9px; }
QToolButton#layers:checked { background:#324c68; border:1px solid #b7c7d7; }
QToolButton#layers:hover { background:#080808; border:1px solid #080808; }
QToolButton#home { background:#fff; border:1px solid #cbd9e6; border-radius:9px; color:#496780; font-size:22px; }
QToolButton#home:hover { background:#dcefff; }
QToolButton#shapeMain { background:#fff; border:1px solid #cbd9e6; border-radius:8px; }
QToolButton#shapeMain[grouped="true"] { border-top-right-radius:0; border-bottom-right-radius:0; }
QToolButton#shapeMain:hover, QToolButton#shapeMain:checked { background:#080808; border-color:#080808; }
QToolButton#shapeExpand { background:#fff; border:1px solid #cbd9e6; border-left:0; border-radius:8px; border-top-left-radius:0; border-bottom-left-radius:0; color:#344e69; font-size:11px; }
QToolButton#shapeExpand:hover { background:#080808; color:#fff; }
QToolButton#padTool { background:#fff; border:1px solid #bdccdb; border-radius:8px; color:#344e69; font-size:18px; font-weight:600; }
QToolButton#padTool:hover { border-color:#187ac1; }
QToolButton#padTool:checked { background:#111; color:#fff; border-color:#111; }
QToolButton#cubeX, QToolButton#cubeY, QToolButton#cubeZ, QToolButton#cubeI { border:1px solid transparent; border-radius:18px; color:#fff; font-weight:700; font-size:12px; }
QToolButton#cubeX { background:#dc5658; } QToolButton#cubeY { background:#39a56d; } QToolButton#cubeZ { background:#4589e7; } QToolButton#cubeI { background:#677e99; }
QToolButton#cubeX:hover, QToolButton#cubeY:hover, QToolButton#cubeZ:hover, QToolButton#cubeI:hover { border:1px solid #fff; }
QToolButton#cubeX:checked, QToolButton#cubeY:checked, QToolButton#cubeZ:checked, QToolButton#cubeI:checked { background:#080808; border:2px solid #aab8c8; }
QFrame#floating { background:rgba(255,255,255,0.94); border:1px solid #d0dce8; border-radius:13px; }
QFrame#bar { background:rgba(255,255,255,0.93); border:1px solid #bdccdb; border-radius:13px; }
QFrame#toolbar { background:rgba(255,255,255,0.92); border:1px solid #cbd9e6; border-radius:12px; }
QFrame#panel { background:rgba(255,255,255,0.97); border:1px solid #b9cde0; border-radius:15px; }
QLabel#ptitle { font-size:13px; font-weight:700; color:#1e3a52; background:transparent; }
QLabel#psub { font-size:11px; color:#6c869b; background:transparent; }
QLabel#badge { background:transparent; }
QFrame#seg { background:transparent; }
QToolButton#segbtn { background:#f3f8fd; border:1px solid #d3e0ec; border-radius:10px; color:#41596f; font-size:11px; padding:7px 2px 4px 2px; }
QToolButton#segbtn:hover { background:#eaf4ff; border-color:#8fc0f2; }
QToolButton#segbtn:checked { background:#e3f0ff; border:2px solid #2f87e8; color:#14508f; font-weight:700; }
QFrame#panel QPushButton#primary, QFrame#bar QPushButton#primary, QFrame#skbar QPushButton#primary { background:#2f87e8; border:1px solid #2379d6; color:#fff; font-weight:700; border-radius:8px; padding:8px 14px; }
QFrame#panel QPushButton#primary:hover, QFrame#bar QPushButton#primary:hover, QFrame#skbar QPushButton#primary:hover { background:#1f6fc9; border-color:#1f6fc9; color:#fff; }
QFrame#skbar { background:rgba(255,255,255,0.97); border:1px solid #b9cde0; border-radius:15px; }
QFrame#skbar QLabel { background:transparent; color:#1e3a52; font-size:12px; }
QFrame#skbar QPushButton { background:#f5f9fd; border:1px solid #a8bfd3; border-radius:8px; padding:8px 14px; color:#29475e; font-size:12px; }
QFrame#panel QLabel, QFrame#bar QLabel { color:#29475e; font-size:12px; background:transparent; border:0; }
QFrame#panel QLabel#title { font-size:12px; font-weight:700; }
QFrame#panel QLabel#label { font-weight:600; }
QFrame#panel QLabel#small { color:#607b90; font-size:10px; }
QFrame#panel QLabel#status { background:#f2f7fc; border-radius:7px; padding:8px; color:#29475e; font-size:12px; }
QFrame#panel QCheckBox, QFrame#bar QCheckBox { color:#29475e; font-size:12px; background:transparent; spacing:8px; }
QCheckBox::indicator { width:18px; height:18px; border:1.6px solid #9db5cc; border-radius:5px; background:#ffffff; }
QCheckBox::indicator:hover { border-color:#2f87e8; }
QCheckBox::indicator:checked { background:#2f87e8; border-color:#2f87e8; image:url(CHECKPNG); }
QCheckBox::indicator:disabled { background:#eef2f6; border-color:#d6e0ea; }
QFrame#panel QComboBox, QFrame#panel QDoubleSpinBox, QFrame#panel QLineEdit, QFrame#panel QPlainTextEdit,
QFrame#bar QDoubleSpinBox, QFrame#bar QLineEdit {
    background:#fff; border:1px solid #b1c5d7; border-radius:6px; padding:5px 7px; color:#254c71; font-size:12px; min-height:18px; selection-background-color:#bcdcff; }
QFrame#bar QDoubleSpinBox, QFrame#bar QLineEdit { border:1px solid #9ab5d0; color:#1264b2; font-weight:700; font-size:13px; }
QFrame#panel QComboBox::drop-down { border:0; width:22px; }
QFrame#panel QComboBox::down-arrow { image:url(""" + chev + """); width:10px; height:6px; }
QFrame#panel QComboBox QAbstractItemView { background:#fff; color:#254c71; border:1px solid #b1c5d7; selection-background-color:#dcefff; selection-color:#254c71; }
QFrame#panel QPushButton, QFrame#bar QPushButton { background:#f5f9fd; border:1px solid #a8bfd3; border-radius:6px; padding:7px 10px; color:#29475e; font-size:12px; }
QFrame#panel QPushButton:hover, QFrame#bar QPushButton:hover { background:#e9f3ff; color:#17314a; border-color:#2f87e8; }
QFrame#panel QPushButton:disabled { color:#9aa9b8; }
QLabel#notice { background:#fff; border:1px solid #d5b880; border-left:4px solid #e2a23a; border-radius:9px; padding:11px 16px; color:#584a32; font-size:13px; }
QLabel#origin { color:#71869b; font-size:12px; background:transparent; }
QLabel#dim { background:rgba(255,255,255,0.93); color:#1c5a8f; font-size:12px; font-weight:700; padding:3px 7px; border-radius:3px; }
QFrame#popup { background:rgba(255,255,255,0.97); border:1px solid #b2c7db; border-radius:11px; }
QFrame#popup QPushButton { background:transparent; border:0; border-radius:7px; padding:9px 11px; color:#29475e; font-size:13px; text-align:left; }
QFrame#popup QPushButton:hover:enabled { background:#e9f3ff; color:#17314a; }
QFrame#popup QPushButton:disabled { color:#a9b6c4; }
QFrame#popup QLabel { background:transparent; color:#29475e; font-size:13px; }
QFrame#popup QLabel#hintlabel { font-size:11px; color:#8aa0b5; }
QFrame#rich { background:#ffffff; border:1px solid #b9cde0; border-radius:15px; }
QLabel#richhead { color:#7b93a8; font-size:10px; font-weight:700; letter-spacing:1px; padding:4px 8px 6px 8px; background:transparent; }
QFrame#richsep { background:#e3ebf3; border:0; margin:4px 8px; }
QPushButton#richrow { background:transparent; border:0; border-radius:10px; text-align:left; }
QPushButton#richrow:hover:enabled { background:#e9f3ff; }
QPushButton#richrow:disabled { background:transparent; }
QLabel#richtile { background:#f1f6fb; border:1px solid #dbe6f0; border-radius:10px; }
QPushButton#richrow:hover:enabled QLabel#richtile { background:#ffffff; border-color:#9ccbf6; }
QLabel#richname { color:#1e3a52; font-size:13px; font-weight:600; background:transparent; }
QLabel#richhint { color:#7890a5; font-size:11px; background:transparent; }
QFrame#dimpanel { background:rgba(255,255,255,0.93); border:1px solid #b9cbdc; border-radius:11px; }
QFrame#dimpanel QLabel { color:#344e69; font-size:12px; font-weight:600; background:transparent; }
QFrame#dimpanel QLabel#help { color:#71869b; font-weight:400; }
QFrame#dimpanel QLineEdit { background:#fff; border:1px solid #9ab5d0; border-radius:6px; padding:6px 8px; color:#0969d9; font-size:14px; font-weight:700; min-width:80px; max-width:94px; }
""".replace('CHECKPNG', check)


def _pixmap_from_svg(svg: str, color: str, size: int, scale: int = 2) -> QPixmap:
    text = svg.replace('currentColor', color)
    renderer = QSvgRenderer(QByteArray(text.encode('utf-8')))
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap


def svg_icon(svg: str, normal: str = INK, active: str = '#ffffff', size: int = 27) -> QIcon:
    icon = QIcon()
    icon.addPixmap(_pixmap_from_svg(svg, normal, size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_pixmap_from_svg(svg, active, size), QIcon.Normal, QIcon.On)
    icon.addPixmap(_pixmap_from_svg(svg, active, size), QIcon.Active, QIcon.Off)
    icon.addPixmap(_pixmap_from_svg(svg, '#b9c4d0', size), QIcon.Disabled, QIcon.Off)
    return icon


def stroked_shape_svg(svg: str) -> str:
    """Ikona narzędzia szkicu: w HTML obrys nadaje CSS (fill:none; stroke; zaokrąglone końce)."""
    svg = re.sub(r'<svg ', '<svg xmlns="http://www.w3.org/2000/svg" fill="none" stroke="currentColor" stroke-width="2" '
                           'stroke-linecap="round" stroke-linejoin="round" ', svg, count=1)
    return svg


def png_icon(name: str, size: int = 38) -> QIcon:
    """Ikona PNG z HTML; w stanie aktywnym (czarne tło) kolory są odwracane jak `filter: invert(1)`."""
    pixmap = QPixmap(str(ASSETS / name))
    icon = QIcon()
    icon.addPixmap(pixmap, QIcon.Normal, QIcon.Off)
    image = pixmap.toImage().convertToFormat(QImage.Format_ARGB32)
    image.invertPixels(QImage.InvertRgb)
    inverted = QPixmap.fromImage(image)
    icon.addPixmap(inverted, QIcon.Normal, QIcon.On)
    icon.addPixmap(inverted, QIcon.Active, QIcon.On)
    return icon


def file_svg(name: str) -> str:
    return (ASSETS / name).read_text(encoding='utf-8')


def load_shapes() -> list[dict]:
    return json.loads((ASSETS / 'shapes.json').read_text(encoding='utf-8'))


def big_tool(icon: QIcon, tooltip: str, checkable=True) -> QToolButton:
    button = QToolButton()
    button.setObjectName('tool')
    button.setIcon(icon)
    button.setIconSize(QSize(38, 38))
    button.setFixedSize(52, 52)
    button.setCheckable(checkable)
    button.setToolTip(tooltip)
    button.setCursor(Qt.PointingHandCursor)
    return button


def panel(width: int) -> QFrame:
    frame = QFrame()
    frame.setObjectName('panel')
    frame.setFixedWidth(width)
    return frame


def shadow(widget, blur=20, dy=5, alpha=51):
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(32, 60, 90, alpha))
    widget.setGraphicsEffect(effect)
    return widget


def tinted_icon(name: str, normal: str, on: str | None = None, size=29) -> QIcon:
    """Ikona PNG zabarwiona jednolitym kolorem (jak CSS filter: brightness(0) invert(1) / kolor)."""
    base = QImage(str(ASSETS / name)).convertToFormat(QImage.Format_ARGB32)
    icon = QIcon()
    for color, state in ((normal, QIcon.Off), (on or normal, QIcon.On)):
        img = QImage(base.size(), QImage.Format_ARGB32)
        img.fill(QColor(color))
        painter = QPainter(img)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        painter.drawImage(0, 0, base)
        painter.end()
        pm = QPixmap.fromImage(img).scaled(size * 2, size * 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(2)
        icon.addPixmap(pm, QIcon.Normal, state)
        icon.addPixmap(pm, QIcon.Active, state)
    return icon


class _Row(QPushButton):
    def __init__(self):
        super().__init__()
        self.labels = []

    def _tint(self, hot):
        for label, base in self.labels:
            label.setStyleSheet(f'color:{"#ffffff" if hot and self.isEnabled() else base};')

    def enterEvent(self, event):
        self._tint(True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._tint(False)
        super().leaveEvent(event)


class PopupMenu(QFrame):
    """Menu w stylu HTML (#fileMenu / #ctxMenu / warianty kształtów): wiersze z opisem po prawej, czarne podświetlenie."""

    def __init__(self, parent, items, min_width=170, row_height=None):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName('popup')
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(2)
        self.setMinimumWidth(min_width)
        self.actions = []
        for item in items:
            text, hint, callback = item[0], item[1], item[2]
            enabled = item[3] if len(item) > 3 else True
            button = _Row()
            button.setEnabled(enabled)
            row = QHBoxLayout(button)
            row.setContentsMargins(11, 0, 11, 0)
            if row_height:
                button.setFixedHeight(row_height)
            left = QLabel(text)
            left.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(left)
            button.labels.append((left, '#29475e' if enabled else '#a9b6c4'))
            row.addStretch(1)
            if hint:
                right = QLabel(hint)
                right.setObjectName('hintlabel')
                right.setAttribute(Qt.WA_TransparentForMouseEvents)
                row.addWidget(right)
                button.labels.append((right, '#8aa0b5'))
            button.clicked.connect(lambda _=False, cb=callback: (self.close(), cb()))
            lay.addWidget(button)
            self.actions.append((text, button))
        shadow(self, 22, 6, 68)

    def popup_at(self, global_pos):
        self.adjustSize()
        self.move(global_pos)
        self.show()


# ---------- panele narzędzi: nagłówek z plakietką i przełączniki graficzne ----------
from PySide6.QtCore import Signal
from . import icons


def panel_header(kind: str, title: str, subtitle: str = '', color: str = icons.BLUE) -> QWidget:
    box = QWidget()
    box.setObjectName('phead')
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    pic = QLabel()
    pic.setObjectName('badge')
    pic.setPixmap(icons.badge(kind, color, 36))
    pic.setFixedSize(36, 36)
    lay.addWidget(pic)
    col = QVBoxLayout()
    col.setSpacing(0)
    head = QLabel(title)
    head.setObjectName('ptitle')
    col.addWidget(head)
    if subtitle:
        sub = QLabel(subtitle)
        sub.setObjectName('psub')
        col.addWidget(sub)
    lay.addLayout(col, 1)
    return box


class Segmented(QFrame):
    """Graficzny wybór jednej opcji (ikona + podpis). API zbliżone do QComboBox: currentData / currentIndex / setCurrentIndex."""
    currentIndexChanged = Signal(int)

    def __init__(self, items, icon_size=34, parent=None):
        super().__init__(parent)
        self.setObjectName('seg')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._data, self._buttons, self._index = [], [], 0
        for i, (label, data, kind) in enumerate(items):
            button = QToolButton()
            button.setObjectName('segbtn')
            button.setCheckable(True)
            button.setText(label)
            button.setIcon(QIcon(icons.pixmap(kind, icon_size)))
            button.setIconSize(QSize(icon_size, icon_size))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setMinimumHeight(icon_size + 30)
            button.setSizePolicy(button.sizePolicy().horizontalPolicy(), button.sizePolicy().verticalPolicy())
            button.clicked.connect(lambda _=False, n=i: self.setCurrentIndex(n))
            lay.addWidget(button, 1)
            self._buttons.append(button)
            self._data.append(data)
        self._buttons[0].setChecked(True)

    def currentIndex(self):
        return self._index

    def currentData(self):
        return self._data[self._index]

    def count(self):
        return len(self._data)

    def setCurrentIndex(self, index):
        index = max(0, min(index, len(self._data) - 1))
        for i, b in enumerate(self._buttons):
            b.setChecked(i == index)
        if index != self._index:
            self._index = index
            self.currentIndexChanged.emit(index)


class RichMenu(QFrame):
    """Graficzne menu: kafelek z ikoną + tytuł + opis w każdym wierszu, nagłówek i separatory (plik, warianty kształtów)."""

    def __init__(self, parent, entries, title='', min_width=300):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName('rich')
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(2)
        self.setMinimumWidth(min_width)
        if title:
            head = QLabel(title.upper())
            head.setObjectName('richhead')
            lay.addWidget(head)
        self.actions = []
        for entry in entries:
            if entry is None:
                line = QFrame()
                line.setObjectName('richsep')
                line.setFixedHeight(1)
                lay.addWidget(line)
                continue
            icon, text, hint, callback = entry[:4]
            enabled = entry[4] if len(entry) > 4 else True
            button = QPushButton()
            button.setObjectName('richrow')
            button.setEnabled(enabled)
            button.setFixedHeight(54)
            row = QHBoxLayout(button)
            row.setContentsMargins(8, 4, 12, 4)
            row.setSpacing(12)
            tile = QLabel()
            tile.setObjectName('richtile')
            tile.setFixedSize(40, 40)
            tile.setAlignment(Qt.AlignCenter)
            tile.setPixmap(icon)
            tile.setAttribute(Qt.WA_TransparentForMouseEvents)
            row.addWidget(tile)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.setContentsMargins(0, 0, 0, 0)
            name = QLabel(text)
            name.setObjectName('richname')
            name.setAttribute(Qt.WA_TransparentForMouseEvents)
            col.addWidget(name)
            if hint:
                sub = QLabel(hint)
                sub.setObjectName('richhint')
                sub.setAttribute(Qt.WA_TransparentForMouseEvents)
                col.addWidget(sub)
            row.addLayout(col, 1)
            button.clicked.connect(lambda _=False, cb=callback: (self.close(), cb()))
            lay.addWidget(button)
            self.actions.append((text, button))
        shadow(self, 26, 8, 70)

    def popup_at(self, global_pos):
        self.adjustSize()
        self.move(global_pos)
        self.show()


class StepRow(QFrame):
    """Graficzny krok kreatora (np. lustro): numer / ptaszek, ikona, tytuł i wartość. Stany: pending, active, done."""

    def __init__(self, number, icon_kind, title):
        super().__init__()
        self.number = number
        self.icon_kind = icon_kind
        self.setObjectName('step')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 12, 8)
        lay.setSpacing(10)
        self.mark = QLabel()
        self.mark.setFixedSize(26, 26)
        self.mark.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.mark)
        self.pic = QLabel()
        self.pic.setFixedSize(34, 34)
        lay.addWidget(self.pic)
        col = QVBoxLayout()
        col.setSpacing(0)
        self.title = QLabel(title)
        self.title.setStyleSheet('font-weight:700;color:#27415a;')
        self.value = QLabel('')
        self.value.setStyleSheet('color:#6c869b;')
        col.addWidget(self.title)
        col.addWidget(self.value)
        lay.addLayout(col, 1)
        self.set_state('pending', '')

    def set_state(self, state, value):
        colors = {'pending': ('#f3f6fa', '#d6e0ea', '#9fb2c4'), 'active': ('#fff6e8', '#f09a22', '#f09a22'), 'done': ('#eaf8f1', '#2fa56d', '#2fa56d')}
        bg, border, accent = colors[state]
        self.setStyleSheet(f'QFrame#step{{background:{bg};border:1.6px solid {border};border-radius:10px;}}')
        self.mark.setStyleSheet(f'background:{accent};color:white;border-radius:13px;font-weight:800;border:none;')
        self.mark.setText('✓' if state == 'done' else str(self.number))
        self.pic.setStyleSheet('border:none;background:transparent;')
        self.pic.setPixmap(icons.badge(self.icon_kind, accent, 34))
        self.value.setText(value)
        self.value.setStyleSheet('color:#6c869b;border:none;')
        self.title.setStyleSheet('font-weight:700;color:#27415a;border:none;')
