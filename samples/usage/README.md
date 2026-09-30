# Sample production usage export

`ST03N_workload_sample_365d.tsv` imitates an ST03N *Workload → Transaction profile* export for the sample repository: 365 days, one row per report/transaction/class pool with dialog steps, users and last use. Roughly 45 % of the custom objects do not appear (never executed), 15 % ran a handful of times in late 2025, the rest are in daily use.

Upload it on the Executive view (Custom code retirement → Upload usage CSV) or run `run.bat usage-import samples\usage\ST03N_workload_sample_365d.tsv`.

A real export: ST03N → Expert mode → Workload → Total → Transaction profile (or SCMON/SUSG aggregates via SUSG_CUSTOM_CODE_EXPORT) → export to spreadsheet; keep the object-name, steps/calls, users and last-used columns.
