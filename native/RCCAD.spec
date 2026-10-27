# Build on the target OS: Windows makes an EXE, Linux makes a Linux executable.
from pathlib import Path
import sys
from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs, collect_delvewheel_libs_directory, copy_metadata

root = Path(SPECPATH)
datas = collect_data_files('cadquery')
for package in ['cadquery','cadquery-ocp','PySide6-Essentials','shiboken6','numpy','pyqtgraph','PyOpenGL','vtk']:
    datas += copy_metadata(package, recursive=True)
binaries = collect_dynamic_libs('OCP')
if sys.platform == 'win32':
    datas, binaries = collect_delvewheel_libs_directory('OCP', libdir_name='cadquery_ocp.libs', datas=datas, binaries=binaries)
hiddenimports = collect_submodules('OCP') + collect_submodules('cadquery') + ['pyqtgraph.opengl', 'vtkmodules.util.numpy_support']
a = Analysis([str(root/'main.py')], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports,
    excludes=['PyQt5','PyQt6','PySide2','tkinter','IPython','jupyter','notebook','pytest','matplotlib.tests','scipy.tests'],
    hooksconfig={'matplotlib': {'backends': []}}, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='RCCAD Desktop',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='RCCAD Desktop')
