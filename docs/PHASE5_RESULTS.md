# Phase 5 results — backend application

Verified on 2026-10-20. Phase 5 is complete; Phase 6 remains unstarted. No commits, remote repository or pushes were created. All ML/inventory source, frozen forecasting/inventory artifacts and evaluation ledgers were preserved.

## Implemented

- FastAPI system, dataset/quality/product/history, training/model, forecast/value, inventory/scenario/result, CSV and job endpoints; strict Pydantic bodies, bounded lists, safe error responses, CORS, request size limits and generated OpenAPI/Swagger/ReDoc.
- PostgreSQL persistence for nine application tables in static migration `0002_application`, extending the three Phase 1 tables. Database constraints enforce lineage, finite ordered uncertainty, whole-unit demand conservation, relative artifact paths and valid leases.
- Separate durable worker: atomic `SKIP LOCKED` claims, canonical idempotency, database-clock leases, heartbeats, bounded attempts/backoff, expired-owner recovery and atomic resource-registration/success. Stale workers cannot commit results. IO/database/pool timeouts are retryable; validation/integrity failures expose permanent static codes.
- Existing/file/checksum-pinned official imports, new pre-test training or frozen-run registration, real saved-model inference plus three baselines, verified retrospective evaluation registration and existing inventory simulation orchestration. No endpoint reevaluates the final forecasting test.
- Structured request/job logs omit bodies, raw queries, customer records, credentials and exception details. The unexpected-error ASGI boundary prevents Uvicorn from logging the original private traceback. Already-started responses close with a static error because sent bytes cannot be replaced.
- Reproducible HTTP demonstration and integration tests, documentation, environment settings and pinned backend dependencies. Raw/generated data, models, logs and local environments remain ignored.

The synthetic integration workflow performs actual three-family training, serialization, inference, a synthetic final evaluation, simulation and database/CSV reads. Its synthetic metrics are not evidence of official model performance. The live official-data demo registers the existing frozen training run rather than retuning it.

## Complete verification

Before Phase 5, all 848 existing tests passed in 17.30 s. Final result: **1173 passed in 26.83 s**, with zero failures, errors, skips or warnings. This is 848 existing tests plus 325 new tests. Collection identifies 164 PostgreSQL integration tests and 1009 other tests; all executed in the full run. Dedicated DB tests use `demandiq_test`, refuse non-`_test` databases and clear their own tables.

| New test module | Passed |
| --- | ---: |
| `backend/tests/test_api.py` |69|
| `backend/tests/test_application_db.py` |139|
| `backend/tests/test_application_services.py` |12|
| `backend/tests/test_forecasting_service.py` |22|
| `backend/tests/test_jobs.py` |46|
| `backend/tests/test_operation_integrity.py` |18|
| `backend/tests/test_worker.py` |19|
| Total added |325|

Migration0002 roundtrip, preservation of existing metadata, schema/default/type drift, foreign keys, numeric/path/lease constraints, concurrent enqueue/claim, stale ownership, callback rollback, retry bounds, dependency failure, API validation, read/export fidelity and secret redaction all passed. Independent focused runs passed 139 database tests, 46 queue tests, 88 API/worker tests, 22 inference tests and 30 service/integrity tests. Ruff passed; Black reported 94 files unchanged; `pip check` found no broken requirements. A lock-file dry run found every applicable pin already satisfied.

Development failures were fixed before the final gate: Starlette required HTTPX2 for warning-free tests; a typed Parquet reason-list conversion initially failed CSV export; review found missing source/request identity checks, missing database503 handling, transient pool timeout classification and a generic server traceback leak. Regression tests now cover those cases. Early sandboxed localhost DB attempts failed before setup; authorized reruns succeeded. An exploratory command without `TEST_DATABASE_URL` correctly skipped two integrations; it is not counted as database verification.

All 151 protected files matched SHA-256 before/after: 52 ML Python files, 49 Phase 3 files, 48 Phase 4 files and 2 evaluation ledgers. The official final-test ledger remains completed and unchanged. Earlier [Phase 3](PHASE3_RESULTS.md) and [Phase 4](PHASE4_RESULTS.md) metrics retain their original meanings; no new forecast improvement or business savings is claimed.

Full final pytest output:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-8.3.5, pluggy-1.7.0
rootdir: /path/to/demandiq
configfile: pyproject.toml
plugins: platformdirs-4.13.4, anyio-4.15.1
collected 1173 items

ml/tests/test_acquisition.py .............                               [  1%]
ml/tests/test_baselines.py .............................                 [  3%]
ml/tests/test_cleaning.py .............................................. [  7%]
........................................................................ [ 13%]
                                                                         [ 13%]
