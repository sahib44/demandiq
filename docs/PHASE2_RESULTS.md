# Phase 2 delivery record

Verified 2026-10-18, America/New_York. Phase 2 only is complete; no Phase 3 model has been started. Results below come from actual official-source runs. No test-set score or business savings are claimed.

## Implementation

- Complete Monday-start product-week panels with zero-demand weeks and separate gross units, returned units, cancellation units, signed net units, gross purchase revenue, purchase line-item counts, known unique purchasers and weighted average selling price.
- Training-only eligibility/ranking with deterministic tie-breaking, configurable default top 50 and explicit minimum history. Product cohorts are reselected at each expanding training boundary and frozen within that fold.
- Explicit versioned chronological configuration, three expanding validation folds and a reserved eight-week test block.
- Leakage-safe lags, shifted rolling means/standard deviations, trend, historical revenue/price/transaction/customer covariates, separate return/cancellation rates and known calendar/optional ISO-week indicators. Warm-up and undefined values remain null; no imputation, encoding or scaling is fitted.
- Last-observed, four-week mean and configurable seasonal-naive recurrence baselines, all one week ahead with strict history bounds.
- JSON-safe MAE, RMSE, WAPE, sMAPE and signed bias; reports by model, fold, product, week and training-volume segment; under/overforecast counts and magnitudes.
- Four standalone deterministic PNG figures, a generated Markdown report, immutable source/config/runtime-derived artifacts, hashes/count checks and atomic publication.
- A reproducible CLI; focused synthetic tests, future-perturbation checks, full Phase 1 regression and real PostgreSQL integration verification.

Architecture and formulas are documented in [the methodology](FORECASTING_METHODOLOGY.md), [data dictionary](DATA_DICTIONARY.md) and [implementation plan](IMPLEMENTATION_PLAN.md). Phase 2 analytical outputs remain Parquet/JSON files. Weekly database persistence, fitted models and the application are future integration work.

## Dates fixed before selection

All dates are **week starts**, Monday 00:00 London wall time. Each week's upper timestamp bound is the following Monday, exclusive.

| Block | First week | Last week | Weeks |
| --- | --- | --- | ---: |
| Initial training | 2010-12-06 | 2011-07-11 | 32 |
| Validation | 2011-07-18 | 2011-10-03 | 12 |
| Reserved test | 2011-10-10 | 2011-11-28 | 8 |

| Fold | Training start | Training end | Validation start | Validation end | Products |
| --- | --- | --- | --- | --- | ---: |
| 1 | 2010-12-06 | 2011-07-11 | 2011-07-18 | 2011-08-08 | 50 |
| 2 | 2010-12-06 | 2011-08-08 | 2011-08-15 | 2011-09-05 | 50 |
| 3 | 2010-12-06 | 2011-09-05 | 2011-09-12 | 2011-10-03 | 50 |

The partial source weeks beginning 2010-11-29 and 2011-12-05 are excluded. The runner filters Parquet **before loading** to `2010-12-06 <= invoice_date < 2011-10-10`. The held-out target block has no Phase 2 weekly panel, features, predictions or scores. Source-wide file hashing and date-coverage metadata checks do not interpret its target values. The original Phase 1 source artifacts still contain the complete historical dataset, as intended.

Each validation prediction uses only weeks already completed. Prior validation actuals can inform a later one-week forecast. Product ranking and volume segments use that fold's expanding training period, not the validation weeks being scored. A synthetic test changes all reserved test quantities and verifies identical validation facts, selections, features, forecasts and metrics.

## Official run and reproducibility

Source dataset ID: `3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d` (official source provenance in [Phase 1 results](PHASE1_RESULTS.md)).

Phase 2 implementation version: `1.0.1`.

Final run ID: `889a5f5aa212e096168042ee16313072b9c1474b5ea9f7e4faa4f4b9188ad335`.

Default output: `data/phase2/<run_id>/`; independent cold reproduction: `data/phase2-repro-check/<run_id>/`. All **17 files**, including the manifest and four PNG figures, had identical SHA-256 digests between those cold runs. A pre-final development run under version 1.0.0 may remain in ignored local artifacts; it is not the delivered run.

