# Phase 6 — dashboard and local delivery

Verification date: 2026-10-21. **Phase 6 is complete for the documented local ARM64 delivery scope.** No known functional blockers remain; platform, data and methodological limits are listed below.

## Implemented behavior

The React 19/TypeScript/Vite application has six real-backend pages: executive overview, data quality, forecast explorer, inventory planner, scenario comparison and model performance. Typed requests, abortable resource loading, request-bound planner results, dataset/run selection, safe errors, durable-job progress, empty states and CSV downloads are shared. Pages load on demand. Recharts renders verified historical/forecast/simulation values with numerical tables; native controls, keyboard navigation, a focus-managed activation dialog, reduced motion and responsive layouts support access.

Activation registers the existing dataset and frozen run, generates the first historical post-refit forecast, reads completed retrospective predictions and runs the inventory scenario. It does not submit a new modeling search or final-test evaluation. Alternative import and existing-run controls are available. The dashboard selects the resources returned by successful activation instead of retaining an unrelated prior selection.

New backend projections verify file inventories/checksums, completion ledgers, database/file agreement and bounded result sizes before exposing context, run evidence, product forecasts/features or scenario summaries/risk. The stateless planner calls the existing Phase 4 recommendation function. It uses the fixed first origin and pretest calibration errors; later test residuals do not enter its uncertainty estimate. Its normal approximation to next-week shortage and short-horizon cost estimates are labeled assumptions, not observed or guaranteed outcomes. Export endpoints return genuine CSV values and escape spreadsheet formula-leading identifiers.

Full Compose delivery includes PostgreSQL, an ownership initializer, migrations, FastAPI, a separate durable worker, Nginx/React and an optional five-job demo bootstrap. API/worker use a read-only image and shared named runtime volumes; published ports bind to loopback. Same-origin `/api` proxying includes functional OpenAPI/docs root paths. Python/runtime and Node/npm package graphs are pinned. Docker build contexts exclude private data, models, ledgers, secrets and local caches.

The trusted demonstration bundle is copied from completed local artifacts. Only its copied ledger's absolute results path is relocated to `/runtime`; original bytes and original/relocated provenance hashes are retained. This does not create another untouched test. The original ledger SHA-256 is `2e9b78c5a2ba3d74c8ab6369608cbef307bdec340a2bb9a26433e46329f5edb2`; the explicitly relocated copy is `01b267227b0c9a50e51e8ebd3a97f60f95b8625fc552acec5e0891b3b0ae1126`. A source checkout without these deliberately ignored artifacts starts with an empty application, not invented models or results. See [delivery](DELIVERY.md), [user guide](USER_GUIDE.md), [API](API.md) and [architecture](BACKEND_ARCHITECTURE.md).

## Verification scope and preserved forecasting choices

Before Phase 6, all **1173 existing tests passed in 55.46 s**. The final Python regression run passed **1250 tests in 87.21 s**, with **165 PostgreSQL integration tests** and no failures, skips or warnings. Phase 6 adds 55 dashboard/preview tests and 22 bundle tests. Strict Python warning checks remain enabled. Ruff, Black (102 files), and `pip check` pass.

No official training selection or test evaluation was rerun. The dataset is `3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d`; the frozen run is `6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa`. The original forecasting result remains: Ridge selection-validation WAPE 53.52% versus mean 60.22%; final-test WAPE 52.75% versus mean 51.97%. Ridge did not beat that baseline on the final test, and the UI says so. Equal scores are described as tied.

A SHA-256 snapshot covers **163 original ML source/test, model, analytical, forecast-wrapper and evaluation-ledger files**. They matched byte-for-byte after implementation and verification. No Git commit, push or remote was created. Existing development PostgreSQL storage was retained.

The actual Docker demo registered 531240 accepted records, 3928 catalog products, a frozen 50-product cohort, 2200 pretest weekly facts and three models; it persisted 300 first-origin inference rows and 2400 completed retrospective predictions. It exported 2400 forecast rows, 2000 recommendation rows and 2000 weekly simulation rows. Five newly keyed jobs succeeded on their first attempt. Job wait times below include enqueue/polling and verified artifact reuse; they are not new training benchmarks:

