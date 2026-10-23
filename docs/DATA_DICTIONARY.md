# Data dictionary

The source contract is implemented in `ml/data/schema.py`; cleaning version **1.0.1** is implemented in `ml/data/cleaning.py`. See [the pipeline guide](DATA_PIPELINE.md) for source decisions and reason codes, [forecasting methodology](FORECASTING_METHODOLOGY.md) for chronology and cohorts, [ML methodology](ML_METHODOLOGY.md) for model fitting and calibration, and [inventory methodology](INVENTORY_METHODOLOGY.md) for simulated policies and assumptions. This dictionary covers completed Phase 1 transactions/metadata, Phase 2 weekly facts/features/baselines, Phase 3 frozen forecasting artifacts, and Phase 4 retrospective inventory scenarios. Intended use and limitations are in the [model card](MODEL_CARD.md); measured evidence is in [Phase 3 results](PHASE3_RESULTS.md) and [Phase 4 results](PHASE4_RESULTS.md).

## Source table

Input must contain exactly these eight unique, case-sensitive headers in any order. Extra, missing, duplicate or hierarchical headers fail the import. Row-level invalid scalar values are audited rather than causing a schema failure.

| Source field | Accepted interpretation | Missing or invalid behavior |
| --- | --- | --- |
| `InvoiceNo` | Text or integral numeric identifier; surrounding whitespace removed; numeric `.0` suffix removed | Missing, boolean or unsupported numeric/object value rejects the row |
| `StockCode` | Text or integral numeric product identifier; same normalization; maximum 128 Unicode characters after normalization | Missing, malformed, overlong or explicitly excluded nonmerchandise code rejects the row |
| `Description` | Nullable text, trimmed | Missing retained as null; invalid nontext value nulled and flagged |
| `Quantity` | Nonzero signed integer within `[-2^63, 2^63-1]`; numeric strings and integral numeric values supported | Missing, boolean, fractional, nonfinite, zero or out-of-range value rejects the row |
| `InvoiceDate` | Native naive datetime/date or one of the explicit string formats below | Missing, invalid, timezone-aware or nanosecond-out-of-range date rejects the row |
| `UnitPrice` | Finite, strictly positive float64; numeric strings supported | Missing, boolean, nonnumeric, nonpositive, overflow or underflow-to-zero value rejects the row |
| `CustomerID` | Nullable text or integral numeric identifier, normalized before pseudonymization | Missing retained as null; malformed value nulled and flagged; quantity is retained if other required fields are valid |
| `Country` | Nullable text, trimmed | Missing retained as null; invalid nontext value nulled and flagged |

Native dates become midnight. String formats are `YYYY-MM-DD`, ISO date plus `T` or space and `HH:MM[:SS[.ffffff]]`, and explicit day-first `DD/MM/YYYY[ HH:MM[:SS]]`. Fractional seconds in strings have at most six digits. Two-digit years, inferred month-first dates, numeric Excel serial dates, timezone suffixes and timezone-aware native values are unsupported. Stored values are naive London wall time, without a UTC conversion or inferred daylight-saving offset.

CSV is UTF-8, optionally with a BOM; every source field remains text until cleaning. Each row must match the header width. XLSX uses the first worksheet, a single header row and actual cell values; formulas are read as formula text rather than evaluated. Empty/whitespace-only strings, null values and numeric NaN count as missing. Literal text such as `NA` is not automatically converted to null.

## Accepted transaction Parquet files

`purchases.parquet`, `cancellations.parquet` and `returns.parquet` share this schema, including when empty. Rows retain their original relative order within each partition. Files use PyArrow, Zstandard compression and no DataFrame index.

| Output field | pandas type | Meaning |
| --- | --- | --- |
| `source_row` | `int64` | One-based data-row position after the header, independent of an in-memory input index |
| `invoice_no` | `string` | Required normalized invoice ID; lowercase leading `c` becomes `C` |
| `stock_code` | `string` | Required normalized merchandise code, at most 128 characters |
| `description` | nullable `string` | Trimmed source description; no imputation |
| `quantity` | `int64` | Signed movement: purchases positive; cancellations and returns negative |
| `invoice_date` | `datetime64[ns]` | Required naive London wall datetime |
| `unit_price` | `float64` | Required positive source unit price; no currency conversion or inferred purchase cost |
| `customer_key` | nullable `string` | Lowercase hexadecimal SHA-256 pseudonym of normalized customer ID with a fixed domain prefix |
| `country` | nullable `string` | Trimmed source country; no imputation |

`CustomerID` is never an output column. Missing customer IDs do **not** cause otherwise valid sales volume to be discarded. Distinct-known-customer counts consequently exclude customers with missing or malformed IDs; they are not estimates of total customers.

## Row audit

`audit.parquet` has exactly one row per source row, including accepted records. It contains no transaction values or customer identifiers.

