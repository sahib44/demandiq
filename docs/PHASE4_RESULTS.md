# Phase 4 delivery record

Verified **2026-10-19**, America/New_York. Phase 4 is complete; Phase 5 has not started. Every outcome below comes from actual execution on the frozen official-data forecasting artifacts. Costs, initial stock and supplier behavior are illustrative assumptions. **All savings are simulated estimates; none are savings achieved by the original retailer or another company.**

## Implemented

- Typed, validated inventory parameters/state; lead-time demand, safety stock, reorder/target levels, inventory position and explained whole-unit recommendations. Configurable MOQ, case packs and conservative capacity apply to positive orders; infeasible constraints return zero with reasons.
- Configurable lead/review periods, service target, purchase/selling/holding/stockout/order costs, initial on-hand, dated prepaid initial orders, fixed-policy levels, global defaults and per-product overrides. Backorders are supported in standalone inventory-position planning; the lost-sales simulator explicitly rejects nonzero initial backlog.
- A chronological simulator with receipts → demand → fulfillment/loss → ending stock → review/order. Orders wait complete lead-time weeks; no negative inventory, early receipts, duplicated charges or lost pipeline. Stock/order and monetary conservation are checked.
- Five policy comparisons: literal previous-demand repeat, four-week-mean repeat, fixed reorder point, validation-selected frozen ML plus safety stock, and a matched four-week-mean/safety controller.
- Fill rate, weekly no-stockout service, lost units/events/revenue/margin, average/ending inventory, outstanding units, purchase/holding/stockout/order costs, assumed revenue, gross cash cost and terminal-adjusted net cost. Signed ML estimates against every baseline include negative/zero-denominator handling.
- Frozen-source/ledger verification, pre-test-only stock/error derivation, atomic immutable scenario artifacts, checked cache reuse, standalone CLI, CSV exports, three deterministic figures per scenario and a worked historical business example.
- 260 new tests and updated documentation. No dependency addition, model retraining, forecasting reevaluation, database migration, API, worker or frontend was introduced.

Architecture, assumptions and exact equations are in [inventory methodology](INVENTORY_METHODOLOGY.md); [data dictionary](DATA_DICTIONARY.md), [worked scenario](EXAMPLE_SCENARIO.md), [model card](MODEL_CARD.md) and [implementation plan](IMPLEMENTATION_PLAN.md) describe the interfaces and limits.

## Protocol fixed before the first simulation

