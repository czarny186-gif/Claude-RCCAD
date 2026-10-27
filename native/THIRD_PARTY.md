# Komponenty zewnętrzne

RCCAD Desktop korzysta z bibliotek dystrybuowanych jako odrębne pliki w katalogu
`_internal`. Nie usuwaj tego katalogu ani nie przenoś samego EXE.

- OpenCascade Technology / OCP: LGPL 2.1 z wyjątkiem OCCT;
  https://dev.opencascade.org/resources/licensing
- CadQuery: Apache License 2.0; https://github.com/CadQuery/cadquery
- PySide6 / Qt: LGPL 3 / GPL / licencja komercyjna, zależnie od modułu;
  używane są moduły Qt Core, Gui, Widgets, OpenGL;
  https://www.qt.io/licensing/open-source-lgpl-obligations
- pyqtgraph: MIT; https://github.com/pyqtgraph/pyqtgraph
- NumPy: BSD 3-Clause; https://numpy.org/doc/stable/license.html
- PyOpenGL: BSD-style; https://pyopengl.sourceforge.net/license.html
- VTK: BSD 3-Clause; https://vtk.org/about/
- PyInstaller: GPL z wyjątkiem bootloadera umożliwiającym dystrybucję aplikacji;
  https://pyinstaller.org/en/stable/license.html

Zachowaj informacje licencyjne bibliotek dołączone w pakiecie. Użytkownik może
wymieniać dynamiczne biblioteki zgodnie z warunkami odpowiedniej licencji.
Kod aplikacji, konfiguracja budowania oraz dokładne wersje zależności są dostępne
w tym repozytorium. Ten wykaz nie zastępuje pełnych tekstów licencji komponentów.
