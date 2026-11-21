import os
import re
import socket
import ssl
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from core import zapret

CREATE_NO_WINDOW = 0x08000000
UA = "ZapretGUI-tests"

DEFAULT_TARGETS = [
    ("Discord Main", "https://discord.com"),
    ("Discord Gateway", "https://gateway.discord.gg"),
    ("Discord CDN", "https://cdn.discordapp.com"),
    ("Discord Updates", "https://updates.discord.com"),
    ("YouTube Web", "https://www.youtube.com"),
    ("YouTube Short", "https://youtu.be"),
    ("YouTube Image", "https://i.ytimg.com"),
    ("YouTube Video Redirect", "https://redirector.googlevideo.com"),
    ("Google Main", "https://www.google.com"),
    ("Google Gstatic", "https://www.gstatic.com"),
    ("Cloudflare Web", "https://www.cloudflare.com"),
    ("Cloudflare CDN", "https://cdnjs.cloudflare.com"),
    ("Cloudflare DNS 1.1.1.1", "PING:1.1.1.1"),
    ("Cloudflare DNS 1.0.0.1", "PING:1.0.0.1"),
    ("Google DNS 8.8.8.8", "PING:8.8.8.8"),
    ("Google DNS 8.8.4.4", "PING:8.8.4.4"),
    ("Quad9 DNS 9.9.9.9", "PING:9.9.9.9"),
]


def debug_dir():
    base = os.environ.get("APPDATA") or tempfile.gettempdir()
    return Path(base) / "ZapretGUI" / "debug"


def load_targets(zapret_dir):
    f = Path(zapret_dir) / "utils" / "targets.txt"
    pairs = []
    if f.exists():
        for line in f.read_text(encoding="utf-8", errors="ignore").splitlines():
            m = re.match(r'^\s*(\w+)\s*=\s*"(.+)"\s*$', line)
            if m:
                pairs.append((m.group(1), m.group(2)))
    if not pairs:
        pairs = list(DEFAULT_TARGETS)
    targets = []
    for name, value in pairs:
        if value.startswith("PING:"):
            targets.append({"name": name, "url": None, "ping": value[5:].strip()})
        else:
            host = re.sub(r"^https?://", "", value)
            host = re.sub(r"/.*$", "", host)
            targets.append({"name": name, "url": value, "ping": host})
    return targets


def _ssl_context(tls):
    ctx = ssl.create_default_context()
    if tls == "TLS1.2":
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.maximum_version = ssl.TLSVersion.TLSv1_2
    elif tls == "TLS1.3":
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.maximum_version = ssl.TLSVersion.TLSv1_3
    return ctx


def check_url(url, tls, timeout=4):
    ctx = _ssl_context(tls)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx):
            return "OK"
    except urllib.error.HTTPError:
        return "OK"  # got an HTTP response => reachable
    except ssl.SSLCertVerificationError:
        return "SSL"
    except ssl.SSLError as e:
        msg = str(e).lower()
        if "protocol" in msg or "unsupported" in msg or "no protocols" in msg:
            return "UNSUP"
        return "SSL"
    except (urllib.error.URLError, socket.timeout, OSError):
        return "ERROR"


def ping_ms(host, timeout=1000):
    try:
        r = subprocess.run(["ping", "-n", "1", "-w", str(timeout), host],
                           capture_output=True, timeout=5, creationflags=CREATE_NO_WINDOW)
        out = r.stdout.decode("cp866", errors="replace")
        nums = re.findall(r"=\s*(\d+)\s*(?:ms|мс)", out)
        return int(nums[-1]) if nums else None
    except Exception:
        return None


def _wait_winws_gone(timeout=2.0):
    # WinDivert needs a moment to release the device after a kill,
    # otherwise the next winws exits immediately.
    deadline = time.time() + timeout
    while zapret.is_winws_running() and time.time() < deadline:
        time.sleep(0.1)


