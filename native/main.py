"""Entry point for Python and PyInstaller; never starts a web browser/server."""
import argparse
import json
import os
from pathlib import Path
import sys
import traceback


def main():
    parser=argparse.ArgumentParser(description='RCCAD Desktop')
    parser.add_argument('--self-test',action='store_true')
    parser.add_argument('--report')
    parser.add_argument('--demo',action='store_true')
    parser.add_argument('--classic',action='store_true',help='stare okno z panelem bocznym')
    args=parser.parse_args()
    # Application caches must be writable in a portable install as well.
    cache=Path(os.environ.get('LOCALAPPDATA') or os.environ.get('XDG_CACHE_HOME') or Path.home()/'.cache')/'RCCAD'
    try:
        cache.mkdir(parents=True,exist_ok=True)
        os.environ.setdefault('XDG_CACHE_HOME',str(cache))
    except OSError:
        import tempfile
        os.environ.setdefault('XDG_CACHE_HOME',tempfile.gettempdir())
    if args.self_test:
        from rccad.selftest import run
        result=run(args.report)
        if sys.stdout is not None:
            print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QFont, QIcon, QSurfaceFormat
    format=QSurfaceFormat();format.setDepthBufferSize(24);format.setSamples(4)
    QSurfaceFormat.setDefaultFormat(format)
    app=QApplication(sys.argv[:1]);app.setApplicationName('RCCAD Desktop');app.setOrganizationName('RCCAD');app.setFont(QFont('Segoe UI',10))
    icon_path=Path(__file__).resolve().parent/'rccad'/'assets'/'rccad.png'
    if icon_path.exists():app.setWindowIcon(QIcon(str(icon_path)))
    splash=None
    try:
        from rccad.splash import Splash, run_with_splash
        splash=Splash(str(icon_path));splash.show();app.processEvents()
    except Exception:
        run_with_splash=None
    def exception_hook(kind,value,tb):
        text=''.join(traceback.format_exception(kind,value,tb))
        try:(cache/'error.log').write_text(text,encoding='utf-8')
        except OSError:pass
        QMessageBox.critical(None,'RCCAD — błąd',f'Wystąpił błąd: {value}\n\nDotychczasowy zapis projektu nie został nadpisany.\nSzczegóły: {cache / "error.log"}')
    sys.excepthook=exception_hook
    def build():
        if args.classic:
            from rccad.window import MainWindow
            return MainWindow()
        from rccad.studio import StudioWindow
        return StudioWindow()
    if splash is not None:
        window=run_with_splash(app,splash,build)
    else:
        window=build()
    if args.demo:
        from rccad import kernel as k
        from rccad.document import Body
        shape=k.hole(k.box(40,40,30),6,20,20)
        shape=k.blend(shape,range(len(shape.Edges())),2)
        window.document.commit([Body('Przykład — otwór i zaokrąglenia',shape).prepared()])
        window.refresh(True)
    window.show()
    if splash is not None:splash.close()
    return app.exec()


if __name__=='__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        # CI can inspect startup errors even for a --windowed Windows executable.
        if '--report' in sys.argv:
            target=Path(sys.argv[sys.argv.index('--report')+1])
            target.write_text(json.dumps(dict(passed=False,error=str(exc),traceback=traceback.format_exc()),indent=2),encoding='utf-8')
        raise
