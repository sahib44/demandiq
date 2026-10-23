# DemandIQ user guide

DemandIQ connects historical retail transactions, one-week demand forecasts and configurable inventory simulations. Start the application using [local delivery](DELIVERY.md). The dashboard uses the real FastAPI service and separate job worker; it does not substitute generated metrics when data is missing.

## Activate a workspace

1. Select **Activate data** in the top bar.
2. Choose **Activate historical sample** when the verified historical dataset, frozen models and completed ledger have been installed. This submits five real worker jobs: verify/register the dataset, load the frozen run, generate historical one-week forecasts, load completed test predictions and load/run the default inventory simulation.
3. Wait for the job status to complete. The panel reports state and attempt count. Closing it does not cancel work already submitted to the worker.
4. Select the dataset and frozen run in the workspace selectors. Use **Refresh workspace** after another process registers results.

The advanced activation controls accept an existing dataset ID, an official UCI download, or a relative CSV/XLSX path already present under the backend's raw-data directory. They also load a verified existing training run. A path entry is not a browser file upload. Dataset import alone does not create fitted models or a completed final evaluation. The sample button requires the installed trusted sample artifacts; see [delivery](DELIVERY.md) when those files are absent.

The official sample's first post-refit inference origin is **2011-10-10**. Its one-week batch has unknown actuals. Retrospective views use already-observed rolling one-week predictions from the completed historical test. They are not current-date forecasts, a newly untouched evaluation, or a forecast of true unmet demand.

## Read the scope labels

| Label / information | Meaning |
| --- | --- |
| Historical facts | Recorded accepted sales/credit movements and their aggregates; the source contains neither original inventory nor true lost demand |
| Predictions | Frozen model/baseline forecasts for a stated origin; one-week issuance has no observed actual attached |
| Assumptions | User-entered stock, lead time, costs and inventory controls; illustrative defaults are not retailer facts |
| Simulated outcomes | Inventory fulfillment, lost units, costs and policy differences produced by a chronological simulation under those assumptions |

Never interpret a simulated cost difference as savings achieved by the retailer. Point forecast accuracy and inventory-policy performance answer separate questions. A favorable inventory simulation does not prove a model beat the strongest forecasting baseline. Intervals are empirical uncertainty estimates, with no coverage guarantee.

## Overview

Open **Overview** for the selected frozen run and available scenario. It shows one-week forecasted units, products with simulated stockouts, simulated net inventory cost, simulated fill rate and the matched-policy cost difference. The weekly chart compares recorded demand with simulated fulfillment; it does not turn simulated sales into historical sales.

The product-risk table ranks lost units in the historical ML-policy simulation. Filter by stock code/description and open a product in the inventory planner. The risk export contains simulated product outcomes rather than a probability that the company will stock out next week. The cost comparison identifies the assumptions and terminal inventory credit behind its numbers. If a forecast or scenario is missing, activate/load it rather than treating an empty value as zero.

## Data quality

Open **Data quality** to inspect source/accepted/duplicate/rejected counts, cleaning stages, date coverage, optional missing fields, invalid values, cancellations and other returns. Stage counts reconcile with source dispositions. Reason counts can overlap, because one row can carry several flags; missing optional values are not all rejected rows.

C-prefixed negative movements are cancellations. Other negative movements are returns. Positive C-prefixed sign anomalies are quarantined. Credits are not assumed to match a particular original sale. Exact source duplicates are removed before normalization, and all exclusion/normalization decisions remain in the local audit.

The selected-products table contains the frozen training-selected cohort, with training-only volume/history information. Filter it by stock code or description. It is distinct from the full accepted product catalog. No customer identifiers or transaction-level customer records are displayed.

## Forecast explorer

Open **Forecast explorer**, choose a product, and compare the available model and baseline methods for its dated historical origins. Inspect actual demand where available, point forecasts, empirical intervals and product-level errors. Historical features are dated before their forecasted week; current/future targets must not appear as predictors.

The **Forecast scope** selector distinguishes **Completed historical test** from **First post-refit origin**. The **Forecast method** selector switches the displayed model/baseline while the chart also provides the four-week-mean comparison. The causal feature panel is explicitly the fixed first post-refit snapshot; it is not the feature state for every later rolling test week.

Treat one-week issuance and completed retrospective testing as separate scopes. A null one-week actual means it was unknown at issuance; it does not mean zero sales. The historical model remains frozen, while rolling evaluation can use a previous week once that week's actual has become available. Product selection and preprocessing do not refit using test outcomes.

Use the forecast CSV control for real persisted forecast values. Include its method, week, scope and uncertainty label when sharing it. Do not imply that an empirical interval guarantees a service level or that it covers every supply-chain risk.

## Inventory planner

Open **Inventory planner** and select a product from the frozen cohort. The preview combines the available forecast/error estimate with editable inventory assumptions. Change stock, lead/review time, service factor, economics and order constraints, then inspect the returned reorder point, safety stock, target position, recommended quantity, feasibility reasons and cost assumptions. Preview calculations do not place a purchase order.

The defaults are illustrative:

| Assumption | Default |
| --- | --- |
| Supplier lead time / review interval | 1 / 1 complete weeks |
| Desired service level | 0.95 normal-approximation input |
| Unit purchase / selling price | GBP 1.00 / 2.00 |
| Holding cost | GBP 0.02 per ending on-hand unit per week |
| Lost-unit penalty | GBP 3.00 per lost unit |
| Order fee | GBP 5.00 per positive order |
| Minimum order / case pack | 0 / 1 whole units |
| Capacity | Unbounded unless configured |
| Default simulated initial stock | Two weeks of pretest mean demand, rounded up |

