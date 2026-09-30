# Security and upgrade notes - ABAP Beacon

## Attack surface
- Runs locally, binds to 127.0.0.1:8080 only, no inbound network access, no accounts.
- Outbound traffic only when an AI provider is configured, and only masked text (see Guardrails).
- Pure Python (SQLite, NiceGUI, SQLAlchemy, python-docx, pypdf); no native binaries shipped.

## Dependency vulnerability scan
    .\run.bat audit          runs pip-audit against the installed environment (installs it on first use)
Run it before every release and after every `run.bat upgrade`. Findings with a fix version: bump the pin
in `pyproject.toml`, reinstall, re-run the tests.

## Upgrades
- Versioned releases (`atlas version`); the database is checked and repaired at every start (`db-check`,
  `db-repair`); the schema is created additively (new tables/columns) so an existing `data\atlas.db`
  keeps working after an upgrade.
- Assessment rules are data: yearly SAP readiness changes (new simplification items, new released
  APIs) land as rule updates in `atlas/assess/rules.py`; a rule pack per target release is planned.

## Reporting
Security issues in ABAP Beacon: report to the InfraBeat delivery lead; include version (`atlas version`),
steps and the `data\output` log excerpt with credentials removed.
