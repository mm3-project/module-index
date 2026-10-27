"""Validate every catalog entry in ``modules/`` (MOD-97, MOD-98).

Checks:

- the file parses and matches :class:`ModuleEntry`;
- the file name equals the module name (``mm3-foo`` -> ``foo.yaml``);
- the license is in the OSI-approved allow list;
- no two entries share a PyPI name.

Release checks against PyPI (attestations, ``mm3 module check``) run in the
``build-index`` workflow, not here.

Exit code 0 when all entries are valid, 1 otherwise.
"""

from __future__ import annotations

import sys
from pathlib import Path

from pydantic import ValidationError
from ruamel.yaml import YAML

from entry_model import ModuleEntry

OSI_LICENSES = {
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "GPL-2.0-only",
    "GPL-2.0-or-later",
    "GPL-3.0-only",
    "GPL-3.0-or-later",
    "LGPL-2.1-or-later",
    "LGPL-3.0-or-later",
    "MPL-2.0",
    "AGPL-3.0-only",
    "AGPL-3.0-or-later",
    "ISC",
    "EUPL-1.2",
}


def validate(root: Path) -> list[str]:
    """Validate all entries under ``root / "modules"``.

    Args:
        root: Repository root.

    Returns:
        Human-readable error messages; empty when everything is valid.
    """
    yaml = YAML(typ="safe")
    errors: list[str] = []
    seen: dict[str, Path] = {}
    for path in sorted((root / "modules").glob("*.yaml")):
        rel = path.relative_to(root)
        try:
            entry = ModuleEntry.model_validate(yaml.load(path.read_text()))
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                errors.append(f"{rel}: {loc}: {err['msg']}")
            continue
        except Exception as exc:  # noqa: BLE001 - report any parse error per file
            errors.append(f"{rel}: cannot parse: {exc}")
            continue
        expected = entry.pypi.removeprefix("mm3-").replace("-", "_") + ".yaml"
        if path.name != expected:
            errors.append(f"{rel}: file must be named {expected}")
        if entry.license not in OSI_LICENSES:
            errors.append(f"{rel}: license {entry.license!r} is not in the OSI allow list")
        if entry.pypi in seen:
            errors.append(f"{rel}: duplicate of {seen[entry.pypi].relative_to(root)}")
        seen[entry.pypi] = path
    return errors


def main() -> int:
    """Validate the catalog and print the result.

    Returns:
        Process exit code.
    """
    root = Path(__file__).resolve().parent.parent
    errors = validate(root)
    for line in errors:
        print(f"ERROR {line}")
    count = len(list((root / "modules").glob("*.yaml")))
    print(f"{count} entries checked, {len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
