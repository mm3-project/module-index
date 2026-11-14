"""Build ``index.json``: list only the releases that pass every check.

For every entry in ``modules/`` and every PyPI release of its package this
decides whether the release is listed. A release is listed only when all of
these hold; anything else leaves it on PyPI but out of the index:

- the entry's source repository is public, its license is OSI-approved and the
  README has the "Grants" and "Notifications" sections (MOD-97);
- every wheel's SHA-256 equals the one PyPI reports, and PyPI serves a
  PEP 740 provenance for it, so it was uploaded with Trusted Publishing
  (MOD-96, CORE-123);
- the provenance names the entry's source repository, and its signature
  verifies for that publisher (CORE-123, CORE-352);
- ``mm3 module check`` finds the wheel compliant for its declared
  ``api_version`` (MOD-99, CORE-121).

The network, the verification libraries and the checker are passed in as
:class:`Source`, :class:`Verifier` and :class:`Checker`, so the decisions are
tested without them. A network failure raises :class:`SourceError` and ends the
build: a partial index is never published because PyPI was unreachable.

Implements (core spec 10.6, Module Contract 12.3; see README):
    CORE-121, CORE-122, CORE-123, CORE-350, MOD-96, MOD-97, MOD-99.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from entry_model import ModuleEntry
from index_model import (
    CheckOut,
    FileOut,
    IndexOut,
    ModuleOut,
    PublisherOut,
    ReleaseOut,
)
from validate_entries import OSI_LICENSES

__all__ = [
    "BuildResult",
    "CheckOutcome",
    "Checker",
    "Decision",
    "DistFile",
    "Rejected",
    "RepoInfo",
    "Source",
    "SourceError",
    "Upload",
    "Verifier",
    "build",
    "claimed_publisher",
]

LIFETIME = timedelta(days=10)
"""``expires`` after ``generated_at``; the spec allows at most 14 days."""
REQUIRED_SECTIONS = ("Grants", "Notifications")
"""README sections MOD-97 asks for (the scaffold writes both)."""


class SourceError(RuntimeError):
    """The network or a service failed; nothing may be published from this run."""


class Rejected(ValueError):
    """A release or an entry is not listed; the message is the reason."""


@dataclass(frozen=True)
class DistFile:
    """One uploaded file of a PyPI release."""

    filename: str
    url: str
    sha256: str
    kind: Literal["wheel", "sdist", "other"]
    yanked: bool = False


@dataclass(frozen=True)
class Upload:
    """One PyPI release with its files."""

    version: str
    files: tuple[DistFile, ...]


@dataclass(frozen=True)
class RepoInfo:
    """What the builder needs to know about a GitHub repository."""

    public: bool
    license: str | None
    readme: str


@dataclass(frozen=True)
class CheckOutcome:
    """The result of checking one wheel."""

    compliant: bool
    api_version: str
    capabilities: tuple[str, ...]
    failed: tuple[str, ...]
    report: dict[str, object]


class Source(Protocol):
    """PyPI and GitHub, as far as the builder reads them."""

    def uploads(self, pypi: str) -> list[Upload]:
        """All releases of a package (empty when it does not exist)."""

    def fetch(self, url: str, dest: Path) -> None:
        """Download ``url`` to ``dest``."""

    def provenance(self, pypi: str, version: str, filename: str) -> bytes | None:
        """The PEP 740 provenance of a file, or None when PyPI has none."""

    def repo(self, repository: str) -> RepoInfo | None:
        """The repository ``owner/name``, or None when it is not public."""


class Verifier(Protocol):
    """Verify a wheel's provenance for a publisher (CORE-352)."""

    def verify_wheel(self, wheel: Path, provenance: bytes, publisher: PublisherOut) -> None:
        """Verify, or raise :class:`Rejected` with the reason."""


class Checker(Protocol):
    """Run ``mm3 module check`` on a wheel (MOD-99)."""

    def check(self, wheel: Path) -> CheckOutcome:
        """Check one wheel."""


