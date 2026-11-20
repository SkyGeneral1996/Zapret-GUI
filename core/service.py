import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from core import github
from version import ZAPRET_REPO

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_CONSOLE = 0x00000010
RAW = f"https://raw.githubusercontent.com/{ZAPRET_REPO}/refs/heads/main/.service/"
REG_KEY = r"HKLM\System\CurrentControlSet\Services\zapret"
REG_VAL = "zapret-discord-youtube"


def _run(args, timeout=30):
    return subprocess.run(args, capture_output=True, text=True,
                          encoding="utf-8", errors="replace",
                          timeout=timeout, creationflags=CREATE_NO_WINDOW)


def _sc_query(name):
    try:
        r = _run(["sc", "query", name])
        if r.returncode != 0:
            return None
        m = re.search(r"STATE\s*:\s*\d+\s+(\w+)", r.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


# ---------- service ----------
def installed_strategy():
    try:
        r = _run(["reg", "query", REG_KEY, "/v", REG_VAL])
        if r.returncode != 0:
            return ""
        m = re.search(r"REG_SZ\s+(.+)", r.stdout)
        return m.group(1).strip() if m else ""
    except Exception:
        return ""


def install_service(zapret_dir, bat_name, log=None):
    from core import zapret
    zapret_dir = Path(zapret_dir)
    exe, args = zapret.parse_strategy(zapret_dir, bat_name)
    zapret.enable_tcp_timestamps()
    cmdline = subprocess.list2cmdline([exe] + args)

    def _log(m):
        if log:
            log(m)

    _run(["net", "stop", "zapret"])
    _run(["sc", "delete", "zapret"])
    r = _run(["sc", "create", "zapret", "binPath=", cmdline,
              "DisplayName=", "zapret", "start=", "auto"])
    if r.returncode != 0:
        raise RuntimeError(f"sc create failed: {r.stdout} {r.stderr}")
    _run(["sc", "description", "zapret", "Zapret DPI bypass software"])
    r = _run(["sc", "start", "zapret"])
    _run(["reg", "add", REG_KEY, "/v", REG_VAL, "/t", "REG_SZ", "/d", bat_name, "/f"])
    _log(f"Служба zapret установлена со стратегией {bat_name}")
    if r.returncode != 0:
        _log(f"Предупреждение: sc start вернул {r.returncode}: {r.stdout} {r.stderr}")


def remove_services(log=None):
    def _log(m):
        if log:
            log(m)
    if _sc_query("zapret") is not None:
        _run(["net", "stop", "zapret"])
        _run(["sc", "delete", "zapret"])
        _log("Служба zapret удалена")
    from core import zapret
    if zapret.is_winws_running():
        zapret.kill_winws()
    for name in ("WinDivert", "WinDivert14"):
        if _sc_query(name) is not None:
            _run(["net", "stop", name])
            _run(["sc", "delete", name])
            _log(f"Служба {name} удалена")


def service_status(zapret_dir):
    """Return list of (level, message) lines describing current status."""
    from core import zapret
    lines = []
    st = _sc_query("zapret")
    if st:
        lines.append(("ok", f"Служба zapret: {st}"))
        strat = installed_strategy()
        if strat:
            lines.append(("info", f"Стратегия службы: {strat}"))
    else:
        lines.append(("info", "Служба zapret не установлена"))
    wd = _sc_query("WinDivert")
    lines.append(("ok" if wd == "RUNNING" else "info",
                  f"Служба WinDivert: {wd or 'не установлена'}"))
    sys_file = Path(zapret_dir) / "bin" / "WinDivert64.sys"
    lines.append(("ok" if sys_file.exists() else "err",
                  "WinDivert64.sys на месте" if sys_file.exists() else "WinDivert64.sys НЕ найден"))
    lines.append(("ok" if zapret.is_winws_running() else "err",
                  "winws.exe ЗАПУЩЕН" if zapret.is_winws_running() else "winws.exe НЕ запущен"))
    return lines


# ---------- game filter ----------
def set_game_filter_ranges(zapret_dir, mode, tcp, udp):
    utils = Path(zapret_dir) / "utils"
    utils.mkdir(parents=True, exist_ok=True)
    (utils / "game_filter.enabled").write_text(
        f"mode={mode}\ntcp={tcp}\nudp={udp}\n", encoding="utf-8")


def game_filter_status(zapret_dir):
    from core import zapret
    mode, tcp, udp = zapret.read_game_filter(zapret_dir)
    if mode == "disabled":
        return "disabled"
    if mode == "all":
        return "enabled (TCP+UDP)"
    return f"enabled ({mode.upper()})"


# ---------- ipset ----------
def read_ipset_mode(zapret_dir):
    f = Path(zapret_dir) / "lists" / "ipset-all.txt"
    if not f.exists():
        return "any"
    text = f.read_text(encoding="utf-8", errors="ignore")
    if not text.strip():
        return "any"
    if "203.0.113.113/32" in text:
        return "none"
    return "loaded"


def switch_ipset(zapret_dir):
    """Cycle loaded -> none -> any -> loaded, like service.bat."""
    d = Path(zapret_dir) / "lists"
    f = d / "ipset-all.txt"
    backup = d / "ipset-all.txt.backup"
    mode = read_ipset_mode(zapret_dir)
    if mode == "loaded":
        if backup.exists():
            backup.unlink()
        if f.exists():
            shutil.move(str(f), str(backup))
        f.write_text("203.0.113.113/32\n", encoding="utf-8")
        return "none"
    if mode == "none":
        f.write_text("", encoding="utf-8")
        return "any"
    # any -> loaded
    if backup.exists():
        if f.exists():
            f.unlink()
        shutil.move(str(backup), str(f))
        return "loaded"
    raise RuntimeError("Нет backup для восстановления. Сначала обновите IPSet список.")


def update_ipset_list(zapret_dir, log=None):
    dest = Path(zapret_dir) / "lists" / "ipset-all.txt"
    dest.parent.mkdir(parents=True, exist_ok=True)
    github.download(RAW + "ipset-service.txt", dest)
    if log:
        log("IPSet список обновлён")


# ---------- auto-update check ----------
def autoupdate_enabled(zapret_dir):
    return (Path(zapret_dir) / "utils" / "check_updates.enabled").exists()


def toggle_autoupdate(zapret_dir):
    flag = Path(zapret_dir) / "utils" / "check_updates.enabled"
    if flag.exists():
        flag.unlink()
        return False
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text("ENABLED\n", encoding="utf-8")
    return True


# ---------- active fakes ----------
def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def get_fakes(zapret_dir):
    bin_dir = Path(zapret_dir) / "bin"
    fakes = []
    discord_cur = game_cur = "(не найден)"
    d_hash = g_hash = None
    da = bin_dir / "ACTIVE_DISCORD_UDP.bin"
    ga = bin_dir / "ACTIVE_GAME_UDP.bin"
    if da.exists():
        d_hash = _sha(da)
    if ga.exists():
        g_hash = _sha(ga)
    for p in sorted(bin_dir.glob("*.bin")):
        if p.name.startswith("ACTIVE_"):
            continue
        h = _sha(p)
        fakes.append(p.name)
        if d_hash and h == d_hash:
            discord_cur = p.stem
        if g_hash and h == g_hash:
            game_cur = p.stem
    return {"discord": discord_cur, "game": game_cur, "fakes": fakes}


def replace_fake(zapret_dir, kind, fake_name):
    bin_dir = Path(zapret_dir) / "bin"
    target = bin_dir / ("ACTIVE_DISCORD_UDP.bin" if kind == "discord" else "ACTIVE_GAME_UDP.bin")
    src = bin_dir / fake_name
    if not src.exists():
        raise FileNotFoundError(fake_name)
    shutil.copy2(src, target)


# ---------- hosts ----------
def update_hosts_file(zapret_dir, log=None):
    hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    tmp = Path(tempfile.gettempdir()) / "zapret_hosts.txt"
    github.download(RAW + "hosts", tmp)
    repo_lines = [l for l in tmp.read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    cur = hosts.read_text(encoding="utf-8", errors="ignore") if hosts.exists() else ""
    needs = False
    if repo_lines:
        if repo_lines[0] not in cur or repo_lines[-1] not in cur:
            needs = True
    if needs:
        subprocess.Popen(["notepad", str(tmp)], creationflags=CREATE_NEW_CONSOLE)
        subprocess.Popen(["explorer", f"/select,{hosts}"], creationflags=CREATE_NO_WINDOW)
        if log:
            log("Hosts требует обновления: открыт блокнот с новым файлом и папка hosts.")
        return "needs_update"
    tmp.unlink(missing_ok=True)
    if log:
        log("Hosts файл актуален")
    return "up_to_date"


# ---------- diagnostics ----------
def _svc_exists(substring):
    try:
        r = _run(["sc", "query"])
        return substring.lower() in r.stdout.lower()
    except Exception:
        return False


def diagnostics(zapret_dir):
    from core import zapret
    L = []
    ok, warn, err = "ok", "warn", "err"
    L.append((ok, f"Zapret установлен в: {zapret_dir}"))

    bfe = _sc_query("BFE")
    L.append((ok, "Base Filtering Engine работает") if bfe == "RUNNING"
             else (err, "Base Filtering Engine НЕ запущен (необходим для zapret)"))

    try:
        r = _run(["reg", "query", r"HKCU\Software\Microsoft\Windows\CurrentVersion\Internet Settings",
                  "/v", "ProxyEnable"])
        if "0x1" in r.stdout:
            L.append((warn, "Включён системный прокси — убедитесь, что он корректен"))
        else:
            L.append((ok, "Прокси выключен"))
    except Exception:
        L.append((ok, "Прокси выключен"))

    try:
        r = _run(["netsh", "interface", "tcp", "show", "global"])
        if re.search(r"timestamps\w*\s*:\s*enabled", r.stdout, re.I):
            L.append((ok, "TCP timestamps включены"))
        else:
            zapret.enable_tcp_timestamps()
            L.append((warn, "TCP timestamps были выключены — включены"))
    except Exception:
        pass

    try:
        r = _run(["tasklist", "/FI", "IMAGENAME eq AdguardSvc.exe", "/NH"])
        L.append((err, "Найден Adguard — может мешать Discord") if "adguardsvc" in r.stdout.lower()
                 else (ok, "Adguard не найден"))
    except Exception:
        pass

    for name, msg in (("Killer", "Killer конфликтует с zapret"),
                      ("SmartByte", "SmartByte конфликтует с zapret")):
        L.append((err, f"Службы {name} найдены: {msg}") if _svc_exists(name)
                 else (ok, f"{name} не найден"))
    if _svc_exists("Intel") and _svc_exists("Connectivity"):
        L.append((err, "Intel Connectivity Network Service конфликтует с zapret"))
    if _svc_exists("TracSrvWrapper") or _svc_exists("EPWD"):
        L.append((err, "Службы Check Point найдены — конфликтуют с zapret"))

    if re.search(r"[а-яА-ЯёЁ]", str(zapret_dir)):
        L.append((warn, "Путь содержит кириллицу — при проблемах перенесите zapret, напр. в C:\\zapret"))
    if os.environ.get("OneDrive") and str(zapret_dir).lower().startswith(os.environ["OneDrive"].lower()):
        L.append((err, "Zapret в папке OneDrive — перенесите в другую папку"))

    sys_file = Path(zapret_dir) / "bin" / "WinDivert64.sys"
    L.append((ok, "WinDivert64.sys на месте") if sys_file.exists() else (err, "WinDivert64.sys НЕ найден"))

    if _svc_exists("VPN HappService"):
        L.append((warn, "Найдены VPN-службы — некоторые VPN конфликтуют с zapret"))

    hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "drivers" / "etc" / "hosts"
    if hosts.exists():
        t = hosts.read_text(encoding="utf-8", errors="ignore").lower()
        if "youtube.com" in t or "youtu.be" in t:
            L.append((warn, "В hosts есть записи youtube — могут мешать доступу к YouTube"))

    winws_run = zapret.is_winws_running()
    wd = _sc_query("WinDivert")
    if not winws_run and wd in ("RUNNING", "STOP_PENDING"):
        L.append((warn, "winws не запущен, но WinDivert активен — возможен конфликт"))
    conflicts = [s for s in ("GoodbyeDPI", "discordfix_zapret", "winws1", "winws2") if _sc_query(s)]
    if conflicts:
        L.append((err, "Конфликтующие службы обхода: " + ", ".join(conflicts)))
    return L


def remove_conflicting_services(log=None):
    for s in ("GoodbyeDPI", "discordfix_zapret", "winws1", "winws2"):
        if _sc_query(s):
            _run(["net", "stop", s])
            _run(["sc", "delete", s])
            if log:
                log(f"Удалена конфликтующая служба: {s}")
    for name in ("WinDivert", "WinDivert14"):
        _run(["net", "stop", name])
        _run(["sc", "delete", name])


def clear_discord_cache(log=None):
    closed = False
    for proc, folder in (("Discord.exe", "discord"), ("DiscordPTB.exe", "discordptb"),
                         ("DiscordCanary.exe", "discordcanary"), ("DiscordDevelopment.exe", "discorddevelopment")):
        base = Path(os.environ.get("APPDATA", "")) / folder
        if not base.exists():
            continue
        try:
            r = _run(["tasklist", "/FI", f"IMAGENAME eq {proc}", "/NH"])
            if proc.lower() in r.stdout.lower():
                _run(["taskkill", "/IM", proc, "/F"])
                closed = True
        except Exception:
            pass
        for sub in ("Cache", "Code Cache", "GPUCache"):
            p = base / sub
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                if log:
                    log(f"Очищен кэш: {p}")
    if not closed and log:
        log("Установки Discord не найдены")