| Measured artifact fact | Value |
| --- | ---: |
| Pre-test products with accepted activity | 3,772 |
| Continuous weeks per product | 44 |
| Weekly panel rows | 165,968 |
| Zero gross-demand product-weeks | 87,242 |
| Missing selling-price observations, matching zero-gross weeks | 87,242 |
| Products selected per fold | 50 / 50 / 50 |
| Distinct products across all fold cohorts | 55 |
| Products common to all three folds | 44 |
| Fold 1/2 and fold 2/3 cohort intersections | 46 / 48 |
| Forecast observations per baseline | 600 |
| Validation rows including all three baselines | 1,800 |
| Fold training-volume rows | 150 |
| Feature rows by fold (training + its validation) | 1,800 / 2,000 / 2,200 |

The 3,772-product panel is historical pre-test context, not a selected forecasting cohort. Aggregate validation metrics describe the fold-specific top-product policy. All three methods share the same cohort within each fold. Changing cohorts mean a single pooled number should not be presented as performance on one fixed basket.

## Measured validation baseline results

| Method | MAE, units | RMSE, units | WAPE, % | sMAPE, % | Bias, units |
| --- | ---: | ---: | ---: | ---: | ---: |
| Four-week moving average | 225.1271 | 371.3434 | 57.7745 | 58.1823 | -9.4279 |
| Last observed demand | 261.6633 | 445.6451 | 67.1508 | 64.3035 | -11.9533 |
| Four-week seasonal recurrence | 277.8483 | 476.3330 | 71.3044 | 67.5852 | -16.2417 |

Bias is mean `prediction - actual`; negative values indicate underforecasting. WAPE is a percentage with no upper bound, and is null when total actual is zero. sMAPE is in [0, 200]%, with a zero/zero pair contributing zero. No ordinary MAPE is used. All methods have 600 aligned validation observations. Detailed fold/product/week/segment/error-direction records remain in `metrics.json` and real row-level forecasts in `validation_predictions.parquet`.

The moving average has the lowest measured overall validation error among these three candidates. This does not establish test performance, prove an ML model will improve, or demonstrate inventory savings. The seasonal comparator assumes a four-week recurrence solely as a predeclared comparison. Four weeks are not a calendar month. Initial training contains 32 weeks, so an annual 52-week seasonal-naive baseline is unsupported and no annual-seasonality claim is made.

Four visually inspected figures are generated from these actual predictions: `baseline_metrics.png` (WAPE/RMSE), `validation_demand.png` (observed/forecast totals and MAE by week with fold boundaries), `residuals_and_bias.png` (residuals and under/overforecast units), and `product_errors.png` (MAE for products chosen by training volume). The product plot does not cherry-pick validation errors. Figures are private local analytical outputs, not fabricated application screenshots.

## Measured timings

| Operation | First final cold run | Independent cold run |
| --- | ---: | ---: |
| Filtered IO + validation + weekly aggregation | 1.704349 s | 1.802646 s |
| Per-fold feature generation | 0.202532 s | 0.201003 s |
| Baseline prediction calls | 0.106227 s | 0.105016 s |
| Plot generation | 0.696860 s | 0.688679 s |
| Complete runner | 6.294426 s | 6.348034 s |

These are individual measurements on Python 3.12.14/macOS ARM64 and include the specific stage boundaries in code. The complete runner also verifies source/artifact hashes, computes metrics and writes files. The feature number covers three fold-scoped panels, not every pre-test product. This is neither a universal throughput benchmark nor a model-training measurement. Runtime durations are logged separately from deterministic files.

## Complete verification results

Before implementation, all **182 Phase 1 tests passed in 5.78 seconds**, with real PostgreSQL 16.6 and zero skips. Existing Ruff, Black, dependency and Compose configuration checks also passed.

After implementation, the combined command collected **402 tests** and finished:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-8.3.5, pluggy-1.7.0
rootdir: /path/to/demandiq
configfile: pyproject.toml
plugins: platformdirs-4.13.4
collected 402 items