ml/tests/test_features.py ..................................             [ 16%]
ml/tests/test_final_test.py ............................................ [ 20%]
..................................                                       [ 23%]
ml/tests/test_ingestion.py ...............                               [ 24%]
ml/tests/test_inventory_config.py ...................................... [ 27%]
..............................................................           [ 32%]
ml/tests/test_inventory_pipeline.py .................................... [ 36%]
..................                                                       [ 37%]
ml/tests/test_inventory_planning.py .................................... [ 40%]
...........                                                              [ 41%]
ml/tests/test_inventory_plots.py ........                                [ 42%]
ml/tests/test_inventory_simulation.py .................................. [ 45%]
.................                                                        [ 46%]
ml/tests/test_metrics.py .................................               [ 49%]
ml/tests/test_model_plots.py .....                                       [ 49%]
ml/tests/test_modeling_pipeline.py ...............                       [ 51%]
ml/tests/test_phase2_pipeline.py ...............                         [ 52%]
ml/tests/test_plots.py ..                                                [ 52%]
ml/tests/test_splits.py .....................                            [ 54%]
ml/tests/test_training.py .............................................. [ 58%]
.......................                                                  [ 60%]
ml/tests/test_uncertainty.py ...................                         [ 61%]
ml/tests/test_weekly.py ................................................ [ 65%]
......................................                                   [ 69%]
backend/tests/test_api.py .............................................. [ 73%]
.......................                                                  [ 75%]
backend/tests/test_application_db.py ................................... [ 78%]
........................................................................ [ 84%]
................................                                         [ 86%]
backend/tests/test_application_services.py ............                  [ 87%]
backend/tests/test_db.py ....................................            [ 91%]
backend/tests/test_forecasting_service.py ......................         [ 92%]
backend/tests/test_jobs.py ............................................. [ 96%]
.                                                                        [ 96%]
backend/tests/test_operation_integrity.py ..................             [ 98%]
backend/tests/test_worker.py ...................                         [100%]

