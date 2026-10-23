# DemandIQ model card — Phase 3

Version: frozen experiment `6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa`, evaluated 2026-10-18. This is a historical forecasting experiment, not a deployed purchasing system. Full commands, all six methods' metrics and test evidence are in [Phase 3 results](PHASE3_RESULTS.md); implementation details are in [ML methodology](ML_METHODOLOGY.md).

## Intended use and prohibited uses

Support analysis of **one-week-ahead gross recorded purchase units** for a configurable cohort of established, high-volume products. The measured default uses 50 products, selected separately at each training boundary. Compare simple forecasting methods, inspect historical errors and evaluate practical uncertainty before designing an inventory policy.

Do not use these artifacts for autonomous purchasing, customer profiling or customer-level decisions, credit decisions, real-time trading, pricing optimization, unreviewed production replenishment, new-product forecasting, or claims about present-day retail demand. Do not treat the intervals as guarantees, sales observations as unconstrained demand, or forecast accuracy as proven cost savings. Load joblib files only from trusted local sources; a matching checksum establishes integrity, not safety of an untrusted pickle.

## Data and target

[UCI Online Retail](https://archive.ics.uci.edu/dataset/352/online+retail), Chen (2015), [DOI 10.24432/C5BW33](https://doi.org/10.24432/C5BW33), CC BY 4.0. Source identity, cleaning decisions and complete counts are preserved in [Phase 1 results](PHASE1_RESULTS.md) and [data pipeline](DATA_PIPELINE.md). Dataset ID: `3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d`.

The target is positive purchase units per product and full Monday–Sunday week, using London wall-clock timestamps. Cancellations and unmatched returns are separate accounting measures, not negative target demand. Exact duplicates and invalid transactions follow the audited Phase 1 policies; unusual valid sales are retained. Continuous zero weeks describe recorded purchases, including weeks preceding first observed sales; they do not prove stock availability or zero latent demand. The partial weeks beginning 2010-11-29 and 2011-12-05 are excluded rather than extrapolated.

The historical retailer, limited period, high-volume selection, wholesale-like bulk purchases, incomplete known-customer coverage and non-random availability of transactions limit generalization. Only known customer counts enter aggregate features; no customer identifier enters model artifacts. Raw/processed data and all fitted artifacts remain ignored local files. There is insufficient initial training history for annual seasonal-naive evaluation. Four-week recurrence is a declared comparator, not a discovered monthly pattern.

## Chronological evaluation and preprocessing

| Role | Training end | Forecast weeks | Observations per method |
| --- | --- | --- | ---: |
| Selection fold 1 | 2011-07-11 | 2011-07-18–2011-08-08 | 200 |
| Selection fold 2 | 2011-08-08 | 2011-08-15–2011-09-05 | 200 |
| Dedicated calibration fold 3 | 2011-09-05 | 2011-09-12–2011-10-03 | 200 |
| Final test | 2011-10-03 | 2011-10-10–2011-11-28 | 400 |

Training starts 2010-12-06. The first 12 panel weeks are warm-up and excluded from supervised fitting. Final fits contain 1,600 product-week rows, from 50 products and 32 supervised weeks. Features use only completed prior weeks: demand lags, shifted rolling statistics/trend, previous revenue/price/transactions/known customers, past return/cancellation rates, product ID and known calendar fields. There are 20 declared predictors including product ID and no configured holiday indicators. Median imputation with missingness indicators, Ridge scaling and one-hot product encoding are fitted independently within each training boundary. Unknown categories are ignored. No random chronological split, future-filled covariate, random validation or early-stopping test use occurs.

Two predeclared parameter candidates per family are evaluated on the first two expanding folds only. Selection minimizes pooled WAPE, then MAE and identifier, with MAE fallback for zero total actual demand. Chosen parameters: Ridge alpha 1; Random Forest 100 trees, maximum depth 8, minimum leaf size 2; XGBoost 150 trees, depth 2, learning rate 0.05, histogram trees and squared error. Applicable seed is 42 and tree estimators use one worker. This is a small comparison, not an exhaustive search.

Both the best ML family and best overall method including baselines were **Ridge before the test**. After calibration, the final cohort is selected from all 44 pre-test weeks and each model is refit through 2011-10-03. This cohort is frozen for testing, as are parameters, preprocessing and interval radii. Each forecast is one week ahead; completed earlier test actuals may enter later lags and baseline histories. The eight weeks are not an eight-week-ahead forecast. No refitting or product reselection occurs in the test block.

An atomic local ledger reserved the plan immediately before semantic test-target access. The evaluation completed once; subsequent evaluation verifies and returns the same stored results without loading test targets again. This trusted-workspace audit guard is not a security boundary or distributed service. The test is now observed: further tuning requires new future evaluation data and must not be relabeled as another untouched test.

## Measured performance and error patterns

| Method | Selection WAPE, % | Final-test WAPE, % | Final-test MAE, units | Final-test RMSE, units | Final-test bias, units |
| --- | ---: | ---: | ---: | ---: | ---: |
| Four-week moving average | 60.2248 | 51.9682 | 222.3081 | 410.3353 | -4.9519 |
| Last observed | 70.9678 | 64.4161 | 275.5575 | 530.7029 | 9.7575 |
| Four-week recurrence | 75.9377 | 63.0182 | 269.5775 | 522.5691 | -24.4325 |
| Ridge | 53.5219 | 52.7545 | 225.6719 | 438.8753 | -29.6721 |
| Random Forest | 59.0547 | 55.8036 | 238.7150 | 425.0277 | 36.5651 |
| XGBoost | 59.1661 | 53.0436 | 226.9087 | 435.4433 | 3.1690 |

Selection contains 400 observations per method on expanding cohorts; final test contains 400 observations per method on one fixed pre-test cohort. They are separate periods and baskets, not repeated measurements of identical observations. Bias means prediction minus actual. Complete sMAPE and fold/product/week/training-volume breakdowns are stored in the results.

**Ridge did not beat the four-week moving average on the final test.** Its WAPE was 0.7863 percentage points higher. All three ML families had higher final-test WAPE than that baseline. The frozen selection remains Ridge for auditability; no model is promoted or tuned using the test results. There is no demonstrated inventory or financial improvement.

Ridge's overall bias is negative despite overforecasting 239 of 400 observations: its 161 underforecasts have greater total magnitude (51,068.79 units versus 39,199.96 overforecast units). High training-volume products have MAE 365.67 and WAPE 55.07%; medium-volume products have MAE 189.15 and WAPE 52.12%; low-volume products have MAE 115.72 and WAPE 47.10%. The relative volume groups refer only to the selected basket. Large spikes remain difficult: product 23166, chosen for plotting by highest pre-test volume, has a late test spike outside the interval. These are retrospective descriptive patterns, not causes or a new selection rule.

Native importance is stored for all three families. Ridge uses absolute coefficient magnitudes with numeric features standardized and product dummies unscaled; Random Forest uses impurity importance; XGBoost uses gain. Product identity and calendar terms appear among Ridge's large magnitudes. Correlation, coding/scaling and tree splitting affect these values; they are not causal effects or evidence that changing a feature changes sales.

## Uncertainty method and reliability

The separate calibration fold supplies 200 out-of-sample residuals per method. Normalize each absolute residual by `max(previous_four_week_mean, 10)`; take rank 161 of 200 for the predeclared 80% level; apply that radius to the same preforecast scale. Bounds clip at zero. Every prediction carries a nominal coverage and an empirical uncertainty label.

Ridge's final-test coverage was **79.5%**, with mean width **738.34 units**, 11.75% of actuals below the lower bound and 8.75% above the upper bound. The four-week mean covered 85.5%, with mean width 719.59 units. Wide intervals and aggregate coverage can conceal weak product-level calibration. Time dependence, changing cohorts, seasonality and the final refit on data including calibration weeks mean these are practical transferred residual estimates, without a formal conformal or future-coverage guarantee. No radius was adjusted using the test block.

## Business assumptions, risks and operational limits

Inventory, supplier lead times, purchase/holding/order costs, service levels, lost sales and stockout penalties are not observed in this dataset. Phase 3 makes no default business-cost assumptions, generates no orders, and computes no business savings. Phase 4 must introduce explicit configurable assumptions, lead-time forecasting conventions and identical-policy chronological simulations before business claims can be evaluated.

Recorded sales can be censored by stockouts; macroeconomic conditions, product mix and customer behavior have changed since 2011. The model has no evidence of present-day validity, verified causal holiday effects, annual stability or cold-start quality. Human review and operational data are necessary. DemandIQ is decision support because forecasts omit important constraints and do not establish the cost or feasibility of an order.

Models are local joblib pipelines with source/config/runtime/code hashes, features, seed, selected parameters, timestamps, split dates, metrics and serialized hashes. Git hash is null because no commits exist. Runtime pins and local OpenMP setup are in the README. Two independent cold runs had byte-identical predictions, intervals and model files on the tested macOS ARM64 environment. Cross-platform equivalence, live monitoring, drift alerts, API serving, worker durability and database model persistence remain unverified or later work. MLflow is optional and deferred in favor of local JSON/Parquet tracking to keep setup reliable.

## Phase 4 integration status

Phase 4 now uses the same frozen Ridge forecasts in a **retrospective, assumption-driven inventory simulation**. The Phase 3 forecasting metrics, selection protocol, calibration, fixed top-50 cohort and completed evaluation ledger above remain historical evidence from the original experiment. Inventory scenarios do not refit a model, create another forecasting test, change which ML family was selected, or establish that Ridge forecasts outperform the moving-average baseline.

Business defaults are now explicit external scenario configuration in `configs/phase4.json`, with product overrides supported. Illustrative defaults include one complete future lead-time week, weekly review, service parameter 0.95, assumed GBP purchase/selling prices 1/2, holding cost 0.02 per unit/week, lost-unit penalty 3, order fee 5, MOQ zero and case pack one. Default initial stock is derived from two weeks of pre-test average recorded demand; error magnitudes use dedicated pre-test calibration residuals. These are stated assumptions and historical estimates, not observed retailer inventory, supplier or cost data. Full formulas and defaults are in [inventory methodology](INVENTORY_METHODOLOGY.md).

The simulator compares repeat-last, four-week mean, fixed reorder point, Ridge with safety stock, and a matched four-week-mean safety-stock controller under identical starting conditions. End-week decisions use completed observations and the next-origin forecast; longer lead/review horizons explicitly carry that forecast forward flat. Orders arrive at `t+L+1`, no final-week orders are placed, and late pipeline remains valued. The primary metric adjusts cash cost for initial and terminal on-hand/pipeline assets; full terminal recovery at purchase cost is assumed. Fill rate, weekly no-stockout fraction and the desired normal-service parameter are distinct quantities. The normal/square-root safety approximation assumes more stable, independent errors than historical retail data may provide.

Results are signed **simulated estimates**, which can favor or disadvantage ML depending on the policy and assumptions. They are not savings achieved by a company, evidence of future operational performance, or a reason to revise the frozen forecasting selection using the already-observed test block. Forecast accuracy and simulated policy cost remain separate evaluations; the matched controller helps expose that distinction. Measured scenarios, reproducible commands, outputs and limitations are in [Phase 4 results](PHASE4_RESULTS.md). DemandIQ continues to require human review and remains decision support rather than an autonomous purchasing system.
