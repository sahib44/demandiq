# Phase 1 delivery record

Verified on 2026-10-18, America/New_York. This records actual execution, not expected output. The initial instruction's six-phase boundaries govern: aggregation, training-only product ranking and forecasting have not begun.

## Implemented

- Complete original specification, architecture/implementation plan, environment template, ignore rules and setup documentation.
- Python 3.12 package with pinned direct dependencies and a resolved Phase 1 dependency lock; Ruff, Black and pytest configuration.
- Official UCI source acquisition with timeouts, bounded retries, streaming size limits, SHA-256 checks, expected-digest option, safe ZIP handling, corruption detection, verified caching and atomic publication.
- Local XLSX/CSV readers preserving identifiers, strict eight-column schema validation, explicit dates and row-level scalar validation.
- Exact-source duplicate removal before normalization; deterministic signed purchase/cancellation/return partitions; quarantine reasons for invalid required values, prices, quantities, identifiers, fee codes and cancellation sign anomalies.
- Privacy-safe row audit covering every source row; missing optional fields retained/flagged; customer IDs replaced by deterministic domain-separated pseudonyms.
- Typed Zstandard Parquet, sequential quality report, immutable manifest, input/configuration versioning, complete-directory publication and verified repeat imports.
- PostgreSQL datasets, aggregate quality reports and unranked products; Alembic migrations, database constraints, transactional/idempotent persistence, concurrency protection and rollback.
- Local PostgreSQL Compose service, health check and dedicated test database.
- Synthetic unit/IO/downloader tests and real PostgreSQL migration/constraint/idempotency/concurrency integration tests.

## Verified environment

| Component | Observed version / state |
| --- | --- |
| Default shell Python | 3.9.6; unsuitable for this project |
| Project runtime | Python 3.12.14; `.venv` created with the bundled runtime |
| Node.js | 24.19.0 via bundled runtime; not needed in Phase 1 |
| Git | 2.39.5 (Apple Git-154); empty repository on `main`, no commits |
| Docker client / server | 29.8.0 / 29.8.0 |
| Docker Compose | 5.5.1 |
| PostgreSQL | 16.6 in `postgres:16.6-alpine`, healthy, bound to localhost:5432 |

PostgreSQL host binaries were initially absent and Docker was initially stopped. Two attempts to open Docker from the sandbox failed. A temporary project-cache PostgreSQL 16.2 cluster was initialized and started as a fallback; it was stopped after the user opened Docker. All reported database test passes and the official dataset registration use **Compose PostgreSQL 16.6**, not that fallback. No system software installation was required.

## Actual source and dataset provenance

