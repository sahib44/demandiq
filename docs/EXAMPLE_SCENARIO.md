# Reproducible historical business scenario

A single-location retailer compares replenishment policies using recorded purchases as hypothetical demand, frozen forecasts, and explicit illustrative stock/cost assumptions. This is a retrospective demonstration for 2011-10-10–2011-11-28, not a purchasing recommendation for today or a claim about the original retailer's operations.

## Run the demonstration

Complete the README's dataset/Phase 3 workflow first, retaining its completed ledger. From the repository root:

```bash
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa --config configs/phase4_lead2.json
.venv/bin/python -m scripts.run_inventory --phase3-run artifacts/phase3/6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa --config configs/phase4_high_holding.json
```

Repeated successful commands verify cached outputs. The default produces `artifacts/phase4/a6b3fa34d8663859368185afd5f940f9d165bde7024630e444a0cc1f99ebe967/` with a Markdown report, reconciled policy/product summaries, weekly stock flows, dated orders, explained recommendations, three figures and three CSV exports. [Phase 4 results](PHASE4_RESULTS.md) records real comparisons and checksums. The third scenario is an explicitly exploratory sensitivity introduced after the default run, not an untouched policy validation.

## One actual generated order

The first positive ML order by chronological week and product code in the default output is product **15036**, reviewed after the historical week beginning **2011-10-10**. These numbers are read from the generated recommendation, rather than invented example performance:

| Input/calculation | Recorded value |
| --- | ---: |
| Available next-week forecast, for 2011-10-17 | 585.585639 units |
| Empirical calibrated error magnitude | 494.336140 units |
| Inventory position after current demand | 801 units |
| One-week lead-time demand | 585.585639 units |
| Lead-time safety stock | 813.110593 units |
| Reorder point | 1398.696232 units |
| Two-week protection target (L+R) | 2321.083306 units |
| Target minus inventory position | 1520.083306 units |
| Feasible order after whole-unit rounding | 1521 units |

Inventory position is below the reorder point. The default MOQ is zero, pack is one and capacity is unbounded, so the positive request rounds upward to 1521. With the documented full-week wait, this end-week order arrives before demand in week **2011-10-24**. The one available forecast is explicitly carried forward flat for the second protection week; it is not a separately validated two-week forecast. The large safety allowance reflects uncertain historical demand, not guaranteed service.

## Configure a product

Save a separate local JSON file, then pass it with `--config`. This example specifies illustrative assumptions, not measured operating facts or a claim that this configuration performs better:

```json
{
  "name": "illustrative_pack_and_capacity",
  "currency": "GBP",
  "initial_coverage_weeks": 2.0,
  "defaults": {"lead_time_weeks": 1, "service_level": 0.95},
  "products": {
    "15036": {
      "initial_on_hand": 100,
      "initial_orders": [{"week": "2011-10-17", "quantity": 24}],
      "parameters": {
        "lead_time_weeks": 2,
        "min_order_quantity": 24,
        "case_pack_size": 12,
        "max_inventory_capacity": 500
      }
    }
  }
}
```

Initial arrivals are assumed prepaid and identical across policies. Capacity reserves on-hand plus all outstanding units. If a case pack/MOQ cannot fit, the planner returns zero with an explanation rather than violating a constraint. Unknown product overrides or infeasible initial capacity fail explicitly.

Service/lead/review and physical constraints change orders. Holding, stockout and order costs change reported economics; this rule-based controller does not optimize quantities against those costs. Compare fill rate, weekly no-stockout service, stock exposure, gross cash outflow and terminal-adjusted cost together. Full recovery of closing on-hand/pipeline value at purchase cost is a consequential assumption. The higher-holding-cost run shows why the default's simulated advantage cannot be assumed under other economics. The Phase 3 finding that Ridge failed to beat the best forecasting baseline remains unchanged. No orders are sent to a supplier.
