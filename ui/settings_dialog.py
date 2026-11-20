from pathlib import Path

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

from core import zapret


class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Настройки")
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(form.labelAlignment())

        # zapret folder
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(config.zapret_dir)
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._browse)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)
        dir_wrap = QWidget()
        dir_wrap.setLayout(dir_row)
        form.addRow("Папка zapret:", dir_wrap)

        # app self-update repo
        self.repo_edit = QLineEdit(config.app_repo)
        self.repo_edit.setPlaceholderText("owner/repo (например, myname/zapret-gui)")
        form.addRow("Репозиторий приложения:", self.repo_edit)
        hint = QLabel("GitHub-репозиторий, где публикуются новые версии этого приложения (.exe в releases).")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #9aa0a6; font-size: 11px;")
        form.addRow("", hint)

        # game filter
        self.game_combo = QComboBox()
        self.game_combo.addItem("Выключен", "disabled")
        self.game_combo.addItem("TCP и UDP", "all")
        self.game_combo.addItem("Только TCP", "tcp")
        self.game_combo.addItem("Только UDP", "udp")
        if config.zapret_dir:
            mode, _, _ = zapret.read_game_filter(config.zapret_dir)
            idx = self.game_combo.findData(mode)
            self.game_combo.setCurrentIndex(max(idx, 0))
        form.addRow("Игровой фильтр:", self.game_combo)

        root.addLayout(form)

        self.auto_check = QCheckBox("Проверять обновления при запуске")
        self.auto_check.setChecked(bool(config.auto_check_updates))
        root.addWidget(self.auto_check)

        self.tray_check = QCheckBox("Сворачивать в трей при закрытии окна")
        self.tray_check.setChecked(bool(config.minimize_to_tray))
        root.addWidget(self.tray_check)

        self.start_min = QCheckBox("Запускать свёрнутым в трей")
        self.start_min.setChecked(bool(config.start_minimized))
        root.addWidget(self.start_min)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                                   QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self):
        start = self.dir_edit.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Выберите папку zapret", start)
        if path:
            self.dir_edit.setText(path)

    def _on_accept(self):
        new_dir = self.dir_edit.text().strip()
        if new_dir and not (Path(new_dir) / "bin" / "winws.exe").exists():
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Ошибка",
                                "В выбранной папке нет bin\\winws.exe.\nВыберите корректную папку zapret.")
            return
        self.config.zapret_dir = new_dir
        self.config.app_repo = self.repo_edit.text().strip()
        self.config.auto_check_updates = self.auto_check.isChecked()
        self.config.minimize_to_tray = self.tray_check.isChecked()
        self.config.start_minimized = self.start_min.isChecked()
        if new_dir:
            zapret.set_game_filter(new_dir, self.game_combo.currentData())
        self.config.save()
        self.accept()