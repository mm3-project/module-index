"""Command line of the index builder.

``python scripts/publish_index.py --out dist`` reads ``modules/``, checks every
release (see :mod:`build_index`) and writes ``dist/index.json``,
``dist/reports/<package>/<version>.json`` and ``dist/decisions.md``. Signing and
publishing are steps of ``.github/workflows/publish.yml``.

Exit codes: 0 built, 1 ``--strict`` and something was not listed, 2 the
network or an entry file failed (nothing to publish).

Implements (core spec 10.6): CORE-121, CORE-350, MOD-96, MOD-99.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from build_index import BuildResult, SourceError, build
from entry_model import ModuleEntry

BASE_URL = "https://mm3-project.github.io/module-index"


def load_entries(root: Path, files: list[Path]) -> list[ModuleEntry]:
    """Read entry files (already validated by ``validate_entries``).

    Args:
        root: Repository root.
        files: Entry files to read; empty reads all of ``modules/``.

    Returns:
        The entries.

    Raises:
        ValidationError: An entry file is invalid.
    """
    yaml = YAML(typ="safe")
    paths = sorted(files) if files else sorted((root / "modules").glob("*.yaml"))
    return [ModuleEntry.model_validate(yaml.load(path.read_text())) for path in paths]


def next_serial(previous: Path | None, now: datetime) -> int:
    """A serial above the published one (CORE-350).

    Args:
        previous: The index published now, when there is one.
        now: The generation time.

    Returns:
        Seconds since the epoch, or one more than the previous serial when
        that is higher (a clock that went back never lowers the serial).
    """
    serial = int(now.timestamp())
    if previous is not None and previous.is_file():
        serial = max(serial, int(json.loads(previous.read_text())["serial"]) + 1)
    return serial


def write(result: BuildResult, out: Path) -> None:
    """Write the index, the reports and the decision summary.

    Args:
        result: The build.
        out: Output directory.
    """
    (out / "reports").mkdir(parents=True, exist_ok=True)
    (out / "index.json").write_text(
        result.index.model_dump_json(by_alias=True, indent=2) + "\n", encoding="utf-8"
    )
    for key, report in result.reports.items():
        target = out / "reports" / f"{key}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (out / "decisions.md").write_text(summary(result), encoding="utf-8")


def summary(result: BuildResult) -> str:
    """The decisions as a Markdown table (also the job summary on GitHub)."""
    lines = ["| Package | Version | Listed | Reason |", "| --- | --- | --- | --- |"]
    for d in result.decisions:
        reason = d.reason.replace("|", "\\|").replace("\n", " ")
        listed = "yes" if d.listed else "no"
        lines.append(f"| {d.pypi} | {d.version or 'entry'} | {listed} | {reason} |")
    listed = sum(d.listed for d in result.decisions)
    lines.append("")
    lines.append(f"{listed} releases listed in {len(result.index.modules)} modules.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Build the index.

    Args:
        argv: Arguments; ``sys.argv[1:]`` by default.

    Returns:
        The process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--previous", type=Path, help="the index published now (for the serial)")
    parser.add_argument("files", nargs="*", type=Path, help="entry files (default: all)")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--strict", action="store_true", help="exit 1 if anything is not listed")
    args = parser.parse_args(argv)

    from mm3_adapter import SigstoreVerifier, WheelChecker
    from net_source import NetSource

    root = Path(__file__).resolve().parent.parent
    now = datetime.now(UTC).replace(microsecond=0)
    try:
        entries = load_entries(root, args.files)
        with tempfile.TemporaryDirectory(prefix="mm3-index-") as work:
            result = build(
                entries,
                NetSource(),
                SigstoreVerifier(),
                WheelChecker(),
                now=now,
                serial=next_serial(args.previous, now),
                workdir=Path(work),
                base_url=args.base_url.rstrip("/"),
            )
    except (SourceError, ValidationError, OSError) as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    write(result, args.out)
    print(summary(result))
    unlisted = [d for d in result.decisions if not d.listed]
    return 1 if args.strict and unlisted else 0


if __name__ == "__main__":
    sys.exit(main())
