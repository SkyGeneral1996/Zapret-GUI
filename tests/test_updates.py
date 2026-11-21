import json

import pytest

import config as config_mod
from core import github, updater
from version import APP_REPO_DEFAULT, ZAPRET_REPO

EXE = {"name": "ZapretGUI.exe", "size": 1, "url": "x"}
ZIP = {"name": "zapret.zip", "size": 1, "url": "x"}


def rel(version, assets=()):
    return github.Release(tag="v" + version, version=version, url="u", notes="", assets=list(assets))


@pytest.mark.parametrize("raw,expect", [
    ("SkyGeneral1996/Zapret-GUI", "SkyGeneral1996/Zapret-GUI"),
    ("https://github.com/SkyGeneral1996/Zapret-GUI", "SkyGeneral1996/Zapret-GUI"),
    ("https://github.com/SkyGeneral1996/Zapret-GUI/", "SkyGeneral1996/Zapret-GUI"),
    ("https://github.com/SkyGeneral1996/Zapret-GUI.git", "SkyGeneral1996/Zapret-GUI"),
    ("  owner/repo  ", "owner/repo"),
    ("https://github.com/Flowseal/zapret-discord-youtube", "Flowseal/zapret-discord-youtube"),
    ("", ""),
    ("github.com/owner/repo", ""),
    ("owner", ""),
])
def test_normalize_repo(raw, expect):
    assert github.normalize_repo(raw) == expect


def test_get_latest_release_invalid_repo_no_network():
    assert github.get_latest_release("nonsense") is None


def test_check_app_update_newer_with_exe(monkeypatch):
    monkeypatch.setattr(github, "get_latest_release", lambda repo: rel("9.9.9", [EXE]))
    r = updater.check_app_update(APP_REPO_DEFAULT, "1.0.0")
    assert r and r.version == "9.9.9"


def test_check_app_update_newer_without_exe(monkeypatch):
    monkeypatch.setattr(github, "get_latest_release", lambda repo: rel("9.9.9", [ZIP]))
    assert updater.check_app_update(APP_REPO_DEFAULT, "1.0.0") is None


def test_check_app_update_older(monkeypatch):
    monkeypatch.setattr(github, "get_latest_release", lambda repo: rel("1.0.0", [EXE]))
    assert updater.check_app_update(APP_REPO_DEFAULT, "9.9.9") is None


def test_check_app_update_empty_repo():
    assert updater.check_app_update("", "1.0.0") is None


def test_check_app_update_accepts_url(monkeypatch):
    seen = {}

    def fake(repo):
        seen["repo"] = repo
        return rel("9.9.9", [EXE])

    monkeypatch.setattr(github, "get_latest_release", fake)
    r = updater.check_app_update("https://github.com/o/r", "1.0.0")
    assert seen["repo"] == "o/r" and r


def test_check_zapret_update_release(monkeypatch):
    monkeypatch.setattr(updater, "fetch_zapret_main_version", lambda: "9.9.9")
    monkeypatch.setattr(github, "get_latest_release", lambda repo: rel("9.9.9", [ZIP]))
    r = updater.check_zapret_update("1.0.0")
    assert r and github.pick_asset(r, ".zip")


def test_check_zapret_update_pending(monkeypatch):
    monkeypatch.setattr(updater, "fetch_zapret_main_version", lambda: "9.9.9")
    monkeypatch.setattr(github, "get_latest_release", lambda repo: rel("1.0.0", [ZIP]))
    r = updater.check_zapret_update("1.0.0")
    assert r and not github.pick_asset(r, ".zip")


def test_check_zapret_update_current(monkeypatch):
    monkeypatch.setattr(updater, "fetch_zapret_main_version", lambda: "1.0.0")
    assert updater.check_zapret_update("1.0.0") is None


def _write_config(tmp_path, monkeypatch, data):
    p = tmp_path / "config.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(config_mod, "CONFIG_PATH", p)
    return config_mod.Config()


def test_config_heals_zapret_repo_url(tmp_path, monkeypatch):
    c = _write_config(tmp_path, monkeypatch,
                      {"app_repo": "https://github.com/" + ZAPRET_REPO})
    assert c.app_repo == APP_REPO_DEFAULT


def test_config_heals_empty_repo(tmp_path, monkeypatch):
    c = _write_config(tmp_path, monkeypatch, {"app_repo": ""})
    assert c.app_repo == APP_REPO_DEFAULT


def test_config_keeps_custom_repo(tmp_path, monkeypatch):
    c = _write_config(tmp_path, monkeypatch, {"app_repo": "me/mygui"})
    assert c.app_repo == "me/mygui"


def test_checkworker_offers_update_with_healed_config(tmp_path, monkeypatch):
    """Regression: a config storing the zapret repo URL must still offer app updates."""
    from ui.workers import CheckWorker
    c = _write_config(tmp_path, monkeypatch,
                      {"app_repo": "https://github.com/" + ZAPRET_REPO})
    monkeypatch.setattr(github, "get_latest_release",
                        lambda repo: rel("9.9.9", [EXE]) if repo == APP_REPO_DEFAULT else None)
    monkeypatch.setattr(updater, "fetch_zapret_main_version", lambda: None)
    w = CheckWorker("1.0.0", c.app_repo, "both")
    out = {}
    w.done.connect(lambda r: out.update(r))
    w.run()
    assert out["app"] and out["app"].version == "9.9.9"
    assert not out["errors"]