| Operation | Observed wait seconds |
| --- | ---: |
| Dataset registration | 0.880054 |
| Frozen-run registration | 1.088487 |
| First-origin forecasting job | 1.064691 |
| Completed retrospective registration | 1.072411 |
| Inventory simulation registration | 1.069481 |

The report is ignored `artifacts/phase6/compose-final-demo-report.json`. A prior bootstrap replay is separately retained as `compose-demo-report.json`; its shorter waits are not evidence of cold computation. The same default simulated outcomes as Phase 4 were verified: ML net cost GBP 194633.74, fill rate 96.3749%, versus matched mean net cost GBP 199496.02 and fill 94.4925%. The GBP 4862.28 difference is a retrospective simulated estimate with illustrative economics and full terminal recovery, not achieved company savings. Wrapper IDs change with the explicitly relocated ledger hash; frozen predictions/metrics do not.

Fresh project-scoped Compose volumes were exercised for the historical demo (`demandiq-phase6-check`) and separately for an application with no bundle (`demandiq-phase6-empty`). Initializer/migration/demo exit codes were zero; API/frontend/PostgreSQL health passed and the worker completed real jobs. The empty application's health/readiness return 200, dataset/run lists are empty, projections contain null resources/empty products, and the browser shows “Your workspace starts with data.” Neither test deletes or replaces development data.

## Measured dashboard timings

These are 30 sequential local warm HTTP samples per operation after one excluded warm-up, including connection/transfer/JSON decode. Other process activity was not controlled. They measure verified projections, not concurrent load capacity. Raw samples, environment and resource IDs are in ignored `artifacts/phase6/dashboard-benchmark.json`.

| Operation | Median ms | Nearest-rank P95 ms |
| --- | ---: | ---: |
| Workspace context | 532.596 | 601.223 |
| Frozen run evidence | 143.827 | 211.741 |
| Product forecast | 61.734 | 66.269 |
| Scenario projection | 348.945 | 373.551 |
| Stateless planner preview | 62.048 | 64.548 |

The final browser workflow took **13.352 seconds**, including real jobs, preview changes, simulation and CSV downloads. The complete three-test browser suite passed in **36.2 seconds**. All six pages passed automated axe checks at both 1440×1000 and 390×844 (12 scans, zero violations), mobile page-width checks and fresh-document keyboard skip-link navigation. Eight real screenshots were captured and visually inspected. The following single warm navigation samples were measured:

| Page | Observed navigation ms |
| --- | ---: |
| Overview | 1396.786 |
| Data quality | 832.150 |
| Forecast explorer | 819.905 |
| Inventory planner | 820.392 |
| Scenario comparison | 830.300 |
| Model performance | 832.905 |

Navigation samples include verified data reads; one sample per page is not a load benchmark. Existing ingestion/training/feature/batch timings remain in their original phase reports; no modeling benchmark was invented in Phase 6.

## Exact run and verification commands

Commands run from the repository root unless noted. Python is `.venv/bin/python` 3.12.14. The host has Node 24.19.0 outside PATH and checksum-verified npm 11.6.2 in the ignored tool cache. For an ordinary installation, `npm` from Node 24 is equivalent to the explicit host CLI below. Important executable commands used during implementation and final verification follow; repetitive file reads/status inspection are omitted.

