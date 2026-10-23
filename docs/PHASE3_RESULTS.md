# Phase 3 delivery record

Verified 2026-10-18 on macOS ARM64/Python 3.12.14. **Phase 3 is complete; Phase 4 has not started.** Numbers below come from the actual official-source run. Ridge won pre-test selection but did **not** beat the best baseline in the final test. No business savings or completed API/frontend is claimed.

## Implemented

- Pooled product-level Ridge, Random Forest and XGBoost, two predeclared candidates per family, seed 42, time-aware selection and comparison with all three Phase 2 baselines.
- Training-boundary product selection and fitted numeric imputation/missing indicators, Ridge scaling and product encoding. First 12 panel weeks excluded from supervised fitting; only causal predictors accepted. Predictions are clipped nonnegative.
- Separate selection, calibration and final test roles; frozen final cohort/models/preprocessing, one-week rolling origins, no test refitting or reselection. Best ML and best overall method including baselines are recorded independently.
- Practical residual intervals for all six methods, explicit empirical labels and measured retrospective coverage/width. Native importance for all three fitted models.
- Joblib pipelines, feature/config/source/runtime/code lineage, chosen parameters, metrics, fold predictions, artifact checksums, timestamps/timings and Git hash when available (null here because no commits exist).
- Thin training/evaluation CLIs, atomic immutable artifacts, complete cache verification and a dataset-scoped atomic final-test ledger. Full plan/cohort/calibration/model validation happens before reservation; completed repeats return cached results without rereading targets.
- Six real-run figures, all opened and visually inspected: selection/test comparison, actual/forecast intervals, coverage/width, native importance, residual/time/product diagnostics, under/overforecast magnitudes.
- 186 additional tests, model card, methodology, runtime instructions and updated architecture/data dictionary. Optional MLflow is explicitly deferred; local JSON/Parquet tracking works without a tracking service.

See [ML methodology](ML_METHODOLOGY.md), [model card](MODEL_CARD.md), [data dictionary](DATA_DICTIONARY.md) and [implementation plan](IMPLEMENTATION_PLAN.md).

## Dates and frozen selection

All dates are full Monday–Sunday week labels in London wall time. Training starts 2010-12-06. Partial source weeks beginning 2010-11-29 and 2011-12-05 are excluded. Initial training has 32 weeks, so annual 52-week recurrence is unsupported; four-week recurrence is a declared comparator assumption, not discovered monthly seasonality.

| Role | Training through | Forecast weeks | Products | Observations per method |
| --- | --- | --- | ---: | ---: |
| Selection fold 1 | 2011-07-11 | 2011-07-18–2011-08-08 | 50 | 200 |
| Selection fold 2 | 2011-08-08 | 2011-08-15–2011-09-05 | 50 | 200 |
| Calibration fold 3 | 2011-09-05 | 2011-09-12–2011-10-03 | 50 | 200 |
| Final test | 2011-10-03 | 2011-10-10–2011-11-28 | 50 | 400 |

The third expanding fold calibrates residuals after selection. Historical Phase 2 scores pool all 12 validation weeks; Phase 3 selection uses the first eight, so those scores are not interchangeable. Selection minimizes pooled WAPE, then MAE and identifier; MAE is the fallback for zero total actual demand. No random chronological split or test-based early stopping occurs.

Chosen candidates, fixed before final testing:

- Ridge alpha 1, versus 100.
- Random Forest: 100 trees, maximum depth 8 versus unrestricted, minimum leaf size 2, seed 42, one worker.
- XGBoost: 150 trees, depth 2 versus 4, learning rate 0.05, histogram trees, squared error, full row/column sampling, seed 42, one worker. Pinned library defaults apply to parameters not overridden.

Random Forest is the permitted alternative to tentative HistGradientBoosting: the small pooled panels make it practical and it exposes native importance. XGBoost adds a distinct boosted-tree comparison without receiving preferential selection. This is a small grid, not exhaustive optimization.

