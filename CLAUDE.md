# Notes for Claude

- The project rules are `docs/rules.md` in `mm3-project/mm3-core`
  (https://raw.githubusercontent.com/mm3-project/mm3-core/main/docs/rules.md);
  follow them. The specs they link are authoritative; for this repository the
  relevant parts are Core spec 10.6 (catalog and index CI: CORE-121, CORE-123,
  CORE-350) and the Module Contract MOD-95..99.
- The issue and enhancement log (ISS-nnn, ENH-nnn) is `docs/log/` in mm3-core;
  reports about the catalog are recorded there, not here.
- This repository holds the catalog entries (`modules/<name>.yaml`), the entry
  schema and the index builder (`scripts/build_index.py`). The workflow name
  `publish.yml` is fixed: the signing identity is `publish.yml@refs/heads/main`.
- Before finishing a change: `python scripts/validate_entries.py` and
  `pytest -q tests` (both run in `validate.yml`).
- main is protected: branch, pull request, CI green, **Squash and merge**.
