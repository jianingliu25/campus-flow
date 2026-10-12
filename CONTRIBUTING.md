# Contributing

This project publishes an offline beta reconstruction. Read README and docs/privacy.md
before introducing real-data routes. Use policy/session/scoped repository checks
for every route and processing branch; keep PRs within the stated milestone.

Install with `python scripts/manage.py setup`, then run validation and tests.
Use synthetic data for bug reports and screenshots. Never attach real emails,
credentials, personal profiles or unredacted logs. Document model/fixture changes
without treating preset responses as measured inference quality.

Contributions to the reconstruction are provided under the repository MIT license.
Keep attribution and third-party asset/license notices intact; do not copy original
course-team code or private datasets without the relevant rights.

Run `python scripts/manage.py evaluate` and preserve frozen evaluation hashes. Do not tune against held-out cases without declaring a new benchmark version.
