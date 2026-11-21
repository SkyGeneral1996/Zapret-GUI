import pytest

from core import github, zapret
from ui.manager_tab import GameFilterDialog

GENERAL_BAT = """@echo off
chcp 65001 >nul
cd /d "%~dp0bin"
start "" /min "%~dp0bin\\winws.exe" ^
 --wf-tcp=80,443 ^
 --wf-udp=443 ^
 --dpi-desync=fake,multidisorder ^
 --dpi-desync-fake-tls=^! ^
 --dpi-desync-split-pos=1 ^
 --ipset="%LISTS%ipset-all.txt"
"""


@pytest.fixture
def zapret_dir(tmp_path):
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "winws.exe").write_bytes(b"")
    (tmp_path / "lists").mkdir()
    (tmp_path / "utils").mkdir()
    (tmp_path / "service.bat").write_text(
        '@echo off\nset "LOCAL_VERSION=1.10.4"\n', encoding="utf-8")
    (tmp_path / "general.bat").write_text(GENERAL_BAT, encoding="utf-8")
    (tmp_path / "general ALT2.bat").write_text(GENERAL_BAT, encoding="utf-8")
    (tmp_path / "general ALT11.bat").write_text(GENERAL_BAT, encoding="utf-8")
    return tmp_path


def test_parse_strategy_args(zapret_dir):
    exe, args = zapret.parse_strategy(zapret_dir, "general.bat")
    assert exe == str(zapret_dir / "bin" / "winws.exe")
    assert "--wf-tcp=80,443" in args
    assert "--wf-udp=443" in args
    assert "--dpi-desync=fake,multidisorder" in args
    assert "--dpi-desync-fake-tls=!" in args
    assert "--dpi-desync-split-pos=1" in args
    assert any(a.startswith("--ipset=") and a.endswith("ipset-all.txt") for a in args)
    assert all("^" not in a for a in args)
    assert all("%" not in a for a in args)


def test_parse_strategy_keeps_backslashes(zapret_dir):
    _, args = zapret.parse_strategy(zapret_dir, "general.bat")
    ipset = next(a for a in args if a.startswith("--ipset="))
    assert "\\" in ipset


def test_list_strategies_natural_sort(zapret_dir):
    names = zapret.list_strategies(zapret_dir)
    assert "service.bat" not in names
    assert names.index("general ALT2.bat") < names.index("general ALT11.bat")


def test_read_local_version(zapret_dir):
    assert zapret.read_local_version(zapret_dir) == "1.10.4"


def test_read_local_version_from_folder_name(tmp_path):
    d = tmp_path / "zapret-discord-youtube-1.9.9"
    d.mkdir()
    assert zapret.read_local_version(d) == "1.9.9"


def test_version_compare():
    assert github.is_newer("1.10.4", "1.10.3")
    assert github.is_newer("v1.2.0", "1.1.9")
    assert not github.is_newer("1.10.4", "1.10.4")
    assert not github.is_newer("1.9.9", "1.10.0")
    assert github.normalize_version("v1.2.0") == "1.2.0"
    assert github.version_tuple("1.2.0") == (1, 2, 0)


def test_game_filter_ranges():
    valid = GameFilterDialog._valid_range
    assert valid("1024-65535")
    assert valid("1024-1934,1936-65535")
    assert valid("443")
    assert not valid("")
    assert not valid("0-100")
    assert not valid("100-99")
    assert not valid("70000")
    assert not valid("abc")
    assert not valid("1-2-3")


def test_load_targets(zapret_dir):
    from core import tests
    (zapret_dir / "utils" / "targets.txt").write_text(
        'Discord="https://discord.com"\nDNS="PING:1.1.1.1"\n', encoding="utf-8")
    targets = tests.load_targets(zapret_dir)
    assert targets[0] == {"name": "Discord", "url": "https://discord.com",
                          "ping": "discord.com"}
    assert targets[1] == {"name": "DNS", "url": None, "ping": "1.1.1.1"}


def test_load_targets_defaults(zapret_dir):
    from core import tests
    targets = tests.load_targets(zapret_dir)
    assert len(targets) == len(tests.DEFAULT_TARGETS)


def test_commandline_parse(zapret_dir):
    exe = str(zapret_dir / "bin" / "winws.exe")
    cmd = f'"{exe}" --wf-tcp=443 --dpi-desync-fake-tls=!'
    parsed = zapret.parse_commandline(cmd)
    assert parsed == (exe, ["--wf-tcp=443", "--dpi-desync-fake-tls=!"])
    assert zapret.parse_commandline("not a winws line") is None