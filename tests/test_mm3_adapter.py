"""The builder's two mm3-core adapters against a real, hand-packed wheel.

Skipped when mm3-core is not installed (``requirements-build.txt``).
"""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

pytest.importorskip("mm3.cli.main")
pytest.importorskip("sigstore")

from build_index import Rejected  # noqa: E402
from index_model import PublisherOut  # noqa: E402
from mm3.cli.main import main as mm3  # noqa: E402
from mm3_adapter import SigstoreVerifier, WheelChecker  # noqa: E402


def _wheel(tmp_path: Path, readme_edit: tuple[str, str] | None = None) -> Path:
    """Scaffold ``mm3-greeting`` and pack it as a wheel (what hatchling would do)."""
    cwd = Path.cwd()
    os.chdir(tmp_path)
    try:
        assert mm3(["new-module", "greeting", "--kind", "full"]) == 0
    finally:
        os.chdir(cwd)
    src = tmp_path / "mm3-greeting"
    pkg = src / "src" / "mm3_greeting"
    assert mm3(["i18n", "compile", str(pkg / "locales")]) == 0
    readme = (src / "README.md").read_text()
    if readme_edit:
        readme = readme.replace(*readme_edit)
    dist_info = "mm3_greeting-0.1.0.dist-info"
    files = {
        f"mm3_greeting/{f.relative_to(pkg).as_posix()}": f.read_bytes()
        for f in sorted(pkg.rglob("*"))
        if f.is_file() and "__pycache__" not in f.parts
    }
    files[f"{dist_info}/METADATA"] = (
        "Metadata-Version: 2.1\nName: mm3-greeting\nVersion: 0.1.0\n"
        "Requires-Python: >=3.11\nRequires-Dist: mm3-core<2,>=1.0\n"
        f"Description-Content-Type: text/markdown\n\n{readme}"
    ).encode()
    files[f"{dist_info}/WHEEL"] = (
        b"Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    )
    files[f"{dist_info}/entry_points.txt"] = (
        b"[mm3.modules]\ngreeting = mm3_greeting:GreetingModule\n"
    )
    record = [
        f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b'=').decode()},{len(data)}"
        for name, data in files.items()
    ]
    files[f"{dist_info}/RECORD"] = ("\n".join([*record, f"{dist_info}/RECORD,,"]) + "\n").encode()
    wheel = tmp_path / "mm3_greeting-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return wheel


def test_mod_99_a_compliant_wheel_passes_the_check(tmp_path: Path) -> None:
    outcome = WheelChecker().check(_wheel(tmp_path))
    assert outcome.compliant
    assert outcome.failed == ()
    assert outcome.api_version == "1.0"
    assert outcome.report["result"] == "compliant"
    assert outcome.report["stages"] == ["static"]


def test_mod_99_a_wheel_that_breaks_a_must_does_not_pass(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path, ("## Notifications", "## Events"))
    outcome = WheelChecker().check(wheel)
    assert not outcome.compliant
    assert "MOD-41" in outcome.failed


def test_mod_99_a_file_that_is_not_a_wheel_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "mm3_greeting-0.1.0-py3-none-any.whl"
    bad.write_bytes(b"not a zip")
    with pytest.raises(Rejected, match="cannot be checked"):
        WheelChecker().check(bad)


def test_core_352_a_provenance_that_does_not_verify_is_rejected(tmp_path: Path) -> None:
    wheel = _wheel(tmp_path)
    publisher = PublisherOut(repository="example/mm3-greeting", workflow="release.yml")
    with pytest.raises(Rejected):
        SigstoreVerifier().verify_wheel(wheel, b'{"attestation_bundles": []}', publisher)
    with pytest.raises(Rejected, match="invalid provenance"):
        SigstoreVerifier().verify_wheel(wheel, b"nonsense", publisher)
