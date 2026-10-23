# Forecasting methodology

The Phase 2 foundation below records its original data boundary and baseline protocol. Phase 3 has now completed model selection, separate uncertainty calibration and the once-only final test. The [Phase 3 extension](#completed-phase-3-extension) describes that transition; detailed fitting choices are in [ML methodology](ML_METHODOLOGY.md), intended use/limitations in the [model card](MODEL_CARD.md), and measured results in [Phase 3 results](PHASE3_RESULTS.md).

## Protocol fixed before product selection

The versioned default configuration is [`configs/phase2.json`](../configs/phase2.json). These dates were fixed from the already documented source coverage before any product-volume ranking or baseline comparison in Phase 2. Weeks start Monday at 00:00 London wall time; a week ends at the next Monday, exclusively.

| Block | First week | Last week | Complete weeks |
| --- | --- | --- | ---: |
| Initial training | 2010-12-06 | 2011-07-11 | 32 |
| Validation | 2011-07-18 | 2011-10-03 | 12 |
| Reserved test | 2011-10-10 | 2011-11-28 | 8 |

| Fold | Expanding training end | Validation weeks |
| --- | --- | --- |
| 1 | 2011-07-11 | 2011-07-18 through 2011-08-08 |
| 2 | 2011-08-08 | 2011-08-15 through 2011-09-05 |
| 3 | 2011-09-05 | 2011-09-12 through 2011-10-03 |

The partial source weeks starting 2010-11-29 and 2011-12-05 are excluded. The latter is after the reserved test interval. The source first/last timestamps alone determine coverage; target magnitudes do not determine split dates. No demand is inflated to compensate for partial coverage. A changed source with incomplete configured training/validation coverage must fail rather than silently shorten blocks.

The Phase 2 runner reads accepted transactions only before **2011-10-10**, using Parquet date filters. Within Phase 2, reserved test target values are not aggregated, featured, plotted, scored, inspected for product choice or used for parameter choice. Full-file integrity hashing reads bytes without interpreting held-out target values. At Phase 2 completion the eight-week test block was identified in metadata only and retained for a single evaluation after Phase 3 model selection. No Phase 2 test-set metric was produced. Phase 3 has since completed that separate final evaluation; the test is no longer globally unseen.

## Weekly facts and product eligibility

The forecasting target is **gross positive purchased units**, with separate positive returned and cancelled-unit measures. Net accounting units subtract both negative classes exactly once; the classes are mutually exclusive. Returns/credits are accounting signals, not matched physical movements. Purchase revenue and average selling price describe purchases, not purchase cost or inventory facts. Missing customer IDs retain unit demand; known unique-customer counts exclude null pseudonyms. Continuous weeks have zero gross/negative movements/revenue/transactions/customers when absent. Average selling price is null without purchases, because a zero price would imply a false observation.

Eligibility requires at least the configured number of continuous training panel weeks and positive training-period gross units. Zero filling assumes an observed source week with no transaction means zero recorded demand; it does not prove availability, stockouts, launch dates or unmet demand. Products are ranked by training gross units descending with stock code ascending as deterministic tie-breaker. Default limit is 50 and is configurable; fewer eligible products are reported honestly rather than fabricated. Eligibility does not require future activity or future completeness.

Product selection runs again at each fold's expanding training boundary. Every method in that fold receives exactly the same cohort. Cohorts can differ across folds, so pooled validation metrics describe the rolling top-product policy, not one unchanging basket. The initial training cohort is also saved for reproducibility; nothing is selected from the test block. Volume segments use training ranks within the fold.

## Baselines and leakage boundaries

- Naive: last completed week's demand.
- Moving average: the mean of the previous four completed weeks, including inserted zeros.
- Seasonal naive: demand four completed weeks earlier. The period is a configuration assumption fixed before validation, representing a short periodic persistence candidate. Four weeks are not a calendar month and there is no claim that the data proves a four-week retail cycle. An annual 52-week baseline cannot be validated from the initial 32-week training history. A period without sufficient prior observations must fail explicitly, never borrow a future or synthetic observation.

Forecasts are made one week ahead. Within a validation fold, last week's actual becomes known before forecasting the next week. This is rolling-origin evaluation, not a single forecast of an entire four-week block. Re-ranking remains frozen within the fold. This information boundary follows [Forecasting: Principles and Practice, time-series cross-validation](https://otexts.com/fpp3/toolbox.html#time-series-cross-validation); the [simple benchmark definitions](https://otexts.com/fpp3/toolbox.html#some-simple-forecasting-methods) distinguish naive and seasonal recurrence. The four-week assumption is DemandIQ's explicitly labeled comparison choice, not evidence supplied by that reference.

Lagged demand, rolling means/standard deviations, trend, prior revenue/price/transactions/customers and return/cancellation rates use only weeks strictly before their target. Calendar month, ISO week and quarter are known in advance. Optional named ISO-week indicators are configured externally and are not inferred from validation/test demand. Warm-up values and undefined price/rate values remain null. No preprocessing is fitted in Phase 2; completed Phase 3 fits encoders, imputers and any scaler inside each training fold, as described in [ML methodology](ML_METHODOLOGY.md).

## Evaluation and scope

Metrics use nonnegative actual/predicted unit demand. MAE and RMSE are in units; bias is mean `(prediction - actual)` and positive means overforecasting. WAPE and sMAPE are percentages; ordinary MAPE is omitted. WAPE is null when total actual demand is zero, including a perfect all-zero case. A zero/zero sMAPE pair contributes zero. JSON outputs use null instead of nonfinite numbers. Error is broken down by fold, product, week, training-volume segment and under/overforecast direction.

Phase 2 itself implemented no fitted model, hyperparameter search, feature importance or prediction interval. Its real baseline results, artifact locations, commands, limitations and test outputs remain in [Phase 2 results](PHASE2_RESULTS.md). The subsequent Phase 3 work below adds those ML capabilities. Inventory policies, an API and a frontend remain later phases.

## Completed Phase 3 extension

Phase 3 preserves the three expanding windows while separating their purposes before final-test access:

| Role | Target weeks | Observations per retained method | Permitted use |
| --- | --- | ---: | --- |
| Selection validation, folds 1–2 | 2011-07-18 through 2011-09-05 | 400 | Model-family and declared hyperparameter selection |
| Calibration only, fold 3 | 2011-09-12 through 2011-10-03 | 200 | Frozen-method residual calibration; no revision of selection |
| Final test | 2011-10-10 through 2011-11-28 | 400 | Once-only final point-error and interval evaluation after choices are frozen |

Each selection/calibration fold uses 50 products chosen from that fold's training history. The final cohort is separately ranked using all 44 pretest weeks through 2011-10-03, then fixed at 50 products throughout the eight test weeks. Every retained method receives that same final cohort. Cohort or hyperparameter changes based on test errors are prohibited. Phase 2's historical twelve-week baseline aggregate and Phase 3's eight-week selection aggregate describe different windows and must not be presented as the same score.

Ridge, Random Forest and XGBoost are evaluated against the three baselines. Two declared parameter candidates per ML family use the first two folds; pooled selection-validation WAPE determines the winner, with MAE and deterministic identifiers resolving ties and MAE handling undefined WAPE. Best ML family and recommended overall method are recorded separately so a baseline may win honestly. In the completed run Ridge was selected before testing. Preprocessing is training-fitted; the first 12 weeks are excluded from supervised fitting for feature warm-up. The final refit uses 1,600 supervised product-week rows from the fixed cohort's 44-week history.

Models, hyperparameters, preprocessing and interval radii remain frozen during final testing. This remains **one-week rolling-origin evaluation**: earlier completed test actuals can provide lags, baseline history and the next week's known scale. It is not an eight-week open-loop forecast made with no intervening observations. The first test origin's 300 forecasts were frozen before test-target access and verified against final evaluation.

Uncertainty uses a separate calibration window. For each method, score absolute residuals divided by `max(previous_four_week_mean, 10)` and use one-based rank `min(n, ceil((n+1)*0.8))`. With 200 residuals this is rank 161. At a later forecast origin, multiply the frozen radius by its known historical scale, subtract/add that amount to the point prediction, and clip only the lower bound at zero. These are empirical retrospective estimates under assumptions about residual stability; serial dependence, changing products and drift prevent a coverage guarantee. The completed Ridge result covered 318 of 400 test observations, **79.5% against nominal 80%**; no interval was adjusted after observing that outcome.

The authoritative experiment is `6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa`. Its frozen models, selection/calibration results, lineage and plan are under `artifacts/phase3/<experiment_id>/`; final-test predictions, point/interval metrics and plots are under `artifacts/phase3/evaluations/<experiment_id>/`. The [data dictionary](DATA_DICTIONARY.md#phase-3-training-and-frozen-evaluation-plan) documents their schemas. A dataset-scoped atomic evaluation ledger records the once-only test access; successful repeat commands verify/reuse those completed results rather than reopening selection.

See [ML methodology](ML_METHODOLOGY.md) for preprocessing, candidates, serialization and access details; the [model card](MODEL_CARD.md) for intended/prohibited uses and risks; and [Phase 3 results](PHASE3_RESULTS.md) for measured comparisons, commands, timing and verification evidence. Forecast accuracy and interval coverage do not establish inventory cost savings; those require the later configurable policy simulation.