The final 50-product cohort, Ridge model and forecast outputs remain those selected in Phase 3. Historical gross purchases supply hypothetical demand for the eight full weeks **2011-10-10–2011-11-28**. Products are not reselected. Initial stock is ceil(two times each product's 44-week pre-test mean); fixed levels use those means. Pooled normalized RMSE uses only the dedicated 200-observation-per-method calibration block, never final-test residuals. The calibration cohort may differ from the final cohort. The default common initial stock totals **38,871 units** with no initial outstanding orders.

Default illustrative economics: GBP; purchase 1.00/sell 2.00 per unit; holding 0.02/unit/week; stockout penalty 3.00/lost unit; order fee 5.00; service 0.95; lead 1/review 1 week; MOQ 0, pack 1 and no capacity. Every input is configurable. The stockout penalty was set to3 before outcomes to avoid making fulfilled-unit purchase cost and lost-unit penalty identical. No default was optimized or changed from observed results.

An order reviewed after demand in week t arrives before demand in **t+L+1**: L complete following demand weeks pass. Thus L=1 first orders from Oct10 arrive Oct24; L=2 arrive Oct31. Protection horizon is L+R. At review only the already-issued forecast for t+1 is available; all further lead/review weeks use a labeled flat carry-forward approximation. Later rolling-origin forecasts cannot enter an earlier decision. No final-week order is placed for any policy, because no next-origin forecast exists. Earlier late orders remain in the pipeline and terminal assets.

The reorder point is `L*d + z*sigma*sqrt(L)` and target is `(L+R)*d + z*sigma*sqrt(L+R)`. At/below the reorder point, request max(target−position,0), then apply MOQ/pack/capacity. `z` is the normal service factor floored at zero. Sigma is a transferred empirical normalized-RMSE magnitude, not a validated independent Gaussian error standard deviation. Desired service is not guaranteed realized service.

Purchase cost is paid at placement; initial pipeline is prepaid. Gross cash cost sums purchases, holding, penalty and order fees. Primary **net inventory cost** adds initial inventory assets and subtracts terminal on-hand/pipeline assets, all valued at purchase cost. It reconciles to consumed goods + holding + penalty + order fees; the equivalent consumed-goods expression prevents floating-point cancellation artifacts. Full recovery of terminal stock value is assumed. Estimated lost margin is separate and never added to penalty again. Fill rate is fulfilled/demand (one for zero demand); service is product-weeks without lost units, not an order-cycle statistic. Average inventory is the average of total weekly on-hand across the cohort, not a per-SKU mean.

## Measured default policy results

400 historical product-weeks are simulated for each policy, yielding 2,000 weekly records:

| Policy | Net cost, GBP | Gross cash cost, GBP | Fill rate, % | Weekly service, % | Lost units | Stockout product-weeks | Average total on-hand |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Previous demand | 245999.10 | 259655.10 | 79.5449 | 76.0000 | 35,001 | 96 | 19631.875 |
| Four-week mean | 241845.58 | 251666.58 | 80.6926 | 77.5000 | 33,037 | 90 | 18191.125 |
| Fixed reorder point | 206067.80 | 243405.80 | 92.2273 | 93.0000 | 13,300 | 28 | 47917.500 |
| Frozen ML + safety | 194633.74 | 265044.74 | 96.3749 | 95.0000 | 6,203 | 20 | 65510.875 |
| Four-week mean + safety | 199496.02 | 267782.02 | 94.4925 | 93.0000 | 9,424 | 28 | 55387.625 |

### Default cost and exposure details

| Policy | Purchase cash | Holding | Stockout penalty | Order fees | Assumed revenue | Estimated lost margin | Ending on-hand | Closing pipeline |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Previous demand | 149766.00 | 3141.10 | 105003.00 | 1745.00 | 272220.00 | 35001.00 | 32,627 | 19,900 |
| Four-week mean | 147895.00 | 2910.58 | 99111.00 | 1750.00 | 276148.00 | 33037.00 | 25,176 | 23,516 |
| Fixed reorder point | 195149.00 | 7666.80 | 39900.00 | 690.00 | 315622.00 | 13300.00 | 60,076 | 16,133 |
| Frozen ML + safety | 235319.00 | 10481.74 | 18609.00 | 635.00 | 329816.00 | 6203.00 | 95,902 | 13,380 |
| Four-week mean + safety | 229973.00 | 8862.02 | 28272.00 | 675.00 | 323374.00 | 9424.00 | 75,725 | 31,432 |

The matched mean/safety controller is the most informative baseline for separating ordering-rule differences from forecast inputs. Default ML net cost is 4,862.28 lower (2.4373%), but its average stock is 65,510.875 versus 55,387.625 units. It uses a larger calibrated error multiplier (1.851446 versus 1.476391) and therefore more safety stock. The difference includes forecast/error-buffer effects and extra inventory exposure; it does not prove better ML point forecasting. Direct-repeat policies have different controllers, so their larger differences cannot be attributed solely to ML.

The Phase 3 final-test result remains unchanged: Ridge WAPE 52.75% failed to beat the four-week mean's 51.97%. Inventory cost and forecast accuracy answer different questions. These retrospective economics depend heavily on penalty/holding/terminal assumptions and unknown original stock availability.

## Sensitivities and signed simulated savings

The lead-two scenario changes only L from 1 to 2 (and the scenario name). The higher-holding scenario changes holding 0.02 to 0.10 and was added **after** the default/lead-two runs as an explicitly exploratory exposure check. It is not preregistered validation, retuning, policy selection or a recommendation. Cost parameters score outcomes; this rule-based controller does not optimize order quantities against them.

| Scenario | Policy | Net cost, GBP | Fill rate, % | Lost units |
| --- | --- | ---: | ---: | ---: |
| lead2 | Previous demand | 284541.42 | 68.0547 | 54,662 |
| lead2 | Four-week mean | 279879.66 | 69.4052 | 52,351 |
| lead2 | Fixed reorder point | 237071.90 | 83.4692 | 28,286 |
| lead2 | Frozen ML + safety | 232351.38 | 85.6473 | 24,559 |
| lead2 | Four-week mean + safety | 233982.84 | 84.7216 | 26,143 |
| high-holding | Previous demand | 258563.50 | 79.5449 | 35,001 |
| high-holding | Four-week mean | 253487.90 | 80.6926 | 33,037 |
| high-holding | Fixed reorder point | 236735.00 | 92.2273 | 13,300 |
| high-holding | Frozen ML + safety | 236560.70 | 96.3749 | 6,203 |
| high-holding | Four-week mean + safety | 234944.10 | 94.4925 | 9,424 |

| Scenario | Baseline | Baseline net cost minus ML net cost, GBP | Signed simulated savings, % |
| --- | --- | ---: | ---: |
| default | Previous demand | 51365.36 | 20.8803 |
| default | Four-week mean | 47211.84 | 19.5215 |
| default | Fixed reorder point | 11434.06 | 5.5487 |
| default | Four-week mean + safety | 4862.28 | 2.4373 |
| lead2 | Previous demand | 52190.04 | 18.3418 |
| lead2 | Four-week mean | 47528.28 | 16.9817 |
| lead2 | Fixed reorder point | 4720.52 | 1.9912 |
| lead2 | Four-week mean + safety | 1631.46 | 0.6973 |
| high-holding | Previous demand | 22002.80 | 8.5096 |
| high-holding | Four-week mean | 16927.20 | 6.6777 |
| high-holding | Fixed reorder point | 174.30 | 0.0736 |
| high-holding | Four-week mean + safety | -1616.60 | -0.6881 |

In the exploratory higher-holding run, ML costs **1,616.60 more** than the matched mean/safety controller. Orders and stock flows are unchanged from default, as expected for this rule-based controller; only economics change. A default simulated advantage is therefore not a robust benefit claim. Longer lead time also reduces default ML fill from 96.37% to 85.65% with the same initial stock. No policy/input is selected from these outcomes.

## Artifacts and immutability evidence

Frozen forecast experiment: `6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa`.

Source dataset: `3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d`.

Scenario run IDs (under ignored `artifacts/phase4/`):

- default: `a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967`.
- lead2: `698c6dc1a77f25c843116a2346a886166044e00523b0318916ed1331dee19511`.
- high-holding: `d5c6bdc5cf636aca9973d98471fcaf8714b10f37ba26bd152838211c7dfe5e8f`.

Each run has 16 files: resolved config, source lineage, resolved per-product assumptions, historical demand Parquet, simulated weekly/orders/recommendation Parquet, summary JSON, Markdown report, three PNG figures and three CSV exports, plus manifest. Default row counts are400 demand, 2,000 weekly results, 1,099 orders and 2,000 review/nonreview/final-boundary recommendation records. Zero-order explanations remain visible. The CSVs export actual generated simulation records, not fixture/mock results.

All **16 files**, including manifest and figures, are byte-identical between independent default cold runs in `artifacts/phase4/` and `artifacts/phase4-repro-check/`. Repeating the default command returns verified cached results. All **33 frozen training/evaluation/ledger files** retain their before-run SHA-256 hashes, and the completed forecasting ledger remains unchanged. All 12 frozen Phase 3 protocol source-file hashes also match the original training manifest. All three published scenario inventories verify. No raw transactions or serialized models are loaded by this workflow. Metadata identity, complete grids, shared actual/scale, pre-test boundaries and first-issued forecast consistency are verified before simulation. The forecasting test block is already observed and has not been relabeled as new evaluation.

All nine scenario figures were opened and visually inspected. [Default comparison](../artifacts/phase4/a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967/plots/policy_comparison.png), [inventory trajectory](../artifacts/phase4/a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967/plots/inventory_trajectory.png) and [cost components](../artifacts/phase4/a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967/plots/cost_components.png) are local ignored analytical artifacts, not application screenshots.

## Measured timing

| Run | Pure simulation, s | Internal runner total, s |
| --- | ---: | ---: |
| default | 0.131092 | 0.497269 |
| lead2 | 0.594007 | 1.259236 |
| high-holding | 0.129787 | 0.531481 |
| repro | 0.570889 | 1.259586 |

Verified cache reuse: **0.021231 s**. These are individual on-host measurements, not controlled throughput benchmarks; the sensitivity/cold check ran concurrently with regression work. Internal totals start after interpreter/import initialization and include input hashing/IO, simulation, exports, figures and publication. Source ingestion and model training are excluded. No API latency benchmark was measured.

## Complete verification results

Before implementation: **588 passed in 15.17 s**, real PostgreSQL=16.6. An intermediate complete run passed 847 in 20.61 s. After adding the final staging-cleanup test, the final complete output was:

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-8.3.5, pluggy-1.7.0
rootdir: /path/to/demandiq
configfile: pyproject.toml
plugins: platformdirs-4.13.4
collected 848 items

ml/tests/test_acquisition.py .............                               [  1%]
ml/tests/test_baselines.py .............................                 [  4%]
ml/tests/test_cleaning.py .............................................. [ 10%]
........................................................................ [ 18%]
                                                                         [ 18%]
ml/tests/test_features.py ..................................             [ 22%]
ml/tests/test_final_test.py ............................................ [ 28%]
..................................                                       [ 32%]
ml/tests/test_ingestion.py ...............                               [ 33%]
ml/tests/test_inventory_config.py ...................................... [ 38%]
..............................................................           [ 45%]
ml/tests/test_inventory_pipeline.py .................................... [ 49%]
..................                                                       [ 52%]
ml/tests/test_inventory_planning.py .................................... [ 56%]
...........                                                              [ 57%]
ml/tests/test_inventory_plots.py ........                                [ 58%]
ml/tests/test_inventory_simulation.py .................................. [ 62%]
.................                                                        [ 64%]
ml/tests/test_metrics.py .................................               [ 68%]
ml/tests/test_model_plots.py .....                                       [ 68%]
ml/tests/test_modeling_pipeline.py ...............                       [ 70%]
ml/tests/test_phase2_pipeline.py ...............                         [ 72%]
ml/tests/test_plots.py ..                                                [ 72%]
ml/tests/test_splits.py .....................                            [ 75%]
ml/tests/test_training.py .............................................. [ 80%]
.......................                                                  [ 83%]
ml/tests/test_uncertainty.py ...................                         [ 85%]
ml/tests/test_weekly.py ................................................ [ 91%]
......................................                                   [ 95%]
backend/tests/test_db.py ....................................            [100%]

============================= 848 passed in 17.39s =============================
```

**848 passed, 0 failed, 0 skipped, 0 test warnings**: 588 existing and 260 new. New tests by file:

| File | Passed |
| --- | ---: |
| `ml/tests/test_inventory_config.py` | 100 |
| `ml/tests/test_inventory_pipeline.py` | 54 |
| `ml/tests/test_inventory_planning.py` | 47 |
| `ml/tests/test_inventory_plots.py` | 8 |
| `ml/tests/test_inventory_simulation.py` | 51 |
| **New total** | **260** |

Existing file counts are unchanged from [Phase3's complete record](PHASE3_RESULTS.md); full output above includes all existing suites. PostgreSQL tests exercise the disposable `_test` database; the application development database was not cleared. New tests use synthetic products, not official customer rows. They cover hand-calculated thresholds/stock/costs; L=1/L=2 arrivals and review periods; pipeline/backorders/MOQ/pack/capacity; zero demand and negative savings; future-demand/forecast perturbation invariance; exact frozen grids/lineage/first issuance; pre-test-only means/RMSE; matched-controller equality; explicit override precedence/NumPy normalization; source immutability; cold/cache determinism; CSV/plot consistency; protected paths; and atomic cleanup after simulation/plot failures.

Ruff: `All checks passed!`. Black: **67 files unchanged**. `pip check`: `No broken requirements found.` Compose configuration passed; PostgreSQL=16.6 stayed healthy on localhost5432. No frontend/API/Playwright checks apply yet.

Development checks initially caught five missing metadata-identity validations and invalid numeric-date/whitespace/override edge cases, all fixed before the real scenarios. Temporary lint/format failures were corrected. A first shell file write targeted the not-yet-created inventory directory and was retried after creating it. These are not reported as passing checks; the complete final suite above is the delivered verification. No package install or warning suppression was needed. Sandboxed Arrow still prints informational denied-CPU-probe messages during real Parquet reads and succeeds. No automatic approval review rejected an action.

## Exact run and check commands

From `/path/to/demandiq`. Repeated commands are listed once; ordinary reads/edits are omitted. The credential is the existing documented local development value. The default command was run once cold, once into a separate output root and once as verified cache reuse.

```bash
# Existing regression, then full final regression:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test .venv/bin/python -m pytest ml/tests backend/tests
# Final output capture used the same command with this redirect:
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL=postgresql+psycopg://demandiq:CHANGE_ME_LOCAL_ONLY@127.0.0.1:5432/demandiq_test .venv/bin/python -m pytest ml/tests backend/tests > .cache/phase4-final-tests.txt 2>&1

# Focused verification:
.venv/bin/python -m pytest ml/tests/test_inventory_planning.py
.venv/bin/python -m pytest ml/tests/test_inventory_planning.py ml/tests/test_inventory_simulation.py
.venv/bin/python -m pytest ml/tests/test_inventory_planning.py ml/tests/test_inventory_simulation.py ml/tests/test_inventory_plots.py
.venv/bin/python -m pytest ml/tests/test_inventory_config.py ml/tests/test_inventory_pipeline.py

# Code quality/metadata/service verification:
.venv/bin/python -m ruff check .
.venv/bin/python -m black --check .
.venv/bin/python -m pip --cache-dir .cache/pip check
docker compose config --quiet
docker compose ps
git status --short --branch
git remote -v
git diff --check
git check-ignore artifacts/phase4 data/evaluation-ledger .cache/phase4-final-tests.txt .venv
.venv/bin/python -m scripts.run_inventory --help
# During edits, targeted Ruff --fix and Black were also applied to the new modules/tests:
.venv/bin/python -m ruff check ml/inventory ml/pipelines/inventory.py scripts/run_inventory.py ml/tests/test_inventory_plots.py --fix
.venv/bin/python -m black ml/inventory/config.py ml/inventory/plots.py ml/pipelines/inventory.py scripts/run_inventory.py

# Default, lead-two, independent cold reproduction and exploratory higher-holding:
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa > .cache/phase4-default-cli.json
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa --config configs/phase4_lead2.json > .cache/phase4-lead2-cli.json
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa --output-dir artifacts/phase4-repro-check > .cache/phase4-repro-cli.json
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa --config configs/phase4_high_holding.json > .cache/phase4-high-holding-cli.json
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa > .cache/phase4-cache-cli.json
```

The CLI's `--help` lists directory/config flags. The Phase4 CLI consumes frozen tables without XGBoost/OpenMP model loading; the full regression command retains the macOS library prefix because Phase3 tests import/fit synthetic models. Production/reproduction commands without redirection are also in the README.

Cold/default and frozen-file verification (the ignored source snapshot was captured before scenario execution):

```bash
.venv/bin/python - <<'PY'
import json
from pathlib import Path
from ml.data.acquisition import sha256_file
v = json.loads(Path('.cache/phase4-default-cli.json').read_text())
a = Path(v['run_dir'])
b = Path('artifacts/phase4-repro-check') / v['run_id']
comparison = {str(p.relative_to(a)): sha256_file(p) == sha256_file(b/p.relative_to(a))
              for p in sorted(a.rglob('*')) if p.is_file()}
assert len(comparison) == 16 and all(comparison.values())
before = json.loads(Path('.cache/phase4-source-snapshot.json').read_text())
assert len(before) == 33
assert all(sha256_file(Path(p)) == digest for p,digest in before.items())
print('16 byte-identical scenario files; 33 unchanged frozen/ledger files')
PY
```

## Files created or modified

Created **18 files** against the Phase3 delivery:

```text
configs/phase4.json
configs/phase4_lead2.json
configs/phase4_high_holding.json
docs/INVENTORY_METHODOLOGY.md
docs/EXAMPLE_SCENARIO.md
docs/PHASE4_RESULTS.md
ml/inventory/__init__.py
ml/inventory/planning.py
ml/inventory/simulation.py
ml/inventory/config.py
ml/inventory/plots.py
ml/pipelines/inventory.py
scripts/run_inventory.py
ml/tests/test_inventory_planning.py
ml/tests/test_inventory_simulation.py
ml/tests/test_inventory_config.py
ml/tests/test_inventory_pipeline.py
ml/tests/test_inventory_plots.py
```

Modified **5 files**:

```text
README.md
docs/IMPLEMENTATION_PLAN.md
docs/DATA_DICTIONARY.md
docs/MODEL_CARD.md
docs/ML_METHODOLOGY.md
```

All files remain untracked because the repository has no commits. `PROJECT_SPEC.md`, existing source/ML logic, dependencies, PostgreSQL migrations/schema and all frozen analytical artifacts/ledger are unchanged. Generated data/models/reports/CSVs/plots/logs/local environments remain ignored. No remote, commit or push was created.

## Assumptions, limitations and unresolved problems

- **No unresolved implementation/test blocker remains for Phase4.** The full product remains incomplete until Phases 5–6 pass their gates. This phase provides local analytical logic, not an API/worker/dashboard or autonomous purchase integration.
- Results are an eight-week retrospective, truncated experiment on recorded purchases. Original availability, lost demand, starting inventory, supplier behavior and operating costs are unknown. Simulated lost sales are not observed retailer losses. Partial edge weeks stay excluded; no annual seasonal or current-day validity claim is made.
- Flat one-week carry-forward is an approximation for multiweek lead/review horizons. The explicit full-demand-week arrival convention is coarse and must be matched by future integrations. No final-week ordering occurs; initial stock and terminal treatment affect results.
- Safety stock assumes stable independent errors/normal factors and uses pooled pre-test RMSE, including bias. It is not a service guarantee, product-specific calibration certificate or statistically validated multiweek error distribution. Method-specific buffers confound any attribution solely to point forecast quality.
- Holding/stockout/order costs are scored, not optimized. These are constrained rule-based recommendations, not a proof of globally minimum cost. Full terminal asset recovery with zero pipeline carrying cost/discount/obsolescence materially favors stock exposure. The higher-holding reversal demonstrates sensitivity, not robustness across plausible costs.
- Capacity reserves all on-hand/pipeline per product conservatively. Backordered units are accepted in standalone planning but nonzero simulation initial backlog is rejected; unmet new demand is always lost rather than carried forward. No returns are converted into physical arrivals without evidence.
- Economic defaults are uniform illustrative GBP amounts; per-product overrides are available but not a substitute for operational data. Quantities are integer and bounded to 2**53−1 for exact forecast/order arithmetic; extreme numeric magnitudes fail rather than wrap silently.
- Python/runtime verification is on macOS ARM64 with PostgreSQL in Linux ARM64 Docker. Cross-platform application containers, distributed job reliability, API latency, auth/cloud and frontend browser tests remain unimplemented or out of scope. The existing optional MLflow deferral remains unchanged.
- The consumed Phase3 forecasting test and models remain frozen. Inventory sensitivity outcomes cannot justify retuning or another untouched-test claim. Later forecasting research needs new chronological evaluation data.

## Exact recommended next prompt

> Begin DemandIQ Phase 5 only. Read PROJECT_SPEC.md, README.md, docs/IMPLEMENTATION_PLAN.md, docs/DATA_PIPELINE.md, docs/ML_METHODOLOGY.md, docs/INVENTORY_METHODOLOGY.md, docs/MODEL_CARD.md and docs/PHASE4_RESULTS.md first, inspect the repository and rerun existing checks. Build the FastAPI service and PostgreSQL persistence for datasets, weekly demand, training runs, model artifacts, forecasts, inventory configurations and scenario/results metadata. Keep forecasting and inventory business logic in the existing independently tested modules. Add validated documented endpoints, CSV export services, structured logs, health/readiness, and background jobs with atomic claiming, idempotency, bounded retries, leases and failure recovery; add migrations and meaningful unit/integration/concurrency tests. Preserve frozen models/ledger and historical results, label retrospective simulations and assumptions, and do not retune the consumed test block. Update setup/API/worker documentation and demonstrate real jobs and persistence. Do not start Phase 6 or create a remote repository, commit or push.

<!-- Public release note: machine-specific paths and example passwords were normalized; recorded measurements are unchanged. -->
