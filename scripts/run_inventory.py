"""Run a retrospective inventory scenario using verified frozen Phase 3 artifacts."""

import argparse
import json
import sys
from pathlib import Path

from ml.inventory.config import ScenarioConfig
from ml.pipelines.inventory import run_inventory_scenario


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase3-run", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=Path("configs/phase4.json"))
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/phase4"))
    parser.add_argument(
        "--ledger-dir", type=Path, default=Path("data/evaluation-ledger")
    )
    args = parser.parse_args()
    try:
        result = run_inventory_scenario(
            args.phase3_run,
            config=ScenarioConfig.from_file(args.config),
            output_root=args.output_dir,
            ledger_root=args.ledger_dir,
        )
    except (ValueError, OSError) as exc:
        print(
            json.dumps({"event": "inventory_failed", "error": str(exc)}),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "event": "inventory_complete",
                "run_id": result.manifest["run_id"],
                "run_dir": str(result.run_dir),
                "scope": result.summary["scope"],
                "policies": result.summary["policies"],
                "comparisons": result.summary["comparisons"],
                "timings": result.timings,
            },
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