@dataclass(frozen=True)
class Decision:
    """Why an entry or release is, or is not, in the index."""

    pypi: str
    version: str | None
    listed: bool
    reason: str = ""


@dataclass
class BuildResult:
    """The index, the reports it points to and every decision."""

    index: IndexOut
    reports: dict[str, dict[str, object]] = field(default_factory=dict)
    decisions: list[Decision] = field(default_factory=list)


def claimed_publisher(provenance: bytes) -> PublisherOut:
    """Read the publisher an attestation claims (checked later, not trusted).

    Args:
        provenance: The JSON from PyPI's Integrity API.

    Returns:
        The GitHub Trusted Publisher in the first bundle that has one.

    Raises:
        Rejected: No bundle names a GitHub publisher.
    """
    try:
        data = json.loads(provenance)
        bundles = data["attestation_bundles"]
        for bundle in bundles:
            claim = bundle["publisher"]
            if claim.get("kind") == "GitHub" and claim.get("repository") and claim.get("workflow"):
                return PublisherOut(
                    repository=claim["repository"],
                    workflow=claim["workflow"].rsplit("/", 1)[-1],
                    environment=claim.get("environment") or None,
                )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise Rejected(f"unreadable provenance: {exc}") from exc
    raise Rejected("the provenance names no GitHub Trusted Publisher")


def _repository(entry: ModuleEntry) -> str:
    """``owner/name`` of the entry's source URL."""
    return str(entry.source).removeprefix("https://github.com/").strip("/").removesuffix(".git")


def _api_range(declared: str) -> str:
    """The Module API range of a release written for ``declared`` (MOD-90, MOD-93)."""
    match = re.fullmatch(r"(\d+)\.(\d+)", declared)
    if match is None:
        raise Rejected(f"api_version {declared!r} is not <major>.<minor>")
    major, minor = int(match[1]), int(match[2])
    return f">={major}.{minor},<{major + 1}"


def _entry_problems(entry: ModuleEntry, info: RepoInfo | None) -> list[str]:
    """Why an entry may not be listed at all (MOD-97)."""
    if info is None or not info.public:
        return ["the source repository is not public"]
    problems = []
    if info.license is not None and info.license != entry.license:
        problems.append(f"GitHub reports license {info.license}, the entry says {entry.license}")
    if info.license is None or info.license not in OSI_LICENSES:
        problems.append("the repository license is not an OSI-approved license GitHub recognises")
    for section in REQUIRED_SECTIONS:
        pattern = rf"^#{{1,6}}\s*{section}\b"
        if not re.search(pattern, info.readme, re.IGNORECASE | re.MULTILINE):
            problems.append(f"the README has no {section!r} section")
    return problems