============================= 402 passed in 18.59s =============================
```

| Test file | Passed |
| --- | ---: |
| `ml/tests/test_acquisition.py` | 13 |
| `ml/tests/test_baselines.py` | 29 |
| `ml/tests/test_cleaning.py` | 118 |
| `ml/tests/test_features.py` | 34 |
| `ml/tests/test_ingestion.py` | 15 |
| `ml/tests/test_metrics.py` | 33 |
| `ml/tests/test_phase2_pipeline.py` | 15 |
| `ml/tests/test_plots.py` | 2 |
| `ml/tests/test_splits.py` | 21 |
| `ml/tests/test_weekly.py` | 86 |
| `backend/tests/test_db.py` | 36 |
| **Total** | **402** |

**0 failed, 0 skipped, 0 warnings in the complete test run.** The total includes 182 existing tests and 220 new tests. The database cases exercised real migration roundtrips, drift, constraints, rollback and concurrent idempotency. No test block was evaluated to produce these results; synthetic test fixtures are distinct from the official reserved test data.

New tests cover hand-calculated weekly measures, inserted zero weeks, signed accounting movements, missing customer/price behavior, int64 and revenue overflow, chronology, train-only ranking, future introductions/volume, strict forecast histories, leakage perturbations, window boundaries, zero-demand metrics, training-only segments, exact large-integer ranking, independent plot/report consistency, deterministic cold reruns, malformed cache metadata, missing plot inventory, atomic failure cleanup and CLI limit precedence.

Final Ruff: `All checks passed!`. Black: **39 Python files unchanged**. `pip check`: `No broken requirements found.` Compose configuration exited 0. All four actual-run figures were opened and visually inspected. No browser/frontend tests apply yet because those phases remain unimplemented.

## Exact run and test commands

Commands were run from `/path/to/demandiq`. Repeated identical commands are listed once; ordinary source-file reads are omitted. The literal database password below is the development-only value in `.env.example`.

Regression/environment checks:

```bash
git status --short --branch
git remote -v
.venv/bin/python --version
docker compose config --quiet
docker compose ps
docker compose exec -T postgres psql -U demandiq -d demandiq -Atc 'SELECT version();'
TEST_DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test .venv/bin/python -m pytest ml/tests backend/tests
.venv/bin/python -m ruff check .
.venv/bin/python -m black --check .
.venv/bin/python -m pip check
```

Dependency/setup commands:

```bash
.venv/bin/python -m pip install --cache-dir .cache/pip matplotlib==3.10.1
.venv/bin/python -m pip install --cache-dir .cache/pip pyparsing==3.2.1
.venv/bin/python -m pip install --cache-dir .cache/pip --no-index -r requirements-dev.lock
.venv/bin/python -m pip install --cache-dir .cache/pip --no-deps --no-build-isolation -e .
# Diagnostic attempt for the host's hidden editable-install path file:
.venv/bin/python -m pip install --cache-dir .cache/pip --no-deps --no-build-isolation --config-settings editable_mode=compat -e .
chflags nohidden .venv/lib/python3.12/site-packages/__editable__.demandiq-0.1.0.pth
.venv/bin/python scripts/download_data.py --help
.venv/bin/python scripts/run_phase2.py --help
```

The initially resolved pyparsing 3.3.3 caused a Matplotlib deprecation to fail strict test collection. It was replaced with compatible 3.2.1; warnings were not suppressed. The macOS host marks the editable-install `.pth` file hidden, causing direct script imports to fail intermittently even after a diagnostic unhide/compat install. The documented **module commands from the project root** avoid that environment-specific path-file dependency and passed. No system Python files or global packages were modified.

Focused tests and formatting run during implementation:

```bash
.venv/bin/python -m pytest ml/tests/test_splits.py
.venv/bin/python -m pytest ml/tests/test_features.py ml/tests/test_baselines.py -q
.venv/bin/python -m pytest ml/tests/test_weekly.py -q
.venv/bin/python -m pytest ml/tests/test_cleaning.py ml/tests/test_weekly.py -q
.venv/bin/python -m pytest ml/tests/test_metrics.py ml/tests/test_plots.py -q
.venv/bin/python -m pytest ml/tests/test_weekly.py ml/tests/test_features.py ml/tests/test_baselines.py ml/tests/test_splits.py
.venv/bin/python -m pytest ml/tests/test_phase2_pipeline.py ml/tests/test_splits.py
.venv/bin/python -m ruff check ml/features ml/models ml/tests/test_features.py ml/tests/test_baselines.py
.venv/bin/python -m black --check ml/features ml/models ml/tests/test_features.py ml/tests/test_baselines.py
.venv/bin/python -m ruff check . --fix
.venv/bin/python -m black .
```

Official baseline execution, cold reproduction and verified cache:

```bash
.venv/bin/python -m scripts.run_phase2 --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d
.venv/bin/python -m scripts.run_phase2 --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d --output-dir data/phase2-repro-check
```

Cold-run integrity comparison:

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from ml.data.acquisition import sha256_file
run_id = '889a5f5aa212e096168042ee16313072b9c1474b5ea9f7e4faa4f4b9188ad335'
a = Path('data/phase2') / run_id
b = Path('data/phase2-repro-check') / run_id
comparison = {
    str(p.relative_to(a)): sha256_file(p) == sha256_file(b / p.relative_to(a))
    for p in sorted(a.rglob('*')) if p.is_file()
}
assert len(comparison) == 17 and all(comparison.values())
print(comparison)
PY
```

