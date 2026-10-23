"""Register a verified completed demo through HTTP and the separate real worker.

This calls the existing five-job backend demonstration. It never trains a model
or requests final-test evaluation. Prepare/install the trusted local bundle first.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from scripts.prepare_demo_bundle import verify_bundle


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, default=Path(".cache/demo-bundle"))
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/backend/compose-demo")
    )
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument("--idempotency-prefix")
    args = parser.parse_args()
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("timeout must be finite and positive")
    if not args.base_url.startswith(("http://", "https://")):
        parser.error("base-url must be an HTTP URL")
    manifest = verify_bundle(args.bundle_dir)
    deadline = time.monotonic() + args.timeout
    ready = False
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(
                args.base_url.rstrip("/") + "/ready", timeout=3
            ) as response:
                ready = json.loads(response.read()).get("status") == "ready"
            if ready:
                break
        except (OSError, ValueError, urllib.error.URLError):
            pass
        time.sleep(0.25)
    if not ready:
        raise SystemExit("API did not become ready within the demo timeout")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "scripts.demo_backend",
            "--base-url",
            args.base_url,
            "--dataset-id",
            manifest["dataset_id"],
            "--run-id",
            manifest["run_id"],
            "--output-dir",
            str(args.output_dir),
            "--timeout",
            str(args.timeout),
            "--idempotency-prefix",
            args.idempotency_prefix or f"compose-{manifest['bundle_id'][:20]}-v1",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
