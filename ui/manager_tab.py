import csv
import json
import time
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
    QGroupBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from core import applog, service as svc, tests, zapret
from ui.workers import TestWorker, StabilityWorker


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
    need_zapret = Signal()

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
        self.dbg_tests = QCheckBox("Отладка: подробный лог проверок (окно + файл)")
        self.dbg_tests.setToolTip("Тайминги каждой цели, pid/код выхода winws и его вывод в файлах %APPDATA%/ZapretGUI/debug")
        tl.addWidget(self.dbg_tests)
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
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Стратегия", "OK", "ERR", "SSL", "UNSUP", "Ping OK", "Ping Fail", "Время, с"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 8):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(180)
        rl.addWidget(self.table)
        res_row = QHBoxLayout()
        self.hist_combo = QComboBox()
        self.hist_combo.setToolTip("История прогонов тестов (последние 10)")
        self.hist_combo.currentIndexChanged.connect(self._on_history_pick)
        self.b_apply_best = QPushButton("Применить лучшую")
        self.b_apply_best.clicked.connect(self._apply_best)
        self.b_export_csv = QPushButton("Экспорт CSV")
        self.b_export_csv.clicked.connect(lambda: self._export("csv"))
        self.b_export_json = QPushButton("Экспорт JSON")
        self.b_export_json.clicked.connect(lambda: self._export("json"))
        res_row.addWidget(self.hist_combo, 1)
        res_row.addWidget(self.b_apply_best)
        res_row.addWidget(self.b_export_csv)
        res_row.addWidget(self.b_export_json)
        rl.addLayout(res_row)
        self.g_results.hide()
        root.addWidget(self.g_results)

        # STABILITY (probes while bypass keeps running)
        g_stab = QGroupBox("Стабильность соединения")
        sl = QVBoxLayout(g_stab)
        stab_row = QHBoxLayout()
        self.stab_rounds = QComboBox()
        for n in (10, 20, 30):
            self.stab_rounds.addItem(f"{n} проб (≈{n * 2 + n * 3} с)", n)
        self.b_stab = QPushButton("Проверить стабильность")
        self.b_stab.clicked.connect(self._stability)
        self.b_stab_cancel = QPushButton("Отмена")
        self.b_stab_cancel.clicked.connect(self._cancel_stability)
        self.b_stab_cancel.hide()
        stab_row.addWidget(self.stab_rounds, 1)
        stab_row.addWidget(self.b_stab)
        stab_row.addWidget(self.b_stab_cancel)
        sl.addLayout(stab_row)
        self.stab_progress = QProgressBar()
        self.stab_progress.setRange(0, 100)
        self.stab_progress.setValue(0)
        self.stab_progress.setFormat("Пробы: %v/%m")
        sl.addWidget(self.stab_progress)
        self.stab_verdict = QLabel()
        sl.addWidget(self.stab_verdict)
        self.stab_table = QTableWidget(0, 8)
        self.stab_table.setHorizontalHeaderLabels(
            ["Цель", "OK/Проб", "Потери %", "Avg ms", "Min ms", "Max ms",
             "Jitter ms", "Ping avg ms"])
        self.stab_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, 8):
            self.stab_table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self.stab_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.stab_table.verticalHeader().setVisible(False)
        self.stab_table.setMinimumHeight(140)
        sl.addWidget(self.stab_table)
        root.addWidget(g_stab)

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
        self._refresh_history()

    # ---------- helpers ----------
    def _log(self, msg):
        applog.write("MGR", msg)
        self.out.appendPlainText(msg)

    def _dir(self):
        d = self.config.zapret_dir
        if not d or not Path(d).is_dir():
            self.need_zapret.emit()
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
        self._removed_service = ""
        service_bat = svc.installed_strategy() if zapret.is_zapret_service_running() else ""
        if zapret.is_zapret_service_running():
            box = QMessageBox(self)
            box.setWindowTitle("Служба zapret запущена")
            box.setIcon(QMessageBox.Icon.Warning)
            box.setText("Служба zapret запущена: она перезапускает winws.exe и мешает тестам.\n"
                        "Удалить службу и продолжить тестирование?")
            go = box.addButton("Удалить службу и продолжить", QMessageBox.ButtonRole.AcceptRole)
            box.addButton("Отменить тесты", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not go:
                self._log("Тесты отменены: служба zapret запущена.")
                return
            svc.remove_services(log=self._log)
            self._removed_service = service_bat
            self._log("Служба удалена на время тестов.")
            self.changed.emit()
            self.refresh()
        parent = self.window()
        if self.test_scope.currentData() == "one":
            bat = parent.strategy_combo.currentText() if parent else ""
            configs = [bat] if bat else []
        else:
            configs = zapret.list_strategies(d)
        if not configs:
            QMessageBox.warning(self, "Тесты", "Нет стратегий для тестирования.")
            return

        runner_was = bool(parent and parent.runner.is_running())
        self._test_restore = {
            "runner": runner_was,
            "snapshot": [] if runner_was else zapret.winws_snapshot(),
        }
        if runner_was:
            parent.runner.stop()
        zapret.kill_winws()

        self._log(f"--- Тесты ({len(configs)} стратегий), без внешних окон ---")
        self.b_run_tests.setEnabled(False)
        self.test_scope.setEnabled(False)
        self.b_cancel_tests.show()
        self.test_progress.setRange(0, len(configs))
        self.test_progress.setValue(0)
        self.g_results.hide()

        self._test_worker = TestWorker(d, configs, self.dbg_tests.isChecked(), self)
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
        self._last_results, self._last_best = results, best
        self._fill_table(results, best)
        bad = [r["config"] for r in results if not r.get("started", True)]
        if bad:
            self._log("[X] winws не работал в: " + ", ".join(bad)
                      + " — результаты недостоверны, см. лог отладки")
        self._log(f"Тесты завершены. Лучшая стратегия: {best or 'не определена'}")
        self._save_history(results, best)
        self._restore_after_tests()

    def _on_tests_error(self, msg):
        self._tests_finished()
        self._log(f"[X] {msg}")
        self._restore_after_tests()

    def _restore_after_tests(self):
        parent = self.window()
        r = getattr(self, "_test_restore", {})
        if r.get("runner") and parent:
            self._log("Восстановление ранее работавшей стратегии ...")
            parent.start_strategy()
        elif r.get("snapshot"):
            self._log("Восстановление ранее работавших winws (точные аргументы) ...")
            zapret.restore_winws(r["snapshot"])
        bat = getattr(self, "_removed_service", "")
        if bat:
            self._removed_service = ""
            ans = QMessageBox.question(
                self, "Служба zapret",
                f"Вернуть службу zapret со стратегией {bat}, удалённую на время тестов?")
            if ans == QMessageBox.StandardButton.Yes:
                d = self.config.zapret_dir
                try:
                    svc.install_service(d, bat, log=self._log)
                    self.changed.emit()
                    self.refresh()
                except Exception as e:
                    self._log(f"[X] Ошибка установки службы: {e}")

    # ---------- results table / history / export ----------
    def _fill_table(self, results, best):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(results))
        for row, r in enumerate(results):
            vals = [r["config"], r["ok"], r["err"], r["ssl"], r["unsup"],
                    r["ping_ok"], r["ping_fail"], r.get("seconds", "")]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if not r.get("started", True):
                    item.setBackground(QColor("#3a2222"))
                if r["config"] == best:
                    item.setBackground(QColor("#1c3a24"))
                self.table.setItem(row, col, item)
        self.table.setSortingEnabled(True)
        self.best_label.setText(f"Лучшая стратегия: {best or 'не определена'}")
        self.g_results.show()
        self._scroll.ensureWidgetVisible(self.g_results)

    def _history_file(self):
        return tests.debug_dir().parent / "history.json"

    def _save_history(self, results, best):
        try:
            f = self._history_file()
            hist = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
            hist.insert(0, {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            "results": results, "best": best})
            f.write_text(json.dumps(hist[:10], ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self._log(f"[X] Не удалось сохранить историю: {e}")
        self._refresh_history()

    def _refresh_history(self):
        self.hist_combo.blockSignals(True)
        self.hist_combo.clear()
        try:
            f = self._history_file()
            hist = json.loads(f.read_text(encoding="utf-8")) if f.exists() else []
        except Exception:
            hist = []
        for i, h in enumerate(hist):
            self.hist_combo.addItem(f"{h['ts']}  (лучшая: {h['best'] or '—'})", i)
        self.hist_combo.blockSignals(False)

    def _on_history_pick(self, idx):
        if idx < 0:
            return
        try:
            hist = json.loads(self._history_file().read_text(encoding="utf-8"))
            h = hist[self.hist_combo.itemData(idx)]
        except Exception:
            return
        self._last_results, self._last_best = h["results"], h["best"]
        self._fill_table(h["results"], h["best"])

    def _export(self, kind):
        results = getattr(self, "_last_results", None)
        if not results:
            return
        ts = time.strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт результатов", f"zapret_tests_{ts}.{kind}",
            f"{'CSV' if kind == 'csv' else 'JSON'} (*.{kind})")
        if not path:
            return
        try:
            if kind == "csv":
                with open(path, "w", newline="", encoding="utf-8-sig") as f:
                    w = csv.writer(f)
                    w.writerow(["config", "ok", "err", "ssl", "unsup",
                                "ping_ok", "ping_fail", "seconds", "started"])
                    for r in results:
                        w.writerow([r["config"], r["ok"], r["err"], r["ssl"], r["unsup"],
                                    r["ping_ok"], r["ping_fail"], r.get("seconds", ""),
                                    r.get("started", True)])
            else:
                Path(path).write_text(json.dumps(
                    {"best": self._last_best, "results": results},
                    ensure_ascii=False, indent=1), encoding="utf-8")
            self._log(f"Результаты экспортированы: {path}")
        except Exception as e:
            self._log(f"[X] Ошибка экспорта: {e}")

    def _apply_best(self):
        best = getattr(self, "_last_best", None)
        parent = self.window()
        if not best or not parent:
            return
        idx = parent.strategy_combo.findText(best)
        if idx < 0:
            self._log(f"[X] Стратегия {best} не найдена в списке")
            return
        parent.strategy_combo.setCurrentIndex(idx)
        self._log(f"Применяется лучшая стратегия: {best}")
        parent.start_strategy()

    # ---------- stability ----------
    def _stability(self):
        d = self._dir()
        if not d:
            return
        rounds = self.stab_rounds.currentData()
        self._log(f"--- Проверка стабильности ({rounds} проб, обход не останавливается) ---")
        self.b_stab.setEnabled(False)
        self.stab_rounds.setEnabled(False)
        self.b_stab_cancel.show()
        self.stab_progress.setRange(0, rounds)
        self.stab_progress.setValue(0)
        self.stab_verdict.setText("")
        self._stab_worker = StabilityWorker(d, rounds, self)
        self._stab_worker.log.connect(self._log)
        self._stab_worker.progress.connect(lambda v, t: self.stab_progress.setValue(v))
        self._stab_worker.done.connect(self._on_stab_done)
        self._stab_worker.error.connect(self._on_stab_error)
        self._stab_worker.start()

    def _cancel_stability(self):
        if getattr(self, "_stab_worker", None):
            self._stab_worker.cancel()

    def _stab_finished(self):
        self.b_stab.setEnabled(True)
        self.stab_rounds.setEnabled(True)
        self.b_stab_cancel.hide()

    def _on_stab_done(self, payload):
        self._stab_finished()
        rows, verdict = payload["rows"], payload["verdict"]
        self.stab_table.setRowCount(len(rows))
        for row, r in enumerate(rows):
            vals = [r["name"], f"{r['ok']}/{r['probes']}", r["loss"],
                    r["avg"] if r["avg"] is not None else "—",
                    r["min"] if r["min"] is not None else "—",
                    r["max"] if r["max"] is not None else "—",
                    r["jitter"] if r["jitter"] is not None else "—",
                    r["ping_avg"] if r["ping_avg"] is not None else "—"]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(str(v))
                if r["loss"] > 0 or (r["ping_loss"] or 0) > 0:
                    item.setBackground(QColor("#3a2222"))
                self.stab_table.setItem(row, col, item)
        ok = verdict.startswith("Стабильно")
        self.stab_verdict.setStyleSheet(
            f"color:{'#3fb950' if ok else '#f85149'}; font-weight:600;")
        self.stab_verdict.setText(verdict)
        self._log(verdict)

    def _on_stab_error(self, msg):
        self._stab_finished()
        self._log(f"[X] {msg}")