"""Build a local, entirely fictional demonstration without the official dataset.

All fitted files, generated results and the separate synthetic evaluation ledger
stay below .cache. Synthetic outputs are never evidence of retail performance.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import replace
from pathlib import Path

from ml.models.config import Phase3Config
from ml.pipelines.ingestion import ingest_dataset
from ml.pipelines.modeling import evaluate_phase3, train_phase3
from scripts.prepare_demo_bundle import prepare_bundle


def prepare_synthetic_demo(output_dir: Path) -> dict:
    """Fit the normal pipeline on the checked-in fictional, three-product fixture."""
    cache = (Path.cwd() / ".cache").resolve()
    output = output_dir.resolve()
    if output == cache or not output.is_relative_to(cache):
        raise ValueError("Synthetic demo output must be a subdirectory of .cache")
    source = Path("fixtures/synthetic_retail.csv")
    with source.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows or any(
        not row.get("StockCode", "").startswith("SYNTH-")
        or row.get("Country") != "Synthetic"
        or row.get("CustomerID")
        for row in rows
    ):
        raise ValueError("Demo input must contain only fictional, customer-free rows")
    dataset = ingest_dataset(source, output / "processed")
    default = Phase3Config.from_file(Path("configs/phase3.json"))
    config = replace(default, timeline=replace(default.timeline, top_products=3))
    ledger = output / "ledger"
    trained = train_phase3(
        dataset.dataset_dir,
        output / "training",
        config=config,
        phase2_root=output / "weekly",
        ledger_root=ledger,
    )
    # This is a different dataset identity and ledger from the consumed UCI test.
    evaluate_phase3(trained.run_dir, dataset.dataset_dir, ledger_root=ledger)
    bundle = prepare_bundle(
        dataset.dataset_dir, trained.run_dir, ledger, output / "bundle"
    )
    result = {
        "scope": "entirely_synthetic_demo_not_retail_performance",
        "dataset_id": bundle["dataset_id"],
        "run_id": bundle["run_id"],
        "bundle_dir": str(output / "bundle"),
        "notice": "Fictional data; no real customers, business savings or model claims.",
    }
    (output / "demo.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".cache/synthetic-demo")
    )
    args = parser.parse_args()
    print(json.dumps(prepare_synthetic_demo(args.output_dir), indent=2))


if __name__ == "__main__":
    main()