Saved scenarios support the complete validated [inventory configuration](INVENTORY_METHODOLOGY.md), including per-product overrides, initial prepaid arrivals and optional fixed reorder-point/target thresholds. Stock/order counts must be whole units. Lead/review periods and case packs must be positive; costs cannot be negative; desired service level lies strictly between zero and one. Initial reservation and every recommendation must respect capacity, minimum order and case-pack constraints together. An infeasible order can become zero with a reason instead of violating capacity.

Inventory position includes on-hand plus all outstanding orders minus backorders. The planner supports the backorder term; the historical lost-sales simulator requires initial backorders to be zero. An end-of-week order with lead time one arrives before demand two weeks later, after one complete future demand week has elapsed. The protection target covers lead time plus the review period.

The fitted forecast horizon is one week. Longer lead/review demand therefore uses an explicitly labeled flat carry-forward approximation of the one available next-origin forecast. It does not read later-issued forecasts to improve an earlier decision. Economic inputs score costs/revenue; the controller does not automatically optimize order quantities using holding or stockout prices.

To compare a changed policy over history, submit a scenario and wait for its worker job. A planner preview is a single decision; a completed scenario is a dated simulation with identical initial assumptions across its policies. Neither action authorizes purchasing.

The preview updates automatically after valid inputs change. **Export recommendation** downloads that calculated single-decision preview. **Run inventory simulation** applies the entered business defaults across the full frozen cohort and gives the selected product the entered opening-stock override; it then opens the scenario comparison. Positive on-order units need a Monday arrival week for simulation. Backorders can be previewed, but must be zero for the lost-sales simulation. More extensive per-product overrides are available through the documented scenario JSON/API configuration rather than separate simultaneous stock fields in this form.

## Scenario comparison

Open **Scenario comparison** to select completed scenarios and inspect their policy tables/charts. Five policies use common historical demand, starting inventory/pipeline and economic assumptions: previous demand, four-week mean, fixed reorder point, selected ML with safety stock, and matched four-week mean with safety stock. The matched controller helps isolate forecast-input differences; method-specific pretest error buffers still differ.

Use **Scenario** to choose a saved run, **Baseline policy** for its signed ML comparison, and **Compare configuration** for a second saved assumption set. The configuration table and per-product details expose which inputs changed. **Summary CSV**, **Risk CSV**, **Recommendations CSV** and **Weekly results CSV** export the corresponding verified data.

Compare lost units, stockout frequency, fill rate, average inventory, holding/stockout/order/purchase costs and total cost. Fill rate is fulfilled units divided by recorded historical demand; zero total demand gives fill rate one. Realized service is the fraction of simulated product-weeks without lost units. The configured 0.95 factor is a planning input, not either observed metric.

The primary **net inventory cost** adds initial inventory assets and credits terminal on-hand plus pipeline at purchase cost. That full-recovery assumption differs from **gross cash cost**, which sums purchases, holding, stockout penalties and order fees. Estimated lost margin is shown separately and is not added again to a stockout penalty total. Negative savings means the selected policy costs more under that scenario; preserve the sign.

Export recommendations, weekly simulation records, scenario summaries or risk reports through their CSV controls. Exports contain actual persisted/verified results, and formula-leading text is escaped for spreadsheet use. The same product's recommendation can differ across weeks because stock and pending arrivals evolve chronologically.

## Model performance

Open **Model performance** to inspect selection-validation, disjoint calibration and completed final-test evidence separately. Compare all three ML families with all three baselines, product-level errors and native feature importance. The model selected before testing remains selected even if a test baseline performs better.

Switch **Selection validation**, **Residual calibration** and **Final test** tabs using their buttons or arrow/Home/End keys. **Comparison metric** switches WAPE/MAE/RMSE in the model comparison; **Filter performance products** narrows the product table. Completed-test uncertainty remains explicitly labeled with its own scope even when another point-metric tab is active.

WAPE, MAE, RMSE, sMAPE and signed bias describe different error properties; undefined denominators are not silently replaced with flattering zeroes. Ordinary MAPE is not the primary metric because weeks can have zero demand. Importance methods differ by model and do not establish causal effects. Calibration coverage is empirical and must retain its scope and nominal interval label.

Metadata identifies the frozen cohort, split dates, model family/hyperparameters, feature names, artifact hashes and refit boundary. Retrospective metadata exposes already-completed point and uncertainty metrics after ledger/inventory verification. Loading this view does not rerun test evaluation or create a new tuning opportunity. Read the [model card](MODEL_CARD.md) before using the forecasts outside this demonstration.

## Navigation, accessibility and errors

Use the six navigation links or the mobile navigation button. Pages have labeled controls, visible keyboard focus, semantic tables and loading/error/empty states. The activation dialog supports keyboard focus and Escape. Chart-adjacent data tables provide a textual alternative where offered; keyboard and table use should not depend on color alone.

Use the displayed retry control after restoring a failed connection. A safe error code/request ID helps inspect the API/worker without exposing raw payloads or credentials. Refreshing a page is not a cancellation mechanism. Permanent job failures require fixing the input/environment and deliberately submitting a new job; idempotent replays retain the earlier result.

Stop and back up the application using [delivery instructions](DELIVERY.md). Keep completed ledgers, model inventories and source manifests intact. DemandIQ supports a human inventory decision; it does not replace review of supplier behavior, live stock, purchasing authority or the limitations of a single retailer's historical recorded sales.