Final models use 1,600 rows each (50 products × 32 supervised weeks after warm-up). The final top 50 are ranked from all 44 pre-test weeks only. All baselines use the same frozen cohort. Earlier completed test actuals may enter later lags/baseline histories, but models/preprocessing do not refit. These are one-week-ahead results, not an eight-week-ahead forecast.

## Measured selection-validation results

400 aligned observations per method, first two folds only:

| Method | MAE, units | RMSE, units | WAPE, % | sMAPE, % | Bias, units |
| --- | ---: | ---: | ---: | ---: | ---: |
| Four-week moving average | 228.3619 | 386.4669 | 60.2248 | 58.5185 | 1.2006 |
| Last observed | 269.0975 | 471.1194 | 70.9678 | 64.8062 | -0.6925 |
| Random Forest | 223.9249 | 370.2104 | 59.0547 | 58.4664 | 10.9955 |
| Ridge | 202.9455 | 357.4777 | 53.5219 | 55.8247 | -35.6216 |
| Four-week recurrence | 287.9425 | 496.8219 | 75.9377 | 68.9124 | -12.2725 |
| XGBoost | 224.3476 | 372.5637 | 59.1661 | 59.0834 | -2.9656 |

Ridge is the frozen best ML and overall selection method. Selection cohorts can change at each fold; the pooled number describes that policy, not one fixed basket. All candidate scores and product/week/fold/training-volume breakdowns remain in the artifacts.

## Dedicated calibration diagnostics

200 observations per method, third fold only. These scores did not change model choices and are neither selection nor test scores:

| Method | MAE, units | RMSE, units | WAPE, % | sMAPE, % | Bias, units |
| --- | ---: | ---: | ---: | ---: | ---: |
| Four-week moving average | 218.6575 | 339.0788 | 53.2493 | 57.5099 | -30.6850 |
| Last observed | 246.7950 | 389.7327 | 60.1016 | 63.2979 | -34.4750 |
| Random Forest | 229.5665 | 332.3440 | 55.9059 | 61.3440 | -0.6710 |
| Ridge | 212.4802 | 319.4237 | 51.7449 | 57.8133 | -5.8837 |
| Four-week recurrence | 257.6600 | 432.4529 | 62.7475 | 64.9307 | -24.1800 |
| XGBoost | 231.4391 | 336.6266 | 56.3620 | 61.1855 | 6.4180 |

Residual scores are `abs(actual - prediction) / max(prior_four_week_mean, 10)`. At the predeclared 80% level, rank 161 of 200 scores supplies each method's radius; applying the prior-demand scale gives zero-clipped lower bounds. The scale floor is a configurable demand-unit assumption, not a business cost. Changing products/refits/time makes this a practical transferred residual estimate without a formal future-coverage guarantee.

## Measured final-test results

400 aligned observations per method, fixed 50-product cohort, all eight weeks:

| Method | MAE, units | RMSE, units | WAPE, % | sMAPE, % | Bias, units |
| --- | ---: | ---: | ---: | ---: | ---: |
| Four-week moving average | 222.3081 | 410.3353 | 51.9682 | 51.0767 | -4.9519 |
| Last observed | 275.5575 | 530.7029 | 64.4161 | 60.7462 | 9.7575 |
| Random Forest | 238.7150 | 425.0277 | 55.8036 | 55.7623 | 36.5651 |
| Ridge | 225.6719 | 438.8753 | 52.7545 | 53.4712 | -29.6721 |
| Four-week recurrence | 269.5775 | 522.5691 | 63.0182 | 59.7637 | -24.4325 |
| XGBoost | 226.9087 | 435.4433 | 53.0436 | 54.2550 | 3.1690 |

Bias is mean `prediction - actual`; negative means underforecasting. WAPE/sMAPE are percentages; MAE/RMSE/bias are units. WAPE is null for zero total actual demand; zero/zero contributes zero to sMAPE. Ordinary MAPE is omitted. Full product/week/training-volume segment/error-direction records are retained.

**Ridge's final WAPE is 0.7863 percentage points worse than the four-week mean. All three ML families fail to beat that baseline on final-test WAPE.** The frozen selection remains Ridge for auditability. No post-test promotion, retuning or reranking occurred. This is a negative generalization result, not evidence of ML business value. No inventory cost or financial savings have been simulated or achieved.

