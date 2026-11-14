# MM3 module index

The public catalog of modules for [MM3](https://github.com/mm3-project/mm3-core).
Each module is described by one file in [`modules/`](modules/); the packages
themselves live on PyPI. A CI job checks every release and publishes a signed
`index.json` that the `mm3 modules` command and the admin UI read.

> **Status:** entries are validated on every pull request and the signed
> index is built and published daily by
> [`publish.yml`](.github/workflows/publish.yml). Until the first module is
> merged the published index is empty.

## How a module gets listed

1. Your module meets the [MM3 Module Contract](https://claude.ai/artifact/AwhPKtk3ezmyix1NRmKZrR)
   and passes `mm3 module check`.
2. Its source is a public GitHub repository with an OSI-approved license (MOD-97).
3. Releases are uploaded to PyPI with **Trusted Publishing**, so they carry
   PEP 740 attestations (MOD-96). Manual uploads with API tokens are rejected.
4. Open a pull request adding `modules/<name>.yaml`; see
   [`docs/examples/greeting.yaml`](docs/examples/greeting.yaml) and the
   [schema](schema/module-entry.schema.json). The description must be given in
   English, Italian, French, Spanish and German (MOD-98).
5. CI validates the entry. After merge, each new release is checked
   automatically and listed only if it passes (MOD-99, CORE-121).

The file name is the package name without `mm3-`, with `-` replaced by `_`:
`mm3-air-quality` → `modules/air_quality.yaml`.

## How releases are checked

`publish.yml` runs every day, and whenever `modules/` changes on `main`. For
each entry it looks at every release on PyPI and lists a release only if all of
these hold (CORE-121); anything else stays on PyPI but is not listed, and the
reason is in the job summary:

| Check | Requirement |
| --- | --- |
| The GitHub repository is public, its license is OSI-approved and equals the entry's, and the README has "Grants" and "Notifications" sections | MOD-97 |
| Every wheel has the SHA-256 PyPI reports and a PEP 740 attestation, so it was uploaded with Trusted Publishing; releases uploaded with API tokens have none | MOD-96 |
| The attestation names the entry's source repository and its Sigstore signature verifies for that publisher; the workflow may differ between releases of the same repository (the index names the newest release's) | CORE-123, CORE-352 |
| `mm3 module check --wheel` (static checks) finds the wheel compliant for its declared `api_version`; the release is listed for `>=M.m,<M+1` | MOD-99, CORE-121 |

The result is `index.json` with a report per release under `reports/`, signed
with Sigstore by `publish.yml` on `main`; mm3-core accepts exactly that
identity (CORE-350). A run that cannot reach PyPI or GitHub publishes nothing:
the previous index stays live until its `expires`. A module with no passing
release is not shown. The test kit and the browser harness of
`mm3 module check` need the source tree and run in the module's own CI.

A pull request that adds or changes an entry gets the same checks for that
entry in its `dry-run` job, with no signing. Run them locally with
`python scripts/publish_index.py --out dist --strict modules/<name>.yaml`
(needs mm3-core, see `.github/actions/install-mm3-core`).

## Badges

| Badge | Meaning |
| --- | --- |
| official | Published by the MM3 project |
| verified | Code, capabilities and data handling reviewed by catalog maintainers |
| community | Automatic checks only (default) |

Badges are set by maintainers; a pull request that changes a badge is not merged.

## Local checks

```bash
pip install -r requirements.txt
python scripts/validate_entries.py
pytest -q tests
```

The JSON Schema is generated from `scripts/entry_model.py`
(`python scripts/entry_model.py`); do not edit it by hand.

## License

Index data and scripts: [MIT](LICENSE). Each listed module has its own license.
