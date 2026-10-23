# Phase 3 ML protocol

This protocol is fixed before accessing the final test targets. The timeline remains [Phase 2's](FORECASTING_METHODOLOGY.md), with the following explicit roles in [`configs/phase3.json`](../configs/phase3.json):

- Model and hyperparameter selection: expanding folds 1 and 2, validation weeks 2011-07-18 through 2011-09-05. Each has 50 training-selected products and four one-week validation origins.
- Uncertainty calibration only: fold 3, weeks 2011-09-12 through 2011-10-03, after all candidate choices are fixed. Its training ends 2011-09-05.
- Final test: weeks 2011-10-10 through 2011-11-28, evaluated once after the final refit and frozen evaluation plan. This block cannot influence hyperparameters, product ranking or interval calibration.

The third fold is held back from model selection to give residual calibration a separate chronological period. All three folds still provide out-of-sample predictions and baseline comparisons, but calibration results must not be used to revise the selection. Historical Phase 2 baseline scores used all twelve validation weeks; Phase 3 selection scores use only the first eight and are labeled separately.

## Models and preprocessing

Global pooled product models compare Ridge regression, Random Forest and XGBoost, each against all three existing baselines. Random Forest is the permitted tree-model option; it replaces the tentative HistGradientBoosting choice in the earlier plan because the modest panel is inexpensive to fit and the estimator exposes native feature importance. XGBoost supplies a distinct boosted-tree comparison; it earns no preference merely by being more complex.

Two parameter candidates per family are declared in code before training. Ridge alpha is 1 or 100. Random Forest has 100 trees, minimum leaf size 2 and maximum depth 8 or unrestricted. XGBoost has 150 trees, learning rate 0.05 and maximum depth 2 or 4, squared-error objective, histogram trees, full row/column sampling and lambda 1. Each applicable seed is 42; estimators use one worker thread. The grid is deliberately small and is not an exhaustive optimization claim.

Each fold first selects products using only its training history. Features retain the existing causal definitions. The first 12 panel weeks are excluded from supervised fitting because the longest lookback is 12 weeks. Remaining missing numeric values use a training-fitted median imputer with missingness indicators and retained all-empty columns. Ridge also uses a training-fitted standard scaler. Product codes use a training-fitted one-hot encoder; unknown codes are ignored rather than learning a category from evaluation. No target/week field enters predictors. Raw negative demand predictions are clipped to zero consistently for every ML evaluation.

All preprocessing is inside the estimator pipeline and fits only supplied training observations, following [scikit-learn's leakage guidance](https://scikit-learn.org/1.6/common_pitfalls.html#data-leakage). No random train/validation split, out-of-bag selection, early-stopping validation or future imputation is used. Training bagging is restricted to the training rows and does not change temporal validation.

Candidate selection minimizes pooled selection-validation WAPE; ties use MAE and then a deterministic candidate/model identifier. If WAPE is undefined, MAE is the fallback. Each family retains its best candidate. The best ML candidate and best overall method, including baselines, are recorded independently. If a baseline wins, the report recommends that baseline and does not claim ML improvement.

After selection, each chosen family is fit through 2011-09-05 to predict the dedicated calibration fold. Those predictions calibrate uncertainty without in-sample fitted residuals. Each chosen family is then refit using all 44 pre-test weeks through 2011-10-03, excluding warm-up rows. The final cohort is the top 50 ranked using this pre-test history, frozen for all eight test weeks. Baselines receive that same cohort. Models and preprocessing are not refit during testing; features/baselines may use earlier completed test actuals for the documented one-week horizon.

## Practical uncertainty

Nominal coverage is 80%, configured before evaluation. For each method, calibration scores are `abs(actual - forecast) / max(previous_four_week_mean, 10)`. The scale is known before the forecast period. Use the ordered score at rank `min(n, ceil((n+1)*0.8))`; multiply that radius by the same known-demand scale at inference. Lower bounds are clipped at zero; upper bounds add the scaled radius. Each forecast records the nominal level, bounds and an empirical uncertainty label.

This is a practical residual-based estimate, not a guarantee of coverage or a claim that time-series observations are exchangeable. The pooled calibration cohort can differ from the final pre-test cohort; product heterogeneity, seasonality and drift can miscalibrate bounds. In-sample calibration coverage is not presented as evidence of test reliability. Final-test empirical coverage and interval width are measured separately, with no interval adjustment after seeing them.

## Artifacts, final-test access and limits

Training and final evaluation are separate commands. Training publishes source/config/runtime lineage, complete candidate metrics, per-fold predictions, selected parameters, calibration metadata, product cohort, three joblib pipelines, feature-importance data, training timestamps/timings and Git hash when available. With no commits, Git hash is null. Only trusted local model artifacts may be loaded; checksums detect corruption and do not make pickle/joblib safe for untrusted files.

The final evaluation plan lists all six frozen methods, source identity, model/calibration/cohort hashes and the declared test dates. A dataset-scoped local ledger is claimed atomically immediately before the first semantic test-target read. An alternate experiment is refused after reservation; a repeated successful command verifies and reuses completed results without reloading test targets. Interrupted access remains locked for explicit investigation rather than silently making a second test run. The ledger is an audit guard for a trusted local workspace, not an access-control system preventing a human from reading files.

MLflow remains optional and is deferred: local JSON/Parquet metadata and joblib artifacts give reproducible tracking without adding a service or making setup less reliable. Native importance is descriptive: Ridge coefficient magnitudes depend on scaling, tree importance can favor high-cardinality inputs, and no importance is causal evidence. Inventory recommendations, business savings, API services and a dashboard remain later phases.

## Phase 4 integration status

As of 2026-10-19, the frozen forecasts are consumed by the separate [inventory protocol](INVENTORY_METHODOLOGY.md) and [retrospective policy demonstration](EXAMPLE_SCENARIO.md). The forecasting experiment, model choices, calibration, observed final test and ledger remain unchanged. Inventory outcomes use explicit business assumptions and are not new forecasting validation or real company savings; measured simulation results are in [Phase 4 results](PHASE4_RESULTS.md).
