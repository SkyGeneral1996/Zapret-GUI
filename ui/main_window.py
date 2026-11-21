from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPlainTextEdit, QProgressDialog, QPushButton, QSystemTrayIcon, QMenu,
    QTabWidget, QVBoxLayout, QWidget,
)

from core import github, zapret, updater
from core import applog
from core import service as svc
from ui.settings_dialog import SettingsDialog
from ui.manager_tab import ManagerTab
from ui.workers import CheckWorker, ZapretInstallWorker, AppInstallWorker, ZapretSetupWorker
from version import APP_NAME, APP_VERSION


class MainWindow(QMainWindow):
    def __init__(self, config, icon):
        super().__init__()
        self.config = config
        self._icon = icon
        self.runner = zapret.WinwsRunner(self)
        self.runner.output.connect(self._append_raw)
        self.runner.started.connect(self._on_started)
        self.runner.stopped.connect(self._on_stopped)
        self.runner.error.connect(self._on_runner_error)

        self._check_worker = None
        self._install_worker = None
        self._setup_worker = None
        self._zapret_release = None
        self._app_release = None
        self._external_running = False
        self._tray_notified = False

        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        applog.write("APP", f"{APP_NAME} {APP_VERSION} start")
        self.setWindowIcon(icon)
        self.resize(880, 780)

        self._build_ui()
        self._build_tray()
        self.manager.check_updates.connect(lambda: self.check_updates(manual=True, mode="zapret"))
        self.manager.changed.connect(self._update_status)
        self.manager.need_zapret.connect(self._offer_zapret_download)
        self._refresh_strategies()
        self._update_status()
        QTimer.singleShot(0, self._ensure_zapret)

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_external)
        self._poll_timer.start(4000)

        if config.auto_check_updates:
            QTimer.singleShot(1200, lambda: self.check_updates(manual=False))

    # ---------- UI ----------
    def _build_ui(self):
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel(APP_NAME)
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        self.ver_label = QLabel()
        self.ver_label.setStyleSheet("color: #9aa0a6;")
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(self.ver_label)
        root.addLayout(header)

        status_row = QHBoxLayout()
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("font-size: 16px;")
        self.status_text = QLabel()
        self.zapret_ver = QLabel()
        self.zapret_ver.setStyleSheet("color: #9aa0a6;")
        status_row.addWidget(self.status_dot)
        status_row.addWidget(self.status_text)
        status_row.addStretch(1)
        status_row.addWidget(self.zapret_ver)
        root.addLayout(status_row)

        self.tabs = QTabWidget()
        run_tab = QWidget()
        run_lay = QVBoxLayout(run_tab)
        ctrl = QHBoxLayout()
        ctrl.addWidget(QLabel("Стратегия:"))
        self.strategy_combo = QComboBox()
        self.strategy_combo.setMinimumWidth(280)
        ctrl.addWidget(self.strategy_combo, 1)
        self.start_btn = QPushButton("Старт")
        self.start_btn.setObjectName("startBtn")
        self.start_btn.clicked.connect(self.start_strategy)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setObjectName("stopBtn")
        self.stop_btn.clicked.connect(self.stop_strategy)
        ctrl.addWidget(self.start_btn)
        ctrl.addWidget(self.stop_btn)
        run_lay.addLayout(ctrl)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.log.setFont(mono)
        run_lay.addWidget(self.log, 1)

        self.manager = ManagerTab(self.config, lambda: self.strategy_combo.currentText(), self)
        self.tabs.addTab(self.manager, "Менеджер")
        self.tabs.addTab(run_tab, "Запуск")
        self.tabs.setCurrentIndex(0)
        root.addWidget(self.tabs, 1)

        # update banner
        self.banner = QFrame()
        self.banner.setObjectName("banner")
        bl = QVBoxLayout(self.banner)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(6)
        self.zapret_upd_row = self._make_update_row("zapret")
        self.app_upd_row = self._make_update_row("app")
        bl.addLayout(self.zapret_upd_row["layout"])
        bl.addLayout(self.app_upd_row["layout"])
        self.banner.hide()
        root.addWidget(self.banner)

        bottom = QHBoxLayout()
        self.check_btn = QPushButton("Проверить обновления ПО")
        self.check_btn.setToolTip("Проверить новую версию Zapret GUI в вашем GitHub-репозитории")
        self.check_btn.clicked.connect(lambda: self.check_updates(manual=True, mode="app"))
        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.clicked.connect(self.open_settings)
        self.clear_btn = QPushButton("Очистить лог")
        self.clear_btn.clicked.connect(self._clear_logs)
        bottom.addWidget(self.check_btn)
        bottom.addWidget(self.settings_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.clear_btn)
        root.addLayout(bottom)

        self.setCentralWidget(central)

    def _make_update_row(self, kind):
        layout = QHBoxLayout()
        label = QLabel()
        label.setWordWrap(True)
        btn = QPushButton("Обновить")
        layout.addWidget(label, 1)
        layout.addWidget(btn)
        row = {"layout": layout, "label": label, "btn": btn}
        if kind == "zapret":
            btn.clicked.connect(self._zapret_row_clicked)
        else:
            btn.clicked.connect(self.update_app)
        return row

    def _zapret_row_clicked(self):
        rel = self._zapret_release
        if rel and not github.pick_asset(rel, ".zip"):
            QDesktopServices.openUrl(QUrl(rel.url))
        else:
            self.update_zapret()

    def _build_tray(self):
        self.tray = QSystemTrayIcon(self._icon, self)
        menu = QMenu()
        show_act = QAction("Показать", self)
        show_act.triggered.connect(self._show_window)
        self.tray_start = QAction("Старт", self)
        self.tray_start.triggered.connect(self.start_strategy)
        self.tray_stop = QAction("Стоп", self)
        self.tray_stop.triggered.connect(self.stop_strategy)
        quit_act = QAction("Выход", self)
        quit_act.triggered.connect(self._quit)
        menu.addAction(show_act)
        menu.addSeparator()
        menu.addAction(self.tray_start)
        menu.addAction(self.tray_stop)
        menu.addSeparator()
        menu.addAction(quit_act)
        self.tray.setContextMenu(menu)
        self.tray.setToolTip(APP_NAME)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    # ---------- helpers ----------
    def _append_raw(self, line):
        self.log.appendPlainText(line)

    def _sys(self, msg):
        applog.write("GUI", msg)
        self.log.appendPlainText(f"[GUI] {msg}")

    def _clear_logs(self):
        self.log.clear()
        self.manager.out.clear()

    def _refresh_strategies(self):
        self.strategy_combo.clear()
        d = self.config.zapret_dir
        if d and Path(d).is_dir():
            names = zapret.list_strategies(d)
            self.strategy_combo.addItems(names)
            idx = self.strategy_combo.findText(self.config.strategy)
            self.strategy_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.zapret_ver.setText(f"zapret {zapret.read_local_version(d) or '?'}")
        else:
            self.zapret_ver.setText("zapret не найден")
        self.ver_label.setText(f"v{APP_VERSION}")
        self.manager.refresh()

    def _update_status(self):
        if self.runner.is_running():
            self.status_dot.setStyleSheet("color: #3fb950; font-size: 16px;")
            self.status_text.setText("Работает")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.strategy_combo.setEnabled(False)
        elif self._external_running:
            self.status_dot.setStyleSheet("color: #d29922; font-size: 16px;")
            self.status_text.setText("Работает (сторонний winws.exe)")
            self.start_btn.setEnabled(False)
            self.stop_btn.setEnabled(True)
            self.strategy_combo.setEnabled(True)
        else:
            self.status_dot.setStyleSheet("color: #f85149; font-size: 16px;")
            self.status_text.setText("Остановлено")
            self.start_btn.setEnabled(bool(self.config.zapret_dir))
            self.stop_btn.setEnabled(False)
            self.strategy_combo.setEnabled(True)
        self.tray_start.setEnabled(self.start_btn.isEnabled())
        self.tray_stop.setEnabled(self.stop_btn.isEnabled())

    def _poll_external(self):
        if self.runner.is_running():
            return
        was = self._external_running
        self._external_running = zapret.is_winws_running()
        if was != self._external_running:
            self._update_status()

    # ---------- start / stop ----------
    def start_strategy(self):
        d = self.config.zapret_dir
        if not d or not Path(d).is_dir():
            QMessageBox.warning(self, "Ошибка", "Папка zapret не найдена. Укажите её в настройках.")
            return
        if zapret.is_zapret_service_running():
            QMessageBox.warning(self, "Служба zapret",
                                "Обнаружена запущенная служба zapret.\nСначала удалите её через service.bat (Remove Services).")
            return
        if zapret.is_winws_running():
            ans = QMessageBox.question(self, "winws.exe уже запущен",
                                       "winws.exe уже работает. Остановить его и запустить выбранную стратегию?")
            if ans != QMessageBox.StandardButton.Yes:
                return
            zapret.kill_winws()

        bat = self.strategy_combo.currentText()
        self.config.strategy = bat
        self.config.save()

        zapret.ensure_user_lists(d)
        zapret.enable_tcp_timestamps()
        self._sys(f"Запуск стратегии: {bat}")
        try:
            self.runner.start(d, bat)
        except Exception as e:
            self._sys(f"Ошибка запуска: {e}")
            QMessageBox.critical(self, "Ошибка запуска", str(e))

    def stop_strategy(self):
        if self.runner.is_running():
            self._sys("Остановка winws.exe ...")
            self.runner.stop()
        elif self._external_running:
            self._sys("Остановка стороннего winws.exe ...")
            zapret.kill_winws()
            self._external_running = False
            self._update_status()

    def _on_started(self):
        self._external_running = False
        self._sys("winws.exe запущен")
        self._update_status()

    def _on_stopped(self, code):
        self._sys(f"winws.exe завершён (код {code})")
        self._update_status()

    def _on_runner_error(self, msg):
        self._sys(msg)
        self._update_status()

    # ---------- updates ----------
    def check_updates(self, manual=False, mode="both"):
        if self._check_worker and self._check_worker.isRunning():
            return
        d = self.config.zapret_dir
        if not manual and mode == "both" and d and not svc.autoupdate_enabled(d):
            mode = "app"
        self.check_btn.setEnabled(False)
        self.check_btn.setText("Проверка…")
        if manual:
            what = {"app": "обновлений приложения", "zapret": "обновлений zapret",
                    "both": "обновлений"}[mode]
            self._sys(f"Проверка {what} ...")
        local = zapret.read_local_version(d) if d else "0"
        self._check_worker = CheckWorker(local, self.config.app_repo, mode, self)
        self._check_worker.done.connect(lambda r: self._on_check_done(r, manual, mode))
        self._check_worker.start()

    def _on_check_done(self, result, manual, mode):
        self.check_btn.setEnabled(True)
        self.check_btn.setText("Проверить обновления ПО")
        for e in result["errors"]:
            applog.write("UPD", f"check error (repo={self.config.app_repo}): {e}")
        if mode in ("both", "zapret"):
            self._zapret_release = result["zapret"]
            rel = self._zapret_release
            if rel:
                pending = not github.pick_asset(rel, ".zip")
                self.zapret_upd_row["label"].setText(
                    f"Доступна новая версия zapret: {rel.version}"
                    + (" (релиз с архивом ещё не опубликован)" if pending else ""))
                self.zapret_upd_row["btn"].setText("Страница релиза" if pending else "Обновить")
                self.zapret_upd_row["btn"].show()
                self.zapret_upd_row["label"].show()
                if manual:
                    self._sys(f"zapret: новая версия {rel.version} — {rel.url}")
            else:
                self.zapret_upd_row["btn"].hide()
                self.zapret_upd_row["label"].hide()
                if manual:
                    self._sys(f"zapret: установлена последняя версия "
                              f"{zapret.read_local_version(self.config.zapret_dir) or '?'}")

        if mode in ("both", "app"):
            self._app_release = result["app"]
            if self._app_release:
                self.app_upd_row["label"].setText(
                    f"Доступна новая версия приложения: {self._app_release.version}")
                self.app_upd_row["btn"].show()
                self.app_upd_row["label"].show()
            else:
                self.app_upd_row["btn"].hide()
                self.app_upd_row["label"].hide()

        self.banner.setVisible(not self.zapret_upd_row["label"].isHidden()
                               or not self.app_upd_row["label"].isHidden())

        if manual:
            if result["errors"]:
                self._sys("Ошибки проверки: " + "; ".join(result["errors"]))
            checked = [k for k in ("zapret", "app") if mode in ("both", k)]
            if not any(result[k] for k in checked) and not result["errors"]:
                QMessageBox.information(self, "Обновления", "Установлены последние версии.")
            for e in result["errors"]:
                self._sys(e)

    def _confirm_release(self, title, release):
        notes = release.notes.strip()
        if len(notes) > 1200:
            notes = notes[:1200] + "\n…"
        text = f"Версия {release.version}\n\n{notes}" if notes else f"Версия {release.version}"
        ans = QMessageBox.question(self, title, text + "\n\nОбновить?")
        return ans == QMessageBox.StandardButton.Yes

    def update_zapret(self):
        if not self._zapret_release:
            return
        if not self._confirm_release("Обновление zapret", self._zapret_release):
            return
        was_running = self.runner.is_running() or self._external_running
        bat = self.strategy_combo.currentText()
        if self.runner.is_running():
            self.runner.stop()
        elif self._external_running:
            zapret.kill_winws()
            self._external_running = False

        old_dir = self.config.zapret_dir
        self._install_worker = ZapretInstallWorker(self._zapret_release, old_dir, self)
        dlg = self._progress_dialog("Обновление zapret", self._install_worker)
        self._install_worker.log.connect(self._sys)
        self._install_worker.done.connect(
            lambda nd: self._on_zapret_installed(nd, dlg, was_running, bat, old_dir))
        self._install_worker.error.connect(lambda e: self._on_install_error(e, dlg))
        self._install_worker.start()
        dlg.show()

    def _on_zapret_installed(self, new_dir, dlg, was_running, bat, old_dir):
        dlg.close()
        self.config.zapret_dir = new_dir
        self.config.save()
        self._zapret_release = None
        self.zapret_upd_row["btn"].hide()
        self.zapret_upd_row["label"].hide()
        self.banner.setVisible(bool(self._app_release))
        self._refresh_strategies()
        idx = self.strategy_combo.findText(bat)
        if idx >= 0:
            self.strategy_combo.setCurrentIndex(idx)
        self._sys(f"zapret обновлён. Старая папка сохранена: {old_dir}")
        self._sys(f"Новая версия: {zapret.read_local_version(new_dir)}")
        if was_running:
            self._sys("Перезапуск стратегии ...")
            QTimer.singleShot(500, self.start_strategy)
        QMessageBox.information(self, "Готово",
                                f"zapret обновлён до {zapret.read_local_version(new_dir)}.\n"
                                f"Старая версия оставлена в соседней папке — её можно удалить вручную.")

    def update_app(self):
        if not self._app_release:
            return
        if not updater.is_frozen():
            QMessageBox.information(self, "Самообновление",
                                    "Самообновление работает только в собранном .exe.\n"
                                    "Запустите собранную версию приложения.")
            return
        if not self._confirm_release("Обновление приложения", self._app_release):
            return
        self._install_worker = AppInstallWorker(self._app_release, self)
        dlg = self._progress_dialog("Обновление приложения", self._install_worker)
        self._install_worker.log.connect(self._sys)
        self._install_worker.done.connect(lambda s: self._on_app_ready(s, dlg))
        self._install_worker.error.connect(lambda e: self._on_install_error(e, dlg))
        self._install_worker.start()
        dlg.show()

    def _on_app_ready(self, script, dlg):
        dlg.close()
        self._sys("Перезапуск для установки обновления ...")
        updater.launch_swap_script(script)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def _on_install_error(self, msg, dlg):
        dlg.close()
        self._sys(f"Ошибка обновления: {msg}")
        QMessageBox.critical(self, "Ошибка обновления", msg)

    def _progress_dialog(self, title, worker):
        dlg = QProgressDialog(title, "Отмена", 0, 100, self)
        dlg.setWindowTitle(title)
        dlg.setWindowModality(Qt.WindowModality.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setAutoReset(False)
        dlg.setValue(0)
        worker.progress.connect(
            lambda d, t: dlg.setValue(int(d * 100 / t) if t else 0))
        dlg.canceled.connect(worker.cancel)
        return dlg

    # ---------- first-run zapret download ----------
    def _ensure_zapret(self):
        d = self.config.zapret_dir
        if not d or not (Path(d) / "bin" / "winws.exe").exists():
            self._offer_zapret_download()

    def _offer_zapret_download(self):
        if self._setup_worker and self._setup_worker.isRunning():
            return
        dest = zapret.project_root()
        ans = QMessageBox.question(
            self, "zapret не найден",
            "Папка zapret не найдена на ПК.\n"
            f"Скачать последнюю версию с GitHub автора и распаковать в:\n{dest}\n\n"
            "Папка хранится внутри проекта (рядом с приложением) и обновляется из него.\n"
            "Скачать?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        self._setup_worker = ZapretSetupWorker(dest, self)
        dlg = self._progress_dialog("Загрузка zapret", self._setup_worker)
        self._setup_worker.log.connect(self._sys)
        self._setup_worker.done.connect(lambda nd: self._on_zapret_setup(nd, dlg))
        self._setup_worker.error.connect(lambda e: self._on_install_error(e, dlg))
        self._setup_worker.start()
        dlg.show()

    def _on_zapret_setup(self, new_dir, dlg):
        dlg.close()
        self.config.zapret_dir = new_dir
        self.config.save()
        self._refresh_strategies()
        self._update_status()
        self._sys(f"zapret загружен: {new_dir}")
        QMessageBox.information(
            self, "Готово",
            f"zapret {zapret.read_local_version(new_dir)} загружен в:\n{new_dir}\n\n"
            "Выберите стратегию на вкладке «Запуск» и нажмите «Старт».")

    # ---------- settings / tray / close ----------
    def open_settings(self):
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            self._refresh_strategies()
            self._update_status()
            self._sys("Настройки сохранены")

    def _tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self._show_window()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _quit(self):
        self.tray.hide()
        from PySide6.QtWidgets import QApplication
        QApplication.instance().quit()

    def closeEvent(self, event):
        if self.config.minimize_to_tray and self.tray.isVisible():
            event.ignore()
            self.hide()
            if not self._tray_notified:
                self.tray.showMessage(APP_NAME,
                                      "Приложение свёрнуто в трей. Обход продолжает работать.",
                                      self._icon, 3000)
                self._tray_notified = True
        else:
            self.tray.hide()
            event.accept()