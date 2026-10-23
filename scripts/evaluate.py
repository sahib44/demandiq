"""Evaluate a frozen Phase 3 plan once, then verify/reuse its final test results."""

import argparse
import json
import sys
from pathlib import Path

from ml.pipelines.modeling import evaluate_phase3


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--dataset-dir", required=True, type=Path)
    parser.add_argument(
        "--ledger-dir", type=Path, default=Path("data/evaluation-ledger")
    )
    args = parser.parse_args()
    try:
        result = evaluate_phase3(
            args.run_dir, args.dataset_dir, ledger_root=args.ledger_dir
        )
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"event": "evaluation_failed", "error": str(exc)}),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "event": "evaluation_complete",
                "results_dir": str(result.run_dir),
                "metrics": result.metrics["overall"],
                "timings": result.timings,
            },
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
