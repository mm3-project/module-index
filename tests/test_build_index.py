"""Tests of the listing decisions of the index builder, without network."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from ruamel.yaml import YAML

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from build_index import (  # noqa: E402
    CheckOutcome,
    DistFile,
    Rejected,
    RepoInfo,
    Upload,
    build,
    claimed_publisher,
)
from entry_model import ModuleEntry  # noqa: E402
from index_model import PublisherOut  # noqa: E402
from publish_index import main, next_serial, summary  # noqa: E402

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)
README = "# mm3-greeting\n\n## Grants\n\nnone\n\n## Notifications\n\nnone\n"


def _entry(**changes: object) -> ModuleEntry:
    raw = YAML(typ="safe").load((ROOT / "docs/examples/greeting.yaml").read_text())
    raw.update(changes)
    return ModuleEntry.model_validate(raw)


def _provenance(repository: str = "example/mm3-greeting", workflow: str = "release.yml") -> bytes:
    claim = {"kind": "GitHub", "repository": repository, "workflow": workflow}
    return json.dumps({"attestation_bundles": [{"publisher": claim, "attestations": []}]}).encode()


class FakeSource:
    """PyPI and GitHub with files made in memory."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.provenances: dict[tuple[str, str], bytes | None] = {}
        self._uploads: list[Upload] = []
        self.info: RepoInfo | None = RepoInfo(public=True, license="MIT", readme=README)

    def release(
        self,
        version: str,
        *,
        provenance: bytes | None = None,
        content: bytes | None = None,
        listed_sha: str | None = None,
        yanked: bool = False,
        kind: str = "wheel",
    ) -> None:
        name = f"mm3_greeting-{version}-py3-none-any.whl"
        data = content if content is not None else f"wheel {version}".encode()
        self.blobs[name] = data
        self.provenances[("mm3-greeting", name)] = (
            _provenance() if provenance is None else provenance
        )
        sha = listed_sha or hashlib.sha256(data).hexdigest()
        self._uploads.append(
            Upload(version, (DistFile(name, f"https://files/{name}", sha, kind, yanked),))  # type: ignore[arg-type]
        )

    def no_attestation(self, version: str) -> None:
        self.provenances[("mm3-greeting", f"mm3_greeting-{version}-py3-none-any.whl")] = None

    def uploads(self, pypi: str) -> list[Upload]:
        return list(self._uploads)

    def fetch(self, url: str, dest: Path) -> None:
        dest.write_bytes(self.blobs[url.rsplit("/", 1)[-1]])

    def provenance(self, pypi: str, version: str, filename: str) -> bytes | None:
        return self.provenances[(pypi, filename)]

    def repo(self, repository: str) -> RepoInfo | None:
        return self.info


class FakeVerifier:
    def __init__(self, bad: set[str] | None = None) -> None:
        self.bad = bad or set()
        self.calls: list[tuple[str, PublisherOut]] = []

    def verify_wheel(self, wheel: Path, provenance: bytes, publisher: PublisherOut) -> None:
        self.calls.append((wheel.name, publisher))
        if any(version in wheel.name for version in self.bad):
            raise Rejected(f"no attestation for {wheel.name} verifies")


class FakeChecker:
    def __init__(self, failing: set[str] | None = None, api: str = "1.0") -> None:
        self.failing = failing or set()
        self.api = api

    def check(self, wheel: Path) -> CheckOutcome:
        failed = any(version in wheel.name for version in self.failing)
        return CheckOutcome(
            compliant=not failed,
            api_version=self.api,
            capabilities=("http.outbound", "clock"),
            failed=("MOD-70",) if failed else (),
            report={"module": "mm3-greeting", "result": "non_compliant" if failed else "compliant"},
        )


def _build(
    source: FakeSource,
    tmp_path: Path,
    *,
    entry: ModuleEntry | None = None,
    verifier: FakeVerifier | None = None,
    checker: FakeChecker | None = None,
):
    return build(
        [entry or _entry()],
        source,
        verifier or FakeVerifier(),
        checker or FakeChecker(),
        now=NOW,
        serial=7,
        workdir=tmp_path,
        base_url="https://pages.example/module-index",
    )


def _reasons(result) -> dict[str | None, str]:
    return {d.version: d.reason for d in result.decisions if not d.listed}