Official source: [UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail). Citation: Chen, D. (2015), DOI [10.24432/C5BW33](https://doi.org/10.24432/C5BW33), CC BY 4.0.

| Field | Observed value |
| --- | --- |
| Archive SHA-256 | `f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b` |
| Workbook SHA-256 | `43465a06f2ccf7c8b5bd2892bc7defb52f97487934fe93b16ae4c3936424676d` |
| Archive bytes | 23,715,478 |
| Workbook bytes | 23,715,344 |
| Final cleaning version | `1.0.1` |
| Final dataset ID | `3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d` |

Raw files are private local artifacts under `data/raw/uci-online-retail/`. Final processed files are under `data/processed/<dataset_id>/`. A second cold parse under `data/repro-check/<dataset_id>/` produced identical SHA-256 digests for **all six files**: purchases, cancellations, returns, audit, quality report and manifest. A prior development run under cleaning 1.0.0 may also remain in ignored local data; it is not the final registered version.

## Measured data-quality summary

| Measure | Actual value |
| --- | ---: |
| Original rows | 541,909 |
| Exact duplicate rows | 5,268 |
| Rows after exact deduplication | 536,641 |
| Quarantined rows | 5,401 |
| Accepted rows, all three classes | 531,240 |
| Purchase rows | 522,572 |
| Cancellation rows | 8,668 |
| Other negative-quantity return rows accepted | 0 |
| Missing descriptions | 1,454 |
| Missing customer IDs | 135,037 |
| Invalid/nonpositive prices | 2,512 |
| Invalid quantities | 0 |
| Invalid dates | 0 |
| Missing invoice/product IDs | 0 / 0 |
| Overlong/invalid product IDs | 0 |
| Known nonmerchandise-code flags | 2,903 |
| Accepted unique products | 3,928 |
| Accepted unique invoices | 23,196 |
| Accepted unique known customer pseudonyms | 4,362 |
| Accepted countries | 38 |
| Accepted start / end, London wall time | 2010-12-01 08:26 / 2011-12-09 12:50 |

Quality flags count **nonduplicate rows before rejection**, may overlap and are not additive. Entity counts/date coverage describe all accepted classes. One additional description had an invalid scalar type; it became null with a separate audit flag. Zero accepted non-C returns is an observed result of these rules on this source, not a claim that physical returns did not occur: C-prefix rows are classified as cancellations, and non-C negative rows with invalid prices are quarantined. Credits are not matched to original orders.

Conservation: `541909 = 5268 + 5401 + 522572 + 8668 + 0`. Audit has one row for each original row. Full reasons, policies, country list and sequential stages are available in the ignored `quality.json`; no customer/source rows are copied into this document.

PostgreSQL verification after repeated official registration returned **1 dataset, 1 quality report, 3,928 product records**. The catalog contains all accepted products and is not a selected top-50 list.

## Measured timings

| Actual operation | Wall time reported by CLI |
| --- | ---: |
| First official archive download and extraction | 3.541 seconds |
| Final cleaning 1.0.1 cold XLSX ingestion | 39.247 seconds |
| Independent cold re-ingestion into a new output root | 34.819 seconds |
| Verified cached-source checksum lookup | 0.052 seconds |
| Cached dataset verification + first database registration | 0.887 seconds |
| Cached dataset verification + repeated database registration | 0.932 seconds |

These are individual measurements on this host, not portable performance promises or isolated database benchmarks. They exclude dependency installation. No model, feature, forecasting, API or business benchmark exists yet.

## Run and test commands

All commands below were run from the repository root. Development credentials are the literal local-only values in `.env.example`. Shell inspection/file reads are omitted; setup, execution, tests and diagnostic failures are included. Repeated identical invocations are listed once.

Environment inspection:

```bash
pwd
git status --short --branch
git --version
python3 --version
python3.12 --version
node --version
npm --version
docker --version
docker compose version
psql --version
pg_config --version
docker context ls
docker info --format '{{json .ServerVersion}}'
python3.12 --version
node --version
```

Setup (the first editable install preceded package creation, so it was repeated after scaffolding):

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --cache-dir .cache/pip -e '.[dev]'
.venv/bin/python -m pip freeze --exclude-editable
.venv/bin/python -m pip install --cache-dir .cache/pip -r requirements-dev.lock
.venv/bin/python -m pip install --cache-dir .cache/pip --no-deps --no-build-isolation -e .
.venv/bin/python -m pip install --no-index --cache-dir .cache/pip -r requirements-dev.lock
.venv/bin/python -m pip check
```

The first `--no-build-isolation` attempt failed because setuptools was not yet installed; installing the full lock resolved it, and the repeated editable install passed. README instructions install the lock first. An initial direct script invocation before the editable package was refreshed failed with `ModuleNotFoundError`; subsequent documented direct commands passed.

Official-source and database execution:

```bash
# Initial source acquisition used an explicit import path during scaffolding:
PYTHONPATH=. .venv/bin/python scripts/download_data.py
.venv/bin/python scripts/download_data.py --expected-sha256 f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b
.venv/bin/python scripts/ingest_data.py --input 'data/raw/uci-online-retail/Online Retail.xlsx'
.venv/bin/python scripts/ingest_data.py --input 'data/raw/uci-online-retail/Online Retail.xlsx' --output-dir data/repro-check
docker compose up -d postgres
docker compose config --quiet
docker compose ps
DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq .venv/bin/python -m alembic -c backend/alembic.ini upgrade head
DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq .venv/bin/python scripts/ingest_data.py --input 'data/raw/uci-online-retail/Online Retail.xlsx' --persist
docker compose exec -T postgres psql -U demandiq -d demandiq -Atc 'SELECT version();'
docker compose exec -T postgres psql -U demandiq -d demandiq -Atc 'SELECT (SELECT count(*) FROM datasets), (SELECT count(*) FROM data_quality_reports), (SELECT count(*) FROM products);'
docker version --format '{{.Server.Version}}'
```

Artifact reproducibility verification was executed as this inline Python command:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from ml.data.acquisition import sha256_file
version = '3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d'
a = Path('data/processed') / version
b = Path('data/repro-check') / version
assert b.is_dir()
comparison = {p.name: sha256_file(p) == sha256_file(b / p.name)
              for p in sorted(a.iterdir()) if p.is_file()}
assert all(comparison.values())
print(comparison)
PY
```

Tests and quality checks (focused tests ran while implementation proceeded):

```bash
.venv/bin/python -m pytest ml/tests/test_cleaning.py
.venv/bin/python -m pytest backend/tests/test_db.py -q
.venv/bin/python -m pytest ml/tests backend/tests
.venv/bin/python -m pytest ml/tests backend/tests -m 'not integration'
TEST_DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test .venv/bin/python -m pytest ml/tests backend/tests
.venv/bin/python -m ruff check backend
.venv/bin/python -m black --check backend
.venv/bin/python -m ruff check ml/data/schema.py ml/data/cleaning.py ml/tests/test_cleaning.py ml/data/__init__.py ml/__init__.py
.venv/bin/python -m black ml/data/schema.py ml/data/cleaning.py ml/tests/test_cleaning.py ml/data/__init__.py ml/__init__.py
.venv/bin/python -m ruff check . --fix
.venv/bin/python -m black .
.venv/bin/python -m ruff check .
.venv/bin/python -m black --check .
```

Docker/network/fallback diagnostics, followed by cleanup:

```bash
curl -I --max-time 20 'https://archive.ics.uci.edu/static/public/352/online+retail.zip'
open -a Docker
open '/Applications/Docker.app/Contents/MacOS/Docker Desktop.app'
'/Applications/Docker.app/Contents/MacOS/Docker Desktop.app/Contents/MacOS/Docker Desktop' --version
.venv/bin/python -m pip install --cache-dir .cache/pip --target .cache/pg-tools pgserver==0.1.4
.cache/pg-tools/pgserver/pginstall/bin/postgres --version
.cache/pg-tools/pgserver/pginstall/bin/initdb -D .cache/pgdata -U demandiq --auth=trust --no-locale -E UTF8
.cache/pg-tools/pgserver/pginstall/bin/pg_ctl -D .cache/pgdata -l .cache/postgres.log -o '-F -p 55432 -h 127.0.0.1 -k /private/tmp' -w start
.cache/pg-tools/pgserver/pginstall/bin/createdb -h 127.0.0.1 -p 55432 -U demandiq demandiq_test
.cache/pg-tools/pgserver/pginstall/bin/createdb -h 127.0.0.1 -p 55432 -U demandiq demandiq
.cache/pg-tools/pgserver/pginstall/bin/pg_ctl -D .cache/pgdata -m fast -w stop
```

Sandbox network restrictions caused the initial curl, initial initdb shared-memory operation and native createdb connections to fail. Approved network/server commands succeeded; no automatic approval review rejected an action. Docker then became available, so the native fallback was stopped without creating application databases. It is an ignored verification tool, not a project dependency. The Compose service remains running and local metadata is preserved.

## Complete test results

The full PostgreSQL run produced:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-8.3.5, pluggy-1.7.0
rootdir: /path/to/demandiq
configfile: pyproject.toml
plugins: platformdirs-4.13.4
collected 182 items

ml/tests/test_acquisition.py .............                               [  7%]
ml/tests/test_cleaning.py .............................................. [ 32%]
........................................................................ [ 71%]
                                                                         [ 71%]
ml/tests/test_ingestion.py ...............                               [ 80%]
backend/tests/test_db.py ....................................            [100%]

============================= 182 passed in 7.43s ==============================
```

| Suite | Passed | Scope |
| --- | ---: | --- |
| Acquisition | 13 | Official URL, checksums, cache, corrupt/path-traversal/multi-member archives, size/truncation limits, retries and interrupted streams |
| Cleaning/schema | 118 | Strict columns/types, identifiers, exact duplicates, cancellation/return precedence, missingness, quantities/prices, dates, privacy, audit, report and deterministic output |
| Ingestion/IO/CLI | 15 | XLSX/CSV/Parquet, leading zeros, malformed input, duplicate headers, conservation, immutable versions, artifact/cache metadata integrity, publication failure, DB retry and safe errors |
| Database | 36 | 21 validation/offline cases and 15 real PostgreSQL migration, drift, constraints, foreign-key/cascade, idempotency/conflict, rollback and concurrency cases |
| **Total** | **182** | **0 failed, 0 skipped** |

Intermediate runs before PostgreSQL was available reported 146 passed/15 skipped; after final cleaning/regression additions the offline run reported 167 passed/15 deselected. Those are intermediate results, not additional independent tests. Final Ruff output: `All checks passed!`; Black: all 21 Python files unchanged; Compose config exited 0; pip check: `No broken requirements found.`

## Files created

The repository was empty apart from `.git`, so all project files are new. No pre-existing application files were modified.

```text
.env.example
.gitignore
PROJECT_SPEC.md
README.md
pyproject.toml
requirements-dev.in
requirements-dev.lock
docker-compose.yml
docker/postgres/init-test-db.sql
backend/__init__.py
backend/app/__init__.py
backend/app/db/__init__.py
backend/app/db/models.py
backend/app/db/repository.py
backend/alembic.ini
backend/alembic/env.py
backend/alembic/script.py.mako
backend/alembic/versions/0001_data_foundation.py
backend/tests/test_db.py
ml/__init__.py
ml/data/__init__.py
ml/data/acquisition.py
ml/data/cleaning.py
ml/data/io.py
ml/data/schema.py
ml/pipelines/__init__.py
ml/pipelines/ingestion.py
ml/tests/test_acquisition.py
ml/tests/test_cleaning.py
ml/tests/test_ingestion.py
scripts/download_data.py
scripts/ingest_data.py
docs/IMPLEMENTATION_PLAN.md
docs/DATA_DICTIONARY.md
docs/DATA_PIPELINE.md
docs/PHASE1_RESULTS.md
```

Ignored local outputs include `.venv/`, dependency caches, the stopped native test cluster, downloaded raw source, processed datasets, a second reproducibility dataset, tool caches and the PostgreSQL Docker volume. None were added to Git. No commits, remotes or pushes were created.

## Assumptions, limitations and unresolved work

- No unresolved Phase 1 test failures or database blockers remain. Compose startup, migration and persistence were exercised; the full application/container workflow is not implemented yet.
- Strict column matching rejects unexpected fields rather than silently discarding them. Date strings are ISO or explicit day-first; aware timestamps are quarantined. Source dates remain naive London wall time.
- Missing customer/description/country values are retained; invalid optional scalar values become null and are flagged. Nonpositive prices are quarantined even for negative/cancellation movements. Nine explicitly listed fee/accounting codes are excluded; unusual valid merchandise quantities are retained.
- Hashing customer IDs is pseudonymization, not guaranteed anonymization; the small original identifier space is guessable. Raw and processed data must remain private local artifacts, not public exports or logs.
- The source does not prove physical returns or cancellation matching. Exact-source duplicates may include legitimate identical line items; the chosen removal policy is explicit and auditable.
- XLSX loading and row audits are in memory; large-source streaming beyond this official workbook is future work. No claim of arbitrary dataset scale is made.
- First download uses trust on first acquisition. Expected checksum support pins the measured official archive for future runs. The lock is tested on Python 3.12/macOS ARM64; conditional Linux/Windows dependencies are pinned but those Python environments were not tested.
- Immutable artifact publication and DB registration are separate transactions; a DB outage may leave verified files awaiting a retry. Database artifact paths require the configured processed root to remain available.
- The demonstration database uses local-only credentials and no authentication layer for the future app. No inventory facts, forecasts, ML metrics, business savings or user interface exist yet.
- Phases 2–6, their tests, API/frontend documentation, ML model card, inventory formulas/defaults, screenshots and complete Compose application remain planned, with explicit verification gates in the implementation plan.

## Exact recommended next prompt

> Begin DemandIQ Phase 2 only. Read PROJECT_SPEC.md, README.md, docs/IMPLEMENTATION_PLAN.md, docs/DATA_PIPELINE.md, and docs/PHASE1_RESULTS.md first, then inspect the repository and rerun the Phase 1 checks. Implement product-level weekly aggregation with continuous zero-filled weeks and separate gross units, returned units, cancellation units, net units, revenue, transactions, known unique customers and average price. Define and document chronological train/validation/test dates before selecting the configurable top 50 eligible products using training data only. Add naive, four-week moving-average and a justified seasonal-naive baseline, leakage-safe lag/rolling features, at least three expanding-window backtesting folds if the available history supports them, and MAE/RMSE/WAPE/sMAPE/bias reports with initial plots from real runs. Keep preprocessing and product selection inside each training boundary, test future-perturbation invariance and zero-demand cases, document partial weeks and insufficient annual history, and preserve the test block for final evaluation after model selection. Update documentation and run all relevant tests. Do not start Phase 3, create a remote repository, commit or push. Report files, exact commands, complete test results, real measured baseline results, assumptions, limitations and unresolved problems.

<!-- Public release note: machine-specific paths and example passwords were normalized; recorded measurements are unchanged. -->
