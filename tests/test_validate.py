"""Tests for the catalog entry validator."""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from validate_entries import validate  # noqa: E402


def _repo(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / name).write_text(text)
    return tmp_path


def test_mod_98_example_entry_is_valid(tmp_path: Path) -> None:
    (tmp_path / "modules").mkdir()
    shutil.copy(ROOT / "docs/examples/greeting.yaml", tmp_path / "modules/greeting.yaml")
    assert validate(tmp_path) == []


def test_mod_98_missing_language_is_rejected(tmp_path: Path) -> None:
    text = (ROOT / "docs/examples/greeting.yaml").read_text().replace("  de:", "  xx:")
    errors = validate(_repo(tmp_path, "greeting.yaml", text))
    assert any("de" in e for e in errors)


def test_mod_97_non_osi_license_is_rejected(tmp_path: Path) -> None:
    text = (ROOT / "docs/examples/greeting.yaml").read_text().replace("MIT", "Proprietary")
    errors = validate(_repo(tmp_path, "greeting.yaml", text))
    assert any("license" in e for e in errors)


def test_file_name_must_match_package(tmp_path: Path) -> None:
    text = (ROOT / "docs/examples/greeting.yaml").read_text()
    errors = validate(_repo(tmp_path, "hello.yaml", text))
    assert any("greeting.yaml" in e for e in errors)


def test_repository_entries_are_valid() -> None:
    assert validate(ROOT) == []