## Final-test uncertainty

| Method | Nominal coverage, % | Actual coverage, % | Mean width, units | Actual below lower, % | Actual above upper, % |
| --- | ---: | ---: | ---: | ---: | ---: |
| Four-week moving average | 80.00 | 85.50 | 719.5914 | 1.00 | 13.50 |
| Last observed | 80.00 | 82.25 | 810.2974 | 7.50 | 10.25 |
| Random Forest | 80.00 | 80.50 | 804.3298 | 12.50 | 7.00 |
| Ridge | 80.00 | 79.50 | 738.3436 | 11.75 | 8.75 |
| Four-week recurrence | 80.00 | 81.00 | 796.4764 | 6.50 | 12.50 |
| XGBoost | 80.00 | 81.25 | 790.3281 | 12.25 | 6.50 |

Ridge covered 318/400 actuals. These aggregate retrospective results and wide intervals are not product-level certification or guarantees. Time dependence, product heterogeneity, cohort change, refitting and drift can invalidate residual stability. No radius was adjusted using test outcomes. Error patterns and intended/prohibited uses are in the model card.

## Identity, artifacts and reproducibility

Source: `3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d`.

Frozen experiment: `6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa`.

Frozen plan SHA-256: `ccbad63a1adfdc693fc22f66585dd798df378ce1fa26bde2ff801cdb2435971f`.

Directories (replace `<run_id>` with the frozen experiment above):

- Training: `artifacts/phase3/<run_id>/`.
- Independent cold training: `artifacts/phase3-repro-check/<run_id>/`.
- Final results: `artifacts/phase3/evaluations/<run_id>/`.

Of 19 training files, **17 deterministic files are byte-identical across two cold runs**, including all three model files, predictions, calibration, configuration, plan and importance. Only real timestamp/timing metadata and its containing manifest differ. Same-host byte identity is stronger than the numerical prediction tolerance exercised in tests.

Training contains 3,600 candidate-comparison predictions (six candidates plus three baselines × 400 observations), 2,400 chosen-method selection predictions, 1,200 calibration predictions, 2,200 pre-test weekly rows and 300 first-origin forecasts issued before target access. Final results have 2,400 predictions with intervals and 12 files including six figures. The first final week is asserted equal to its preissued forecasts/bounds.

The patched NumPy runtime derives Phase 2 cache ID `0808b696cffe0b159cc593f8963208a2b43f41a29670ac6bc6344c74cb06c2ce`. Historical delivery IDs remain valid records of their runtimes. Older ignored development runs are not the frozen run. Inventory/hashes/Parquet counts are checked on reuse; do not add files inside immutable directories.

The dataset-scoped ledger `data/evaluation-ledger/<dataset_id>.json` reserved the plan at 2026-10-18T14:22:40.107531Z and completed at 14:22:41.750614Z. A repeated command verified cached results without rereading targets. Alternate plans/new training are refused after reservation. Do not delete/change the ledger to manufacture another untouched test. Interrupted claims require investigation. This trusted local POSIX mechanism is not a distributed worker or an adversarial security boundary.

## Measured timings

| Operation | Duration |
| --- | ---: |
| Primary cold training: 18 estimator fits total | 4.382042 s |
| Primary cold complete training | 5.760459 s |
| Independent cold training: 18 estimator fits | 3.610547 s |
| Independent cold complete training | 4.908978 s |
| Final batch ML prediction calls: 3 × 400 rows | 0.075890 s |
| Complete first evaluation, including metrics/figures | 1.678662 s |
| Verified evaluation cache reuse | 0.042497 s |
| Verified training cache reuse | 0.029326 s |

These are individual observed durations, not statistical or universal throughput benchmarks. Training uses the verified Phase 2 cache, excluding its cold rebuild, ingestion and environment setup. Fit time includes fitted preprocessing; batch prediction excludes IO/features/baselines/intervals. CLI totals include publication overhead and differ slightly from internal metadata totals. No API benchmark was measured.

## Complete test results

