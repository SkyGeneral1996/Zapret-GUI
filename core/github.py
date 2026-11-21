import json
import re
import urllib.request
from dataclasses import dataclass

from version import APP_NAME, APP_VERSION

UA = f"{APP_NAME}/{APP_VERSION}"
API = "https://api.github.com"


@dataclass
class Release:
    tag: str
    version: str
    url: str
    notes: str
    assets: list  # list of dicts: name, size, url


def _request(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/vnd.github+json",
    })
    return urllib.request.urlopen(req, timeout=timeout)


def normalize_version(tag):
    return tag.lstrip("vV").strip()


def normalize_repo(value):
    """Accept 'owner/repo' or a github.com URL and return 'owner/repo' ('' if invalid)."""
    v = (value or "").strip()
    m = re.match(r"^https?://(?:www\.)?github\.com/([^/]+/[^/]+?)(?:\.git)?/?$", v, re.I)
    if m:
        v = m.group(1)
    v = v.removesuffix(".git").strip("/")
    if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", v):
        return v
    return ""


def version_tuple(v):
    parts = re.findall(r"\d+", normalize_version(v))
    return tuple(int(p) for p in parts) if parts else (0,)


def is_newer(remote, local):
    return version_tuple(remote) > version_tuple(local)


def get_latest_release(repo):
    """Return Release for the latest published release, or None if none."""
    repo = normalize_repo(repo)
    if not repo:
        return None
    url = f"{API}/repos/{repo}/releases/latest"
    with _request(url) as resp:
        data = json.load(resp)
    assets = [
        {
            "name": a.get("name", ""),
            "size": a.get("size", 0),
            "url": a.get("browser_download_url", ""),
        }
        for a in data.get("assets", [])
    ]
    return Release(
        tag=data.get("tag_name", ""),
        version=normalize_version(data.get("tag_name", "")),
        url=data.get("html_url", ""),
        notes=data.get("body", "") or "",
        assets=assets,
    )


def pick_asset(release, suffix):
    for a in release.assets:
        if a["name"].lower().endswith(suffix):
            return a
    return None


def download(url, dest, progress=None, cancel=None, timeout=60):
    """Stream url to dest file. progress(done, total). cancel() -> bool stops."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with _request(url, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length", 0))
        done = 0
        with open(dest, "wb") as f:
            while True:
                if cancel and cancel():
                    raise InterruptedError("cancelled")
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    return dest