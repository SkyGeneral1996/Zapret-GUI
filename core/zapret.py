import os
import re
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

CREATE_NO_WINDOW = 0x08000000


def _run_hidden(args, timeout=15):
    return subprocess.run(
        args, capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout, creationflags=CREATE_NO_WINDOW,
    )


def find_zapret_dir(search_roots):
    """Look for a zapret-discord-youtube-* folder containing bin/winws.exe."""
    best = None
    best_ver = (0,)
    for root in search_roots:
        root = Path(root)
        if not root.is_dir():
            continue
        candidates = [root] if (root / "bin" / "winws.exe").exists() else []
        candidates += [p for p in root.glob("zapret-discord-youtube-*") if p.is_dir()]
        for c in candidates:
            if not (c / "bin" / "winws.exe").exists():
                continue
            ver = version_tuple(read_local_version(c) or "0")
            if ver >= best_ver:
                best, best_ver = c, ver
    return best


def version_tuple(v):
    parts = re.findall(r"\d+", str(v))
    return tuple(int(p) for p in parts) if parts else (0,)


def read_local_version(zapret_dir):
    """Version from service.bat LOCAL_VERSION, fallback to folder name."""
    zapret_dir = Path(zapret_dir)
    sb = zapret_dir / "service.bat"
    if sb.exists():
        try:
            text = sb.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'LOCAL_VERSION=([0-9][0-9.]*)', text)
            if m:
                return m.group(1)
        except OSError:
            pass
    m = re.search(r"zapret-discord-youtube-([0-9][0-9.]*)", zapret_dir.name)
    return m.group(1) if m else ""


def _natural_key(name):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def list_strategies(zapret_dir):
    zapret_dir = Path(zapret_dir)
    bats = [p.name for p in zapret_dir.glob("*.bat")
            if not p.name.lower().startswith("service")]
    return sorted(bats, key=_natural_key)


def read_game_filter(zapret_dir):
    """Return (mode, tcp_range, udp_range) from utils/game_filter.enabled."""
    flag = Path(zapret_dir) / "utils" / "game_filter.enabled"
    mode, tcp, udp = "disabled", "1024-65535", "1024-65535"
    if flag.exists():
        try:
            for line in flag.read_text(encoding="utf-8", errors="ignore").splitlines():
                if "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k, v = k.strip().lower(), v.strip()
                if k == "mode":
                    mode = v or "disabled"
                elif k == "tcp" and v:
                    tcp = v
                elif k == "udp" and v:
                    udp = v
                elif k == "all":
                    mode = "all"
        except OSError:
            pass
    return mode, tcp, udp


def game_filter_ports(zapret_dir):
    mode, tcp, udp = read_game_filter(zapret_dir)
    if mode == "all":
        return tcp, udp
    if mode == "tcp":
        return tcp, "12"
    if mode == "udp":
        return "12", udp
    return "12", "12"


def set_game_filter(zapret_dir, mode):
    utils = Path(zapret_dir) / "utils"
    utils.mkdir(parents=True, exist_ok=True)
    flag = utils / "game_filter.enabled"
    _, tcp, udp = read_game_filter(zapret_dir)
    if mode == "disabled":
        flag.write_text(f"mode=disabled\ntcp={tcp}\nudp={udp}\n", encoding="utf-8")
    else:
        flag.write_text(f"mode={mode}\ntcp={tcp}\nudp={udp}\n", encoding="utf-8")


def ensure_user_lists(zapret_dir):
    lists = Path(zapret_dir) / "lists"
    lists.mkdir(parents=True, exist_ok=True)
    defaults = {
        "ipset-exclude-user.txt": "203.0.113.113/32\n",
        "list-general-user.txt": "# Never leave this file empty\ndomain.example.abc\n",
        "list-exclude-user.txt": "domain.example.abc\n",
    }
    for name, content in defaults.items():
        p = lists / name
        if not p.exists():
            p.write_text(content, encoding="utf-8")


