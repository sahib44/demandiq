"""Validate, clean and publish an immutable private transaction dataset."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from ml.pipelines.ingestion import ingest_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("DEMANDIQ_DATA_DIR", "data")) / "processed",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Register metadata/products in migrated PostgreSQL",
    )
    args = parser.parse_args()
    database_url = os.getenv("DATABASE_URL") if args.persist else None
    if args.persist and not database_url:
        parser.error("--persist requires DATABASE_URL")
    started = time.perf_counter()
    try:
        result = ingest_dataset(args.input, args.output_dir, database_url=database_url)
    except Exception as exc:
        # Database errors may embed credentials/SQL parameters; expose only the
        # safe interface errors and exception class for unexpected failures.
        from ml.data.acquisition import DownloadError
        from ml.data.io import InputError
        from ml.data.schema import SchemaError
        from ml.pipelines.ingestion import ArtifactError

        safe_message = (
            str(exc)
            if isinstance(exc, InputError | ArtifactError | DownloadError | SchemaError)
            else type(exc).__name__
        )
        print(
            json.dumps({"event": "ingestion_failed", "error": safe_message}),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {
                "event": "ingestion_complete",
                "dataset_id": result.manifest["dataset_id"],
                "dataset_dir": str(result.dataset_dir),
                "seconds": round(time.perf_counter() - started, 3),
                "original_rows": result.report["original_rows"],
                "cleaned_rows": result.report["cleaned_rows"],
                "database_persisted": args.persist,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