============================ 1173 passed in 26.83s =============================
```

## Real HTTP demonstration

The final API and independent worker used real PostgreSQL 16.6 and the official frozen dataset/run. Five newly keyed jobs succeeded on their first attempt. Dataset registration verified 531240 accepted transactions and 3928 catalog products; training registration persisted three models and 2200 pre-test facts (50 products ×44 weeks). These are cached artifact registration counts, not newly measured XLSX-cleaning throughput or retraining performance.

| Job | Worker compute/registration seconds | HTTP submission-to-completion seconds |
| --- | ---: | ---: |
| dataset_import | 0.169003 | 0.846842 |
| training | 1.011899 | 2.107804 |
| forecasting (one_week) | 0.137341 | 1.064850 |
| forecasting (retrospective) | 0.169656 | 1.253135 |
| inventory (retrospective_simulation) | 0.180209 | 1.298742 |

A further default-key demo replay matched all final forecast/scenario resource IDs without duplicating those resources; its separate report is `artifacts/backend/demo-replay/report.json`.

Worker timing includes verified file computation/cache reuse and the fenced database transaction, excludes the queue wait, and is local-process timing. HTTP wall time includes the one-second polling scheduler and client status checks. The first historical forecast batch performs real inference at 2011-10-10, producing 300 rows (50 products × 6 methods) with null actuals. Retrospective registration persists 2400 previously evaluated rows. The scenario reuses the verified Phase 4 default simulation and persists 2000 weekly rows. Exports contain 2400 forecast, 2000 recommendation and 2000 weekly-result rows; CSV counts reconcile with persisted batch/scenario counts.

The default simulated ML cost remains GBP 194633.74 and fill rate 96.3749%, versus the matched mean policy's GBP 199496.02 and 94.4925%. The difference remains a retrospective simulated estimate with illustrative costs and terminal recoverability; Ridge still failed to beat the best point-forecast baseline on the final test. This backend run introduces no new evaluation.

Identifiers:

- One-week forecast: `b25c0d283935577f6b6c246ec5f11d15033e685b99c73524786477fc7ce4015c`
- Retrospective forecast: `1517ba6cfa906fa80c76501f1833bcadb0b0755b0961d8aaeb37ff99d65f7492`
- Backend scenario: `80b1e349a934aeb6870b32fcd11eb2436aa20694214275d4c421d9689a2faea9`
- Analytical inventory run: `a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967`

The backend scenario ID includes its forecast wrapper identity; the analytical inventory run remains unchanged. The point metric field `evaluation_scope` and uncertainty field `scope` both remain `test` in the retrospective metadata.

Warm sequential HTTP latency, 30 requests per endpoint, measured with `urllib.request` including connection/JSON decoding. P95 is the 29th sorted observation (nearest-rank). This is a local demonstration, not a load/concurrency benchmark:

| Endpoint | Median ms | P95 ms | Min ms | Max ms |
| --- | ---: | ---: | ---: | ---: |
| GET /health | 0.430 | 0.500 | 0.399 | 0.789 |
| GET /datasets | 1.810 | 4.479 | 1.561 | 5.053 |
| GET /forecasts/{id}/values?limit=100 | 5.646 | 10.282 | 5.138 | 10.846 |
| GET /inventory/scenarios/{id} | 5.476 | 8.702 | 4.979 | 9.096 |

Full machine-readable outputs are ignored locally at `artifacts/backend/demo/report.json` and its CSV siblings. Read [API.md](API.md) for request formats and setup. Existing prototype demo jobs/forecast wrappers remain versioned local records; use the final identifiers above or the versioned demo keys for the reviewed implementation.

## Files created or modified

Created:

- `backend/app/main.py`, `backend/app/worker.py`, `backend/app/db/session.py`
- `backend/app/api/__init__.py`, `backend/app/api/routes.py`
- `backend/app/core/__init__.py`, `backend/app/core/config.py`, `backend/app/core/logging.py`
- `backend/app/schemas/__init__.py`, `backend/app/schemas/requests.py`
- `backend/app/services/__init__.py`, `application.py`, `configuration.py`, `errors.py`, `forecasting.py`, `jobs.py`, `operations.py` in that services directory
- `backend/alembic/versions/0002_application.py`
- The seven new test modules in the table above
- `scripts/run_worker.py`, `scripts/demo_backend.py`
- `docs/API.md`, `docs/BACKEND_ARCHITECTURE.md`, `docs/PHASE5_RESULTS.md`

Modified: `.env.example`, `pyproject.toml`, `requirements-dev.lock`, `backend/app/db/models.py`, `README.md`, `docs/IMPLEMENTATION_PLAN.md`, `docs/DATA_DICTIONARY.md`. The original specification, Git ignore rules, original ML/inventory modules and earlier phase reports are unchanged. Generated reports/CSV/forecast artifacts and verification logs are private ignored outputs.

## Exact run and verification commands

Commands below run from the repository root with Python 3.12. The URLs contain documented local-only development credentials. API and worker are separate terminals; stop them with Ctrl-C after the demo. The verification API/worker were stopped after successful checks; PostgreSQL was left running. `DYLD_LIBRARY_PATH` is specific to the inspected Mac's pinned cached OpenMP library. A different supported OpenMP installation can omit that prefix.

```bash
# Dependencies added in this phase, then editable metadata refreshed:
.venv/bin/python -m pip install --cache-dir .cache/pip fastapi==0.154.0 pydantic==2.14.1 uvicorn==0.54.0 httpx==0.28.1
.venv/bin/python -m pip install --cache-dir .cache/pip httpx2==2.15.1
.venv/bin/python -m pip install --cache-dir .cache/pip --no-deps --no-build-isolation -e .
.venv/bin/python -m pip install --cache-dir .cache/pip --no-deps -r requirements-dev.lock --dry-run
.venv/bin/python -m pip check

# Actual runtime/database state:
.venv/bin/python --version
git --version
docker --version
docker compose version
docker compose ps
docker compose exec -T postgres postgres --version
git status --short
git remote -v

# Apply the tested application migration to the existing development database:
DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq' .venv/bin/python -m alembic -c backend/alembic.ini upgrade head

# Pre-implementation regression (848 passed) and final complete suite (1173 passed):
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test' .venv/bin/python -m pytest ml/tests backend/tests > .cache/phase5-prechecks.txt 2>&1
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test' .venv/bin/python -m pytest ml/tests backend/tests > .cache/phase5-tests.txt 2>&1
# Test-classification collection only; does not rerun test bodies:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest ml/tests backend/tests --collect-only -m integration -q

