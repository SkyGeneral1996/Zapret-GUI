import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

from core import github
from version import ZAPRET_REPO

CREATE_NO_WINDOW = 0x08000000

# Same source the original service.bat uses for its update check.
ZAPRET_MAIN_VERSION_URL = (
    f"https://raw.githubusercontent.com/{ZAPRET_REPO}/main/.service/version.txt"
)

# Files preserved across a zapret upgrade (user data / settings).
USER_LISTS = [
    "lists/list-general-user.txt",
    "lists/list-exclude-user.txt",
    "lists/ipset-exclude-user.txt",
    "lists/ipset-all.txt",
    "lists/ipset-all.txt.backup",
]
USER_UTILS = [
    "utils/game_filter.enabled",
    "utils/check_updates.enabled",
    "utils/targets.txt",
]


def fetch_zapret_main_version():
    """Version published on the main branch, exactly like service.bat does."""
    req = urllib.request.Request(ZAPRET_MAIN_VERSION_URL, headers={
        "User-Agent": github.UA,
        "Cache-Control": "no-cache",
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("utf-8", errors="replace").strip() or None
    except Exception:
        return None


def check_zapret_update(local_version):
    """Original zapret check: main-branch version.txt vs LOCAL_VERSION.

    Returns an installable Release when the release archive is already out,
    otherwise a Release without assets (version announced, release pending).
    """
    local = local_version or "0"
    main_ver = fetch_zapret_main_version()
    if not main_ver or not github.is_newer(main_ver, local):
        return None
    try:
        rel = github.get_latest_release(ZAPRET_REPO)
    except Exception:
        rel = None
    if rel and github.is_newer(rel.version, local) and github.pick_asset(rel, ".zip"):
        return rel
    return github.Release(
        tag=main_ver,
        version=main_ver,
        url=f"https://github.com/{ZAPRET_REPO}/releases/latest",
        notes="Версия уже опубликована в main, но релиз с архивом ещё не вышел.",
        assets=[],
    )


def check_app_update(repo, local_version):
    if not repo:
        return None
    rel = github.get_latest_release(repo)
    if rel and github.is_newer(rel.version, local_version):
        if github.pick_asset(rel, ".exe"):
            return rel
    return None


def _find_extracted_root(extract_dir):
    extract_dir = Path(extract_dir)
    if (extract_dir / "bin" / "winws.exe").exists():
        return extract_dir
    for sub in extract_dir.iterdir():
        if sub.is_dir() and (sub / "bin" / "winws.exe").exists():
            return sub
    raise FileNotFoundError("bin/winws.exe not found in archive")


def _fetch_and_extract(release, progress=None, cancel=None, log=None):
    asset = github.pick_asset(release, ".zip")
    if not asset:
        raise FileNotFoundError("В релизе нет .zip архива")

    def _log(msg):
        if log:
            log(msg)

    tmp = Path(tempfile.mkdtemp(prefix="zapret_upd_"))
    zip_path = tmp / asset["name"]
    _log(f"Скачивание {asset['name']} ...")
    github.download(asset["url"], zip_path, progress=progress, cancel=cancel)

    _log("Распаковка ...")
    extract_dir = tmp / "extracted"
    extract_dir.mkdir()
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extract_dir, filter="data")
    return tmp, _find_extracted_root(extract_dir)


def install_zapret_fresh(release, dest_root, progress=None, cancel=None, log=None):
    """First-time download: extract zapret into dest_root (project folder)."""
    dest_root = Path(dest_root)
    dest_root.mkdir(parents=True, exist_ok=True)
    tmp, new_root = _fetch_and_extract(release, progress, cancel, log)
    try:
        target = dest_root / new_root.name
        if target.exists():
            raise FileExistsError(f"Папка уже существует: {target}")
        if log:
            log("Установка ...")
        shutil.move(str(new_root), str(target))
        if log:
            log(f"Готово: {target}")
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_zapret_update(release, old_dir, progress=None, cancel=None, log=None):
    """Download + extract new zapret next to old_dir, migrate user data.

    Returns the new zapret directory Path. Old folder is left intact.
    """
    old_dir = Path(old_dir)
    tmp, new_root = _fetch_and_extract(release, progress, cancel, log)
    try:
        target = old_dir.parent / new_root.name
        if target.exists():
            raise FileExistsError(f"Папка уже существует: {target}")

        if log:
            log("Установка новой версии ...")
        shutil.move(str(new_root), str(target))

        if log:
            log("Перенос пользовательских списков и настроек ...")
        for rel_path in USER_LISTS + USER_UTILS:
            src = old_dir / rel_path
            if src.exists():
                dst = target / rel_path
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        # carry over any custom strategy bats the user added
        for bat in old_dir.glob("*.bat"):
            if not (target / bat.name).exists():
                shutil.copy2(bat, target / bat.name)

        if log:
            log(f"Готово: {target.name}")
        return target
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def is_frozen():
    return getattr(sys, "frozen", False)


def install_app_update(release, progress=None, cancel=None, log=None):
    """Download new exe and stage a swap script. Returns script path to run.

    Only works for a frozen (PyInstaller) build. Caller must quit the app
    and launch the returned .bat, which waits for exit, replaces the exe
    and relaunches it.
    """
    if not is_frozen():
        raise RuntimeError("Самообновление доступно только в собранном .exe")

    def _log(msg):
        if log:
            log(msg)

    asset = github.pick_asset(release, ".exe")
    if not asset:
        raise FileNotFoundError("В релизе нет .exe файла")

    exe_path = Path(sys.executable).resolve()
    new_path = exe_path.with_name(exe_path.stem + "_new.exe")

    _log(f"Скачивание {asset['name']} ...")
    github.download(asset["url"], new_path, progress=progress, cancel=cancel)

    pid = os.getpid()
    exe_name = exe_path.name
    script = Path(tempfile.gettempdir()) / "zapret_gui_selfupdate.bat"
    lines = [
        "@echo off",
        "setlocal",
        f'set "TARGET={exe_path}"',
        f'set "NEW={new_path}"',
        ":wait",
        f'tasklist /FI "PID eq {pid}" /NH 2>nul | find /I "{exe_name}" >nul',
        "if not errorlevel 1 (",
        "  ping -n 2 127.0.0.1 >nul",
        "  goto wait",
        ")",
        'move /y "%NEW%" "%TARGET%" >nul',
        'start "" "%TARGET%"',
        'del "%~f0"',
    ]
    script.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    _log("Подготовка перезапуска ...")
    return script


def launch_swap_script(script):
    subprocess.Popen(
        ["cmd", "/c", str(script)],
        creationflags=CREATE_NO_WINDOW,
        close_fds=True,
    )