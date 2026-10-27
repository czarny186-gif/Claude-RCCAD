"""Elementy interfejsu w stylu wersji HTML: ikony, pływające przyciski i panele (QSS odpowiada CSS z RCCAD.html)."""
from __future__ import annotations
import json
from pathlib import Path
import re
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QToolButton

ASSETS = Path(__file__).resolve().parent / 'assets'

INK = '#344e69'
PANEL_TEXT = '#29475e'

STYLE = """
QToolButton#tool { background:#fff; border:1px solid #bdcbd8; border-radius:11px; }
QToolButton#tool:hover { background:#eef8ff; border-color:#2087d6; }
QToolButton#tool:checked { background:#080808; border:2px solid #080808; }
QToolButton#round { background:#fff; border:1px solid #bdcbd8; border-radius:20px; color:#344e69; }
QToolButton#round:hover:enabled { background:#080808; color:#fff; border-color:#080808; }
QToolButton#round:disabled { background:#fafbfd; }
QToolButton#layers { background:#324c68; border:1px solid #b7c7d7; border-radius:9px; }
QToolButton#layers:checked { background:#fff; border-color:#e4b9b9; }
QToolButton#layers:hover { background:#080808; border-color:#080808; }
QToolButton#home { background:#fff; border:1px solid #cbd9e6; border-radius:9px; color:#496780; font-size:22px; }
QToolButton#home:hover { background:#dcefff; }
QToolButton#shape { background:#fff; border:1px solid #cbd9e6; border-radius:8px; }
QToolButton#shape:hover, QToolButton#shape:checked { background:#080808; border-color:#080808; }
QToolButton#expand { background:#fff; border:1px solid #cbd9e6; border-radius:8px; color:#344e69; font-size:11px; }
QToolButton#expand:hover { background:#080808; color:#fff; }
QToolButton#pad { background:#fff; border:1px solid #bdcbd8; border-radius:7px; color:#2c4a66; font-size:15px; }
QToolButton#pad:hover { background:#eef8ff; border-color:#2087d6; }
QToolButton#pad:checked { background:#080808; color:#fff; border-color:#080808; }
QToolButton#cube { border:2px solid #fff; border-radius:17px; color:#fff; font-weight:700; font-size:12px; }
QToolButton#cube:hover { border-color:#080808; }
QFrame#floating { background:rgba(255,255,255,0.94); border:1px solid #dbe4ee; border-radius:13px; }
QFrame#toolbar { background:rgba(255,255,255,0.92); border:1px solid #cbd9e6; border-radius:12px; }
QFrame#panel { background:rgba(255,255,255,0.96); border:1px solid #b2c7db; border-radius:11px; }
QFrame#panel QLabel { color:#29475e; font:12px "Segoe UI"; background:transparent; border:0; }
QFrame#panel QLabel#title { font:bold 12px "Segoe UI"; letter-spacing:0px; }
QFrame#panel QLabel#small { color:#6b8196; font:10px "Segoe UI"; }
QFrame#panel QLabel#status { background:#f1f5f9; border-radius:7px; padding:9px; font:13px "Segoe UI"; color:#33516b; }
QFrame#panel QCheckBox { color:#29475e; font:12px "Segoe UI"; background:transparent; }
QFrame#panel QComboBox, QFrame#panel QDoubleSpinBox { background:#fff; border:1px solid #9db8cf; border-radius:6px; padding:6px; color:#254c71; font:13px "Segoe UI"; min-height:20px; }
QFrame#panel QPushButton { background:#f3f7fb; border:1px solid #9db8cf; border-radius:6px; padding:7px 12px; color:#254c71; font:13px "Segoe UI"; }
QFrame#panel QPushButton:hover { background:#dcecff; }
QLabel#hint { color:#516a82; font:13px "Segoe UI"; background:transparent; }
QLabel#notice { background:#fff; border:1px solid #d5b880; border-left:4px solid #e2a23a; border-radius:9px; padding:11px 16px; color:#33445a; font:13px "Segoe UI"; }
QLabel#dim { background:rgba(255,255,255,0.92); color:#1c5a8f; font:bold 12px "Segoe UI"; padding:3px 7px; border-radius:3px; }
QMenu { background:#fff; border:1px solid #cbd9e6; border-radius:9px; padding:6px; font:13px "Segoe UI"; color:#254c71; }
QMenu::item { padding:8px 26px 8px 14px; border-radius:5px; }
QMenu::item:selected { background:#dcefff; }
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