def test_core_121_a_release_that_passes_every_check_is_listed(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    result = _build(source, tmp_path)
    (module,) = result.index.modules
    (release,) = module.releases
    assert release.version == "1.0.0"
    assert release.api == ">=1.0,<2"
    assert release.capabilities == ["clock", "http.outbound"]
    assert release.check.report_url.endswith("/reports/mm3-greeting/1.0.0.json")
    assert release.files[0].sha256 == hashlib.sha256(b"wheel 1.0.0").hexdigest()
    assert "mm3-greeting/1.0.0" in result.reports


def test_core_121_a_release_that_fails_the_check_is_not_listed(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    source.release("1.1.0")
    result = _build(source, tmp_path, checker=FakeChecker(failing={"1.1.0"}))
    assert [r.version for r in result.index.modules[0].releases] == ["1.0.0"]
    assert "MOD-70" in _reasons(result)["1.1.0"]
    assert "mm3-greeting/1.1.0" not in result.reports


def test_mod_99_a_module_with_no_passing_release_is_not_shown(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    result = _build(source, tmp_path, checker=FakeChecker(failing={"1.0.0"}))
    assert result.index.modules == []


def test_mod_96_a_release_without_attestation_is_rejected(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    source.release("1.1.0")
    source.no_attestation("1.1.0")
    result = _build(source, tmp_path)
    assert [r.version for r in result.index.modules[0].releases] == ["1.0.0"]
    assert "MOD-96" in _reasons(result)["1.1.0"]


def test_core_123_a_release_from_another_repository_is_rejected(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0", provenance=_provenance(repository="someone/else"))
    result = _build(source, tmp_path)
    assert result.index.modules == []
    assert "someone/else" in _reasons(result)["1.0.0"]


def test_core_123_the_repository_comparison_ignores_case(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0", provenance=_provenance(repository="Example/MM3-Greeting"))
    assert _build(source, tmp_path).index.modules


def test_core_123_the_signature_is_verified_for_the_claimed_publisher(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0", provenance=_provenance(workflow="publish.yml"))
    verifier = FakeVerifier()
    result = _build(source, tmp_path, verifier=verifier)
    assert verifier.calls[0][1] == PublisherOut(
        repository="example/mm3-greeting", workflow="publish.yml"
    )
    assert result.index.modules[0].publisher.workflow == "publish.yml"


def test_core_352_a_release_whose_signature_does_not_verify_is_rejected(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    source.release("1.1.0")
    result = _build(source, tmp_path, verifier=FakeVerifier(bad={"1.1.0"}))
    assert [r.version for r in result.index.modules[0].releases] == ["1.0.0"]


def test_core_123_older_releases_from_another_workflow_are_listed(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0", provenance=_provenance(workflow="old.yml"))
    source.release("1.1.0", provenance=_provenance(workflow="publish.yml"))
    result = _build(source, tmp_path)
    module = result.index.modules[0]
    assert [r.version for r in module.releases] == ["1.1.0", "1.0.0"]
    assert module.publisher.workflow == "publish.yml"  # the newest listed release


def test_a_wheel_that_differs_from_the_pypi_digest_is_rejected(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0", listed_sha="0" * 64)
    result = _build(source, tmp_path)
    assert result.index.modules == []
    assert "SHA-256" in _reasons(result)["1.0.0"]


def test_only_wheels_are_listed_and_yanked_files_are_ignored(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0", kind="sdist")
    source.release("1.1.0", yanked=True)
    result = _build(source, tmp_path)
    assert result.index.modules == []
    assert set(_reasons(result)) == {"1.0.0", "1.1.0"}


@pytest.mark.parametrize(
    ("info", "needle"),
    [
        (None, "not public"),
        (RepoInfo(public=False, license="MIT", readme=README), "not public"),
        (RepoInfo(public=True, license=None, readme=README), "OSI"),
        (RepoInfo(public=True, license="Apache-2.0", readme=README), "entry says MIT"),
        (RepoInfo(public=True, license="MIT", readme="# x\n## Grants\n"), "Notifications"),
        (RepoInfo(public=True, license="MIT", readme="# x\n## Notifications\n"), "Grants"),
    ],
)
def test_mod_97_an_entry_whose_repository_breaks_the_rules_is_not_listed(
    tmp_path: Path, info: RepoInfo | None, needle: str
) -> None:
    source = FakeSource()
    source.release("1.0.0")
    source.info = info
    result = _build(source, tmp_path)
    assert result.index.modules == []
    assert needle in result.decisions[0].reason
    assert result.decisions[0].version is None


def test_mod_97_readme_sections_may_be_written_in_any_case(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    source.info = RepoInfo(public=True, license="MIT", readme="### grants\n\n# NOTIFICATIONS\n")
    assert _build(source, tmp_path).index.modules


@pytest.mark.parametrize("declared", ["1", "1.0.1", "v1.0", "x"])
def test_an_api_version_that_is_not_major_minor_is_rejected(tmp_path: Path, declared: str) -> None:
    source = FakeSource()
    source.release("1.0.0")
    result = _build(source, tmp_path, checker=FakeChecker(api=declared))
    assert result.index.modules == []
    assert "api_version" in _reasons(result)["1.0.0"]


def test_core_122_the_badge_comes_from_the_entry(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    assert _build(source, tmp_path).index.modules[0].badge == "community"
    assert _build(source, tmp_path, entry=_entry(badge="verified")).index.modules[0].badge == (
        "verified"
    )


def test_releases_are_listed_newest_first(tmp_path: Path) -> None:
    source = FakeSource()
    for version in ("1.2.0", "1.10.0", "1.9.0"):
        source.release(version)
    result = _build(source, tmp_path)
    assert [r.version for r in result.index.modules[0].releases] == ["1.10.0", "1.9.0", "1.2.0"]


def test_core_350_the_index_has_a_lifetime_of_at_most_fourteen_days(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    index = _build(source, tmp_path).index
    assert index.serial == 7
    assert index.expires - index.generated_at <= timedelta(days=14)


def test_core_350_the_index_parses_with_the_engine_reader(tmp_path: Path) -> None:
    catalog = pytest.importorskip("mm3.core.catalog")
    source = FakeSource()
    source.release("1.0.0")
    result = _build(source, tmp_path)
    parsed = catalog.parse_index(result.index.model_dump_json(by_alias=True).encode())
    entry = catalog.find_entry(parsed, "mm3-greeting")
    assert entry is not None
    assert catalog.compatible(entry.releases[0])
    catalog.validate_lifetime(parsed, NOW)


def test_core_350_the_serial_rises_even_when_the_clock_went_back(tmp_path: Path) -> None:
    previous = tmp_path / "index.json"
    previous.write_text(json.dumps({"serial": int(NOW.timestamp()) + 500}))
    assert next_serial(previous, NOW) == int(NOW.timestamp()) + 501
    assert next_serial(None, NOW) == int(NOW.timestamp())
    assert next_serial(tmp_path / "missing.json", NOW) == int(NOW.timestamp())


def test_claimed_publisher_reads_the_first_github_bundle() -> None:
    assert claimed_publisher(_provenance(workflow="release.yml")).workflow == "release.yml"
    with pytest.raises(Rejected, match="no GitHub"):
        claimed_publisher(json.dumps({"attestation_bundles": []}).encode())
    with pytest.raises(Rejected, match="unreadable"):
        claimed_publisher(b"not json")


def test_the_summary_lists_each_decision(tmp_path: Path) -> None:
    source = FakeSource()
    source.release("1.0.0")
    source.release("1.1.0")
    source.no_attestation("1.1.0")
    text = summary(_build(source, tmp_path))
    assert "| mm3-greeting | 1.0.0 | yes |" in text
    assert "| mm3-greeting | 1.1.0 | no |" in text
    assert "1 releases listed in 1 modules." in text


def test_a_network_failure_ends_the_build_without_writing_an_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import net_source
    from build_index import SourceError

    class Down(net_source.NetSource):
        def uploads(self, pypi: str):  # type: ignore[no-untyped-def]
            raise SourceError("pypi.org unreachable")

    monkeypatch.setattr(net_source, "NetSource", Down)
    monkeypatch.setitem(sys.modules, "mm3_adapter", type(sys)("mm3_adapter"))
    adapter = sys.modules["mm3_adapter"]
    adapter.SigstoreVerifier = FakeVerifier  # type: ignore[attr-defined]
    adapter.WheelChecker = FakeChecker  # type: ignore[attr-defined]
    monkeypatch.setattr("publish_index.load_entries", lambda root, files: [_entry()])
    FakeSourceRepo = FakeSource()  # noqa: N806
    monkeypatch.setattr(Down, "repo", lambda self, repository: FakeSourceRepo.info)
    out = tmp_path / "dist"
    assert main(["--out", str(out)]) == 2
    assert "unreachable" in capsys.readouterr().err
    assert not (out / "index.json").exists()