The first attempted direct `.venv/bin/python scripts/run_phase2.py --dataset-dir ...` commands failed on the host import-path issue described above; the module commands succeeded. Sandboxed Arrow emits informational C++ CPU-capability probe messages about denied `sysctlbyname` calls on this host, then completes successfully; no data or test result was fabricated to hide them. Approved PostgreSQL test execution had no test warnings. No approval review rejected an action.

## Files created or modified in Phase 2

The repository still has no Git commits, so status lists all project files as untracked. The following list distinguishes changes against the saved Phase 1 delivery manifest without creating a commit.

Created (21 files):

```text
configs/phase2.json
docs/FORECASTING_METHODOLOGY.md
docs/PHASE2_RESULTS.md
ml/data/weekly.py
ml/evaluation/__init__.py
ml/evaluation/metrics.py
ml/evaluation/plots.py
ml/evaluation/splits.py
ml/features/__init__.py
ml/features/weekly.py
ml/models/__init__.py
ml/models/baselines.py
ml/pipelines/forecasting_foundation.py
ml/tests/test_baselines.py
ml/tests/test_features.py
ml/tests/test_metrics.py
ml/tests/test_phase2_pipeline.py
ml/tests/test_plots.py
ml/tests/test_splits.py
ml/tests/test_weekly.py
scripts/run_phase2.py
```

Modified (8 files):

```text
.env.example
README.md
pyproject.toml
requirements-dev.lock
docs/IMPLEMENTATION_PLAN.md
docs/DATA_DICTIONARY.md
docs/DATA_PIPELINE.md
ml/pipelines/ingestion.py
```

The ingestion change exposes `verify_dataset`, checking a published source's content-derived identity and artifact integrity without loading all transactions. The original cleaning policy and dataset version are unchanged. `PROJECT_SPEC.md`, PostgreSQL schema/migrations and backend implementation are unchanged. Raw/processed data, caches, analytical reports/figures and logs remain ignored. No remote, commit or push was created.

## Assumptions, limitations and unresolved issues

- No unresolved test failures or Phase 2 functional blockers remain. The macOS hidden-path issue is handled by the documented module invocation; Arrow CPU-probe messages remain an environment limitation, with successful runs and reproducibility checks recorded.
- Gross recorded positive purchases are the target. No stock-availability or lost-demand information exists, so inserted zeros are not proof that unconstrained demand was zero. Continuous pre-launch history is an observational convention, not verified product availability.
- Credits/cancellations are separate unmatched accounting signals, not reconstructed inventory returns. Net accounting units may be negative. Revenue is gross selling revenue and costs/margins remain unknown.
- Each fold's selected cohort may differ. Pooled validation metrics are suitable for comparing the three methods under that policy, not for claiming performance for all products or one fixed 50-product basket.
- Four-week recurrence is an assumption. Annual history is insufficient. No holiday effects are inferred; optional indicators are supplied externally. No fitted preprocessing or advanced ML occurs here.
- Observing previous validation actuals is legitimate for the documented one-week rolling-origin horizon. These results are not a four-week-ahead block forecast and cannot be used as such.
- WAPE with no actual demand is undefined; missing price/rate and warm-up features remain null. Phase 3 must handle them within each training fold. Segments use training volume only.
- Historical product/customer coverage is imperfect, customer counts exclude unknown IDs, duplicates may remove identical legitimate line items, and extreme valid quantities are not arbitrarily clipped. These source limitations continue from Phase 1.
- Python tests/figures were verified on macOS ARM64; PostgreSQL runs in Linux ARM64 Docker. Cross-platform Python reproducibility is pinned but not measured. Figures use a deterministic current-runtime rendering path; timing values are host-specific.
- Weekly facts and validation artifacts are local immutable files. Database weekly-demand integration, fitted model tracking/artifacts, uncertainty, inventory policy/simulation, API/worker, dashboard, exports and end-to-end browser testing remain later phases.
- The final test block remains sealed for final evaluation after model selection. Validation results cannot justify claims of test accuracy, real company savings or purchasing recommendations.

<!-- Public release note: machine-specific paths and example passwords were normalized; recorded measurements are unchanged. -->
