"""Measure real sequential dashboard reads and a stateless planner preview.

Uses existing API resources discovered from dashboard/context. No job, training,
evaluation, import or database mutation is submitted. Timings include HTTP,
response transfer and JSON decoding; this is not a concurrent load benchmark.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import statistics
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from http.client import HTTPException
from pathlib import Path
from typing import Any

MAX_RESPONSE_BYTES = 8 * 1024 * 1024


class BenchmarkError(ValueError):
    """A bounded, safe diagnostic with no raw HTTP response or credentials."""


def benchmark(
    base_url: str,
    *,
    samples: int = 30,
    warmup: int = 1,
    request_timeout: float = 30,
    total_timeout: float = 300,
) -> dict[str, Any]:
    if not isinstance(base_url, str) or any(
        char.isspace() or ord(char) < 32 or ord(char) == 127 for char in base_url
    ):
        raise BenchmarkError("base-url must be a valid HTTP URL")
    try:
        parsed = urllib.parse.urlsplit(base_url)
        _ = parsed.port
    except ValueError:
        raise BenchmarkError("base-url must be a valid HTTP URL") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise BenchmarkError(
            "base-url must be an HTTP URL without credentials, query or fragment"
        )
    if type(samples) is not int or samples not in {10, 30}:
        raise BenchmarkError("samples must be 10 or 30")
    if type(warmup) is not int or not 1 <= warmup <= 5:
        raise BenchmarkError("warmup must be between one and five")
    if (
        isinstance(request_timeout, bool)
        or not isinstance(request_timeout, int | float)
        or not math.isfinite(request_timeout)
        or not 0 < request_timeout <= 60
        or isinstance(total_timeout, bool)
        or not isinstance(total_timeout, int | float)
        or not math.isfinite(total_timeout)
        or not 0 < total_timeout <= 1800
    ):
        raise BenchmarkError(
            "timeouts must be finite and positive within the supported bounds"
        )
    base = base_url.rstrip("/")
    deadline = time.monotonic() + total_timeout

    def request(path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BenchmarkError("Dashboard benchmark exceeded its total timeout")
        encoded = (
            json.dumps(payload, allow_nan=False).encode()
            if payload is not None
            else None
        )
        headers = {"Content-Type": "application/json"} if encoded is not None else {}
        req = urllib.request.Request(base + path, data=encoded, headers=headers)
        try:
            with urllib.request.urlopen(
                req, timeout=min(request_timeout, remaining)
            ) as response:
                contents = response.read(MAX_RESPONSE_BYTES + 1)
            if len(contents) > MAX_RESPONSE_BYTES:
                raise BenchmarkError(
                    "Dashboard response exceeds the benchmark size bound"
                )
            result = json.loads(contents)
        except urllib.error.HTTPError as exc:
            raise BenchmarkError(
                f"Dashboard request failed with HTTP status {exc.code}"
            ) from None
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            urllib.error.URLError,
            HTTPException,
        ):
            raise BenchmarkError(
                "Dashboard request failed or returned unreadable JSON"
            ) from None
        if not isinstance(result, dict):
            raise BenchmarkError("Dashboard response is not a JSON object")
        return result

    context = request("/dashboard/context")
    try:
        dataset_id = context["dataset"]["dataset_id"]
        run_id = context["run"]["run_id"]
        forecast = context["one_week_forecast"] or context["retrospective_forecast"]
        forecast_id = forecast["forecast_id"]
        scenario_id = context["scenario"]["scenario_id"]
        products = [row["stock_code"] for row in context["products"]]
        stock_code = "84077" if "84077" in products else products[0]
        if any(
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in (dataset_id, run_id, forecast_id, scenario_id)
        ):
            raise ValueError
        if (
            not isinstance(stock_code, str)
            or not stock_code.strip()
            or len(stock_code) > 128
            or forecast.get("scope") not in {"one_week", "retrospective"}
        ):
            raise ValueError
    except (KeyError, TypeError, IndexError, ValueError):
        raise BenchmarkError(
            "Activate a complete dataset, frozen run, forecast and scenario before benchmarking"
        ) from None
    forecast_path = f"/dashboard/forecasts/{forecast_id}?" + urllib.parse.urlencode(
        {"stock_code": stock_code}
    )
    details = request(forecast_path)
    try:
        on_hand = details["planner_defaults"]["on_hand"]
        if type(on_hand) is not int or on_hand < 0:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise BenchmarkError(
            "The forecast projection lacks valid planner defaults"
        ) from None
    preview = {
        "forecast_id": forecast_id,
        "stock_code": stock_code,
        "on_hand": on_hand,
        "on_order": 0,
        "backordered_units": 0,
        "parameters": {},
    }
    endpoints = [
        ("context", "/dashboard/context", None),
        ("run", f"/dashboard/runs/{run_id}", None),
        ("forecast_product", forecast_path, None),
        ("scenario", f"/dashboard/scenarios/{scenario_id}", None),
        ("inventory_preview", "/inventory/preview", preview),
    ]
    timings = {}
    for name, path, payload in endpoints:
        for _ in range(warmup):
            request(path, payload)
        values = []
        for _ in range(samples):
            started = time.perf_counter()
            request(path, payload)
            values.append(1000 * (time.perf_counter() - started))
        timings[name] = {
            "method": "POST" if payload is not None else "GET",
            "samples": samples,
            "warmup_requests_excluded": warmup,
            "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[math.ceil(0.95 * samples) - 1],
            "min_ms": min(values),
            "max_ms": max(values),
            "samples_ms": values,
        }
    return {
        "scope": "real local sequential warm HTTP dashboard reads and stateless assumption-driven preview; no jobs or final evaluation",
        "measured_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "timing_includes": "client HTTP connection, transfer and JSON decoding",
        "p95_definition": "nearest rank, ceil(0.95*n)-th sorted sample",
        "concurrency": 1,
        "other_process_activity": "not controlled; not a load or capacity benchmark",
        "client_environment": {
            "python": platform.python_version(),
            "system": platform.system(),
            "machine": platform.machine(),
        },
        "resources": {
            "dataset_id": dataset_id,
            "run_id": run_id,
            "forecast_id": forecast_id,
            "forecast_scope": forecast["scope"],
            "scenario_id": scenario_id,
            "stock_code": stock_code,
        },
        "preview_assumptions": preview,
        "endpoints": timings,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=int, choices=(10, 30), default=30)
    parser.add_argument("--warmup", type=int, choices=range(1, 6), default=1)
    parser.add_argument("--request-timeout", type=float, default=30)
    parser.add_argument("--total-timeout", type=float, default=300)
    parser.add_argument(
        "--output", type=Path, default=Path("artifacts/phase6/dashboard-benchmark.json")
    )
    args = parser.parse_args()
    try:
        report = benchmark(
            args.base_url,
            samples=args.samples,
            warmup=args.warmup,
            request_timeout=args.request_timeout,
            total_timeout=args.total_timeout,
        )
        encoded = json.dumps(report, indent=2, allow_nan=False) + "\n"
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix=".dashboard-benchmark-", dir=args.output.parent
        )
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(encoded)
            os.replace(temporary, args.output)
        finally:
            temporary.unlink(missing_ok=True)
    except BenchmarkError as exc:
        parser.exit(1, json.dumps({"error": str(exc)}) + "\n")
    except OSError:
        parser.exit(1, '{"error":"The benchmark report could not be written"}\n')
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