```bash
git status --short
git remote -v
git --version
.venv/bin/python --version
node --version
docker version
docker compose version
docker compose exec -T postgres psql -U demandiq -d demandiq -c 'SELECT version();'

# Before implementation, with the unchanged Phase 5 suite:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test' .venv/bin/python -m pytest ml/tests backend/tests > .cache/phase6-prechecks.txt 2>&1

# Final complete Python checks:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test' .venv/bin/python -m pytest ml/tests backend/tests > .cache/phase6-tests-final.txt 2>&1
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest ml/tests backend/tests --collect-only -m integration -q > .cache/phase6-integration-count.txt
.venv/bin/ruff check .
.venv/bin/black --check .
PIP_CACHE_DIR="$PWD/.cache/pip" .venv/bin/python -m pip check

# Focused implementation checks (database tests were not run concurrently):
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL='postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test' .venv/bin/python -m pytest backend/tests/test_dashboard.py -q
.venv/bin/python -m pytest backend/tests/test_dashboard.py -m 'not integration' -q
.venv/bin/python -m pytest backend/tests/test_demo_bundle.py -q
.venv/bin/python -m pytest backend/tests/test_api.py backend/tests/test_worker.py -q

.venv/bin/python -m scripts.prepare_demo_bundle prepare
.venv/bin/python -m scripts.prepare_demo_bundle verify
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check --profile demo up --build -d
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check --profile demo ps -a
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check logs --tail=15 api worker
# Subsequent frontend-only review/fix builds:
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check up --build -d --no-deps frontend
# Five new keys; reuses and verifies existing frozen analytical artifacts:
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check --profile demo run --rm --no-deps demo python -m scripts.bootstrap_demo --bundle-dir /opt/demo-bundle --base-url http://api:8000 --output-dir /runtime/artifacts/backend/phase6-final-demo --idempotency-prefix phase6-final-verification
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check cp api:/runtime/artifacts/backend/phase6-final-demo/report.json artifacts/phase6/compose-final-demo-report.json

mkdir -p .cache/empty-demo-bundle
POSTGRES_PORT=55433 API_PORT=58001 FRONTEND_PORT=58081 DEMANDIQ_IMAGE_TAG=phase6 DEMANDIQ_DEMO_BUNDLE_DIR=./.cache/empty-demo-bundle docker compose -p demandiq-phase6-empty up -d

.venv/bin/python -m scripts.benchmark_dashboard --base-url http://127.0.0.1:58000 --samples 30 > .cache/phase6-dashboard-benchmark-output.json

# From frontend/, with the bundled host Node directory on PATH:
export PATH="/path/to/node/bin:$PATH"
node ../.cache/tools/npm/package/bin/npm-cli.js test
node ../.cache/tools/npm/package/bin/npm-cli.js run lint
node ../.cache/tools/npm/package/bin/npm-cli.js run format:check
node ../.cache/tools/npm/package/bin/npm-cli.js run build
node ../.cache/tools/npm/package/bin/npm-cli.js audit --registry=https://registry.npmjs.org
node ../.cache/tools/npm/package/bin/npm-cli.js exec -- prettier --write src/styles.css src/components/UI.tsx e2e/dashboard.spec.ts playwright.config.ts
# Matching Playwright Chromium binary, installed once in the ignored cache:
PLAYWRIGHT_BROWSERS_PATH="$PWD/../.cache/playwright" node node_modules/playwright/cli.js install chromium
env -u NO_COLOR PLAYWRIGHT_BROWSERS_PATH="$PWD/../.cache/playwright" PLAYWRIGHT_BASE_URL=http://127.0.0.1:58080 node ../.cache/tools/npm/package/bin/npm-cli.js run test:e2e
# Focused accessibility/layout iteration:
env -u NO_COLOR PLAYWRIGHT_BROWSERS_PATH="$PWD/../.cache/playwright" PLAYWRIGHT_BASE_URL=http://127.0.0.1:58080 node ../.cache/tools/npm/package/bin/npm-cli.js run test:e2e -- --grep 'all six pages'
```

Docker's frontend stage runs `npm ci --no-audit --no-fund` followed by `npm run build`; the Python stage installs the exact runtime lock and checks dependencies. The final npm audit separately reports zero vulnerabilities. Standard host commands (`npm ci`, `npm test`, etc.) are in [README](../README.md) and [delivery](DELIVERY.md).

The preservation check used SHA-256 against the pre-implementation snapshot:

```bash
.venv/bin/python - <<'PY'
import hashlib, json
from pathlib import Path
files = json.loads(Path('.cache/phase6-source-snapshot.json').read_text())
changed = [p for p, h in files.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest() != h]
print({'protected_files': len(files), 'changed_or_missing': changed})
assert not changed
PY
```

## Assumptions, limitations and unresolved problems