The existing Phase 1/2 suite was rerun first: **402 passed in 20.59 s**, including PostgreSQL. An intermediate run passed 585 tests; the completed pre-test suite passed **588 in 16.01 s**. After the final CLI-status wording fix, the final run produced:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-8.3.5, pluggy-1.7.0
rootdir: /path/to/demandiq
configfile: pyproject.toml
plugins: platformdirs-4.13.4
collected 588 items

ml/tests/test_acquisition.py .............                               [  2%]
ml/tests/test_baselines.py .............................                 [  7%]
ml/tests/test_cleaning.py .............................................. [ 14%]
........................................................................ [ 27%]
                                                                         [ 27%]
ml/tests/test_features.py ..................................             [ 32%]
ml/tests/test_final_test.py ............................................ [ 40%]
..................................                                       [ 46%]
ml/tests/test_ingestion.py ...............                               [ 48%]
ml/tests/test_metrics.py .................................               [ 54%]
ml/tests/test_model_plots.py .....                                       [ 55%]
ml/tests/test_modeling_pipeline.py ...............                       [ 57%]
ml/tests/test_phase2_pipeline.py ...............                         [ 60%]
ml/tests/test_plots.py ..                                                [ 60%]
ml/tests/test_splits.py .....................                            [ 64%]
ml/tests/test_training.py .............................................. [ 72%]
.......................                                                  [ 76%]
ml/tests/test_uncertainty.py ...................                         [ 79%]
ml/tests/test_weekly.py ................................................ [ 87%]
......................................                                   [ 93%]
backend/tests/test_db.py ....................................            [100%]

============================= 588 passed in 14.29s =============================
```

| Test file | Passed |
| --- | ---: |
| `ml/tests/test_acquisition.py` | 13 |
| `ml/tests/test_baselines.py` | 29 |
| `ml/tests/test_cleaning.py` | 118 |
| `ml/tests/test_features.py` | 34 |
| `ml/tests/test_final_test.py` | 78 |
| `ml/tests/test_ingestion.py` | 15 |
| `ml/tests/test_metrics.py` | 33 |
| `ml/tests/test_model_plots.py` | 5 |
| `ml/tests/test_modeling_pipeline.py` | 15 |
| `ml/tests/test_phase2_pipeline.py` | 15 |
| `ml/tests/test_plots.py` | 2 |
| `ml/tests/test_splits.py` | 21 |
| `ml/tests/test_training.py` | 69 |
| `ml/tests/test_uncertainty.py` | 19 |
| `ml/tests/test_weekly.py` | 86 |
| `backend/tests/test_db.py` | 36 |
| **Total** | **588** |

**0 failed, 0 skipped, 0 test warnings.** Includes 402 existing and 186 new tests. PostgreSQL 16.6 integration tests exercise real migrations/persistence/constraints/rollback/concurrency. Strict warnings-as-errors remain enabled. No frontend/API/Playwright tests apply yet.

New tests cover the three models and invalid contracts; predictor isolation; fold-local preprocessing; zero demand/unknown categories; future-perturbation invariance of features/fitted transformations/predictions/selection; calibration perturbations that cannot change selection; serialization/checksummed loading; uncertainty quantiles/chronology/zero bounds/coverage; plot consistency; concurrent atomic ledger claims/completion; alternate/corrupt/interrupted records; malformed-plan refusal before reservation; cache reuse without Parquet reads; frozen first-origin consistency; and synthetic end-to-end training/evaluation.

Ruff: `All checks passed!`. Black: **55 Python files unchanged**. `pip check`: `No broken requirements found.` Compose configuration exited 0; PostgreSQL stayed healthy on localhost:5432. Default external pip-cache permission messages are environment warnings, not test warnings; workspace cache flags avoid them.

## Exact commands for setup, runs and checks

Run from the repository root. Repeated commands are listed once; ordinary source reads/file edits are omitted. The database password is the documented local development value. The commands below include the independent cold run made before final evaluation; on this already-evaluated workspace they verify caches rather than retrain.

```bash
# Existing regression, before installing ML dependencies:
TEST_DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test .venv/bin/python -m pytest ml/tests backend/tests

