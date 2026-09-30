# Contributing to ABAP Beacon

ABAP Beacon is maintained by one person so that every number it produces stays defensible.

1. Do not edit or run from a copied source folder. Install a published release (Releases page).
2. Proposals and fixes go through a pull request against `main`:
   - branch from `main`, keep the change small, add or adjust a test in `tests/`
   - run `pytest -q` (all green) and `atlas audit` (no known vulnerabilities)
   - describe the change and its effect on the sample FSDs / assessments in the PR
3. The maintainer (see CODEOWNERS) reviews, requests changes or merges. Nobody else can merge.
4. Releases are cut by the maintainer with `python release.py <version>` and published with checksums.

Bug reports: open an issue with the version (`atlas version`), the steps and the `data\output` log
excerpt (credentials removed).
