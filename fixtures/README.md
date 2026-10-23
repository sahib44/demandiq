# Fictional demonstration data

`synthetic_retail.csv` is a hand-designed, deterministic 175-row fixture for
three fictional products (`SYNTH-1` through `SYNTH-3`). It contains no UCI rows,
real customers or customer identifiers. Its dates follow the existing example
chronology so the normal training configuration can be reused with three products.

The fixture includes missing-sale weeks, cancellations, one duplicate and a
zero-price row to demonstrate cleaning and continuous weekly aggregation. It is
deliberately small and patterned. Forecast errors, intervals and simulated costs
computed from it do **not** establish real-world performance or company savings.

From the project root after installing the Python dependencies:

```bash
python -m scripts.demo_synthetic
```

All generated datasets, fitted models, results and the fixture's separate final
evaluation ledger remain ignored below `.cache/synthetic-demo/`. This command
never evaluates the official UCI dataset or modifies its original ledger.
See the root README for displaying this bundle in the local dashboard.
