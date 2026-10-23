# Historical development workflow

This preserves the pre-publication development manual. Start with the [current root README](../README.md) for the public synthetic demo, publication scope and setup. Older no-commit statements describe the original experiments, which were completed before public publication.

Sales forecasting and inventory decision support for a single retail location. The full requirements are in [PROJECT_SPEC.md](../PROJECT_SPEC.md); architecture, phase boundaries and verification gates are in [the implementation plan](IMPLEMENTATION_PLAN.md).

## Current status

**Phases 1–6 are complete for local delivery.** The project provides verified acquisition/cleaning, PostgreSQL metadata, continuous weekly facts, causal features, chronological baselines, three trained ML families, separate uncertainty calibration, saved models, a frozen final-test evaluation and configurable inventory planning/simulation. Phase 5 adds FastAPI, PostgreSQL application persistence, durable leased workers, real inference jobs and CSV APIs. The Phase 6 Python regression suite passed **1,250 tests in 87.21 seconds**, including 165 PostgreSQL integrations, with no failures, skips or warnings. The frontend passed **28 component tests** and **3 real-backend Playwright tests**, with twelve desktop/mobile accessibility scans, keyboard checks and responsive layout checks. See [Phase 1 results](PHASE1_RESULTS.md), [Phase 2 results](PHASE2_RESULTS.md), [Phase 3 results](PHASE3_RESULTS.md), [Phase 4 results and commands](PHASE4_RESULTS.md), [Phase 5 results and exact commands](PHASE5_RESULTS.md) and the [model card](MODEL_CARD.md).

Ridge was selected before final testing, but it **did not beat the best baseline on the final test**. Selection-validation WAPE was 53.52% for Ridge versus 60.22% for the four-week mean; final-test WAPE was 52.75% versus 51.97%, respectively. Each comparison uses 400 aligned observations per method within its own scope. The frozen choice was not revised using test results.

Phase 4 compares five policies using already-evaluated frozen forecasts and illustrative economic inputs under the [inventory protocol](INVENTORY_METHODOLOGY.md). Its cost differences are retrospective simulated estimates, not real company savings or evidence that Ridge improved final-test point accuracy. The six-page React/TypeScript dashboard connects to verified backend projections and immediate planner previews. Full Compose services, a trusted historical demo bundle and browser tests are implemented; final verification is recorded in [Phase 6 results](PHASE6_RESULTS.md). The initial six-phase instruction takes precedence over the different grouping in specification section 20. No commits, remote repository or pushes were created.

## Required software

- Python **3.12** with `venv` and pip.
- Docker Engine/Desktop with current Docker Compose for the full application; alternatively Python/Node and PostgreSQL 16 for native development. File ingestion works offline.
- Git. Node.js **24.15–24.x** and npm for native frontend development/testing; containers supply Node 24.19.0.
- An OpenMP runtime for XGBoost; macOS setup is documented below.

Verified environment (Phase 6, 2026-10-21): Git 2.39.5, default Python 3.9.6, bundled Python 3.12.14, bundled Node 24.19.0, Docker client/server 29.8.0, Compose 5.5.1 and containerized PostgreSQL 16.6. Python 3.12 and Node are absent from the default PATH. A host PostgreSQL installation is unnecessary with Compose.

## Run the application with Docker

```bash
cp .env.example .env
docker compose up --build
```