| Field | pandas type | Meaning |
| --- | --- | --- |
| `source_row` | `int64` | One-based data-row position |
| `disposition` | `string` | Exactly one of `duplicate`, `rejected`, `purchase`, `cancellation`, `return` |
| `reasons` | `string` | Alphabetically sorted unique reason codes separated by `\|`; see [the catalogue](DATA_PIPELINE.md#reason-code-catalogue) |

Rejections are quarantined through this audit: rejected source values are not copied into a second processed table. The ignored local source plus `source_row` supports private investigation.

## Quality report and manifest

`quality.json` uses deterministic sorted-key JSON with no NaN/Infinity or wall-clock timestamp.

| Fields | Definition / scope |
| --- | --- |
| `cleaning_version` | Policy/schema implementation version |
| `original_rows`, `cleaned_rows`, `duplicate_rows`, `rejected_rows` | All source rows; cleaned is the sum of the three accepted partitions |
| `purchase_rows`, `cancellation_rows`, `return_rows` | Mutually exclusive accepted partition counts |
| `missing_descriptions`, `missing_customer_ids`, `missing_countries` | Missing-value flags on nonduplicate source rows before rejection |
| `invalid_prices`, `invalid_quantities`, `invalid_dates` | Required-value error flags on nonduplicate source rows before rejection |
| `missing_invoice_ids`, `missing_product_ids`, `invalid_product_ids` | Identifier flags on nonduplicate source rows before rejection; invalid product IDs include overlong codes |
| `date_range` | `{start, end}` ISO datetimes across all accepted partitions; both null when no rows are accepted |
| `unique_products`, `unique_invoices`, `unique_customers`, `unique_countries` | Distinct nonnull values across all accepted partitions |
| `countries` | Sorted distinct accepted nonnull country names |
| `reason_counts` | Number of audit rows containing each reason code; a row may have multiple reasons |
| `count_scopes` | Machine-readable descriptions of the scopes above |
| `stages` | Ordered source → exact deduplication → validation/eligibility → classification entries with `before`, `after`, `removed`; final entry includes partition counts |
| `policies` | Human-readable rules and the explicit excluded-code list |

Flags overlap and must not be summed to infer rejected rows. Duplicate copies receive only `exact_source_duplicate`; their values do not contribute a second time to quality-flag counts. Cancellation/return summary fields count accepted movements, while rejected C-positive anomalies are visible in `reason_counts`.

`manifest.json` contains `dataset_id`, `source_sha256`, `cleaning_version`, `config`, `artifact_dir`, `artifacts`, `original_rows` and `cleaned_rows`. `config` records cleaning version, pipeline version and input format. `artifacts` records SHA-256 for every output file other than the manifest, plus row counts for Parquet files. `artifact_dir` is the dataset ID relative to the configured processed root; it is not an absolute source or machine path.

## PostgreSQL metadata

| Table | Stored data |
| --- | --- |
| `datasets` | Dataset ID primary key, source SHA-256, cleaning version, ready status, source/accepted counts, configuration, artifact hashes/reference, manifest and database insertion time |
| `data_quality_reports` | One JSONB report per dataset; primary/foreign key with cascade deletion |
| `products` | Composite primary key `(dataset_id, stock_code)`, nullable description; stock-code width 128 |

The product catalogue includes all accepted products across purchases, cancellations and returns. Its description is the earliest nonnull accepted description in source-row order. No top-product ranking or training-period selection occurs in Phase 1. Raw transactions and customer pseudonyms are not inserted into these tables.

## Phase 2 artifact boundary

Phase 2 outputs live under `data/phase2/<run_id>/` by default. The runner reads transaction values only from the configured complete training/validation weeks, with a Parquet filter strictly before the reserved test start. **No held-out test rows, test features, test predictions or test scores enter Phase 2 analytical outputs.** Test dates and reserved status appear in that phase's metadata only. This describes the historical Phase 2 boundary: Phase 3 has now completed the separately authorized final test, whose artifacts are documented below. Phase 1 source/accepted files still preserve their original full coverage.

The Phase 2 run ID hashes phase version, source dataset ID, configuration and relevant dependency versions. Its manifest records that identity, `test_status="reserved_unread_unevaluated"`, artifact SHA-256 values and Parquet row counts, feature names and requested/selected cohort sizes. Artifacts are published together and verified on reuse. Measured runtimes remain outside deterministic files. These analytical files do not create weekly-demand or model database tables in Phase 2.

## Weekly facts: `weekly.parquet`

`ml/data/weekly.py::aggregate_weekly` produces unique `(stock_code, week)` keys, sorted by product then week. Every included product has one row for every inclusive Monday label between `start_week` and `end_week`; the last label includes its entire Monday–Sunday week. The caller chooses complete source weeks. Absent movements become zeros; partial-week quantities are never scaled upward.

When no product list is supplied, the cohort is the union of products observed in any accepted movement class within that window. Explicit unique product IDs can include entirely absent products, which receive zero rows for every week. This full factual panel precedes fold-specific training-only selection.

| Field | pandas dtype | Definition |
| --- | --- | --- |
| `stock_code` | `string` | Normalized merchandise code |
| `week` | `datetime64[ns]` | Naive Monday at midnight, London wall time |
| `gross_units` | `int64` | Sum of positive purchase quantities; the initial forecasting target |
| `returned_units` | `int64` | Sum of absolute negative quantities from the non-C return partition |
| `cancellation_units` | `int64` | Sum of absolute negative quantities from the C-prefixed cancellation partition |
| `net_units` | `int64` | `gross_units - returned_units - cancellation_units`; may be negative |
| `revenue` | `float64` | Gross purchase sum of `quantity * unit_price`; excludes return/cancellation credits |
| `transactions` | `int64` | Count of accepted **purchase rows/line items**, not distinct invoices |
| `unique_customers` | `int64` | Distinct nonnull purchase `customer_key` values in that product/week |
| `average_price` | `float64` | Unit-weighted `revenue / gross_units`; NaN without purchases |

The credit classes remain distinct and are subtracted once each for net accounting units. They are not matched physical returns, and net units are not the forecasting target. Empty weeks have zero units, revenue, line-item counts and known customers, with a null average price rather than a fabricated zero selling price. Missing customer IDs retain purchase volume and row counts; they contribute no distinct known customer.

Aggregation requires positive purchase signs, negative credit signs, matching C-prefix classes, finite positive source prices, naive dates and distinct source-row IDs within/across partitions. Normalized duplicate-looking values with different source-row IDs are retained. Unit sums, absolute negative quantities, net units and revenue have explicit range checks; integer overflow is never allowed to wrap silently.

## Product selection and cohorts

`select_top_products(panel, train_end=..., top_n=50, min_history_weeks=12)` ranks positive training-period gross volume through its inclusive Monday `train_end`. A product needs the configured number of continuous training panel rows ending at that boundary. Zero-demand weeks count as history; only positive-demand weeks count as active. Products with no training rows or no positive training volume are excluded. Ranking is `training_units` descending, then `stock_code` ascending; future activity/volume does not determine eligibility or rank.

| Selection field | pandas dtype | Definition |
| --- | --- | --- |
| `stock_code` | `string` | Selected product ID |
| `training_units` | `int64` | Exact gross-unit sum through that fold's training end |
| `active_training_weeks` | `int64` | Count of training rows with positive gross units |

`selected_products.json` is a list of those records for the **first** fold's initial-training cohort. `fold_products.json` is the complete per-fold record list: integer `fold`, ISO-date `train_start`, `train_end`, `validation_start`, `validation_end`, and `products` containing the selection records. Cohorts are recomputed at each expanding training boundary and frozen within that fold. All baselines share the same cohort in a fold; the basket can change across folds.

`training_volumes.parquet` contains one row per evaluated `(fold, stock_code)`: `stock_code` (`string`), `training_units` (`int64`) and `fold` (text labels stored as pandas `object`). These fold-specific training volumes determine demand-volume segments; validation/test actuals do not.

## Features: `features_fold_<fold>.parquet`

`ml/features/weekly.py::generate_features` emits a separate history/validation feature table for each fold cohort, ending at that fold's validation end. It preserves `stock_code` (`string`), `week` (`datetime64[ns]`) and the target `gross_units` (`int64`). The target and week keys are **not numeric model features**. `feature_columns()` lists the categorical product ID plus the feature names below, including any configured seasonal indicators.

For a target week `t`, let `g[t]` be gross purchase units. All historical features use weeks strictly before `t`. These dtypes describe the pinned Phase 2 pipeline's typed weekly inputs; lagged integer observations become float64 so missing warm-up values can remain NaN.

| Feature name | pandas dtype | Formula / information available before `t` |
| --- | --- | --- |
| `demand_lag1` | `float64` | `g[t-1]` |
| `demand_lag2` | `float64` | `g[t-2]` |
| `demand_lag4` | `float64` | `g[t-4]` |
| `demand_lag8` | `float64` | `g[t-8]` |
| `rolling_mean4` | `float64` | Mean of `g[t-4]` through `g[t-1]`; all four rows required |
| `rolling_mean8` | `float64` | Mean of `g[t-8]` through `g[t-1]`; all eight rows required |
| `rolling_mean12` | `float64` | Mean of `g[t-12]` through `g[t-1]`; all twelve rows required |
| `rolling_std4` | `float64` | Population standard deviation (`ddof=0`) of preceding four weeks |
| `rolling_std8` | `float64` | Population standard deviation (`ddof=0`) of preceding eight weeks |
| `recent_trend` | `float64` | Mean of `g[t-4:t-1]` minus mean of `g[t-8:t-5]`, with both endpoints inclusive |
| `previous_week_revenue` | `float64` | Gross purchase revenue at `t-1` |
| `previous_week_average_price` | `float64` | Unit-weighted selling price at `t-1`; null if that week had no purchase |
| `previous_week_transactions` | `float64` | Purchase line-item count at `t-1`, not unique invoice count |
| `previous_week_unique_customers` | `float64` | Distinct known purchase customers at `t-1` |
| `recent_return_rate` | `float64` | Sum of returned units in preceding four weeks / sum of gross units in those weeks |
| `recent_cancellation_rate` | `float64` | Sum of cancelled units in preceding four weeks / sum of gross units in those weeks |
| `month` | `int32` | Calendar month of target Monday |
| `iso_week` | `int64` | ISO week number of target Monday |
| `quarter` | `int32` | Calendar quarter of target Monday |
| `seasonal_<name>` | `int8` | Optional 0/1 indicator that target ISO week is in that externally configured list |

Warm-up values remain NaN until a full lag/window exists. A zero gross denominator makes a recent return/cancellation rate NaN rather than zero; rates can exceed one because credits need not match same-period sales. No encoder, scaler or imputer is fitted here. Configured seasonal names/ISO-week lists are assumptions known in advance, not holidays or seasonal effects inferred from validation data. `seasonal_indicators={}` emits no extra indicator columns.

## Phase 2 baseline validation: `validation_predictions.parquet`

The unique key is `(fold, stock_code, week, model)`. Every model covers the same product/week observations in each fold and shares the same actual demand. Rows are sorted by fold label, week, product and model.

| Field | Emitted pandas dtype | Definition |
| --- | --- | --- |
| `stock_code` | `object` containing text | Fold cohort product |
| `week` | `datetime64[ns]` | One-week-ahead validation target Monday |
| `model` | `object` containing text | `naive`, `moving_average_<window>` or `seasonal_naive_<period>` |
| `prediction` | `float64` | Nonnegative point prediction using only completed weeks before target |
| `actual` | `int64` | Observed gross purchase units for the validation week |
| `fold` | `object` containing text | Expanding-fold label |

Parquet text columns are logical strings even where pandas emits `object`. The configured moving window/seasonal period is reflected in the model label. Completed earlier validation weeks may enter the next one-week origin's history; current/future targets cannot. These Phase 2 baseline outputs contain no uncertainty bounds or fitted ML model predictions; Phase 3 publishes separate outputs for both.

## Evaluation: `metrics.json`

In Phase 2's `metrics.json`, `evaluation_scope` is exactly `"validation"`. Phase 3 reuses the grouped metric schema with the distinct scopes listed below. Each grouped metric record includes `n_observations` (integer product/week/fold count), finite `mae`, `rmse`, `smape`, `bias` (JSON numbers), `wape` (number or null), and `wape_status` (`defined` or `undefined_zero_actual`). MAE/RMSE/bias are units; WAPE/sMAPE are percentages. Bias is `prediction - actual`, so positive means overforecasting. WAPE is null when summed actual demand is zero; a zero/zero sMAPE pair contributes zero.

| Top-level field | Record keys in addition to common metrics / content |
| --- | --- |
| `overall` | `model` |
| `by_fold` | `model`, `fold` |
| `by_product` | `model`, `stock_code` |
| `by_week` | `model`, `fold`, ISO-datetime `week` |
| `by_segment` | `model`, `segment` (`high`, `medium`, `low`) |
| `error_direction` | `model`, integer `underforecast_count`, `overforecast_count`, `exact_count`, numeric `underforecast_units`, `overforecast_units` |
| `training_segments` | `fold`, `stock_code`, numeric `training_units`, `segment` |
| `metric_definitions` | Map of metric/protocol names to explanatory strings |

Segments rank training volume within each evaluated fold cohort, using product IDs to resolve ties, then divide ranks into high/medium/low thirds. Exact integer training volumes retain their precision during ranking and JSON serialization. Pooled metrics use individual product/week/fold errors rather than averaging group means. Consequently Phase 2's aggregate describes its evaluated changing cohorts. Direction counts are observations; direction unit totals sum under/overforecast magnitudes. The metric schema itself does not assert model selection or business savings; Phase 3 records selection and final-test scope explicitly.

`config.json` preserves the explicit phase configuration. `splits.json` records training/validation/test date blocks, exclusive timestamp ends, week counts, fold boundaries and the reserved test status. `report.md` and `plots/` present actual validation results from the same records. Exact configured dates and interpretation are documented in [forecasting methodology](FORECASTING_METHODOLOGY.md); measured results are recorded separately after execution.

## Phase 3 training and frozen evaluation plan

The completed frozen experiment is `6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa`. Training artifacts live under `artifacts/phase3/<experiment_id>/`; the separately published final evaluation lives under `artifacts/phase3/evaluations/<experiment_id>/`. These private generated files remain ignored by Git. Earlier local experiments are not the authoritative final result.

| Training artifact | Content / meaning |
| --- | --- |
| `config.json` | Seed, timeline/product-selection settings, warm-up weeks, nominal interval coverage and scale floor |
| `candidate_predictions.parquet`, `candidate_metrics.json` | Six declared ML parameter candidates plus three baselines on selection folds 1–2; candidate IDs remain distinct; 400 observations per method in this run |
| `selection_predictions.parquet`, `selection_metrics.json` | The chosen candidate from each of Ridge, Random Forest and XGBoost, plus the three baselines; 2,400 rows total, 400 per method; scope `selection_validation` |
| `selection_training_volumes.parquet` | Exact `(fold, stock_code, training_units)` for selection-volume segmentation; 100 rows for two 50-product folds |
| `calibration_predictions.parquet`, `calibration_metrics.json` | Six frozen methods on reserved fold 3; 1,200 rows total, 200 per method; scope `calibration_only_not_selection` |
| `calibration.json` | Per-method frozen normalized residual radius, calibration dates, quantile rank, nominal coverage and warnings; schema below |
| `pretest_weekly.parquet` | Same weekly fact schema as above for the final fixed 50-product cohort over 44 complete pretest weeks; 2,200 rows |
| `cohort.json` | Final 50-product cohort, ranked by exact pretest training volume through 2011-10-03; frozen throughout final testing |
| `models/{ridge,random_forest,xgboost}.joblib` | Three final fitted estimator pipelines, including their training-fitted preprocessing; trusted local files only |
| `importance.json` | Model family → measured feature records with `feature`, nonnegative `importance`, and explicit native `method` |
| `pretest_forecasts.parquet` | 300 forecasts: six methods × 50 products for the first test origin, generated and frozen without reading that origin's target; no `actual` field |
| `plan.json` | Frozen source/experiment identity, selected candidate IDs/parameters, best ML family, recommended overall method, feature list, seed, one-week horizon, role dates, cohort/model/calibration hashes and no-refit/no-reselection declarations |
| `training_metadata.json` | Training UTC timestamp, available Git hash, per-fit stage/rows/measured duration, final fit cutoff/rows, artifact locations, source Phase 2 run and local tracking choice |
| `manifest.json` | Experiment/source identity, phase/runtime/configuration/candidate/code lineage, plan hash, artifact SHA-256 inventory and state `frozen_pretest` |

The final refit has 1,600 supervised rows: 50 products × 32 usable weeks after the 12-week warm-up within the 44-week pretest history. Models and transformations are not refit during testing. Joblib uses Python serialization: hashes detect corruption but do not make an untrusted model safe to load.

## Phase 3 prediction and interval fields

Selection/calibration predictions share `stock_code`, `week`, `actual`, `scale`, `prediction`, `model`, and `fold`. Text fields are Parquet strings, `week` is `timestamp[ns]`, `actual` is `int64`, and `scale`/`prediction` are `float64`. Model-family labels are `ridge`, `random_forest`, `xgboost`, `naive`, `moving_average_4` and `seasonal_naive_4`; candidate-comparison rows instead retain candidate IDs for the six ML choices.

| Additional field | Type | Meaning |
| --- | --- | --- |
| `scale` | `float64` | Previous four completed weeks' mean gross demand, known before the target week; the floor is applied separately |
| `lower` | `float64` | `max(0, prediction - normalized_radius * max(scale, scale_floor))` |
| `upper` | `float64` | `prediction + normalized_radius * max(scale, scale_floor)` |
| `nominal_coverage` | `float64` | Configured target fraction, 0.8 in the completed run; not a guarantee |
| `uncertainty_label` | text | Explicit empirical-interval label and absence of a time-series coverage guarantee |

The last four fields occur in pretest and final-test forecasts. Final-test `predictions.parquet` also contains observed `actual`, enabling retrospective evaluation. Negative ML point outputs are clipped at zero before evaluation; bounds must contain their point forecast. Each method covers the same unique product/week observations. The frozen first-origin forecasts are checked against the first final-test origin.

`calibration.json` maps each method to `method`, `nominal_coverage`, `scale_floor`, `n_calibration`, `calibration_start`, `calibration_end`, `normalized_radius`, `requested_rank`, `quantile_rank`, `insufficient_samples`, and `warning`. The method is `scaled_absolute_residual_higher_quantile`. Calibration score is `abs(actual - prediction) / max(scale, scale_floor)`; use sorted one-based rank `min(n, ceil((n+1)*nominal_coverage))`. This run has 200 calibration residuals per method, floor 10 units and rank 161 for nominal 80%. Applying intervals requires every forecast week to follow that model's calibration end strictly. Future actual demand cannot alter the frozen radius or its applied bounds.

## Phase 3 final evaluation artifacts

Final testing for the frozen experiment is now **completed**, not globally unseen or reserved. Only the historical Phase 2 run retains its original reserved-test status.

| Final evaluation artifact | Content / meaning |
| --- | --- |
| `predictions.parquet` | 2,400 bounded predictions: six frozen methods × 50 fixed products × eight test weeks, 2011-10-10 through 2011-11-28; 400 observations per method |
| `training_volumes.parquet` | 50 exact product volumes from the 44-week pretest history, with final-test fold label; no test demand enters segment ranks |
| `metrics.json` | Shared grouped point-error schema with `evaluation_scope="test"`; separate from selection and calibration metrics |
| `interval_metrics.json` | `scope="test"`, `definition`, per-model `overall` records and optional `by_segment` records; the completed run's `by_segment` list is empty |
| `evaluation_metadata.json` | Experiment/source/plan identity, selected/recommended methods frozen before test, six method labels, horizon, no-refit declaration, UTC evaluation timestamp and measured batch/total duration |
| `manifest.json` | Final-test scope and experiment/source/plan identity, with complete artifact hashes |
| `plots/` | Separate selection/final-test point-error comparison, chosen-product forecast and empirical bounds, final-test coverage/width, and explicitly labeled native importance |

Interval metric rows contain `model`, integer `n_observations`, `coverage`, `mean_width`, `below_rate`, `above_rate` and `nominal_coverage`. Coverage is the fraction of actuals inclusively within the bounds; below/above are actuals outside them; mean width is `upper - lower` in units. The completed Ridge interval coverage is 0.795, or 318 of 400 test observations, against nominal 0.8. This is retrospective evidence for this run, not promised future reliability.

The dataset-scoped `data/evaluation-ledger/<dataset_id>.json` records the atomic final-test reservation and completed result reference. A successful repeated evaluation command verifies/reuses the existing result; it does not treat the test as unseen or authorize another selection cycle. See [ML methodology](ML_METHODOLOGY.md), the [model card](MODEL_CARD.md), and [Phase 3 results](PHASE3_RESULTS.md) for the access protocol, limitations and measured results. No inventory savings or production business outcome is represented by these forecasting artifacts.

## Phase 4 scenario boundary and artifact inventory

Phase 4 consumes the completed, verified Phase 3 experiment and its already-observed final-test forecasts. It does not retrain models, rerank the frozen 50 products, recalibrate forecast intervals, reopen an untouched forecasting test, or read raw transactions. The selected ML family remains the Ridge choice frozen before the Phase 3 test. Five policies simulate the same eight historical weeks, 2011-10-10 through 2011-11-28: `previous_demand`, `moving_average_4`, `fixed_reorder_point`, `ml_safety_stock`, and `moving_average_safety_stock`. Their shared inputs and hypothetical outcomes remain separate.

The measured default scenario is stored locally at `artifacts/phase4/a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967/`. Its verified inventory contains 400 historical product-week rows, 2,000 simulated policy/product/week rows, 1,099 simulated orders and 2,000 decision records. These counts describe this actual default output; overrides can produce different order counts. Files remain ignored local artifacts, with no customer identifiers or fitted models added here.

| Artifact | Category and content |
| --- | --- |
| `config.json` | Scenario assumptions: name, illustrative currency, initial coverage, default business parameters and product overrides |
| `lineage.json` | References to frozen source identities and hashes: dataset, experiment, training/evaluation manifests, plan, completed evaluation ledger and ML family chosen before testing |
| `product_inputs.json` | One resolved input record per frozen product, separating configurable parameters from pre-test-derived stock/forecast/error inputs |
| `demand.parquet` | Historical gross recorded purchase units, deduplicated across forecast methods; the simulator treats these observations as demand |
| `weekly_results.parquet` | Simulated stock, fulfillment, lost units, orders, cash costs and revenue by policy/product/week |
| `orders.parquet` | Hypothetical order/receipt ledger, including configured prepaid initial orders when present |
| `recommendations.parquet` | Decision audit at every policy/product/week boundary, including nonreview/final-week zero-order reasons |
| `summary.json` | Simulated policy/product totals, service definitions, terminal accounting and signed ML-versus-baseline comparisons |
| `report.md`, `plots/` | Human-readable measured scenario report and three figures: `policy_comparison.png`, `inventory_trajectory.png`, `cost_components.png` |
| `exports/` | CSV views of policy summary, weekly results and recommendations; schemas below |
| `manifest.json` | Complete state, run ID, configuration, source lineage, dependency versions, implementation hashes and every artifact's SHA-256; Parquet entries also record row counts |

Run identity hashes the scenario configuration, frozen lineage, runtime and implementation identities. Publication is atomic and reuse verifies the complete artifact inventory. Measured execution time is returned separately rather than inserted into deterministic scenario files. The referenced Phase 3 forecast files and evaluation ledger remain unchanged; Phase 4 does not publish a replacement forecasting evaluation.

## Scenario configuration and resolved product inputs

`config.json` has `name`, `currency`, `initial_coverage_weeks`, `defaults` and `products`. `defaults` contains the `InventoryParameters` fields below. `products` maps a frozen stock code to optional parameter overrides, integer `initial_on_hand`, dated `initial_orders`, and `backordered_units` (only zero is supported). An initial order is `{week, quantity}` with a naive Monday receipt date and positive integer units; it cannot arrive before the simulation starts. It can remain outstanding beyond the final week.

| Parameter | Type / unit | Illustrative default |
| --- | --- | --- |
| `lead_time_weeks` | Positive integer complete future weeks before receipt | 1 |
| `review_period_weeks` | Positive integer weeks between reviews | 1 |
| `service_level` | Number strictly between zero and one; normal-factor input, not a promised outcome | 0.95 |
| `unit_purchase_cost`, `unit_selling_price` | Nonnegative assumed currency per unit | 1.00, 2.00 |
| `holding_cost_per_unit_week` | Nonnegative assumed currency per ending on-hand unit/week | 0.02 |
| `stockout_penalty_per_unit` | Nonnegative assumed currency per lost unit | 3.00 |
| `order_cost` | Nonnegative assumed currency per positive placed order | 5.00 |
| `min_order_quantity`, `case_pack_size` | Nonnegative MOQ and positive pack size, in integer units | 0, 1 |
| `max_inventory_capacity` | Nullable nonnegative integer reservation limit on on-hand plus all outstanding units | null |
| `fixed_reorder_point`, `fixed_target_level` | Nullable paired fixed-policy thresholds; target must be at least reorder point | null, null |

Prices and costs are illustrative GBP inputs in the default, not observed retailer economics or historical source selling prices. Stock/order quantities are bounded to `2^53-1` exact integer units; inputs and calculated quantities/costs must remain finite. All policies share the same resolved parameters and starting inventory for a product.

Each `product_inputs.json` record contains:

| Field | Meaning / source |
| --- | --- |
| `stock_code` | Frozen Phase 3 cohort member; no scenario-driven product selection |
| `parameters` | Fully resolved business parameters, including product overrides |
| `initial_on_hand` | Configured override, or `ceil(initial_coverage_weeks × mean pre-test weekly gross units)`; default coverage is two weeks |
| `initial_orders` | Shared configured prepaid arrivals, each with ISO-date `week` and integer `quantity`; empty in the measured default |
| `fixed_forecast` | Mean demand over all 44 pre-test weeks; held constant for the fixed policy |
| `error_multipliers` | Per-method pooled normalized RMSE from dedicated pre-test calibration: `sqrt(mean(((actual-prediction)/max(scale,10))^2))` |
| `fixed_error_std` | Moving-average calibration multiplier times `max(last four pre-test weeks' mean,10)`, held constant |

The dynamic controllers multiply their own method's frozen calibration multiplier by `max(next-origin scale,10)`. That scale is the preceding four completed weeks' mean, available at the decision. The resulting `error_std` is an empirical error magnitude including bias, rather than an unbiased standard-deviation estimate. Neither test residuals nor simulation costs estimate these multipliers. For a decision after week `t`, the controller consults only the forecast for `t+1`; later horizon weeks carry that value forward flat. The repeat-last policy directly uses the just-completed observed demand. Credits do not become physical receipts.

## Historical scenario demand: `demand.parquet`

| Field | Arrow type | Meaning |
| --- | --- | --- |
| `stock_code` | `string` | Frozen product identifier |
| `week` | `timestamp[ns]` | Historical demand week's naive Monday label |
| `actual` | `int64` | Recorded gross positive purchase units, unchanged from the frozen forecast evaluation |

The key is `(stock_code, week)`. All products share the same continuous weekly grid. These are historical recorded purchases; treating them as complete demand is a simulation assumption. They do not reveal actual inventory, unrecorded stockouts or real lost demand.

## Simulated weekly results: `weekly_results.parquet`

The unique key is `(policy, stock_code, week)`. Text fields are Arrow strings, `week` is `timestamp[ns]`, unit counts below are `int64`, `stockout_event` is Boolean, and cost/revenue fields are `float64`.

| Fields | Meaning |
| --- | --- |
| `policy`, `stock_code`, `week`, `actual` | Policy/product/week identifiers and the common historical demand input |
| `opening_inventory`, `opening_on_order` | On-hand and outstanding units before that week's receipts |
| `received_units`, `available_inventory` | Orders due before demand; available equals opening on-hand plus receipts |
| `fulfilled_units`, `lost_units`, `stockout_event` | Fulfilled units, demand minus fulfilled units, and whether lost units are positive |
| `ending_inventory` | Available units minus fulfilled units; never negative |
| `ordered_units`, `outstanding_units` | New units ordered after demand, and all pipeline units remaining after that decision |
| `purchase_cost`, `order_cost` | New ordered units × assumed purchase price, and the fee for a positive new order; prepaid initial pipeline is not charged again |
| `holding_cost`, `stockout_cost` | Ending on-hand × holding rate, and lost units × assumed penalty |
| `gross_cash_cost` | `purchase_cost + holding_cost + stockout_cost + order_cost` |
| `revenue`, `lost_revenue` | Fulfilled and lost units, respectively, times assumed selling price |
| `estimated_lost_margin` | Lost units × `max(assumed selling price − purchase cost,0)`; reported separately rather than added again to stockout cost |

Every row reconciles `opening_inventory + received_units = fulfilled_units + ending_inventory` and `opening_on_order − received_units + ordered_units = outstanding_units`. Orders placed after `t` arrive before demand in `t+L+1`; L=1 therefore arrives at `t+2`. Reviews follow indices `0,R,2R,...`, with no final-week orders. Orders due after the horizon stay in outstanding inventory and terminal valuation.

## Simulated orders: `orders.parquet`

| Field | Arrow type | Meaning |
| --- | --- | --- |
| `policy`, `stock_code`, `order_id` | `string` | Deterministic simulated order identity, not an external purchase-order identifier |
| `placed_week` | Nullable `timestamp[ns]` | End-week placement label; null for configured prepaid initial orders |
| `due_week` | `timestamp[ns]` | Receipt-before-demand week; never accelerated to fit the horizon |
| `quantity` | `int64` | Positive whole units, respecting the applicable MOQ/pack/capacity constraints for newly placed orders |
| `is_initial`, `received_by_horizon` | `bool` | Whether the order was supplied as initial pipeline and whether its receipt falls inside the horizon |
| `purchase_cost`, `order_cost` | `float64` | Placement costs for a new order; both zero for prepaid initial pipeline |

## Decision audit: `recommendations.parquet`

The key is `(policy, stock_code, week)`, where `week` is the end-of-week decision label after that week's demand. Zero orders and their explanations remain visible. No record executes a real purchase.

| Fields | Type / meaning |
| --- | --- |
| `policy`, `stock_code`, `week` | Strings and naive Monday timestamp identifying the decision |
| `forecast_week`, `review_due` | Nullable next-origin timestamp and Boolean review flag; final `forecast_week` is null and final orders are zero |
| `inventory_position` | `int64` on-hand plus all outstanding units before placement; backorders are zero in this lost-sales simulator |
| `weekly_forecast`, `forecast_model` | Nullable point input and method: selected ML family, `moving_average_4`, `naive` for repeat-last observed demand, or `pretest_fixed` |
| `error_std` | Nullable frozen-calibration error magnitude; not inferred from current/future simulation outcomes |
| `lead_time_demand`, `safety_stock`, `target_safety_stock` | Nullable controller lead demand, lead safety stock and protection-period safety stock |
| `reorder_point`, `target_inventory_position` | Nullable controller threshold and order-up-to target; direct-repeat policies do not use these thresholds |
| `requested_quantity`, `recommended_order_quantity` | Nonnegative raw request (`float64`) and feasible whole-unit order (`int64`) after rounding/constraints |
| `capacity_available`, `service_level_factor` | Nullable reservation room and normal-service factor; uncomputed/noncontroller fields remain null |
| `horizon_assumption`, `reasons` | Text explaining flat carry-forward/timing, and Arrow `list<string>` decision/constraint reason codes |

Numeric controller fields are `float64` except integer position, feasible quantity and nullable capacity. The measured uncapped default has Arrow `null` type for `capacity_available` because every value is null. Null forecast/threshold fields on nonreview or final rows are not zero estimates. At such boundaries, no forecast value is consulted; a nonfinal next-origin label alone does not imply a review occurred.

## Scenario summaries and CSV exports

`summary.json` contains `policies` (five aggregate records), `products` (one record per policy/product; 250 in the default), and `comparisons` (ML against each of the four other policies). It also preserves scenario/currency/source identifiers, `selected_model`, `selected_ml_before_test`, `primary_metric="net_inventory_cost"`, retrospective `scope`, and explicit `accounting`, `timing`, `forecast_information`, `service_definition` and `savings_label` text.

| Summary fields | Definition |
| --- | --- |
| `weeks`, `product_count` | Horizon length and product count; `product_count` occurs on policy aggregates, `stock_code` on product records |
| `total_demand`, `fulfilled_units`, `lost_units` | Common historical input, simulated fulfillment and simulated lost-unit totals |
| `fill_rate` | Total fulfilled / total demand; defined as 1 when total demand is zero |
| `stockout_events`, `stockout_frequency`, `service_level` | Count and fraction of product-weeks with lost units, and its complement; zero-demand weeks count as no-stockout weeks. Product records use their own weeks. This is not an order-cycle service probability. |
| `average_inventory` | Product record: mean ending on-hand over weeks. Policy record: mean weekly **total portfolio** ending on-hand, equal to the sum of product means |
| `initial_on_hand`, `initial_on_order`, `received_units`, `ordered_units`, `ending_inventory`, `outstanding_units` | Initial state, receipt/placement totals, and closing on-hand/pipeline units |
| `purchase_cost`, `holding_cost`, `stockout_cost`, `order_cost`, `gross_cash_cost` | Sums of the corresponding weekly cash-cost fields |
| `initial_inventory_asset_value`, `terminal_inventory_asset_value` | Initial/final on-hand plus pipeline units valued at assumed unit purchase cost; initial pipeline is prepaid |
| `net_inventory_cost` | Primary cost: gross cash cost + initial asset value − terminal asset value; checked against the equivalent consumed-goods form |
| `cost_of_goods_sold` | Fulfilled units × assumed purchase cost; net inventory cost reconciles to this plus holding, stockout and order costs |
| `revenue`, `lost_revenue`, `estimated_lost_margin` | Assumed-price simulated totals, with lost margin kept separate from the penalty objective |

Terminal valuation assumes full recovery at purchase cost, with no discount, obsolescence or salvage loss. It prevents post-horizon pipeline or excess stock from disappearing from accounting. Cash spending and terminal-adjusted costs answer different questions; neither is an observed retailer expense.

Each comparison has `policy="ml_safety_stock"`, `baseline_policy`, `baseline_net_inventory_cost`, `ml_net_inventory_cost`, signed `simulated_savings = baseline cost − ML cost`, and `simulated_savings_percent = 100 × savings / baseline cost` (null for a zero-cost baseline). Negative values mean ML costs more under those assumptions. The matched `moving_average_safety_stock` comparison uses the same controller as ML; direct-repeat comparisons compare complete policies, not forecast quality alone. No policy is selected or optimized from these outcomes.

`exports/summary.csv` is a flat view of `summary.policies`; `exports/weekly_results.csv` and `exports/recommendations.csv` retain their corresponding Parquet column names. Dates are textual in CSV, nullable values are empty cells, and recommendation `reasons` are serialized tuple text rather than an Arrow list. These exports contain real generated scenario records, with simulated quantities/costs clearly separated from historical demand. See [Phase 4 results](PHASE4_RESULTS.md) for measured scenarios, commands and limitations.

## Phase 5 persisted application records

The [backend schema](BACKEND_ARCHITECTURE.md#application-schema) documents relational keys and responsibilities. `weekly_demand` preserves every pre-test weekly measure above, scoped to the training run rather than a global mutable cohort. `forecast_values` uses `method` for analytical `model` and `point` for `prediction`; bounds/nominal coverage/uncertainty labels are retained. One-week actuals are SQL NULL, while verified retrospective actuals are nonnegative whole units. No test accounting facts are inferred from those targets.

`simulation_results` stores historical demand separately from simulated fulfilled/lost/ending inventory, with additional opening/pipeline/order/cost fields in `details`. `actual = fulfilled_units + lost_units` is enforced in PostgreSQL. Public job responses exclude payloads, source paths and lease tokens. Customer pseudonyms never enter these application tables. API CSV exports use typed analytical rows to preserve negative numeric outcomes while escaping formula-leading text; Arrow reason lists become textual lists in the API CSV. File-level Phase 4 exports retain their original representation.

## Dashboard projections and planner scope (Phase 6)

The dashboard reads verified projections described in [API.md](API.md), rather than raw transactions or customer pseudonyms. Product `stock_code` remains a string, including letters and leading zeros. First-origin lag/rolling features use only completed pre-test weeks. Selection-validation error tables retain their fold-specific training-selected cohorts; calibration and final-test scopes are distinct. Missing analytical values remain null and display as an em dash.

The planner uses the first historical post-refit origin, 2011-10-10 for the official run. Its empirical error magnitude comes from the reserved chronological calibration block, not test residuals. The desired service level is a probability input; the normal quantile is a derived factor. Approximate next-week shortage risk excludes undated on-order units and is not a guarantee or a retrospective observed service metric. Preview costs approximate the next week under entered assumptions; simulation costs account across the historical horizon with terminal asset treatment. These scopes are never interchangeable.

Source coverage timestamps have naive London wall-date semantics. The frontend preserves their source calendar date; timestamp values with explicit offsets retain their instant semantics. No live inventory, supplier or customer information is inferred from the historical sample.