- The sample is historical, with the first inference origin 2011-10-10. No current-date business forecast, real company stock or achieved savings is claimed. Short annual history, empirical interval limits, flat multiweek carry-forward and terminal-recovery assumptions remain in the model/inventory documentation.
- Linux ARM64 full application and macOS ARM64 development were exercised. AMD64 packages are pinned, but AMD64 execution, Safari and Firefox were not tested here. Image version tags and Python/npm dependencies are pinned; OS package repositories remain external build inputs.
- The historical demo needs trusted completed private/local artifacts. They are not committed, embedded into images or publicly hosted. Hash checks do not make an untrusted joblib pickle safe; retain the original ledger and coordinated runtime/database backups.
- The planner is a rule-based controller with configurable economics, not a cost optimizer. Its shortage estimate is a normal approximation excluding undated incoming inventory; its short-horizon cost preview is separate from chronological simulation totals. Simulation requires zero backorders and dated prepaid receipts for on-order units.
- UI simulation defaults apply to the whole fixed cohort; selected-product opening stock is an override. Cross-configuration comparisons are sensitivity exercises, not new untouched forecasting or policy evaluations. Screenshots follow the real browser workflow's altered assumptions, so their simulated KPIs can differ from the original default scenario.
- Dashboard projection bounds are 500 products, 100000 rows and 1040 weeks. Local warm context median is about 0.53 s because source/ledger verification is repeated; no capacity or production SLA is asserted. The UI job-poll window is ten minutes; leaving the page stops observation, not a durable worker job.
- Automated axe checks, keyboard checks and mobile overflow checks do not replace a complete assistive-technology audit. Charts include tabular alternatives. MLflow remains the previously documented optional deferral; reliable local tracking is implemented.
- Authentication, cloud deployment, ERP integration, automated purchasing and other excluded scope remain excluded. Local Compose credentials must be URL-safe; loopback binding is intentional.

Initial browser verification exposed contrast issues, a product-control test locator issue and mobile table overflow. They were corrected and the relevant checks rerun. No failed result is represented as a pass. Final unresolved-problem status follows the completed verification block below.

## Files created or modified

No original ML source, model, prediction, official evaluation or original ledger file was modified. Source additions/edits for this phase:

Created:

