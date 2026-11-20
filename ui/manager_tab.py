from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QMessageBox, QPlainTextEdit,
    QProgressBar, QPushButton, QScrollArea, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from core import service as svc
from core import zapret
from ui.workers import TestWorker


class GameFilterDialog(QDialog):
    def __init__(self, zapret_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Игровой фильтр")
        self.zapret_dir = zapret_dir
        mode, tcp, udp = zapret.read_game_filter(zapret_dir)
        form = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItem("Выключен", "disabled")
        self.mode.addItem("TCP и UDP", "all")
        self.mode.addItem("Только TCP", "tcp")
        self.mode.addItem("Только UDP", "udp")
        self.mode.setCurrentIndex(max(self.mode.findData(mode), 0))
        self.tcp = QLineEdit(tcp)
        self.udp = QLineEdit(udp)
        form.addRow("Режим:", self.mode)
        form.addRow("TCP порты:", self.tcp)
        form.addRow("UDP порты:", self.udp)
        hint = QLabel("Пример диапазона: 1024-65535 или 1024-1934,1936-65535")
        hint.setStyleSheet("color:#9aa0a6; font-size:11px;")
        form.addRow(hint)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _accept(self):
        tcp, udp = self.tcp.text().strip(), self.udp.text().strip()
        for val in (tcp, udp):
            if not self._valid_range(val):
                QMessageBox.warning(self, "Ошибка", f"Некорректный диапазон портов: {val}")
                return
        svc.set_game_filter_ranges(self.zapret_dir, self.mode.currentData(), tcp, udp)
        self.accept()

    @staticmethod
    def _valid_range(s):
        if not s:
            return False
        for part in s.split(","):
            m = part.split("-")
            if len(m) not in (1, 2):
                return False
            try:
                nums = [int(x) for x in m]
            except ValueError:
                return False
            if any(n < 1 or n > 65535 for n in nums):
                return False
            if len(nums) == 2 and nums[0] > nums[1]:
                return False
        return True


class FakesDialog(QDialog):
    def __init__(self, zapret_dir, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Замена активных фейков")
        self.zapret_dir = zapret_dir
        info = svc.get_fakes(zapret_dir)
        form = QFormLayout(self)
        form.addRow(QLabel(f"Discord UDP (текущий): {info['discord']}"))
        form.addRow(QLabel(f"Game UDP (текущий): {info['game']}"))
        self.kind = QComboBox()
        self.kind.addItem("Discord UDP", "discord")
        self.kind.addItem("Game Filter UDP", "game")
        self.fake = QComboBox()
        self.fake.addItems(info["fakes"])
        form.addRow("Заменить:", self.kind)
        form.addRow("На фейк:", self.fake)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _accept(self):
        if not self.fake.currentText():
            QMessageBox.warning(self, "Ошибка", "Нет доступных .bin фейков")
            return
        svc.replace_fake(self.zapret_dir, self.kind.currentData(), self.fake.currentText())
        self.accept()


class ManagerTab(QWidget):
    check_updates = Signal()
    changed = Signal()

    def __init__(self, config, get_strategy, parent=None):
        super().__init__(parent)
        self.config = config
        self.get_strategy = get_strategy
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        container = QWidget()
        root = QVBoxLayout(container)
        root.setSpacing(10)

        # SERVICE
        g_service = QGroupBox("Служба")
        sv = QVBoxLayout(g_service)
        self.installed_label = QLabel()
        self.installed_label.setStyleSheet("color:#9aa0a6;")
        sv.addWidget(self.installed_label)
        row = QHBoxLayout()
        b_install = QPushButton("Установить службу")
        b_install.clicked.connect(self._install)
        b_remove = QPushButton("Удалить службы")
        b_remove.clicked.connect(self._remove)
        b_status = QPushButton("Статус")
        b_status.clicked.connect(self._status)
        for b in (b_install, b_remove, b_status):
            row.addWidget(b)
        sv.addLayout(row)
        root.addWidget(g_service)

        # SETTINGS
        g_set = QGroupBox("Настройки")
        st = QVBoxLayout(g_set)
        self.b_game = QPushButton()
        self.b_game.clicked.connect(self._game)
        self.b_ipset = QPushButton()
        self.b_ipset.clicked.connect(self._ipset)
        self.b_auto = QPushButton()
        self.b_auto.clicked.connect(self._auto)
        b_fakes = QPushButton("Заменить активные фейки")
        b_fakes.clicked.connect(self._fakes)
        for b in (self.b_game, self.b_ipset, self.b_auto, b_fakes):
            st.addWidget(b)
        root.addWidget(g_set)

        # UPDATES
        g_upd = QGroupBox("Обновления")
        up = QVBoxLayout(g_upd)
        b_ipset_upd = QPushButton("Обновить IPSet список")
        b_ipset_upd.clicked.connect(self._ipset_update)
        b_hosts = QPushButton("Обновить hosts файл")
        b_hosts.clicked.connect(self._hosts)
        b_check = QPushButton("Проверить обновления zapret")
        b_check.setToolTip("Как пункт 10 в service.bat: версия из main-ветки репозитория Flowseal")
        b_check.clicked.connect(self.check_updates.emit)
        for b in (b_ipset_upd, b_hosts, b_check):
            up.addWidget(b)
        root.addWidget(g_upd)

        # TOOLS
        g_tools = QGroupBox("Инструменты")
        tl = QVBoxLayout(g_tools)
        b_diag = QPushButton("Диагностика")
        b_diag.clicked.connect(self._diagnostics)
        tl.addWidget(b_diag)
        test_row = QHBoxLayout()
        self.test_scope = QComboBox()
        self.test_scope.addItem("Все стратегии", "all")
        self.test_scope.addItem("Выбранная стратегия", "one")
        self.b_run_tests = QPushButton("Запустить тесты")
        self.b_run_tests.clicked.connect(self._tests)
        self.b_cancel_tests = QPushButton("Отмена")
        self.b_cancel_tests.clicked.connect(self._cancel_tests)
        self.b_cancel_tests.hide()
        test_row.addWidget(self.test_scope, 1)
        test_row.addWidget(self.b_run_tests)
        test_row.addWidget(self.b_cancel_tests)
        tl.addLayout(test_row)
        self.test_progress = QProgressBar()
        self.test_progress.setRange(0, 100)
        self.test_progress.setValue(0)
        self.test_progress.setFormat("Тесты: %v/%m")
        tl.addWidget(self.test_progress)
        root.addWidget(g_tools)

        # RESULTS (embedded, shown after tests)
        self.g_results = QGroupBox("Результаты тестов")
        rl = QVBoxLayout(self.g_results)
        self.best_label = QLabel()
        self.best_label.setStyleSheet("color:#3fb950; font-weight:600;")
        rl.addWidget(self.best_label)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Стратегия", "OK", "ERR", "SSL", "UNSUP", "Ping OK", "Ping Fail"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 7):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(180)
        rl.addWidget(self.table)
        self.g_results.hide()
        root.addWidget(self.g_results)

        self.out = QPlainTextEdit()
        self.out.setReadOnly(True)
        self.out.setMaximumBlockCount(5000)
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        self.out.setFont(mono)
        self.out.setMinimumHeight(120)
        root.addWidget(self.out, 1)
        scroll.setWidget(container)
        outer.addWidget(scroll)
        self._scroll = scroll
        self.refresh()

    # ---------- helpers ----------
    def _log(self, msg):
        self.out.appendPlainText(msg)

    def _dir(self):
        d = self.config.zapret_dir
        if not d or not Path(d).is_dir():
            QMessageBox.warning(self, "Ошибка", "Папка zapret не найдена. Укажите её в настройках.")
            return None
        return d

    def refresh(self):
        d = self.config.zapret_dir
        strat = svc.installed_strategy()
        self.installed_label.setText(f"Стратегия службы: {strat or 'не установлена'}")
        if d and Path(d).is_dir():
            self.b_game.setText(f"Игровой фильтр  [{svc.game_filter_status(d)}]")
            self.b_ipset.setText(f"IPSet фильтр  [{svc.read_ipset_mode(d)}]")
            self.b_auto.setText(f"Автопроверка обновлений  [{'enabled' if svc.autoupdate_enabled(d) else 'disabled'}]")
        else:
            self.b_game.setText("Игровой фильтр")
            self.b_ipset.setText("IPSet фильтр")
            self.b_auto.setText("Автопроверка обновлений")

    def _emit(self, lines):
        prefix = {"ok": "[OK]", "warn": "[?]", "err": "[X]", "info": "[i]"}
        for level, msg in lines:
            self._log(f"{prefix.get(level, '[i]')} {msg}")

    # ---------- actions ----------
    def _install(self):
        d = self._dir()
        if not d:
            return
        strategies = zapret.list_strategies(d)
        if not strategies:
            QMessageBox.warning(self, "Ошибка", "В папке zapret нет стратегий (*.bat).")
            return
        current = self.get_strategy()
        idx = strategies.index(current) if current in strategies else 0
        bat, ok = QInputDialog.getItem(
            self, "Установка службы", "Стратегия для службы:", strategies, idx, False)
        if not ok or not bat:
            return
        ans = QMessageBox.question(self, "Установка службы",
                                   f"Установить службу zapret со стратегией {bat}?\n"
                                   "Служба будет запускаться автоматически при старте Windows.")
        if ans != QMessageBox.StandardButton.Yes:
            return
        try:
            svc.install_service(d, bat, log=self._log)
            self.changed.emit()
            self.refresh()
        except Exception as e:
            self._log(f"[X] Ошибка установки службы: {e}")
            QMessageBox.critical(self, "Ошибка", str(e))

    def _remove(self):
        ans = QMessageBox.question(self, "Удаление служб",
                                   "Удалить службы zapret и WinDivert и остановить winws.exe?")
        if ans != QMessageBox.StandardButton.Yes:
            return
        svc.remove_services(log=self._log)
        self.changed.emit()
        self.refresh()

    def _status(self):
        d = self._dir()
        if not d:
            return
        self._emit(svc.service_status(d))

    def _game(self):
        d = self._dir()
        if not d:
            return
        dlg = GameFilterDialog(d, self)
        if dlg.exec():
            self._log("Игровой фильтр сохранён. Перезапустите обход для применения.")
            self.refresh()

    def _ipset(self):
        d = self._dir()
        if not d:
            return
        try:
            mode = svc.switch_ipset(d)
            self._log(f"IPSet фильтр переключён: {mode}")
            self.refresh()
        except Exception as e:
            self._log(f"[X] {e}")
            QMessageBox.warning(self, "IPSet", str(e))

    def _auto(self):
        d = self._dir()
        if not d:
            return
        state = svc.toggle_autoupdate(d)
        self._log(f"Автопроверка обновлений: {'enabled' if state else 'disabled'}")
        self.refresh()

    def _fakes(self):
        d = self._dir()
        if not d:
            return
        dlg = FakesDialog(d, self)
        if dlg.exec():
            self._log("Активный фейк заменён. Перезапустите обход для применения.")

    def _ipset_update(self):
        d = self._dir()
        if not d:
            return
        try:
            svc.update_ipset_list(d, log=self._log)
            self.refresh()
        except Exception as e:
            self._log(f"[X] Ошибка обновления IPSet: {e}")

    def _hosts(self):
        d = self._dir()
        if not d:
            return
        try:
            svc.update_hosts_file(d, log=self._log)
        except Exception as e:
            self._log(f"[X] Ошибка обновления hosts: {e}")

    def _diagnostics(self):
        d = self._dir()
        if not d:
            return
        self._log("--- Диагностика ---")
        lines = svc.diagnostics(d)
        self._emit(lines)
        has_conflict = any(l == "err" and ("Конфликтующие" in m or "WinDivert активен" in m)
                           for l, m in lines)
        if has_conflict:
            ans = QMessageBox.question(self, "Конфликты",
                                       "Обнаружены конфликтующие службы. Удалить их?")
            if ans == QMessageBox.StandardButton.Yes:
                svc.remove_conflicting_services(log=self._log)
        ans = QMessageBox.question(self, "Кэш Discord",
                                   "Очистить кэш Discord (Stable/PTB/Canary/Development)?")
        if ans == QMessageBox.StandardButton.Yes:
            svc.clear_discord_cache(log=self._log)
        self.changed.emit()

    def _tests(self):
        d = self._dir()
        if not d:
            return
        parent = self.window()
        if self.test_scope.currentData() == "one":
            bat = parent.strategy_combo.currentText() if parent else ""
            configs = [bat] if bat else []
        else:
            configs = zapret.list_strategies(d)
        if not configs:
            QMessageBox.warning(self, "Тесты", "Нет стратегий для тестирования.")
            return

        self._test_was_running = bool(parent and parent.runner.is_running()) or zapret.is_winws_running()
        if parent and parent.runner.is_running():
            parent.runner.stop()
        zapret.kill_winws()

        self._log(f"--- Тесты ({len(configs)} стратегий), без внешних окон ---")
        self.b_run_tests.setEnabled(False)
        self.test_scope.setEnabled(False)
        self.b_cancel_tests.show()
        self.test_progress.setRange(0, len(configs))
        self.test_progress.setValue(0)
        self.g_results.hide()

        self._test_worker = TestWorker(d, configs, self)
        self._test_worker.log.connect(self._log)
        self._test_worker.progress.connect(lambda v, t: self.test_progress.setValue(v))
        self._test_worker.done.connect(self._on_tests_done)
        self._test_worker.error.connect(self._on_tests_error)
        self._test_worker.start()

    def _cancel_tests(self):
        if getattr(self, "_test_worker", None):
            self._test_worker.cancel()

    def _tests_finished(self):
        self.b_run_tests.setEnabled(True)
        self.test_scope.setEnabled(True)
        self.b_cancel_tests.hide()

    def _on_tests_done(self, payload):
        self._tests_finished()
        results, best = payload["results"], payload["best"]
        self.table.setRowCount(len(results))
        for row, r in enumerate(results):
            vals = [r["config"], r["ok"], r["err"], r["ssl"], r["unsup"], r["ping_ok"], r["ping_fail"]]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if r["config"] == best:
                    item.setBackground(QColor("#1c3a24"))
                self.table.setItem(row, col, item)
        self.best_label.setText(f"Лучшая стратегия: {best or 'не определена'}")
        self.g_results.show()
        self._scroll.ensureWidgetVisible(self.g_results)
        self._log(f"Тесты завершены. Лучшая стратегия: {best or 'не определена'}")
        parent = self.window()
        if self._test_was_running and parent:
            self._log("Восстановление ранее работавшей стратегии ...")
            parent.start_strategy()

    def _on_tests_error(self, msg):
        self._tests_finished()
        self._log(f"[X] {msg}")
        parent = self.window()
        if getattr(self, "_test_was_running", False) and parent:
            parent.start_strategy()