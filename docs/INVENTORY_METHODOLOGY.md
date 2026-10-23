# Phase 4 inventory protocol

This protocol is defined before the first inventory simulation. It uses the frozen Phase 3 outputs for a **retrospective, assumption-driven policy comparison**, not another forecasting test or evidence of real company savings. Phase 3 forecasts, calibration, model selection, evaluation ledger and source transactions remain unchanged. No API, database migration or frontend is implemented in this phase.

## Boundaries and architecture

`ml/inventory/planning.py` owns validated business parameters, inventory position, lead-time demand, safety stock, reorder/target levels and feasible order constraints. `ml/inventory/simulation.py` owns weekly stock/order/cost conservation and policy comparisons. `ml/pipelines/inventory.py` verifies frozen inputs, derives pre-test assumptions/error estimates, runs common scenarios and publishes reproducible artifacts. `scripts/run_inventory.py` is a thin CLI. Plot/report helpers present real generated results.

Inputs are explicitly separated: historical gross recorded purchases; preissued forecasts; illustrative business assumptions; simulated stock, fulfillment, costs and service outcomes. Recorded purchases are treated as demand for simulation even though original inventory and lost demand are unknown. Credits are not physical stock receipts.

## Illustrative defaults and units

| Input | Default | Meaning |
| --- | ---: | --- |
| Currency | GBP | Illustrative monetary unit, not observed retailer costs |
| Supplier lead time `L` | 1 week | A complete future demand week passes before receipt |
| Review period `R` | 1 week | Review after the first simulated demand week, then every R weeks |
| Service-level parameter | 0.95 | Normal-approximation factor, not guaranteed realized service |
| Unit purchase cost | 1.00 | Assumed constant per product |
| Unit selling price | 2.00 | Assumed constant; does not replace historical revenue facts |
| Holding cost | 0.02/unit/week | Charged on ending on-hand stock |
| Stockout penalty | 3.00/lost unit | Assumed penalty, independent of reported lost margin |
| Order cost | 5.00/order | Charged on a positive placed order |
| Minimum order | 0 units | Applies only to a positive order |
| Case pack | 1 unit | Positive orders must be multiples |
| Capacity | None | Optional integer reservation limit on on-hand plus all outstanding orders |
| Initial on-hand | ceil(2 × pre-test weekly mean) | Derived only from the frozen 44-week pre-test panel; identical across policies |
| Initial outstanding orders | None | Optional dated arrivals, identical across policies |
| Backorders | 0 | Planner supports position subtraction; simulation is lost-sales only and rejects initial backorders |

Defaults and individual product overrides are configurable and stored with each run. They were not fitted to inventory outcomes. Supplier lead/review periods are positive integer weeks; service levels are in `(0,1)` and negative normal factors are floored to zero safety stock. Prices/costs/forecast errors must be finite and nonnegative; MOQ, stock and capacities are nonnegative integers, packs positive integers. Unit quantities are bounded to the exact integer range of float64 where forecast-to-order arithmetic is used. Infeasible initial capacity or conflicting fixed-policy levels fail with useful errors.

## Weekly timing and information

For a week labeled Monday `t`: receive scheduled inventory before demand, observe that week's historical demand, fulfill available units and lose the remainder, calculate ending inventory, then review/order if scheduled. An order placed **after demand in week index t** with lead time L is received **before demand in week t+L+1**. Thus L=1 waits through the next complete demand week before receipt in the following week. This explicit convention makes lead-time demand L weeks and protection demand L+R weeks; it avoids treating an end-of-week order as an immediate next-boundary receipt.

The decision after week t uses only the forecast for t+1, past observations through t, already-calibrated errors and current simulated state. It must never read forecasts for t+2 or later: those rolling-origin forecasts were issued later and can contain intervening actuals. Because Phase 3 supplies only one-week forecasts, all later weeks in a lead/review horizon use an explicit **flat carry-forward approximation** of that one available forecast. This is not a validated multiweek model and does not multiply an unseen future forecast silently.

No new orders are placed after the final simulated demand week because no next-origin forecast is supplied; this rule applies to every policy. Earlier orders due after the horizon remain outstanding and valued, not received early or dropped. Simulations cover the same eight already-observed Phase 3 weeks, 2011-10-10–2011-11-28. This is a finite retrospective experiment; policy/cost sensitivities do not create an untouched future evaluation.

## Planner formulas and constraints

For the available one-week forecast d, error estimate sigma, lead L and review R:

- Inventory position = on-hand + outstanding orders − backordered units.
- Lead-time demand = L × d, explicitly using flat carry-forward.
- `z = max(0, NormalDist().inv_cdf(service_level))`.
- Lead-time safety stock = z × sigma × sqrt(L).
- Reorder point = lead-time demand + lead-time safety stock.
- Protection safety stock = z × sigma × sqrt(L+R).
- Target position = (L+R) × d + protection safety stock.
- At a scheduled review, if inventory position is at/below the reorder point, request max(0, target position − inventory position); otherwise request zero.