# Dependency setup / project registration:
.venv/bin/python -m pip install --cache-dir .cache/pip scikit-learn==1.6.1 xgboost==2.1.4 joblib==1.4.2
.venv/bin/python -m pip install --cache-dir .cache/pip numpy==2.3.5
.venv/bin/python -m pip install --cache-dir .cache/pip --no-index -r requirements-dev.lock
.venv/bin/python -m pip install --cache-dir .cache/pip --no-deps --no-build-isolation -e .
.venv/bin/python -m scripts.setup_macos_openmp

# Focused checks during implementation:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest ml/tests/test_training.py
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest ml/tests/test_uncertainty.py ml/tests/test_model_plots.py
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest ml/tests/test_final_test.py
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m pytest ml/tests/test_modeling_pipeline.py

# Full final regression:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test .venv/bin/python -m pytest ml/tests backend/tests
.venv/bin/python -m ruff check .
.venv/bin/python -m black --check .
.venv/bin/python -m pip check
docker compose config --quiet
docker compose ps
git status --short
git remote -v

# Official training, then independent cold training before final-test access:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m scripts.train --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m scripts.train --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d --output-dir artifacts/phase3-repro-check

# Once semantic evaluation; repeat verifies cached results only:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m scripts.evaluate --run-dir artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa --dataset-dir data/processed/3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d
```

The cold byte comparison used the following assertions (before the ledger claim):

```bash
.venv/bin/python - <<'PY'
from pathlib import Path
from ml.data.acquisition import sha256_file
run = '6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa'
a = Path('artifacts/phase3') / run
b = Path('artifacts/phase3-repro-check') / run
comparison = {str(p.relative_to(a)): sha256_file(p) == sha256_file(b / p.relative_to(a))
              for p in sorted(a.rglob('*')) if p.is_file()}
assert len(comparison) == 19
assert all(v for k,v in comparison.items()
           if k not in ('manifest.json','training_metadata.json'))
