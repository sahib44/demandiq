# Actual dashboard screenshots

Captured from the real Docker-served React application and verified backend by the Phase 6 Playwright workflow on 2026-10-21. These are historical dataset/model/simulation results, not mockups or current company performance. No raw customer records or pseudonyms are displayed.

| View | File |
| --- | --- |
| Executive overview, full page | [overview-desktop.png](overview-desktop.png) |
| Executive overview, viewport | [overview-viewport.png](overview-viewport.png) |
| Data quality | [data-quality-desktop.png](data-quality-desktop.png) |
| Forecast explorer | [forecasts-desktop.png](forecasts-desktop.png) |
| Inventory planner | [inventory-desktop.png](inventory-desktop.png) |
| Scenario comparison | [scenarios-desktop.png](scenarios-desktop.png) |
| Model performance | [performance-desktop.png](performance-desktop.png) |
| Mobile inventory planner | [inventory-mobile.png](inventory-mobile.png) |

Desktop captures use a 1440 × 1000 viewport; mobile uses 390 × 844. Full-page images extend vertically to include all real tables and disclosures. The screenshots follow the actual browser workflow, which creates a sensitivity scenario with lead time 2, pack size 6 and MOQ 12 for the whole frozen cohort, and opening stock 120 for product 84077. Overview and comparison therefore reflect that latest scenario rather than the original Phase 4 default. Fresh planner pages show their labeled illustrative default stock/input state, independently of the stored scenario. Forecast explorer starts at the first frozen product, 23166; performance displays the preserved final-test results.

Recreate with the complete historical-demo stack running:

```bash
cd frontend
PLAYWRIGHT_BASE_URL=http://127.0.0.1:8080 npm run test:e2e
```

For the isolated verification project's ports, use `http://127.0.0.1:58080` instead. The workflow also records measured navigation/workflow durations and twelve automated accessibility scans under ignored `artifacts/phase6/`. No injected outage or synthetic component fixture supplies these screenshots. See [the complete delivery report](../PHASE6_RESULTS.md).

![DemandIQ executive overview](overview-viewport.png)
