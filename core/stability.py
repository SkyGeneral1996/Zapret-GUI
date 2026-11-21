import json
import math
import time

from core import tests


def pick_targets(zapret_dir):
    targets = tests.load_targets(zapret_dir)
    urls = [t for t in targets if t["url"]][:8]
    pings = [t for t in targets if not t["url"]][:4]
    return urls, pings


def _stats(ms):
    if not ms:
        return None, None, None, None
    avg = sum(ms) / len(ms)
    jitter = math.sqrt(sum((x - avg) ** 2 for x in ms) / len(ms))
    return round(avg, 1), round(min(ms), 1), round(max(ms), 1), round(jitter, 1)


def run_stability(zapret_dir, rounds=10, interval=2.0, cancel=None, log=None, progress=None):
    """Repeated probes of main consumers while the bypass keeps running."""
    urls, pings = pick_targets(zapret_dir)
    stats = {}

    def rec(name):
        return stats.setdefault(name, {"ok": 0, "fail": 0, "ms": [],
                                       "ping_ok": 0, "ping_fail": 0, "ping_ms": []})

    for r in range(rounds):
        if cancel and cancel():
            raise InterruptedError()
        if log:
            log(f"Проба {r + 1}/{rounds} ...")
        for t in urls:
            ts = time.perf_counter()
            st = tests.check_url(t["url"], "HTTP")
            ms = (time.perf_counter() - ts) * 1000
            s = rec(t["name"])
            if st == "OK":
                s["ok"] += 1
                s["ms"].append(ms)
            else:
                s["fail"] += 1
            if log:
                log(f"  {t['name']}: {st} {ms:.0f} ms")
        for t in pings:
            ms = tests.ping_ms(t["ping"])
            s = rec(t["name"])
            if ms is None:
                s["ping_fail"] += 1
            else:
                s["ping_ok"] += 1
                s["ping_ms"].append(ms)
        if progress:
            progress(r + 1, rounds)
        if r + 1 < rounds:
            end = time.time() + interval
            while time.time() < end:
                if cancel and cancel():
                    raise InterruptedError()
                time.sleep(0.2)

    rows = []
    for name, s in stats.items():
        probes = s["ok"] + s["fail"]
        avg, mn, mx, jitter = _stats(s["ms"])
        pavg, _, _, _ = _stats(s["ping_ms"])
        ping_probes = s["ping_ok"] + s["ping_fail"]
        rows.append({
            "name": name, "probes": probes, "ok": s["ok"],
            "loss": round(100 * s["fail"] / probes, 1) if probes else 0.0,
            "avg": avg, "min": mn, "max": mx, "jitter": jitter,
            "ping_avg": pavg,
            "ping_loss": round(100 * s["ping_fail"] / ping_probes, 1) if ping_probes else None,
        })
    bad = [r["name"] for r in rows if r["loss"] > 0 or (r["ping_loss"] or 0) > 0]
    verdict = ("Стабильно: потерь нет" if not bad
               else "Нестабильно: потери у " + ", ".join(bad))
    payload = {"rounds": rounds, "interval": interval, "rows": rows, "verdict": verdict}
    try:
        f = tests.debug_dir() / f"stability_{time.strftime('%Y%m%d_%H%M%S')}.json"
        f.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        if log:
            log(f"Отчёт стабильности: {f}")
    except Exception:
        pass
    return rows, verdict