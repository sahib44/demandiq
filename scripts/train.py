"""Train/select/calibrate Phase 3 models without reading reserved test targets."""

import argparse
import json
import os
import sys
from dataclasses import replace
from pathlib import Path

from ml.models.config import Phase3Config
from ml.pipelines.modeling import train_phase3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/phase3.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/phase3"))
    parser.add_argument("--phase2-dir", type=Path, default=Path("data/phase2"))
    parser.add_argument(
        "--ledger-dir", type=Path, default=Path("data/evaluation-ledger")
    )
    parser.add_argument("--top-products", type=int)
    args = parser.parse_args()
    try:
        config = Phase3Config.from_file(args.config)
        count = (
            args.top_products
            if args.top_products is not None
            else os.getenv("TOP_PRODUCTS")
        )
        if count is not None:
            config = replace(
                config, timeline=replace(config.timeline, top_products=int(count))
            )
        result = train_phase3(
            args.dataset_dir,
            args.output_dir,
            config=config,
            phase2_root=args.phase2_dir,
            ledger_root=args.ledger_dir,
        )
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"event": "training_failed", "error": str(exc)}), file=sys.stderr
        )
        return 1
    print(
        json.dumps(
            {
                "event": "training_complete",
                "experiment_id": result.manifest["experiment_id"],
                "run_dir": str(result.run_dir),
                "test_target_access": "none_by_training_command",
                "selection_metrics": result.metrics["overall"],
                "timings": result.timings,
            },
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
