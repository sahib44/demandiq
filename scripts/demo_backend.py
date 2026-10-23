"""Exercise real HTTP -> durable worker -> PostgreSQL -> CSV exports.

Run a migrated API and separate worker first. This registers existing frozen
artifacts and performs one-week inference; it never reevaluates the final test.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_DATASET = "3ec7b0b3e84f29eea43e501736bff880b7fc51aecde23ccadf9a9eae346ca90d"
DEFAULT_RUN = "6ad6f1a67c36a1304ba4aac1b9bf3052a1b5354d905ddf14f3cc99e7d777a6fa"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET)
    parser.add_argument("--run-id", default=DEFAULT_RUN)
    parser.add_argument(
        "--output-dir", type=Path, default=Path("artifacts/backend/demo")
    )
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--idempotency-prefix",
        default="demandiq-demo-v1",
        help="Versioned demo job keys; choose a new prefix for an intentional repeat",
    )
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("timeout must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    timings, jobs = {}, []

    def request(path, payload=None, key=None):
        data = (
            json.dumps(payload, allow_nan=False).encode()
            if payload is not None
            else None
        )
        headers = {"Content-Type": "application/json"} if data else {}
        if key:
            headers["Idempotency-Key"] = key
        req = urllib.request.Request(
            args.base_url.rstrip("/") + path,
            data=data,
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            raise SystemExit(
                f"HTTP demonstration failed with status {exc.code}"
            ) from None

    def read(path):
        return json.loads(request(path))

    def job(path, payload):
        started = time.perf_counter()
        key = (
            f"{args.idempotency_prefix}:{len(jobs) + 1}"
            if args.idempotency_prefix
            else None
        )
        submitted = json.loads(request(path, payload, key=key))
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            status = read(f"/jobs/{submitted['job_id']}")
            if status["status"] == "succeeded":
                jobs.append(
                    {
                        "job_id": status["job_id"],
                        "kind": status["kind"],
                        "attempts": status["attempts"],
                        "result": status["result"],
                        "wall_seconds": time.perf_counter() - started,
                    }
                )
                return status["result"]
            if status["status"] == "failed":
                raise SystemExit(f"Job failed: {status['error_code']}")
            time.sleep(0.2)
        raise SystemExit("Timed out waiting for the separate worker")

    assert read("/ready")["status"] == "ready"
    dataset = job(
        "/datasets/import", {"source": "existing", "dataset_id": args.dataset_id}
    )
    trained = job(
        "/training-runs",
        {"dataset_id": args.dataset_id, "mode": "existing", "run_id": args.run_id},
    )
    one_week = job("/forecasts", {"run_id": args.run_id, "scope": "one_week"})
    retrospective = job("/forecasts", {"run_id": args.run_id, "scope": "retrospective"})
    scenario = job(
        "/inventory/scenarios",
        {"forecast_id": retrospective["forecast_id"], "config": {}},
    )
    one_week_rows = read(f"/forecasts/{one_week['forecast_id']}/values")
    assert one_week_rows["total"] == one_week["rows"]
    assert all(row["actual"] is None for row in one_week_rows["rows"])
    scenario_data = read(f"/inventory/scenarios/{scenario['scenario_id']}")
    export_counts = {}
    for name, url in {
        "forecasts": f"/forecasts/{retrospective['forecast_id']}/export",
        "recommendations": f"/inventory/scenarios/{scenario['scenario_id']}/export",
        "weekly_results": f"/inventory/scenarios/{scenario['scenario_id']}/export?kind=weekly_results",
    }.items():
        content = request(url)
        (args.output_dir / f"{name}.csv").write_bytes(content)
        export_counts[name] = len(list(csv.DictReader(io.StringIO(content.decode()))))
    assert export_counts["forecasts"] == retrospective["rows"]
    assert export_counts["weekly_results"] == scenario["weekly_rows"]
    # Sequential warm local requests, including JSON decoding; no concurrency claim.
    for name, url in {
        "health": "/health",
        "datasets": "/datasets",
        "forecast_values": f"/forecasts/{retrospective['forecast_id']}/values?limit=100",
        "scenario": f"/inventory/scenarios/{scenario['scenario_id']}",
    }.items():
        samples = []
        for _ in range(30):
            started = time.perf_counter()
            read(url)
            samples.append(1000 * (time.perf_counter() - started))
        timings[name] = {
            "samples": len(samples),
            "median_ms": statistics.median(samples),
            "p95_ms": sorted(samples)[28],
            "min_ms": min(samples),
            "max_ms": max(samples),
        }
    report = {
        "scope": "real local HTTP demonstration; existing frozen artifacts; one-week inference and retrospective simulations",
        "dataset": dataset,
        "training": trained,
        "one_week": one_week,
        "one_week_origin": sorted({row["week"] for row in one_week_rows["rows"]}),
        "retrospective": retrospective,
        "scenario": scenario,
        "scenario_summary": scenario_data["summary"],
        "jobs": jobs,
        "export_rows": export_counts,
        "warm_sequential_http_timings": timings,
    }
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, allow_nan=False) + "\n"
    )
    print(
        json.dumps(
            {
                "jobs": len(jobs),
                "exports": export_counts,
                "one_week_rows": one_week["rows"],
                "scenario_id": scenario["scenario_id"],
                "timings": timings,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
