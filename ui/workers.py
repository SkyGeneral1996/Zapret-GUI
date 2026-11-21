import threading

from PySide6.QtCore import QThread, Signal

from core import github, updater, tests, stability
from version import APP_VERSION, ZAPRET_REPO


class CheckWorker(QThread):
    done = Signal(object)  # dict: zapret, app, errors

    def __init__(self, zapret_version, app_repo, mode="both", parent=None):
        super().__init__(parent)
        self._zapret_version = zapret_version
        self._app_repo = app_repo
        self._mode = mode

    def run(self):
        result = {"zapret": None, "app": None, "errors": []}
        if self._mode in ("both", "zapret"):
            try:
                result["zapret"] = updater.check_zapret_update(self._zapret_version)
            except Exception as e:
                result["errors"].append(f"zapret: {e}")
        if self._mode in ("both", "app") and self._app_repo:
            try:
                result["app"] = updater.check_app_update(self._app_repo, APP_VERSION)
            except Exception as e:
                result["errors"].append(f"приложение: {e}")
        self.done.emit(result)


class ZapretInstallWorker(QThread):
    progress = Signal(int, int)
    log = Signal(str)
    done = Signal(str)
    error = Signal(str)

    def __init__(self, release, old_dir, parent=None):
        super().__init__(parent)
        self._release = release
        self._old_dir = old_dir
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            new_dir = updater.install_zapret_update(
                self._release, self._old_dir,
                progress=lambda d, t: self.progress.emit(d, t),
                cancel=self._cancel.is_set,
                log=lambda m: self.log.emit(m),
            )
            self.done.emit(str(new_dir))
        except InterruptedError:
            self.error.emit("Обновление отменено")
        except Exception as e:
            self.error.emit(str(e))


class AppInstallWorker(QThread):
    progress = Signal(int, int)
    log = Signal(str)
    done = Signal(str)  # swap script path
    error = Signal(str)

    def __init__(self, release, parent=None):
        super().__init__(parent)
        self._release = release
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            script = updater.install_app_update(
                self._release,
                progress=lambda d, t: self.progress.emit(d, t),
                cancel=self._cancel.is_set,
                log=lambda m: self.log.emit(m),
            )
            self.done.emit(str(script))
        except InterruptedError:
            self.error.emit("Обновление отменено")
        except Exception as e:
            self.error.emit(str(e))


class ZapretSetupWorker(QThread):
    progress = Signal(int, int)
    log = Signal(str)
    done = Signal(str)  # new zapret dir
    error = Signal(str)

    def __init__(self, dest_root, parent=None):
        super().__init__(parent)
        self._dest = dest_root
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            rel = github.get_latest_release(ZAPRET_REPO)
            if not rel:
                raise RuntimeError("Не удалось получить последний релиз zapret")
            new_dir = updater.install_zapret_fresh(
                rel, self._dest,
                progress=lambda d, t: self.progress.emit(d, t),
                cancel=self._cancel.is_set,
                log=lambda m: self.log.emit(m),
            )
            self.done.emit(str(new_dir))
        except InterruptedError:
            self.error.emit("Загрузка отменена")
        except Exception as e:
            self.error.emit(str(e))


class TestWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    done = Signal(object)  # {"results": [...], "best": str}
    error = Signal(str)

    def __init__(self, zapret_dir, configs, debug=False, parent=None):
        super().__init__(parent)
        self._dir = zapret_dir
        self._configs = configs
        self._debug = debug
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            results, best = tests.run_tests(
                self._dir, self._configs,
                log=lambda m: self.log.emit(m),
                progress=lambda d, t: self.progress.emit(d, t),
                cancel=self._cancel.is_set,
                debug=self._debug,
            )
            self.done.emit({"results": results, "best": best})
        except InterruptedError:
            self.error.emit("Тесты отменены")
        except Exception as e:
            self.error.emit(str(e))


class StabilityWorker(QThread):
    log = Signal(str)
    progress = Signal(int, int)
    done = Signal(object)  # {"rows": [...], "verdict": str}
    error = Signal(str)

    def __init__(self, zapret_dir, rounds, parent=None):
        super().__init__(parent)
        self._dir = zapret_dir
        self._rounds = rounds
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    def run(self):
        try:
            rows, verdict = stability.run_stability(
                self._dir, rounds=self._rounds,
                log=lambda m: self.log.emit(m),
                progress=lambda d, t: self.progress.emit(d, t),
                cancel=self._cancel.is_set,
            )
            self.done.emit({"rows": rows, "verdict": verdict})
        except InterruptedError:
            self.error.emit("Проверка стабильности отменена")
        except Exception as e:
            self.error.emit(str(e))