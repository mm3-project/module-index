"""The two mm3-core pieces the builder uses, behind the builder's protocols.

``mm3-core`` comes with the extra ``installer`` (see ``requirements-build.txt``);
nothing else in this repository imports it, so the tests of the decisions run
without it.

- :class:`SigstoreVerifier`: ``mm3.installer.verify`` (core spec CORE-349,
  CORE-352), the same adapter the installer service uses on a mirror.
- :class:`WheelChecker`: ``mm3 module check --wheel`` (CORE-371), the static
  checks of Module Contract 12.1 on a built wheel. The test kit and the browser
  harness need the source tree and run in the module's own CI.

Implements (core spec 10.6): CORE-121, CORE-123, CORE-352, MOD-99.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from build_index import CheckOutcome, Rejected
from index_model import PublisherOut


class SigstoreVerifier:
    """Verify wheels with ``sigstore`` and ``pypi-attestations`` (CORE-349)."""

    def __init__(self) -> None:
        from mm3.installer.verify import SigstoreVerification

        self._verification = SigstoreVerification()

    def verify_wheel(self, wheel: Path, provenance: bytes, publisher: PublisherOut) -> None:
        """Verify ``wheel``; raise :class:`Rejected` when no attestation verifies."""
        from mm3.core.catalog import Publisher
        from mm3.installer.verify import VerifyError

        try:
            self._verification.verify_wheel(
                wheel, provenance, Publisher(**publisher.model_dump())
            )
        except VerifyError as exc:
            raise Rejected(str(exc)) from exc


class WheelChecker:
    """``mm3 module check --wheel`` for a built wheel (CORE-371)."""

    def check(self, wheel: Path) -> CheckOutcome:
        """Run the static checks and read the declared capabilities."""
        from mm3.core.modcheck.project import ToolError, load_wheel
        from mm3.core.modcheck.runner import run_wheel_check
        from mm3.core.modcheck.static import run_static

        try:
            report = run_wheel_check(wheel, "static")
            with tempfile.TemporaryDirectory(prefix="mm3-index-") as tmp:
                extract = Path(tmp) / "wheel"
                extract.mkdir()
                _, facts = run_static(load_wheel(wheel.resolve(), extract))
        except ToolError as exc:
            raise Rejected(f"{wheel.name}: cannot be checked: {exc}") from exc
        failed = tuple(
            c.id for c in report.checks if c.level == "MUST" and c.status == "fail"
        )
        return CheckOutcome(
            compliant=report.result == "compliant",
            api_version=report.api_version,
            capabilities=tuple(sorted(facts.capabilities)) if facts is not None else (),
            failed=failed,
            report=report.as_dict(),
        )