Open [DemandIQ](http://127.0.0.1:8080) and [API documentation](http://127.0.0.1:8080/api/docs). Without a prepared historical bundle, the application starts with an honest empty state. From this workspace's existing completed artifacts:

```bash
.venv/bin/python -m scripts.prepare_demo_bundle prepare
.venv/bin/python -m scripts.prepare_demo_bundle verify
docker compose --profile demo up --build
```

The demo registers the trusted dataset and frozen run, performs historical first-origin inference, reads completed retrospective predictions and runs an inventory simulation through the API/worker. It never reevaluates the official forecasting test. Click **Activate data → Activate historical sample** for the same workflow in the dashboard. Generated data/models and the private ignored bundle are intentionally absent from source control; a fresh source checkout needs its own trusted completed artifacts for this historical demo. See [delivery, backup and exact demonstration commands](DELIVERY.md), [the six-page user guide](USER_GUIDE.md) and [actual screenshots](screenshots/README.md).

Only loopback ports are published. Stop with `docker compose stop`; preserve named volumes and completed ledgers. Use a separate Compose project and free ports to test a fresh runtime without touching the existing database.

## Local setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
cp .env.example .env
```

On the inspected Codex host, Python 3.12 is available at `python3.12`. Use that executable for the first command if `python3.12` is not on PATH. The lock pins the tested Phase 1–5 dependency graph, including NumPy 2.3.5, scikit-learn 1.6.1, XGBoost 2.1.4, joblib and Matplotlib. Phase 4 adds no dependencies. Phase 5 adds pinned FastAPI, Pydantic, Uvicorn and HTTP test clients. HTTPX2 is required by the pinned Starlette TestClient; strict warning checks remain enabled. NumPy 2.3.5 replaced 2.2.3 after a numeric failure on the inspected Apple Silicon host. Run the commands below from the repository root. Module invocations also work on hosts where hidden editable-install `.pth` files are ignored.

The development lock is verified on Python 3.12/macOS ARM64. Phase 6 additionally builds and runs the full Linux ARM64 stack with `requirements-runtime.lock`; Linux x86_64/NCCL pins are recorded but that platform has not been executed here.

Local `.env` files are ignored. CLI configuration uses environment variables or explicit flags; load `.env` with `set -a; source .env; set +a` in a trusted local shell if needed. Never use production credentials for examples or tests.

On macOS, install OpenMP with Homebrew:

```bash
brew install libomp
```

Alternatively, on supported Apple Silicon macOS 15/26+, the optional helper retrieves a checksum-pinned official Homebrew library into the ignored project cache:

```bash
python -m scripts.setup_macos_openmp
export DYLD_LIBRARY_PATH="$PWD/.cache/libomp"
```

Keep that export in the shell used for training, evaluation and tests when using the cached library. The helper verifies cached archive/library provenance and changes no system directories.

## Data workflow

```bash
python -m scripts.download_data
python -m scripts.ingest_data --input 'data/raw/uci-online-retail/Online Retail.xlsx'
```

The download comes from UCI's official archive and is published atomically under `data/raw/uci-online-retail/`. XLSX and UTF-8 CSV inputs are supported. The first download records observed SHA-256 digests. Pin the verified archive version for later reproduction:

```bash
python -m scripts.download_data --expected-sha256 f5385cbb54bbebf7196389109c6b0621faab0c304e3702548165e71c84aede8b
# Inspect all options:
python -m scripts.download_data --help
python -m scripts.ingest_data --help
```

Imports create `data/processed/<dataset_id>/` with `purchases.parquet`, `cancellations.parquet`, `returns.parquet`, `audit.parquet`, `quality.json` and `manifest.json`. Each source row has an audited disposition; questionable values have explicit reason codes. Source checksum, input format and versioned cleaning configuration determine the dataset ID. Repeated imports verify and reuse completed artifacts. A corrupted cache fails explicitly; preserve it for investigation and use a new `--raw-dir` or `--output-dir` to rebuild.

Real customer IDs become linkable one-way pseudonyms in processed artifacts; these remain private local data. No raw rows, raw identifiers, generated datasets or model artifacts belong in Git. See [the data dictionary](DATA_DICTIONARY.md) and [cleaning policies](DATA_PIPELINE.md). The import command creates Phase 1 transactions; run Phase 2 separately below.

## Phase 2 development workflow

```bash
python -m scripts.run_phase2 \
  --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d
# Override the training-only product limit:
python -m scripts.run_phase2 \
  --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d \
  --top-products 100
python -m scripts.run_phase2 --help
```

Use the actual dataset directory printed by ingestion if its version differs. The verified default configuration is [configs/phase2.json](../configs/phase2.json); use `--config` with another JSON file to change dates, number of folds, history requirements, baseline windows or named ISO-week indicators. Product-limit precedence is `--top-products`, then `TOP_PRODUCTS`, then the config file's `top_products` (default 50).

Training covers weeks 2010-12-06 through 2011-07-11. Three expanding four-week validation folds cover 2011-07-18 through 2011-10-03. Phase 2 reserves weeks 2011-10-10 through 2011-11-28 for the separate Phase 3 final evaluation. Partial edge weeks are excluded. The Phase 2 runner applies a pre-test Parquet date filter before loading transactions and produces **no test-set metric**. The four-week seasonal recurrence is a configured comparison assumption, not evidence of actual seasonality; annual seasonality lacks sufficient training history.

Outputs go to ignored `data/phase2/<run_id>/`: weekly panel, initial/fold product lists, per-fold features, aligned validation predictions, training volumes, split/configuration metadata, metrics by model/fold/product/week/training-volume segment, a Markdown report and four PNG figures. Files and counts are verified on reuse; a second cold run generated byte-identical artifacts. No customer pseudonyms are carried into weekly outputs. See [methodology and leakage boundaries](FORECASTING_METHODOLOGY.md) for formulas, conventions and limitations.

The observed default validation WAPE was 57.77% for the four-week mean, 67.15% for naive and 71.30% for four-week recurrence, each on the same 600 product-week observations. This is a baseline comparison; it is not an ML or business-performance claim. Full MAE/RMSE/sMAPE/bias results and measured runtime are in [Phase 2 results](PHASE2_RESULTS.md).

## Phase 3 training and final evaluation

```bash
python -m scripts.train \
  --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d \
  --config configs/phase3.json
python -m scripts.train --help
```

The [Phase 3 configuration](../configs/phase3.json) preserves the chronological timeline, default 50-product limit and seed 42. Expanding folds 1–2 select two candidates per family for Ridge, Random Forest and XGBoost; fold 3 is reserved for uncertainty calibration after candidate choices are frozen. Random Forest is the permitted tree option and supplies native importance. Numeric imputation, Ridge scaling and product encoding fit inside each training pipeline. No current target enters predictors. Final models refit through 2011-10-03 and keep a cohort chosen from that pre-test history.

Training writes ignored `artifacts/phase3/<experiment_id>/` with candidate/selection/calibration metrics and predictions, frozen cohort/configuration/plan, three joblib models, native importance, pre-test forecasts and lineage metadata. Nominal 80% scaled-residual intervals use a separate chronological calibration block and are empirical estimates without coverage guarantees. JSON/Parquet and joblib provide local tracking; optional MLflow remains deferred to keep setup reliable. Read [ML methodology](ML_METHODOLOGY.md) and the [model card](MODEL_CARD.md) before interpreting results or loading trusted local model artifacts.

After training and all checks, evaluate the frozen run once. This is the verified official experiment; use the directory printed by training if reproducing another source/configuration:

```bash
python -m scripts.evaluate \
  --run-dir artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa \
  --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d
python -m scripts.evaluate --help
```

The official test evaluation is complete. Its files are under `artifacts/phase3/evaluations/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa/`. All six methods, model hashes, cohort, calibration and metrics protocol were frozen before test access. Test weeks use prior completed observations for one-week-ahead features/baselines, with no model refit or product reselection. Selection, calibration and test metrics stay separate; Phase 2's twelve-week baseline score is not the eight-week Phase 3 selection score.

A dataset-scoped ledger under `data/evaluation-ledger/` reserves the final test immediately before target access. Repeating a successful evaluation verifies and reuses completed artifacts; it does not read test targets again. Alternate experiments are refused after reservation. An interrupted running reservation remains blocked for manual investigation: preserve its ledger and partial outputs rather than deleting the guard or rerunning the test. This cooperative local guard depends on retaining one trusted ledger root. Further choices must not be tuned or reselected using the observed test result.

## Phase 4 inventory workflow

Run the default retrospective scenario against the completed frozen Phase 3 experiment:

```bash
.venv/bin/python -m scripts.run_inventory \
  --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa
# An explicitly labeled two-week lead-time sensitivity:
.venv/bin/python -m scripts.run_inventory \
  --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa \
  --config configs/phase4_lead2.json
# Exploratory cost sensitivity, added after the default/lead-time runs:
.venv/bin/python -m scripts.run_inventory \
  --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa \
  --config configs/phase4_high_holding.json
.venv/bin/python -m scripts.run_inventory --help
```

The default configuration is [configs/phase4.json](../configs/phase4.json); lead-time sensitivity uses [configs/phase4_lead2.json](../configs/phase4_lead2.json). The later [high-holding-cost configuration](../configs/phase4_high_holding.json) is explicitly exploratory: it changes holding cost to 0.10/unit/week after observing the other scenario outcomes, without changing the forecast or default controller. It is neither a predeclared untouched evaluation nor a policy-tuning result. Phase 4 verifies the completed evaluation ledger, frozen plan and all artifact hashes. It reads existing Parquet predictions and pretest/calibration facts, does not load XGBoost models, and needs neither an OpenMP runtime nor a running database. It does not retrain models, reopen forecasting model selection, change Phase 3 artifacts or create another untouched test.

Five policies share initial stock, historical demand and business assumptions: previous-demand ordering, four-week-mean ordering, a fixed reorder-point controller, the validation-selected ML forecast with safety stock, and a matched four-week-mean safety-stock controller. The matched controller helps distinguish a forecast-input comparison from comparing different complete ordering policies. No policy or parameter is optimized using the simulated outcomes.

An order placed after demand in week `t` with lead time `L` arrives before demand at `t+L+1`: `L=1` waits through one complete future demand week and receives at `t+2`. Reorder demand covers `L` weeks; target protection covers `L+R`. Only the next-week forecast is available at each review, so later horizon weeks use an explicitly labeled flat carry-forward approximation. There are no final-week orders; orders due beyond the horizon remain outstanding and valued.

The completed default run is `a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967` under ignored `artifacts/phase4/`. Each run contains configuration, source lineage, derived product inputs, demand, weekly stock/cost records, orders, recommendations, summary/report, three PNG figures and CSV exports. Repeating the same command verifies/reuses its completed cache. For an independent cold build, supply a different output root:

```bash
.venv/bin/python -m scripts.run_inventory \
  --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa \
  --output-dir artifacts/phase4-cold
```

The default simulated comparison uses 50 fixed products and eight historical weeks:

| Policy | Net inventory cost (GBP) | Gross cash cost (GBP) | Fill rate | Average on-hand units |
| --- | ---: | ---: | ---: | ---: |
| ML with safety stock | 194,633.74 | 265,044.74 | 96.3749% | 65,510.875 |
| Matched four-week mean with safety stock | 199,496.02 | 267,782.02 | 94.4925% | 55,387.625 |

The default matched comparison's signed simulated net-cost difference is **GBP 4,862.28 (2.4373%)** in favor of the ML policy. ML also holds more average inventory. Net cost credits closing on-hand and pipeline at full purchase cost; the gross cash totals above expose that different accounting view. Method-specific pretest error buffers and these terminal-recovery/economic assumptions influence the outcome. This does not establish a point-forecast improvement or realized savings. With lead time two weeks, ML's simulated net cost is GBP 232,351.38 and fill rate 85.6473%; the matched controller's cost is GBP 233,982.84, a smaller GBP 1,631.46 (0.6973%) gap. At the exploratory holding cost of 0.10/unit/week, ML instead costs GBP 1,616.60 more than the matched mean controller; order quantities are unchanged because costs are scored rather than optimized. Full five-policy comparisons, commands and limitations are in [Phase 4 results](PHASE4_RESULTS.md).

## Inventory configuration

Scenario JSON has `name`, a three-letter uppercase `currency` label, `initial_coverage_weeks` (default 2), `defaults` and `products`. Default starting stock is `ceil(initial_coverage_weeks × pretest weekly mean)`; source inventory and purchase costs are unavailable. All monetary values below are illustrative GBP amounts, not retailer facts.

| `defaults` parameter | Default / units |
| --- | --- |
| `lead_time_weeks`, `review_period_weeks` | 1, 1; positive whole weeks |
| `service_level` | 0.95; normal approximation input in `(0,1)`, not a realized-service guarantee |
| `unit_purchase_cost`, `unit_selling_price` | 1.00, 2.00 per unit |
| `holding_cost_per_unit_week` | 0.02 per ending on-hand unit/week |
| `stockout_penalty_per_unit` | 3.00 per lost unit; lost margin is reported separately |
| `order_cost` | 5.00 per positive placed order |
| `min_order_quantity`, `case_pack_size` | 0, 1 whole units |
| `max_inventory_capacity` | `null`; otherwise reserves on-hand plus all outstanding units |
| `fixed_reorder_point`, `fixed_target_level` | Both `null`, or both nonnegative with target ≥ reorder point; override only the fixed policy |

`products` maps existing frozen-cohort stock codes to optional `parameters`, `initial_on_hand`, `initial_orders` and `backordered_units`. Parameter overrides use the same fields as `defaults`. Initial orders are prepaid dated receipts; stock/backlog/order quantities are whole units bounded by `2^53-1`. The planner supports backorder subtraction, but the lost-sales simulator requires `backordered_units=0`. A positive order must meet MOQ, pack and available capacity together; infeasible MOQ/capacity returns zero with reasons.

Ordering is rule-based: forecast, stock position, service/error assumptions, lead/review periods and quantity constraints determine units. Economic inputs change cost/revenue scoring; they do not automatically optimize order quantities or tune the controller. The high-holding scenario exposes this stock-cost sensitivity rather than claiming a cost-optimal purchasing policy.

For example, the following illustrative override uses product `84077`, which belongs to the documented frozen cohort. Save it as `.cache/scenario_override.json` (ignored) and supply that path with `--config`; use a code from your own frozen `cohort.json` for a different source. A [worked business scenario](EXAMPLE_SCENARIO.md) separately explains an actual generated historical recommendation.

```json
{
  "name": "illustrative_product_override",
  "currency": "GBP",
  "initial_coverage_weeks": 2.0,
  "defaults": {"lead_time_weeks": 1},
  "products": {
    "84077": {
      "initial_on_hand": 100,
      "initial_orders": [{"week": "2011-10-17", "quantity": 24}],
      "backordered_units": 0,
      "parameters": {
        "service_level": 0.95,
        "min_order_quantity": 12,
        "case_pack_size": 6,
        "max_inventory_capacity": 1000,
        "fixed_reorder_point": 100,
        "fixed_target_level": 200
      }
    }
  }
}
```

Normal safety stock uses empirical error magnitudes from the separate pretest calibration period; it assumes stable independent errors. Fill rate, weekly no-stockout service and the configured service-level factor are different quantities. The primary terminal-adjusted cost, cash cost, prepaid pipeline treatment, terminal recoverability, lost-margin separation and every default are specified in [inventory methodology](INVENTORY_METHODOLOGY.md).

## PostgreSQL development

```bash
docker compose up -d postgres
# Wait for the service to report healthy:
docker compose ps
# In a trusted local shell, load the development .env created during setup:
set -a
source .env
set +a
python -m alembic -c backend/alembic.ini upgrade head
python -m scripts.ingest_data --input 'data/raw/uci-online-retail/Online Retail.xlsx' --persist
```

Use `docker compose up -d postgres` for database-only native development. The default Compose now provides the complete application. Use environment variables for connection details. Migrations must run before persistence. Imports without `--persist` require no database. Metadata, the aggregate quality report and the full accepted product catalog are written in one transaction. Identical registrations are idempotent, including concurrent imports; conflicting immutable metadata raises an error. Files are published first, so a database outage can be retried with the same command.

The default credentials are local development values and PostgreSQL binds to `127.0.0.1`. Change them before using a shared environment. A fresh Compose volume also creates `demandiq_test`; on an existing volume create a dedicated test database manually. `docker compose stop postgres` stops the service while preserving local data. Avoid deleting the named volume if you need the stored metadata.

## Backend development (Phase 5)

Migrate PostgreSQL as above, then run the API and worker in separate activated terminals with the same local environment:

```bash
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
# Second terminal; retain DYLD_LIBRARY_PATH on the inspected Mac:
python -m scripts.run_worker
# Third terminal, after the official frozen artifacts/ledger exist:
python -m scripts.demo_backend
```

Open [API docs](http://127.0.0.1:8000/docs). The service provides datasets/quality/products, asynchronous training and forecasting, saved-model metadata, inventory scenarios, CSV exports and job status. `/health` checks liveness; `/ready` checks PostgreSQL, migration and writable storage. No worker is started implicitly. See [API requests and reproducible demo](API.md) and [transaction/lease design](BACKEND_ARCHITECTURE.md).

The official one-week inference origin is historical **2011-10-10**, with unknown actuals in that batch. Retrospective jobs read the completed evaluation without reevaluating its test. Inventory outputs retain their simulated, assumption-driven labels. Full weekly accounting facts are exposed for the pre-test period; no missing test revenue or credit measures are fabricated. The backend is a trusted local service without authentication; bind to loopback. The React client is served by Vite in development or the Compose Nginx service.

## Frontend development

With the native API, worker and PostgreSQL running, use another terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open [the development dashboard](http://127.0.0.1:5173). Vite proxies `/api` to `http://127.0.0.1:8000`; `API_PROXY_TARGET` changes that development target. Export frontend settings in the shell, or place them in ignored `frontend/.env.local`; Vite does not automatically load the repository-root `.env`. `VITE_API_BASE_URL` defaults to `/api` and is a build-time public setting. Hash routes provide Overview, Data quality, Forecast explorer, Inventory planner, Scenario comparison and Model performance. Shared typed requests handle safe errors, cancellation, polling and real CSV downloads. Page bundles load on demand; Recharts provides charts backed by tables. No source customer identifiers are exposed.

```bash
npm run lint
npm run format:check
npm test
npm run build
npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080 npm run test:e2e
```

Playwright requires the complete running backend/worker stack and prepared historical demo. The main workflow uses real HTTP jobs and downloaded CSVs. Component fixtures and one browser dependency-failure injection test check behavior; they do not supply model or business results. Automated accessibility checks complement keyboard and responsive checks and are not full accessibility certification.

## Configuration

| Variable | Purpose / development default |
| --- | --- |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Compose initialization; `demandiq`, `CHANGE_ME_LOCAL_ONLY`, `demandiq` |
| `POSTGRES_PORT` | Local database port; `5432` |
| `API_PORT`, `FRONTEND_PORT` | Compose loopback ports; `8000`, `8080` |
| `API_ROOT_PATH` | Native API default empty; Compose sets `/api` for proxy documentation |
| `VITE_API_BASE_URL`, `API_PROXY_TARGET` | Public frontend API base `/api`; development proxy target `http://127.0.0.1:8000` |
| `DEMANDIQ_DEMO_BUNDLE_DIR`, `DEMANDIQ_IMAGE_TAG` | Compose bundle mount `./.cache/demo-bundle`; local image tag `local` |
| `DATABASE_URL` | API, workers, migrations and `--persist`; PostgreSQL psycopg URL from [.env.example](../.env.example) |
| `TEST_DATABASE_URL` | Disposable database ending `_test`; integration tests migrate and clear DemandIQ tables there |
| `DEMANDIQ_DATA_DIR` | Data root; `data` (CLI directory flags override it) |
| `DEMANDIQ_ARTIFACT_DIR` | Backend private analytical/model root; `artifacts` |
| `DEMANDIQ_LEDGER_DIR` | Backend frozen evaluation ledger; `data/evaluation-ledger` |
| `JOB_MAX_ATTEMPTS`, `JOB_LEASE_SECONDS`, `JOB_POLL_SECONDS` | Worker bounds/lease/polling; `3`, `60`, `1` |
| `MAX_REQUEST_BYTES` | API body limit; `1048576` |
| `CORS_ORIGINS` | Comma-separated allowed frontend origins; local port5173 |
| `TOP_PRODUCTS` | Phase 2/3 product limit selected from training history; default 50; freeze before final testing |
| `DYLD_LIBRARY_PATH` | Optional macOS cached OpenMP path; `$PWD/.cache/libomp` after the helper |

Artifact paths in database manifests are relative dataset IDs; retain or relocate the corresponding processed root along with database metadata. Phase 5 registers training-scoped weekly facts, models, forecasts and scenarios in PostgreSQL while retaining private analytical files under configured roots. Phase 3 uses explicit `--output-dir`, `--phase2-dir` and `--ledger-dir` options for those roots. Phase 4 uses JSON scenario configuration plus `--phase3-run`, `--config`, `--output-dir` and `--ledger-dir`; its inventory controls are documented above.

## Testing and development commands

```bash
# Activate the repository's Python 3.12 environment:
source .venv/bin/activate
# On the inspected macOS host when using the cached OpenMP helper:
export DYLD_LIBRARY_PATH="$PWD/.cache/libomp${DYLD_LIBRARY_PATH:+:$DYLD_LIBRARY_PATH}"
python -m pytest ml/tests backend/tests -m 'not integration'
python -m ruff check .
python -m black --check .
# Run against a disposable PostgreSQL database after setting TEST_DATABASE_URL:
python -m pytest backend/tests -m integration
# Or run the complete Phase 1–6 Python suite with TEST_DATABASE_URL set:
python -m pytest ml/tests backend/tests
# Focused inventory tests (no XGBoost model loading):
python -m pytest ml/tests/test_inventory_*.py
python -m pip check
```

Tests use synthetic fixtures. Without `TEST_DATABASE_URL`, database tests are explicitly skipped; a skip is not a PostgreSQL pass. Phase 5's final run passed **1,173 tests in 26.83 seconds**, including **164 PostgreSQL integrations**, with zero failures, skips or warnings. Ruff passed, Black left 94 files unchanged, and `pip check` was clean. The 325 new tests cover durable claims/retries/leases, atomic persistence, migration/drift/constraints, HTTP validation/redaction/readiness, real inference, integrity boundaries and exports. All 151 protected ML source/artifact/ledger files stayed unchanged. No test reevaluates the official held-out block.

The live HTTP demo completed five jobs, persisted 300 historical one-week and 2,400 retrospective forecasts, and exported 2,000 recommendations and weekly results. It measured local warm read latency with 30 requests per endpoint; full measurements, exact commands, file list, complete pytest output and limitations are in [Phase 5 results](PHASE5_RESULTS.md). Earlier phase reports preserve their original measured outcomes. Phase 6 adds 77 Python tests, 28 component tests and 3 real-backend browser tests. Full final output, twelve automated accessibility scans, exact commands and screenshots are recorded in [Phase 6 results](PHASE6_RESULTS.md).

## Dataset and limitations

Chen, D. (2015). *Online Retail* [Dataset]. UCI Machine Learning Repository. [DOI: 10.24432/C5BW33](https://doi.org/10.24432/C5BW33), [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). [Official source](https://archive.ics.uci.edu/dataset/352/online+retail).

The source is historical UK retail transaction data, with accounting cancellations/returns and incomplete customer coverage. It does not include observed inventory, supplier lead times, purchase costs or true unmet demand. Phase 4 therefore treats recorded purchases as demand and labels all business outcomes as simulations under configurable assumptions. Its eight-week horizon, method-specific error buffers and full closing-inventory recoverability limit interpretation. DemandIQ is decision support; automated purchasing is out of scope.

<!-- Public release note: machine-specific paths and example passwords were normalized; recorded measurements are unchanged. -->
