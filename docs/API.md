# DemandIQ local backend

FastAPI validates requests; a separate PostgreSQL-backed worker performs imports, training, inference and retrospective inventory simulations. Those operations return immediately with HTTP 202 and a `Location: /jobs/<uuid>` header. Dashboard projections and inventory previews return synchronously without submitting jobs or changing PostgreSQL. `/health` remains available during dependency failure; `/ready` checks the migration, database and writable artifact/data roots. The [backend architecture](BACKEND_ARCHITECTURE.md) defines transactions, leases and failure recovery.

## Start and migrate

From the repository root, with the documented Python environment and local `.env` loaded:

```bash
docker compose up -d postgres
python -m alembic -c backend/alembic.ini upgrade head
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

In a second terminal, activate the same virtual environment, load the same environment variables and start:

```bash
# Required on the inspected Mac when using the cached OpenMP runtime:
export DYLD_LIBRARY_PATH="$PWD/.cache/libomp"
python -m scripts.run_worker
# Process at most one eligible job, then exit:
python -m scripts.run_worker --once
```

The native CLI does not migrate automatically. The local API has no authentication and should bind to loopback. Full application Compose starts the database, explicit migration, API, worker and React/Nginx frontend; its verified sample workflow is documented in [DELIVERY.md](DELIVERY.md).

Open [Swagger](http://127.0.0.1:8000/docs), [ReDoc](http://127.0.0.1:8000/redoc) or [OpenAPI JSON](http://127.0.0.1:8000/openapi.json). Resource identifiers are lowercase SHA-256 strings; job identifiers are UUIDs. Products require a `dataset_id` query parameter, because stock codes are dataset-scoped. Lists accept `limit` (1–200) and `offset`; row endpoints allow up to 1,000 rows per page. Exports return all matching records.

Native development defaults `API_ROOT_PATH` to empty. Compose sets `/api`: Nginx forwards `/api/...` with the prefix removed, and ASGI root-path middleware retains the external prefix in Swagger/ReDoc/OpenAPI. Open the container documentation through [the frontend proxy](http://127.0.0.1:8080/api/docs). Root paths accept normalized slash-separated letters, numbers, underscores and hyphens; query strings, traversal and trailing slashes are rejected. This setting describes a trusted reverse proxy; it does not add an authentication boundary or change the underlying route definitions.

## Endpoints

| Operation | Routes |
| --- | --- |
| System | `GET /health`, `/ready`, `/config` |
| Datasets | `POST /datasets/import`; `GET /datasets`, `/datasets/{id}`, `/datasets/{id}/quality` |
| Products | `GET /products`, `/products/{stock_code}`, `/products/{stock_code}/history` |
| Training | `POST /training-runs`; `GET /training-runs`, `/training-runs/{id}`, `/training-runs/{id}/metrics` |
| Models | `GET /models`, `/models/{id}` |
| Forecasts | `POST /forecasts`; `GET /forecasts`, `/forecasts/{id}`, `/forecasts/{id}/values`, `/forecasts/{id}/export` |
| Inventory | `POST /inventory/scenarios`; `GET /inventory/scenarios`, `/inventory/scenarios/{id}`, `/inventory/scenarios/{id}/results`, `/inventory/scenarios/{id}/export` |
| Jobs | `GET /jobs`, `/jobs/{id}` |
| Dashboard | `GET /dashboard/context`, `/dashboard/runs/{run_id}`, `/dashboard/forecasts/{forecast_id}`, `/dashboard/scenarios/{scenario_id}` |
| Decision preview | `POST /inventory/preview`, `/inventory/preview/export` |
| Product-risk CSV | `GET /dashboard/scenarios/{scenario_id}/risk/export` |

`Idempotency-Key` is optional on asynchronous job POST operations. Omission uses the canonical validated payload digest. Replaying a key returns its original job, including failures; using the same key for a different payload returns409. Automatic retries are bounded. To retry a failed permanent job after fixing its input, use a new key. File imports bind the source checksum at submission and verify it again in the worker. Synchronous stateless previews do not create an idempotency/job record.

Dataset import bodies:

```json
{"source":"existing","dataset_id":"<64-character dataset ID>"}
{"source":"official"}
{"source":"file","input_file":"synthetic.csv","expected_sha256":"<optional file digest>"}
```

`input_file` is relative to `DEMANDIQ_DATA_DIR/raw`, accepts CSV/XLSX, and rejects traversal and symlink escape. Official acquisition is pinned to the archive checksum documented in README; arbitrary remote URLs and serialized-model paths are not accepted. Import registers aggregate metadata/catalog/quality; no customer records are exposed.

Training bodies:

```json
{"dataset_id":"<dataset ID>","mode":"existing","run_id":"<frozen run ID>"}
{"dataset_id":"<dataset ID>","mode":"train","config":{}}
```

The second form uses the existing Phase 3 protocol and validation. Training jobs can create a new run for a fresh dataset, or verify/reuse a matching cached run. A dataset with an observed final test cannot be retuned. No endpoint performs final-test evaluation. Selection and calibration metrics remain separate; final metrics are accessible through a verified retrospective forecast's metadata.

Forecast bodies:

```json
{"run_id":"<run ID>","scope":"one_week"}
{"run_id":"<run ID>","scope":"retrospective"}
```

`one_week` generates causal features and performs inference with all three saved ML families and three baselines at the first origin after frozen refitting. For the official run, this is **2011-10-10**, with `actual:null`; it is a historical inference demonstration, not a current-date forecast. Empirical uncertainty retains its no-guarantee label. `retrospective` registers previously completed test predictions after verifying the ledger and artifacts. It never recalculates or consumes the final evaluation. Registered weekly histories contain complete pre-test facts; retrospective actuals are separate forecast records, because missing test revenue/credit measures must not be invented.

Inventory bodies:

```json
{"forecast_id":"<retrospective forecast ID>","config":{}}
```

`config` accepts the [Phase 4 parameters](INVENTORY_METHODOLOGY.md). This runs or verifies the existing assumption-driven simulation with identical policy inputs. Scenario summaries label costs/savings as simulated estimates. A one-week forecast cannot supply the future actuals needed for retrospective simulation. Export `kind` is `recommendations` (default), `summary` or `weekly_results`. Forecast exports come from persisted values; scenario exports verify source artifact checksums before returning CSV. Formula-leading untrusted text is escaped for spreadsheet use.

## Verified dashboard projections

| Endpoint | Selection and returned information |
| --- | --- |
| `GET /dashboard/context` | Optional `dataset_id`/`run_id`; otherwise latest registered dataset/run with deterministic identifier tie-breaks. Returns the frozen cohort, latest one-week/retrospective references, latest scenario for that retrospective batch, overview totals and explicit scope labels. A run must belong to a supplied dataset. An empty workspace returns nullable resources rather than fabricated defaults/results. |
| `GET /dashboard/runs/{run_id}` | Frozen plan/cohort, native importance, selection/calibration metrics, safe training metadata and completed-test metrics/interval coverage only when a verified retrospective batch is registered. `test_status` is `not_registered` or `completed_cached_evaluation`. |
| `GET /dashboard/forecasts/{forecast_id}` | Optional `stock_code` from that frozen cohort, default first cohort entry. Returns pretest weekly history, the product's issued forecasts, available completed-test errors, assumed opening-stock defaults and a causal feature snapshot for the fixed first post-refit origin. The snapshot is not relabeled as the feature state of later rolling weeks. |
| `GET /dashboard/scenarios/{scenario_id}` | Verified configuration, policy/product summary, weekly policy aggregates, latest ML-policy review recommendation per product and product risk from the historical simulation. Full recommendation exports remain available through the scenario export endpoint. |
| `GET /dashboard/scenarios/{scenario_id}/risk/export` | CSV of product-level simulated ML-policy outcomes with scenario ID/scope. No claim of calibrated future stockout probability. |

Each projection verifies registered identities against checksummed analytical files. Forecast and simulation rows must match persisted records; retrospective reads also verify the completed evaluation ledger and point/uncertainty metric sources. These reads do not fit/deserialise a model, reserve a test, evaluate targets, publish artifacts or change PostgreSQL. Missing resources return404; inconsistent registered artifacts return409 `artifact_integrity`. Dashboard projections are bounded at 500 products, 100,000 records and 1,040 history weeks; over-limit projections return422 `projection_limit` instead of unbounded output.

The first-origin forecast total uses the ML family selected before test access. Overview product risk and policy savings use the latest completed retrospective scenario, with simulated labels and the matched four-week-mean safety-stock policy comparison. Those business outcomes do not alter the frozen forecasting selection or establish achieved company savings.

## Stateless inventory preview

`POST /inventory/preview` accepts a registered one-week or retrospective forecast and a product in its frozen cohort:

```json
{
  "forecast_id": "<64-character forecast ID>",
  "stock_code": "84077",
  "on_hand": 100,
  "on_order": 0,
  "backordered_units": 0,
  "parameters": {
    "lead_time_weeks": 1,
    "review_period_weeks": 1,
    "service_level": 0.95,
    "unit_purchase_cost": 1.0,
    "unit_selling_price": 2.0,
    "holding_cost_per_unit_week": 0.02,
    "stockout_penalty_per_unit": 3.0,
    "order_cost": 5.0,
    "min_order_quantity": 0,
    "case_pack_size": 1,
    "max_inventory_capacity": null
  }
}
```

Replace the identifier and use a product from the selected cohort. Omitted parameters receive the illustrated validated defaults. Unknown fields are rejected. Whole-unit fields reject fractional values and booleans; inventory quantities are bounded by `2^53-1`. Lead/review periods are 1–104 complete weeks, case packs positive, service level strictly between zero and one, and monetary inputs finite/nonnegative up to `1e12`. On-hand plus on-order must fit any capacity; combined quantities must also respect the supported integer bound. Fixed-policy override thresholds belong to scenario configuration, not this preview schema.

The response includes the selected-before-test method, first forecast origin, validated state/parameters, reorder point/safety stock/target/recommended quantity, feasibility explanations, horizon assumption, approximate risk/cost and error-estimate provenance. Error magnitude uses only the pretest calibration block, normalized by historical four-week mean with its documented floor. Longer horizons explicitly carry the one available next-origin forecast forward flat.

The preview's next-week risk uses `max(0, Normal(point, pretest_error_magnitude))`; it is an approximation, not a calibrated probability or guarantee. Backorders reduce available on-hand. On-order and newly ordered units are excluded from next-week availability because their arrival dates are unspecified. The cost preview combines new-order cash with approximate next-week holding/stockout costs; it is neither a full historical-simulation total nor realized savings. Estimated lost margin remains separate from total cost.

`POST /inventory/preview/export` accepts the same body and returns one calculated recommendation row as CSV. Neither endpoint writes a job, configuration, scenario, result or artifact. Use `POST /inventory/scenarios` and its dated prepaid arrivals for a saved chronological comparison. The planner supports backorder subtraction; the lost-sales simulator requires zero initial backorders.

## Errors and operations

Validation returns422 with field locations and error types, omitting raw input values and internal validation contexts. Unknown resources return404; key conflicts409; oversized requests413; unavailable dependencies503. Error bodies contain a stable code, safe message and request ID. Worker failures expose only `invalid_input`, `artifact_integrity`, `database_unavailable`, `operation_failed`, `lease_expired` or `attempts_exhausted`.

Inspect `/jobs/{id}` for queued/running/succeeded/failed, attempt count, timestamps and result references. Leases use the database clock and UUID tokens. Worker heartbeats renew live claims; expired claims are retried with backoff until their configured bound. A stale worker cannot commit resource rows. Resource publication and success share one transaction. Complete orphan files can be verified/reused after a crash. Local JSON logs include IDs, route templates, status and durations; no payloads, raw query strings, credentials or customer identifiers are logged.

The choice of a durable worker follows [FastAPI's background-task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/) for heavy work; PostgreSQL exclusivity uses SQLAlchemy's [row-locking support](https://docs.sqlalchemy.org/en/20/core/selectable.html#sqlalchemy.sql.expression.Select.with_for_update). No broker is needed for this local MVP. Operational caveats include no authentication, no job cancellation/retention UI, no external scheduler and no cross-host object store.

## Reproduce the real demonstration

Once the official Phase 1/3 artifacts and completed evaluation ledger exist, run the API and worker above, then:

```bash
python -m scripts.demo_backend
```

This submits five real jobs, checks persisted responses, exports forecasts/recommendations/weekly results and measures 30 warm sequential requests per documented read endpoint. It writes ignored `artifacts/backend/demo/report.json` and CSV exports. The demo uses the versioned key prefix `demandiq-demo-v1`; `--idempotency-prefix` deliberately starts new jobs after an application update. Replays may reuse jobs/artifacts; remove nothing from frozen directories to force a fresh evaluation. See [Phase 5 results](PHASE5_RESULTS.md) for measured values and complete verification.

For portable Compose delivery, use the verified copied-bundle/bootstrap instructions in [DELIVERY.md](DELIVERY.md). The source ledger remains unchanged; only the copied completion record's absolute result directory is relocated, with both digests and the exact field difference recorded. To measure dashboard reads/preview without jobs, use `python -m scripts.benchmark_dashboard` against the running API. Its JSON report records real sequential samples and environment scope; it does not compute forecasting or business metrics.