- `.dockerignore`
- `backend/Dockerfile`
- `backend/app/api/dashboard.py`
- `backend/app/schemas/dashboard.py`
- `backend/app/services/dashboard.py`
- `backend/tests/test_dashboard.py`
- `backend/tests/test_demo_bundle.py`
- `docker/nginx.conf`
- `docs/DELIVERY.md`
- `docs/PHASE6_RESULTS.md`
- `docs/USER_GUIDE.md`
- `docs/screenshots/README.md`
- `frontend/.prettierignore`
- `frontend/.prettierrc.json`
- `frontend/Dockerfile`
- `frontend/e2e/dashboard.spec.ts`
- `frontend/eslint.config.js`
- `frontend/index.html`
- `frontend/package-lock.json`
- `frontend/package.json`
- `frontend/playwright.config.ts`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/components/Activation.tsx`
- `frontend/src/components/Charts.tsx`
- `frontend/src/components/UI.tsx`
- `frontend/src/components/Workspace.tsx`
- `frontend/src/components/format.ts`
- `frontend/src/hooks/useResource.ts`
- `frontend/src/main.tsx`
- `frontend/src/pages/DataQuality.tsx`
- `frontend/src/pages/ForecastExplorer.tsx`
- `frontend/src/pages/InventoryPlanner.tsx`
- `frontend/src/pages/Overview.tsx`
- `frontend/src/pages/Performance.tsx`
- `frontend/src/pages/Scenarios.tsx`
- `frontend/src/styles.css`
- `frontend/src/types/api.ts`
- `frontend/tests/App.test.tsx`
- `frontend/tests/client.test.tsx`
- `frontend/tests/fixtures.ts`
- `frontend/tests/setup.ts`
- `frontend/tsconfig.json`
- `frontend/vite.config.ts`
- `requirements-runtime.lock`
- `scripts/benchmark_dashboard.py`
- `scripts/bootstrap_demo.py`
- `scripts/prepare_demo_bundle.py`

Modified:

- `.env.example`
- `.gitignore`
- `README.md`
- `docker-compose.yml`
- `backend/app/core/config.py`
- `backend/app/main.py`
- `docs/API.md`
- `docs/BACKEND_ARCHITECTURE.md`
- `docs/IMPLEMENTATION_PLAN.md`
- `docs/DATA_DICTIONARY.md`

Generated documentation screenshots:

- `docs/screenshots/data-quality-desktop.png`
- `docs/screenshots/forecasts-desktop.png`
- `docs/screenshots/inventory-desktop.png`
- `docs/screenshots/inventory-mobile.png`
- `docs/screenshots/overview-desktop.png`
- `docs/screenshots/overview-viewport.png`
- `docs/screenshots/performance-desktop.png`
- `docs/screenshots/scenarios-desktop.png`

These cover six full desktop pages, the overview viewport and the mobile inventory planner. Local evidence (`artifacts/phase6/`, `.cache/`) stays ignored.


## Complete final test output

### Complete Python suite

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-8.3.5, pluggy-1.7.0
rootdir: /path/to/demandiq
configfile: pyproject.toml
plugins: platformdirs-4.13.4, anyio-4.15.1
collected 1250 items

ml/tests/test_acquisition.py .............                               [  1%]
ml/tests/test_baselines.py .............................                 [  3%]
ml/tests/test_cleaning.py .............................................. [  7%]
........................................................................ [ 12%]
                                                                         [ 12%]
ml/tests/test_features.py ..................................             [ 15%]
ml/tests/test_final_test.py ............................................ [ 19%]
..................................                                       [ 21%]
ml/tests/test_ingestion.py ...............                               [ 22%]
ml/tests/test_inventory_config.py ...................................... [ 26%]
..............................................................           [ 30%]
ml/tests/test_inventory_pipeline.py .................................... [ 33%]
..................                                                       [ 35%]
ml/tests/test_inventory_planning.py .................................... [ 38%]
...........                                                              [ 39%]
ml/tests/test_inventory_plots.py ........                                [ 39%]
ml/tests/test_inventory_simulation.py .................................. [ 42%]
.................                                                        [ 43%]
ml/tests/test_metrics.py .................................               [ 46%]
ml/tests/test_model_plots.py .....                                       [ 46%]
ml/tests/test_modeling_pipeline.py ...............                       [ 48%]
ml/tests/test_phase2_pipeline.py ...............                         [ 49%]
ml/tests/test_plots.py ..                                                [ 49%]
ml/tests/test_splits.py .....................                            [ 51%]
ml/tests/test_training.py .............................................. [ 54%]
.......................                                                  [ 56%]
ml/tests/test_uncertainty.py ...................                         [ 58%]
ml/tests/test_weekly.py ................................................ [ 61%]
......................................                                   [ 64%]
backend/tests/test_api.py .............................................. [ 68%]
.......................                                                  [ 70%]
backend/tests/test_application_db.py ................................... [ 73%]
........................................................................ [ 79%]
................................                                         [ 81%]
backend/tests/test_application_services.py ............                  [ 82%]
backend/tests/test_dashboard.py ........................................ [ 85%]
...............                                                          [ 86%]
backend/tests/test_db.py ....................................            [ 89%]
backend/tests/test_demo_bundle.py ......................                 [ 91%]
backend/tests/test_forecasting_service.py ......................         [ 93%]
backend/tests/test_jobs.py ............................................. [ 96%]
.                                                                        [ 97%]
backend/tests/test_operation_integrity.py ..................             [ 98%]
backend/tests/test_worker.py ...................                         [100%]

======================= 1250 passed in 87.21s (0:01:27) ========================
```

### React Testing Library / Vitest

```text
> demandiq-frontend@1.0.0 test
> vitest run


 RUN  v5.0.5 /path/to/demandiq/frontend


 Test Files  2 passed (2)
      Tests  28 passed (28)
   Start at  12:37:38
   Duration  7.67s (tests 62%, environment 28%, setup 5%, import 3%, transform 1%)
```

### Playwright against Docker API/worker/PostgreSQL