def run_config(zapret_dir, bat, targets, cancel=None, log=None, winws_log=None):
    zapret.kill_winws()
    _wait_winws_gone()
    exe, args = zapret.parse_strategy(zapret_dir, bat)
    detail = [f"cmd: {exe} " + " ".join(args)]
    out = (open(winws_log, "w", encoding="utf-8", errors="replace")
           if winws_log else subprocess.DEVNULL)
    if winws_log:
        detail.append(f"winws output: {winws_log}")
    proc = subprocess.Popen(
        [exe] + args, cwd=str(Path(zapret_dir) / "bin"),
        stdout=out, stderr=out, creationflags=CREATE_NO_WINDOW,
    )
    tally = {"ok": 0, "err": 0, "ssl": 0, "unsup": 0, "ping_ok": 0, "ping_fail": 0}
    started, exit_code = True, None
    t0 = time.perf_counter()
    try:
        deadline = time.time() + 3
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            if zapret.is_winws_running():
                break
            time.sleep(0.2)
        if proc.poll() is not None:
            started, exit_code = False, proc.returncode
            detail.append(f"winws exited immediately, code {exit_code}")
        else:
            time.sleep(0.8)
            if proc.poll() is not None:
                started, exit_code = False, proc.returncode
                detail.append(f"winws exited before checks, code {exit_code}")
            else:
                detail.append(f"winws pid {proc.pid} alive, checks starting")
                for t in targets:
                    if cancel and cancel():
                        raise InterruptedError()
                    if t["url"]:
                        for tls in ("HTTP", "TLS1.2", "TLS1.3"):
                            ts = time.perf_counter()
                            st = check_url(t["url"], tls)
                            ms = int((time.perf_counter() - ts) * 1000)
                            key = {"OK": "ok", "ERROR": "err",
                                   "SSL": "ssl", "UNSUP": "unsup"}[st]
                            tally[key] += 1
                            detail.append(f"{t['name']} {tls}: {st} ({ms} ms)")
                    if t["ping"]:
                        ts = time.perf_counter()
                        ms = ping_ms(t["ping"])
                        elapsed = int((time.perf_counter() - ts) * 1000)
                        if ms is None:
                            tally["ping_fail"] += 1
                        else:
                            tally["ping_ok"] += 1
                        detail.append(f"{t['name']} ping: "
                                      f"{ms if ms is not None else 'timeout'} ({elapsed} ms)")
                exit_code = proc.poll()
                if exit_code is not None:
                    started = False
                    detail.append(f"winws exited DURING checks, code {exit_code}")
                else:
                    detail.append(f"winws pid {proc.pid} still alive after checks")
        return {"config": bat, **tally, "started": started,
                "seconds": round(time.perf_counter() - t0, 1),
                "winws_exit": exit_code, "detail": detail}
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=5)
        if winws_log:
            out.close()
        zapret.kill_winws()


def best_of(results):
    best, best_score, best_ping = None, -1, -1
    for r in results:
        if not r.get("started", True):
            continue
        score, ping = r["ok"], r["ping_ok"]
        if score > best_score or (score == best_score and ping > best_ping):
            best, best_score, best_ping = r["config"], score, ping
    return best


def run_tests(zapret_dir, configs, targets=None, log=None, progress=None,
              cancel=None, debug=False):
    targets = targets or load_targets(zapret_dir)
    ddir = debug_dir()
    ddir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dbg_file = ddir / f"tests_{stamp}.log"
    lines = []

    def dbg(msg):
        lines.append(msg)
        if debug and log:
            log(msg)

    results = []
    total = len(configs)
    try:
        for i, bat in enumerate(configs):
            if cancel and cancel():
                raise InterruptedError()
            if log:
                log(f"[{i + 1}/{total}] Тест стратегии: {bat}")
            wl = ddir / f"winws_{stamp}_{i + 1}_{Path(bat).stem}.log"
            r = run_config(zapret_dir, bat, targets, cancel=cancel, winws_log=str(wl))
            results.append(r)
            if log:
                log(f"  OK={r['ok']} ERR={r['err']} SSL={r['ssl']} UNSUP={r['unsup']} "
                    f"PingOK={r['ping_ok']} PingFail={r['ping_fail']} "
                    f"за {r['seconds']} с"
                    + ("" if r["started"] else "  [winws НЕ работал — результат недостоверен]"))
            dbg(f"=== {bat} ({r['seconds']} s, started={r['started']}, "
                f"winws_exit={r['winws_exit']}) ===")
            for d in r["detail"]:
                dbg("  " + d)
            if progress:
                progress(i + 1, total)
    finally:
        zapret.kill_winws()
        dbg_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
        if log:
            log(f"Лог отладки: {dbg_file}")
    return results, best_of(results)