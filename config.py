import json
import os
from pathlib import Path

from version import APP_REPO_DEFAULT

CONFIG_DIR = Path(os.environ.get("APPDATA", Path.home())) / "ZapretGUI"
CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULTS = {
    "zapret_dir": "",
    "strategy": "general.bat",
    "app_repo": APP_REPO_DEFAULT,
    "auto_check_updates": True,
    "minimize_to_tray": True,
    "start_minimized": False,
}


class Config:
    def __init__(self):
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                stored = json.load(f)
            for k in DEFAULTS:
                if k in stored:
                    self._data[k] = stored[k]
        except (OSError, ValueError):
            pass

    def save(self):
        try:
            CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def __getattr__(self, name):
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def get(self, name, default=None):
        return self._data.get(name, default)