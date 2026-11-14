"""PyPI and GitHub over HTTPS for the index builder.

Only three hosts are ever contacted. A failure after retries raises
:class:`SourceError`, which ends the build (nothing is published from a run
that could not read PyPI).

Implements (core spec 10.6): CORE-121, CORE-123, MOD-96, MOD-97.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from build_index import DistFile, RepoInfo, SourceError, Upload

PYPI = "https://pypi.org"
FILES_HOST = "files.pythonhosted.org"
GITHUB = "https://api.github.com"
ALLOWED_HOSTS = {"pypi.org", FILES_HOST, "api.github.com"}
MAX_DOWNLOAD = 100 * 1024 * 1024
"""Largest file the builder downloads."""
TIMEOUT = 30
ATTEMPTS = 3


class NetSource:
    """The real :class:`~build_index.Source`.

    Args:
        github_token: Token for the GitHub API (read-only, public data).
    """

    def __init__(self, github_token: str | None = None) -> None:
        self._token = github_token or os.environ.get("GITHUB_TOKEN")

    # --- PyPI ------------------------------------------------------------------------
    def uploads(self, pypi: str) -> list[Upload]:
        """All releases of ``pypi`` with their files."""
        body = self._get(f"{PYPI}/pypi/{urllib.parse.quote(pypi)}/json", missing_ok=True)
        if body is None:
            return []
        out = []
        for version, files in json.loads(body).get("releases", {}).items():
            dist = tuple(_file(f) for f in files)
            if dist:
                out.append(Upload(version, dist))
        return out

    def provenance(self, pypi: str, version: str, filename: str) -> bytes | None:
        """The PEP 740 provenance of one file; None when PyPI has none."""
        url = (
            f"{PYPI}/integrity/{urllib.parse.quote(pypi)}/{urllib.parse.quote(version)}"
            f"/{urllib.parse.quote(filename)}/provenance"
        )
        return self._get(url, missing_ok=True, accept="application/vnd.pypi.integrity.v1+json")

    def fetch(self, url: str, dest: Path) -> None:
        """Download a file of PyPI to ``dest``."""
        data = self._get(url, limit=MAX_DOWNLOAD)
        assert data is not None
        dest.write_bytes(data)

    # --- GitHub ----------------------------------------------------------------------
    def repo(self, repository: str) -> RepoInfo | None:
        """The repository and its README; None when it is missing or private."""
        base = f"{GITHUB}/repos/{repository}"
        body = self._get(base, missing_ok=True, accept="application/vnd.github+json")
        if body is None:
            return None
        meta: dict[str, Any] = json.loads(body)
        license_ = (meta.get("license") or {}).get("spdx_id")
        readme = self._get(
            f"{base}/readme", missing_ok=True, accept="application/vnd.github.raw+json"
        )
        return RepoInfo(
            public=not meta.get("private", True) and meta.get("visibility", "public") == "public",
            license=None if license_ in (None, "NOASSERTION") else license_,
            readme=(readme or b"").decode("utf-8", "replace"),
        )

    # --- HTTP ------------------------------------------------------------------------
    def _get(
        self,
        url: str,
        *,
        missing_ok: bool = False,
        accept: str | None = None,
        limit: int = 8 * 1024 * 1024,
    ) -> bytes | None:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
            raise SourceError(f"refusing to contact {url}")
        headers = {"User-Agent": "mm3-module-index-builder"}
        if accept:
            headers["Accept"] = accept
        if self._token and parts.hostname == "api.github.com":
            headers["Authorization"] = f"Bearer {self._token}"
        last = ""
        for attempt in range(ATTEMPTS):
            try:
                request = urllib.request.Request(url, headers=headers)  # noqa: S310 - https, checked
                with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
                    data: bytes = response.read(limit + 1)
                if len(data) > limit:
                    raise SourceError(f"{url} is larger than {limit} bytes")
                return data
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 451) and missing_ok:
                    return None
                last = f"HTTP {exc.code}"
                if exc.code < 500 and exc.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = str(exc)
            time.sleep(2**attempt)
        raise SourceError(f"{url}: {last}")


def _file(raw: dict[str, Any]) -> DistFile:
    kind = {"bdist_wheel": "wheel", "sdist": "sdist"}.get(raw.get("packagetype", ""), "other")
    return DistFile(
        filename=raw["filename"],
        url=raw["url"],
        sha256=raw["digests"]["sha256"],
        kind=kind,  # type: ignore[arg-type]
        yanked=bool(raw.get("yanked", False)),
    )
