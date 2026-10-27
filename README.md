# MM3 module index

The public catalog of modules for [MM3](https://github.com/mm3-project/mm3-core).
Each module is described by one file in [`modules/`](modules/); the packages
themselves live on PyPI. A CI job checks every release and publishes a signed
`index.json` that the `mm3 modules` command and the admin UI read.

> **Status:** the entry format and validation are ready; publishing of the
> signed index starts once `mm3 module check` is available in mm3-core.

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
