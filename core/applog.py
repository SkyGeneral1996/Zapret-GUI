import os
import tempfile
import time
from pathlib import Path

MAX_BYTES = 1_000_000
KEEP = 3


def data_dir():
    base = os.environ.get("APPDATA") or tempfile.gettempdir()
    d = Path(base) / "ZapretGUI"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write(tag, msg):
    try:
        p = data_dir() / "app.log"
        if p.exists() and p.stat().st_size > MAX_BYTES:
            for i in range(KEEP - 1, 0, -1):
                src = p.with_name(f"app.log.{i}")
                if src.exists():
                    src.replace(p.with_name(f"app.log.{i + 1}"))
            p.replace(p.with_name("app.log.1"))
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{tag}] {msg}\n")
    except Exception:
        pass