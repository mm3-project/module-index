"""Pydantic model of a catalog entry, ``modules/<name>.yaml`` (MOD-98).

The JSON Schema in ``schema/module-entry.schema.json`` is generated from this
model with ``python scripts/entry_model.py``; do not edit the schema by hand.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

REQUIRED_LOCALES = ("en", "it", "fr", "es", "de")
"""Languages every description must provide (MOD-98)."""

Category = Literal[
    "time",
    "weather",
    "calendar",
    "news",
    "home-automation",
    "media",
    "transport",
    "health",
    "utilities",
    "widgets",
    "system",
    "other",
]


class Maintainer(BaseModel):
    """Person or team responsible for the module."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    email: EmailStr


class ModuleEntry(BaseModel):
    """One module listed in the MM3 catalog."""

    model_config = ConfigDict(extra="forbid")

    pypi: str = Field(pattern=r"^mm3-[a-z0-9][a-z0-9-]*$", description="PyPI distribution name")
    source: HttpUrl = Field(description="Public source repository (MOD-97)")
    maintainer: Maintainer
    license: str = Field(description="SPDX identifier of an OSI-approved license")
    category: Category
    description: dict[str, str]
    screenshots: list[str] = Field(default_factory=list)
    badge: Literal["official", "verified", "community"] = Field(
        "community", description="Set by catalog maintainers only (CORE-122)"
    )

    @field_validator("description")
    @classmethod
    def _all_locales(cls, value: dict[str, str]) -> dict[str, str]:
        missing = [loc for loc in REQUIRED_LOCALES if not value.get(loc, "").strip()]
        if missing:
            raise ValueError(f"description missing languages: {', '.join(missing)}")
        return value

    @field_validator("source")
    @classmethod
    def _github_source(cls, value: HttpUrl) -> HttpUrl:
        # Trusted Publishing identities are checked against GitHub repositories.
        if not re.match(r"^https://github\.com/[^/]+/[^/]+/?$", str(value)):
            raise ValueError("source must be a public GitHub repository URL")
        return value


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "schema" / "module-entry.schema.json"
    out.write_text(json.dumps(ModuleEntry.model_json_schema(), indent=2) + "\n")
    print(f"wrote {out}")
