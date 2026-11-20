import ctypes
import sys
from pathlib import Path

from PySide6.QtGui import QColor, QIcon, QPalette
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from config import Config
from core import admin, zapret
from ui.main_window import MainWindow
from version import APP_NAME, APP_VERSION

MUTEX_NAME = "ZapretGUI.SingleInstance.Mutex"


def app_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def resource_path(name):
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / "resources" / name
    return app_dir() / "resources" / name


def apply_dark_theme(app):
    app.setStyle("Fusion")
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor("#1e1f22"))
    pal.setColor(QPalette.ColorRole.WindowText, QColor("#e8e8e8"))
    pal.setColor(QPalette.ColorRole.Base, QColor("#17181a"))
    pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#232427"))
    pal.setColor(QPalette.ColorRole.Text, QColor("#e8e8e8"))
    pal.setColor(QPalette.ColorRole.Button, QColor("#2b2d30"))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e8e8e8"))
    pal.setColor(QPalette.ColorRole.Highlight, QColor("#4f8cff"))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b2d30"))
    pal.setColor(QPalette.ColorRole.ToolTipText, QColor("#e8e8e8"))
    pal.setColor(QPalette.ColorRole.PlaceholderText, QColor("#7a7f85"))
    app.setPalette(pal)
    app.setStyleSheet("""
        QPushButton {
            background: #2b2d30; border: 1px solid #3a3d42;
            border-radius: 6px; padding: 6px 14px;
        }
        QPushButton:hover { background: #34373c; }
        QPushButton:pressed { background: #26282c; }
        QPushButton:disabled { color: #6b7075; background: #232427; }
        QPushButton#startBtn { background: #238636; border-color: #2ea043; font-weight: 600; }
        QPushButton#startBtn:hover { background: #2ea043; }
        QPushButton#startBtn:disabled { background: #1c3a24; color: #6b7075; }
        QPushButton#stopBtn { background: #8b2c2c; border-color: #a43535; font-weight: 600; }
        QPushButton#stopBtn:hover { background: #a43535; }
        QPushButton#stopBtn:disabled { background: #3a2222; color: #6b7075; }
        QComboBox, QLineEdit {
            background: #17181a; border: 1px solid #3a3d42;
            border-radius: 6px; padding: 5px 8px;
        }
        QComboBox QAbstractItemView {
            background: #232427; selection-background-color: #4f8cff;
        }
        QPlainTextEdit { border: 1px solid #3a3d42; border-radius: 6px; }
        QFrame#banner {
            background: #2a2f1c; border: 1px solid #5c6b2f; border-radius: 8px;
        }
        QFrame#banner QLabel { color: #d7e0a8; }
        QFrame#banner QPushButton { background: #4f8cff; border-color: #4f8cff; color: #fff; }
        QProgressBar { border: 1px solid #3a3d42; border-radius: 5px; text-align: center; }
        QProgressBar::chunk { background: #4f8cff; border-radius: 4px; }
    """)


def ensure_single_instance():
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW(None, False, MUTEX_NAME)
    return kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def resolve_zapret_dir(config):
    if config.zapret_dir and (Path(config.zapret_dir) / "bin" / "winws.exe").exists():
        return config.zapret_dir
    roots = [app_dir(), app_dir().parent, app_dir().parent.parent, Path.cwd()]
    found = zapret.find_zapret_dir(roots)
    if found:
        config.zapret_dir = str(found)
        config.save()
        return str(found)
    return ""


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZapretGUI.App")
    except Exception:
        pass

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    apply_dark_theme(app)

    if not ensure_single_instance():
        QMessageBox.information(None, APP_NAME, "Приложение уже запущено.")
        return 0

    if not admin.is_admin():
        ans = QMessageBox.question(
            None, "Нужны права администратора",
            "Для работы zapret (драйвер WinDivert) нужны права администратора.\n"
            "Перезапустить приложение с повышением прав?")
        if ans == QMessageBox.StandardButton.Yes:
            admin.relaunch_as_admin()
        return 0

    icon = QIcon(str(resource_path("icon.png")))
    app.setWindowIcon(icon)

    config = Config()
    resolve_zapret_dir(config)

    window = MainWindow(config, icon)
    if config.start_minimized and window.tray.isVisible():
        window.hide()
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())