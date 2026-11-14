"""Pydantic model of the published ``index.json`` (core spec 10.6, CORE-350).

The builder writes this shape; ``mm3.core.catalog.Index`` in mm3-core reads it.
``tests/test_build_index.py`` checks the two against each other when mm3-core is
installed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class PublisherOut(_Out):
    """The Trusted Publisher the releases come from (CORE-123)."""

    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    workflow: str = Field(pattern=r"^[A-Za-z0-9_.-]+\.ya?ml$")
    environment: str | None = None


class FileOut(_Out):
    """One wheel of a release."""

    filename: str = Field(pattern=r"^[A-Za-z0-9._+-]+\.whl$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class CheckOut(_Out):
    """The result of ``mm3 module check`` for a release (CORE-121)."""

    result: Literal["compliant"]
    report_url: str


class ReleaseOut(_Out):
    """One listed release."""

    version: str
    api: str
    capabilities: list[str]
    grants: dict[str, object]
    check: CheckOut
    files: list[FileOut] = Field(min_length=1)


class ModuleOut(_Out):
    """One listed module."""

    pypi: str
    repository: str
    badge: Literal["official", "verified", "community"]
    publisher: PublisherOut
    category: str
    license: str
    description: dict[str, str]
    releases: list[ReleaseOut] = Field(min_length=1)


class IndexOut(_Out):
    """The whole index, schema 1."""

    schema_: Literal[1] = Field(1, alias="schema")
    serial: int = Field(ge=0)
    generated_at: datetime
    expires: datetime
    modules: list[ModuleOut]
