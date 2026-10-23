"""Run Phase 2 baseline validation while leaving reserved test targets unread."""

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from ml.evaluation.splits import Phase2Config
from ml.pipelines.forecasting_foundation import run_phase2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset-dir",
        type=Path,
        required=True,
        help="Verified Phase 1 processed dataset directory",
    )
    parser.add_argument("--config", type=Path, default=Path("configs/phase2.json"))
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("DEMANDIQ_DATA_DIR", "data")) / "phase2",
    )
    parser.add_argument(
        "--top-products",
        type=int,
        help="Override configured training-only product limit",
    )
    args = parser.parse_args()
    try:
        config = Phase2Config.from_file(args.config)
        product_limit = (
            args.top_products
            if args.top_products is not None
            else os.getenv("TOP_PRODUCTS")
        )
        if product_limit is not None:
            config = replace(config, top_products=int(product_limit))
        result = run_phase2(args.dataset_dir, args.output_dir, config)
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"event": "phase2_failed", "error": str(exc)}), file=sys.stderr
        )
        return 1
    print(
        json.dumps(
            {
                "event": "phase2_complete",
                "run_id": result.manifest["run_id"],
                "run_dir": str(result.run_dir),
                "test_status": result.manifest["test_status"],
                "selected_products_per_fold": result.manifest[
                    "selected_products_per_fold"
                ],
                "validation_metrics": result.metrics["overall"],
                "timings": result.timings,
            },
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