```text
> demandiq-frontend@1.0.0 test:e2e
> playwright test


Running 3 tests using 1 worker

  ✓  1 e2e/dashboard.spec.ts:31:1 › real dataset activation → frozen run → forecast → inventory → comparison → CSV (13.7s)
  ✓  2 e2e/dashboard.spec.ts:156:1 › all six pages render real data, pass automated accessibility checks and fit mobile (19.8s)
  ✓  3 e2e/dashboard.spec.ts:237:1 › proxy serves live OpenAPI and the UI handles dependency failure safely (1.4s)

  3 passed (36.2s)
```

### Ruff

```text
All checks passed!
```

### Black

```text
All done! ✨ 🍰 ✨
102 files would be left unchanged.
```

### Python dependency check

```text
No broken requirements found.
```

### ESLint

```text
> demandiq-frontend@1.0.0 lint
> eslint . --max-warnings 0
```

### Prettier

```text
> demandiq-frontend@1.0.0 format:check
> prettier --check .

Checking formatting...
All matched files use Prettier code style!
```

### TypeScript and production build

```text
> demandiq-frontend@1.0.0 build
> tsc --noEmit && vite build

vite v8.3.4 building client environment for production...
transforming...
✓ 2516 modules transformed.
rendering chunks...
computing gzip size...
dist/index.html                             0.62 kB │ gzip:   0.38 kB
dist/assets/index-CEtybsg-.css             20.72 kB │ gzip:   5.44 kB
dist/assets/search-DdUTjyZR.js              0.20 kB │ gzip:   0.18 kB
dist/assets/ForecastExplorer-Cqw14fWZ.js    5.74 kB │ gzip:   2.19 kB
dist/assets/DataQuality-BFDQguGp.js         6.23 kB │ gzip:   2.19 kB
dist/assets/Overview-DQknDA5e.js            7.47 kB │ gzip:   2.74 kB
dist/assets/Scenarios-BV7fxzbD.js          10.33 kB │ gzip:   3.15 kB
dist/assets/InventoryPlanner-s-AeeKO3.js   10.39 kB │ gzip:   3.98 kB
dist/assets/Performance-e0o9tKES.js        10.91 kB │ gzip:   3.59 kB
dist/assets/index-Bh1L6V0a.js             251.65 kB │ gzip:  79.58 kB
dist/assets/Charts-sB27cqnd.js            404.00 kB │ gzip: 114.58 kB

✓ built in 574ms
```

### npm advisory audit

```text
found 0 vulnerabilities
```

All final checks passed. No test warnings, skips or failures remain. The initial browser iterations are retained under ignored `.cache/phase6-playwright-*-iteration.txt` and were superseded by the complete passing final run. No official test evaluation was invoked.


## Final runtime state

Both temporary verification projects were stopped successfully with their volumes retained. The pre-existing development PostgreSQL service remains running. No `down -v`, volume deletion, original-ledger change or database reset was performed. Healthy service/one-shot snapshots and stop logs are retained under ignored `.cache/phase6-compose-status.txt`, `.cache/phase6-empty-status.txt`, `.cache/phase6-compose-stop.txt` and `.cache/phase6-empty-stop.txt`.

Exact teardown commands:

```bash
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check --profile demo stop
POSTGRES_PORT=55433 API_PORT=58001 FRONTEND_PORT=58081 DEMANDIQ_IMAGE_TAG=phase6 DEMANDIQ_DEMO_BUNDLE_DIR=./.cache/empty-demo-bundle docker compose -p demandiq-phase6-empty stop
```

Restart the already-built, already-verified historical demo without deleting anything:

```bash
POSTGRES_PORT=55432 API_PORT=58000 FRONTEND_PORT=58080 DEMANDIQ_IMAGE_TAG=phase6 docker compose -p demandiq-phase6-check --profile demo up -d
```

Then open `http://127.0.0.1:58080`. For a fresh ordinary project, use the complete preparation/build commands in [delivery](DELIVERY.md). The final preservation check again found all 163 protected files unchanged. There are no unresolved functional blockers within the tested local delivery scope; the explicitly listed limitations remain.

<!-- Public release note: machine-specific paths and example passwords were normalized; recorded measurements are unchanged. -->