def enable_tcp_timestamps():
    try:
        _run_hidden(["netsh", "interface", "tcp", "set", "global", "timestamps=enabled"])
    except Exception:
        pass


def is_winws_running():
    try:
        r = _run_hidden(["tasklist", "/FI", "IMAGENAME eq winws.exe", "/NH"])
        return "winws.exe" in r.stdout.lower()
    except Exception:
        return False


def kill_winws():
    try:
        _run_hidden(["taskkill", "/IM", "winws.exe", "/F"])
    except Exception:
        pass


def is_zapret_service_running():
    try:
        r = _run_hidden(["sc", "query", "zapret"])
        return r.returncode == 0 and "RUNNING" in r.stdout
    except Exception:
        return False


def _split_args(s):
    """Tokenize a Windows command tail: split on whitespace outside quotes,
    drop quote chars, preserve backslashes and spaces inside quoted paths."""
    args, cur, in_q = [], [], False
    for ch in s:
        if ch == '"':
            in_q = not in_q
            continue
        if ch.isspace() and not in_q:
            if cur:
                args.append("".join(cur))
                cur = []
        else:
            cur.append(ch)
    if cur:
        args.append("".join(cur))
    return [a for a in args if a and a != "^"]


def parse_strategy(zapret_dir, bat_name):
    """Extract winws.exe argument list from a strategy .bat file."""
    zapret_dir = Path(zapret_dir)
    text = (zapret_dir / bat_name).read_text(encoding="utf-8", errors="ignore")
    m = re.search(r'"[^"]*winws\.exe"|\S*winws\.exe', text, re.IGNORECASE)
    if not m:
        raise ValueError(f"winws.exe not found in {bat_name}")
    tail = text[m.end():]
    # join caret-continued lines into one logical command line
    tail = re.sub(r"\^\s*\r?\n\s*", " ", tail)
    tail = re.split(r"\r?\n", tail)[0]
    # unfold inline cmd caret escapes (e.g. ^! -> !); paths contain no '^'
    tail = re.sub(r"\^(.)", r"\1", tail)

    bin_path = str(zapret_dir / "bin") + "\\"
    lists_path = str(zapret_dir / "lists") + "\\"
    gf_tcp, gf_udp = game_filter_ports(zapret_dir)
    repl = {
        "%BIN%": bin_path,
        "%LISTS%": lists_path,
        "%GameFilterTCP%": gf_tcp,
        "%GameFilterUDP%": gf_udp,
        "%~dp0": str(zapret_dir) + "\\",
    }
    for k, v in repl.items():
        tail = tail.replace(k, v)

    args = _split_args(tail)
    return str(zapret_dir / "bin" / "winws.exe"), args


class WinwsRunner(QObject):
    output = Signal(str)
    started = Signal()
    stopped = Signal(int)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._proc = QProcess(self)
        self._proc.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        self._proc.readyReadStandardOutput.connect(self._on_output)
        self._proc.started.connect(self.started)
        self._proc.finished.connect(self._on_finished)
        self._proc.errorOccurred.connect(self._on_error)
        self._buffer = ""

    def is_running(self):
        return self._proc.state() != QProcess.ProcessState.NotRunning

    def start(self, zapret_dir, bat_name):
        exe, args = parse_strategy(zapret_dir, bat_name)
        self._proc.setWorkingDirectory(str(Path(zapret_dir) / "bin"))
        self._proc.setProgram(exe)
        self._proc.setArguments(args)
        self._proc.start()

    def stop(self):
        if self.is_running():
            self._proc.kill()
            self._proc.waitForFinished(3000)

    def _on_output(self):
        data = bytes(self._proc.readAllStandardOutput())
        text = data.decode("utf-8", errors="replace")
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self.output.emit(line.rstrip("\r"))
        if self._buffer:
            self.output.emit(self._buffer)
            self._buffer = ""

    def _on_finished(self, code, _status):
        self.stopped.emit(code)

    def _on_error(self, err):
        if err == QProcess.ProcessError.FailedToStart:
            self.error.emit("Не удалось запустить winws.exe")