print(comparison)
PY
```

## Resolved setup issues and diagnostic failures

XGBoost initially could not load the missing `libomp.dylib` on this Apple Silicon host. The official Homebrew 23.1.3 bottle was checksum verified and its bounded library extracted into ignored `.cache/libomp`; no system files changed. The new helper reproduces/verifies this pinned setup on supported macOS versions; `brew install libomp` is the standard alternative. See the official [libomp formula](https://formulae.brew.sh/formula/libomp.html). Use the documented `DYLD_LIBRARY_PATH` prefix/export with the local helper.

NumPy 2.2.3 emitted erroneous finite-matmul floating-point warnings during Ridge fits on this Mac, failing strict tests. Pinning patched 2.3.5 resolved the issue without suppressing warnings. Related primary sources: [Apple Accelerate issue](https://github.com/numpy/numpy/issues/28687), [upstream fix](https://github.com/numpy/numpy/pull/30102). [XGBoost 2.1.4 notes](https://xgboost.readthedocs.io/en/release_3.0.0/changes/v2.1.0.html) document compatibility with sklearn 1.6.

A later diagnostic `.venv/bin/python -m pytest --collect-only -q ml/tests backend/tests` omitted the local library prefix and stopped with **two XGBoost collection errors**, not a passing run. The documented prefixed full command subsequently passed all 588. An initial ad hoc comparison named nonexistent `feature_importance.json`; correcting it to `importance.json` verified all 17 deterministic files. Neither issue changed models or accessed official targets.

Sandboxed Arrow CPU probes print informational denied-`sysctlbyname` messages then complete; these remain a host limitation outside Python test warnings. The default external pip cache is not workspace-writable, so installs use `.cache/pip`. No automatic approval review rejected an action. Native/numerical failures were fixed before test access; final evaluation completed with no ledger reset or interruption.

## Files created or modified

Against Phase 2, created **20 files**:

```text
configs/phase3.json
docs/ML_METHODOLOGY.md
docs/MODEL_CARD.md
docs/PHASE3_RESULTS.md
ml/models/config.py
ml/models/training.py
ml/evaluation/uncertainty.py
ml/evaluation/final_test.py
ml/evaluation/model_plots.py
ml/evaluation/model_diagnostics.py
ml/pipelines/artifacts.py
ml/pipelines/modeling.py
scripts/train.py
scripts/evaluate.py
scripts/setup_macos_openmp.py
ml/tests/test_training.py
ml/tests/test_uncertainty.py
ml/tests/test_model_plots.py
ml/tests/test_final_test.py
ml/tests/test_modeling_pipeline.py
```

Modified **6 files**:

```text
README.md
pyproject.toml
requirements-dev.lock
docs/IMPLEMENTATION_PLAN.md
docs/DATA_DICTIONARY.md
docs/FORECASTING_METHODOLOGY.md
```

The repository still has no commits, so Git reports project files as untracked. PROJECT_SPEC, source cleaning, migrations/schema, existing Phase 2 logic and historical delivery reports are unchanged. Raw/processed data, models, ledger, plots, caches and local environments remain ignored. No remote repository, Git commit or push was created.

## Assumptions, limitations and unresolved problems

- **No unresolved test failure or Phase 3 implementation blocker remains.** The substantive limitation is predictive: ML failed to beat the strongest baseline on the final test. Further model research requires new chronological evaluation data; this block is now observed.
- Recorded sales are not unconstrained demand. Missing customer coverage, exact duplicate policy, unmatched accounting credits, pre-launch zeros and extreme valid purchases remain data limitations. Annual seasonality is unsupported; holiday indicators are absent, not inferred.
- Two candidate settings per family constitute a modest search. Short supervised histories and top-volume selection limit generalization. Product count is configurable; measured results cover 50, not the entire catalog or cold starts.
- Selection/calibration and final cohorts can differ. Pooled residuals assume transfer across products/refits/time; wide intervals and aggregate coverage do not imply product-level reliability or economic benefit.
- Two same-host cold runs match exactly. Python/lock execution was tested on macOS ARM64, PostgreSQL in Linux ARM64 Docker. Cross-platform Python equivalence/install is not measured; Linux XGBoost may resolve extra platform-specific dependencies. Full application containers remain Phase 6.
- The ledger assumes a trusted stable POSIX filesystem. Windows/distributed behavior and background-worker recovery are not demonstrated. Interrupted claims remain locked intentionally. Phase 5 owns durable job leases/retries.
- Model metadata is local JSON/Parquet/joblib; database training/forecast persistence is later integration. Optional MLflow is deferred for setup reliability; native importance satisfies the explanation requirement without SHAP. No out-of-scope deep learning, cloud, authentication or automated purchasing was added.
- Inventory defaults, multiweek lead times, ordering constraints, simulation/policy costs and business KPIs remain Phase 4. API/worker integration is Phase 5; React/CSV endpoints/accessibility/full Compose/Playwright are Phase 6. None is presented as finished.

## Exact recommended next prompt

> Begin DemandIQ Phase 4 only. Read PROJECT_SPEC.md, README.md, docs/IMPLEMENTATION_PLAN.md, docs/ML_METHODOLOGY.md, docs/MODEL_CARD.md and docs/PHASE3_RESULTS.md first, inspect the frozen artifacts and rerun the existing checks. Implement configurable inventory recommendations and a chronological simulator with identical assumptions for previous-demand, four-week-mean, fixed-reorder-point and frozen ML policies. Define units/defaults and the multiweek lead-time forecasting convention before implementation; enforce nonnegative orders/stock, lead-time arrivals, MOQ/case-pack/capacity constraints and reconciled costs. Keep historical facts, forecasts, assumptions and simulated outcomes distinct. Do not retune Phase 3 or reuse its observed test block as an untouched forecasting test; use the frozen outputs for clearly labeled retrospective inventory-policy simulation. Report actual cost/fill-rate/lost-sales results without assuming ML wins, add meaningful tests and update documentation. Do not begin Phase 5, create a remote repository, commit or push.

<!-- Public release note: machine-specific paths and example passwords were normalized; recorded measurements are unchanged. -->