def _release(
    entry: ModuleEntry,
    up: Upload,
    pinned: PublisherOut | None,
    source: Source,
    verifier: Verifier,
    checker: Checker,
    workdir: Path,
    base_url: str,
) -> tuple[ReleaseOut, PublisherOut, dict[str, object]]:
    """Run every check on one release; raise :class:`Rejected` on the first failure."""
    repository = _repository(entry)
    wheels = [f for f in up.files if f.kind == "wheel" and not f.yanked]
    if not wheels:
        raise Rejected("no wheel (or all of them yanked)")
    publisher: PublisherOut | None = None
    outcome: CheckOutcome | None = None
    for wheel in wheels:
        dest = workdir / wheel.filename
        source.fetch(wheel.url, dest)
        if hashlib.sha256(dest.read_bytes()).hexdigest() != wheel.sha256:
            raise Rejected(f"{wheel.filename}: SHA-256 differs from the one PyPI lists")
        provenance = source.provenance(entry.pypi, up.version, wheel.filename)
        if provenance is None:
            raise Rejected(
                f"{wheel.filename}: no PEP 740 attestation; releases must be uploaded "
                "with Trusted Publishing (MOD-96)"
            )
        claim = claimed_publisher(provenance)
        if claim.repository.lower() != repository.lower():
            raise Rejected(
                f"{wheel.filename}: published from {claim.repository}, "
                f"not from the entry's source {repository} (CORE-123)"
            )
        if publisher is not None and claim != publisher:
            raise Rejected("the wheels of this release come from different publishers")
        if pinned is not None and claim != pinned:
            raise Rejected(
                f"published by {claim.workflow}, but newer releases use {pinned.workflow}"
            )
        publisher = claim
        verifier.verify_wheel(dest, provenance, claim)
        result = checker.check(dest)
        if not result.compliant:
            raise Rejected(f"mm3 module check failed: {', '.join(result.failed) or 'see report'}")
        if outcome is not None and result.api_version != outcome.api_version:
            raise Rejected("the wheels of this release declare different api_version values")
        outcome = outcome or result
    assert publisher is not None and outcome is not None  # wheels is not empty
    release = ReleaseOut(
        version=up.version,
        api=_api_range(outcome.api_version),
        capabilities=sorted(outcome.capabilities),
        grants={},
        check=CheckOut(
            result="compliant",
            report_url=f"{base_url}/reports/{canonicalize_name(entry.pypi)}/{up.version}.json",
        ),
        files=[FileOut(filename=w.filename, sha256=w.sha256) for w in wheels],
    )
    return release, publisher, outcome.report


def build(
    entries: Iterable[ModuleEntry],
    source: Source,
    verifier: Verifier,
    checker: Checker,
    *,
    now: datetime,
    serial: int,
    workdir: Path,
    base_url: str,
) -> BuildResult:
    """Decide every release of every entry and assemble the index.

    Args:
        entries: The validated catalog entries.
        source: PyPI and GitHub.
        verifier: Provenance verification.
        checker: ``mm3 module check`` for a wheel.
        now: The generation time (timezone-aware).
        serial: The index serial; it must exceed every published one.
        workdir: Empty directory for downloads.
        base_url: Where ``reports/`` is published, without trailing slash.

    Returns:
        The index, the report of each listed release (key ``<pypi>/<version>``)
        and one decision per entry or release.

    Raises:
        SourceError: The network or a service failed.
    """
    result = BuildResult(
        IndexOut.model_validate(
            {
                "schema": 1,
                "serial": serial,
                "generated_at": now,
                "expires": now + LIFETIME,
                "modules": [],
            }
        )
    )
    for entry in sorted(entries, key=lambda e: e.pypi):
        problems = _entry_problems(entry, source.repo(_repository(entry)))
        if problems:
            result.decisions.append(Decision(entry.pypi, None, False, "; ".join(problems)))
            continue
        releases: list[ReleaseOut] = []
        pinned: PublisherOut | None = None
        for up in sorted(source.uploads(entry.pypi), key=lambda u: _key(u.version), reverse=True):
            try:
                release, publisher, report = _release(
                    entry, up, pinned, source, verifier, checker, workdir, base_url
                )
            except Rejected as exc:
                result.decisions.append(Decision(entry.pypi, up.version, False, str(exc)))
                continue
            pinned = pinned or publisher
            releases.append(release)
            result.reports[f"{canonicalize_name(entry.pypi)}/{up.version}"] = report
            result.decisions.append(Decision(entry.pypi, up.version, True))
        if not releases or pinned is None:
            continue  # nothing installable: the module is not shown
        result.index.modules.append(
            ModuleOut(
                pypi=entry.pypi,
                repository=str(entry.source).rstrip("/"),
                badge=entry.badge,  # set by maintainers only (CORE-122)
                publisher=pinned,
                category=entry.category,
                license=entry.license,
                description=entry.description,
                releases=releases,
            )
        )
    return result


def _key(version: str) -> Version:
    """Sort key; versions PEP 440 rejects sort first (oldest)."""
    try:
        return Version(version)
    except InvalidVersion:
        return Version("0")
