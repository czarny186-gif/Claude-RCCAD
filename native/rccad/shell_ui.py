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
QFrame#panel { background:rgba(255,255,255,0.95); border:1px solid #b2c7db; border-radius:11px; }
QFrame#panel QLabel, QFrame#bar QLabel { color:#29475e; font-size:12px; background:transparent; border:0; }
QFrame#panel QLabel#title { font-size:12px; font-weight:700; }
QFrame#panel QLabel#label { font-weight:600; }
QFrame#panel QLabel#small { color:#607b90; font-size:10px; }
QFrame#panel QLabel#status { background:#f2f7fc; border-radius:7px; padding:8px; color:#29475e; font-size:12px; }
QFrame#panel QCheckBox, QFrame#bar QCheckBox { color:#29475e; font-size:12px; background:transparent; spacing:7px; }
QFrame#panel QComboBox, QFrame#panel QDoubleSpinBox, QFrame#panel QLineEdit, QFrame#panel QPlainTextEdit,
QFrame#bar QDoubleSpinBox, QFrame#bar QLineEdit {
    background:#fff; border:1px solid #b1c5d7; border-radius:6px; padding:5px 7px; color:#254c71; font-size:12px; min-height:18px; selection-background-color:#bcdcff; }
QFrame#bar QDoubleSpinBox, QFrame#bar QLineEdit { border:1px solid #9ab5d0; color:#1264b2; font-weight:700; font-size:13px; }
QFrame#panel QComboBox::drop-down { border:0; width:22px; }
QFrame#panel QComboBox::down-arrow { image:url(""" + chev + """); width:10px; height:6px; }
QFrame#panel QComboBox QAbstractItemView { background:#fff; color:#254c71; border:1px solid #b1c5d7; selection-background-color:#dcefff; selection-color:#254c71; }
QFrame#panel QPushButton, QFrame#bar QPushButton { background:#f5f9fd; border:1px solid #a8bfd3; border-radius:6px; padding:7px 10px; color:#29475e; font-size:12px; }
QFrame#panel QPushButton:hover, QFrame#bar QPushButton:hover { background:#080808; color:#fff; border-color:#080808; }
QFrame#panel QPushButton:disabled { color:#9aa9b8; }
QLabel#notice { background:#fff; border:1px solid #d5b880; border-left:4px solid #e2a23a; border-radius:9px; padding:11px 16px; color:#584a32; font-size:13px; }
QLabel#origin { color:#71869b; font-size:12px; background:transparent; }
QLabel#dim { background:rgba(255,255,255,0.93); color:#1c5a8f; font-size:12px; font-weight:700; padding:3px 7px; border-radius:3px; }
QFrame#popup { background:rgba(255,255,255,0.97); border:1px solid #b2c7db; border-radius:11px; }
QFrame#popup QPushButton { background:transparent; border:0; border-radius:7px; padding:9px 11px; color:#29475e; font-size:13px; text-align:left; }
QFrame#popup QPushButton:hover:enabled { background:#080808; color:#fff; }
QFrame#popup QPushButton:disabled { color:#a9b6c4; }
QFrame#popup QLabel { background:transparent; color:#29475e; font-size:13px; }
QFrame#popup QLabel#hintlabel { font-size:11px; color:#8aa0b5; }
QFrame#dimpanel { background:rgba(255,255,255,0.93); border:1px solid #b9cbdc; border-radius:11px; }
QFrame#dimpanel QLabel { color:#344e69; font-size:12px; font-weight:600; background:transparent; }
QFrame#dimpanel QLabel#help { color:#71869b; font-weight:400; }
QFrame#dimpanel QLineEdit { background:#fff; border:1px solid #9ab5d0; border-radius:6px; padding:6px 8px; color:#0969d9; font-size:14px; font-weight:700; min-width:80px; max-width:94px; }
"""


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
        self.setAttribute(Qt.WA_TranslucentBackground, False)
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
