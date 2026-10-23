"""Download and checksum the official UCI Online Retail source."""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from ml.data.acquisition import DownloadError, download_official


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path(os.getenv("DEMANDIQ_DATA_DIR", "data")) / "raw",
    )
    parser.add_argument("--expected-sha256", help="Expected official ZIP SHA-256")
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    started = time.perf_counter()
    try:
        result = download_official(
            args.raw_dir,
            expected_archive_sha256=args.expected_sha256,
            attempts=args.attempts,
            timeout=args.timeout,
        )
    except (DownloadError, OSError) as exc:
        print(
            json.dumps({"event": "download_failed", "error": str(exc)}), file=sys.stderr
        )
        return 1
    print(
        json.dumps(
            {
                "event": "download_complete",
                "workbook_path": str(result.workbook_path),
                "seconds": round(time.perf_counter() - started, 3),
                **result.provenance,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