# Focused test commands used during development (DB commands need TEST_DATABASE_URL):
.venv/bin/python -m pytest backend/tests/test_application_db.py -q
.venv/bin/python -m pytest backend/tests/test_jobs.py -q
.venv/bin/python -m pytest backend/tests/test_api.py backend/tests/test_worker.py -q
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest backend/tests/test_forecasting_service.py -q
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test' .venv/bin/python -m pytest backend/tests/test_application_services.py -q
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test' .venv/bin/python -m pytest backend/tests/test_application_services.py backend/tests/test_operation_integrity.py -q
.venv/bin/python -m pytest backend/tests/test_operation_integrity.py -q
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest backend/tests/test_application_services.py -m 'not integration' -q
# Environment-absent exploratory collection/run skipped two integrations:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest backend/tests/test_application_services.py -m integration -q

# Final source quality (Ruff --fix and Black without --check were used while editing):
.venv/bin/ruff check .
.venv/bin/black --check .

# Terminal 1, final local API:
DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq' .venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log > .cache/phase5-api-final.log 2>&1
# Terminal 2, final independent worker:
DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq' DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m scripts.run_worker > .cache/phase5-worker-final.log 2>&1
# Terminal 3, final real-data demo and usage help:
.venv/bin/python -m scripts.demo_backend --idempotency-prefix phase5-final > .cache/phase5-demo-final.txt 2>&1
.venv/bin/python -m scripts.demo_backend --output-dir artifacts/backend/demo-replay > .cache/phase5-demo-replay.txt 2>&1
.venv/bin/python -m scripts.demo_backend --help
.venv/bin/python -m scripts.run_worker --help
```

An initial `.venv/bin/python -m scripts.demo_backend` succeeded before the final review fixes, with logs `.cache/phase5-{api,worker,demo}.*`; it is superseded by the final new-key run above. Direct read-only Python snippets also checked preserved SHA-256 files and inspected actual API metric scopes; neither recomputed metrics or modified frozen inputs.

Runtime: Python 3.12.14, Git 2.39.5, Docker 29.8.0, Compose 5.5.1, PostgreSQL 16.6 on macOS ARM64. Node 24.19.0 was verified during the earlier environment inspection; no Node/frontend work was performed in Phase 5. FastAPI 0.154.0, Pydantic 2.14.1, Uvicorn 0.54.0, Starlette 1.9.0 and HTTPX2 2.15.1 are pinned. The existing NumPy/scikit-learn/XGBoost/joblib graph is unchanged. HTTPX2 resolves the pinned Starlette TestClient's deprecated legacy-client fallback without suppressing warnings. Full installation from a clean container remains Phase 6 delivery verification; this run verified the existing environment, lock pins and actual backend behavior.

## Assumptions, limitations and unresolved problems

No unresolved Phase 5 test or integration failure remains. The local service has no authentication, per-user authorization, external broker, scheduler, job cancellation, retention UI or distributed artifact storage; these were not required for the authorized local MVP. Worker availability is operationally separate from API/database/storage readiness. Filesystem publication and DB commits cannot be one distributed transaction; complete orphan files are intentionally recoverable.

Only trusted local checksummed models are deserialized. Checksums detect changed bytes but do not make an untrusted pickle safe. Evaluation-ledger integrity depends on preserving the trusted local workspace. The one-week inference is anchored to historical frozen refitting; there is no latest-date forecasting/refitting service. Inventory remains retrospective, with the Phase 4 demand/lead-time/error/terminal-value assumptions unchanged. API CSVs may normalize textual date/list formatting while preserving numerical values and escaping formula-leading identifiers.

The dashboard, frontend tests, Playwright workflow, full application containers and clean Compose verification remain Phase 6. Dashboard-specific feature/importance projections and an interactive planner preview may require small backend read/preview endpoints using the already-tested analytical functions; they are not represented as completed UI functionality. MLflow remains deferred as previously documented. No automatic purchasing, authentication, cloud deployment or other excluded scope was added.

## Recommended next prompt

> Begin DemandIQ Phase 6 only. Read PROJECT_SPEC.md, README.md, docs/IMPLEMENTATION_PLAN.md, docs/API.md, docs/BACKEND_ARCHITECTURE.md and docs/PHASE5_RESULTS.md first. Inspect the repository and rerun the Phase 5 checks. Build the React/TypeScript dashboard's six specified pages against the real backend, adding necessary verified read projections and planner previews. Add accessible responsive interfaces, real CSV exports, React Testing Library and Playwright coverage, full API/worker/frontend/PostgreSQL Docker Compose delivery, screenshots and a reproducible demonstration. Preserve the frozen forecasting choices and completed evaluation ledger; do not reevaluate the official test, fabricate metrics/savings, commit, push or create a remote. Report files, exact commands, complete test results, measured timings, assumptions, limitations and unresolved problems.

<!-- Public release note: machine-specific paths and example passwords were normalized; recorded measurements are unchanged. -->