Round a positive request up to meet MOQ and a pack multiple. A configured capacity reserves space for on-hand plus every outstanding order, conservatively ignoring future consumption. If the rounded order exceeds that reservation room, reduce to the largest feasible pack multiple, or return zero if MOQ cannot fit. Never violate MOQ to fill capacity. Every recommendation records raw demand/position/thresholds, feasible quantity, horizon convention and reasons including capacity/MOQ limitations.

The fixed reorder-point policy holds its levels constant from pre-test mean demand and the moving-average calibration error. Explicit fixed reorder/target overrides must be supplied together and target must be at least the reorder point. Other policies use the same business constraints.

## Error estimates and policies

For each applicable method, estimate a pooled normalized RMSE from the 200 dedicated pre-test calibration predictions: `sqrt(mean(((actual-prediction)/max(prior_four_week_mean,10))**2))`. Multiply by the same known prior-demand scale at a decision. This includes bias and is an empirical error magnitude, not an unbiased standard-deviation estimator. The normal/square-root approximation assumes stable independent weekly errors; actual retail errors need not satisfy it. A desired service parameter is not a guarantee of fill rate or cycle service.

Compare five policies with identical initial state and economics:

1. `previous_demand`: order the last completed week's demand × R at reviews, constrained by MOQ/pack/capacity; no safety stock or inventory-position correction.
2. `moving_average_4`: order the preceding four-week mean × R, with the same constraints; no safety stock or position correction.
3. `fixed_reorder_point`: constant pre-test reorder/target levels with calibrated safety and inventory-position correction.
4. `ml_safety_stock`: the Phase 3 validation-selected ML family (Ridge in the frozen run), dynamic reorder/target and calibrated safety.
5. `moving_average_safety_stock`: the same dynamic controller as ML, driven by the four-week mean and its own pre-test error estimate. This matched control helps avoid attributing controller improvements to ML forecasts.

No policy is selected or business input optimized using these outcomes. Direct-repeat policies intentionally differ from order-up-to controllers; comparisons describe complete policies, while the matched control more directly compares forecast inputs. The fixed policy and initial stock use pre-test facts only. Product-specific errors are not estimated from four calibration weeks, and test residuals do not enter safety stock.

## Costs, service and terminal accounting

Purchases are paid at placement; initial outstanding orders are assumed already paid. Weekly holding cost uses ending on-hand. Stockout penalty = lost units × configured penalty. Lost revenue and estimated lost margin are reported separately; estimated lost margin = lost units × max(selling−purchase price,0), and is **not** added again to stockout penalty. Revenue = fulfilled units × assumed selling price. No actual retailer margin is inferred. The illustrative penalty is three times purchase cost so the default cost objective does not make fulfilled-versus-lost units cost-equivalent; this ratio is an assumption, not measured or optimized.

`gross_cash_cost = purchase_cost + holding_cost + stockout_cost + order_cost`. For finite-horizon comparison, `net_inventory_cost = gross_cash_cost + initial_inventory_asset_value − terminal_inventory_asset_value`, valuing initial/final on-hand and outstanding orders at the same purchase cost. This prevents unpaid-looking pipeline or excess closing stock from disappearing. It assumes full terminal recoverability at purchase cost, with no discount, obsolescence or salvage loss. Both cash and terminal-adjusted totals are reported. Terminal adjustment is applied once at summary level, not hidden inside weekly costs. Net inventory cost is the predeclared primary comparison metric; any savings are signed **simulated estimates** relative to each baseline and may be negative.

Fill rate = total fulfilled / total demand (1 when demand is zero). Weekly service level = fraction of product-weeks with no lost units (including zero-demand weeks); this is not an order-cycle service statistic. Stockout frequency is the complementary fraction. Track lost units, events, units fulfilled, average/ending inventory, purchase/holding/order/stockout cost, lost revenue/margin, outstanding units and terminal asset values. Check both stock and order conservation, valid due dates, nonnegative stocks and reconciled totals. No realized company savings are claimed.

## Verification gate

Before completing Phase 4: all existing tests pass; hand-calculated safety/position/lead/review/rounding/capacity/MOQ examples pass; simulation arrival and quantity/cost conservation pass; future-demand/forecast perturbations cannot change earlier decisions; every policy shares initial inputs; zero demand is defined; frozen source and ledger hashes are unchanged; cached/cold runs reproduce deterministic artifacts; default and at least one clearly labeled sensitivity run produce measured results; all figures are inspected; documentation records exact commands, complete tests, outputs and limitations. Phase 5 remains unstarted.

## Exploratory cost sensitivity

After the default and predeclared lead-two runs, an additional exploratory scenario raises holding cost from 0.02 to 0.10 per unit/week, holding the other defaults fixed. This probes the observed inventory exposure; it is not a new untouched evaluation, a tuned recommendation or a reason to change the frozen forecasting model/default policy. The rule-based controller uses forecasts, errors, service, lead/review and physical constraints; holding/stockout/order costs affect reported economics but do not optimize its quantity formula. DemandIQ does not claim that this heuristic globally minimizes costs.
