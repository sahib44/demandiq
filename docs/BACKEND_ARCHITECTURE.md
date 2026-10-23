# Backend, dashboard and local delivery protocol

Phase 5 adds a local FastAPI service and independent PostgreSQL worker. Phase 6 adds verified dashboard read projections, synchronous inventory previews, React/TypeScript pages and full local Compose delivery. Existing ML/inventory functions remain the calculation authority; frozen Phase 3/4 artifacts and the consumed forecasting ledger are preserved. No API triggers a second final-test evaluation. [API.md](API.md), [DELIVERY.md](DELIVERY.md) and [USER_GUIDE.md](USER_GUIDE.md) describe the concrete interfaces and workflow.

## Boundaries and persistence

Routes validate Pydantic requests and call application services. PostgreSQL stores registered datasets/catalog/quality, training lineage, serialized-model references, training-scoped weekly facts, forecast batches/values, scenario configurations/results and jobs. Analytical files remain immutable Parquet/JSON/joblib under configured roots. Job execution publishes/verifies files first; one fenced transaction registers resources and marks the job succeeded. A crash can leave complete orphan files, which an idempotent retry verifies/reuses. It cannot expose partly committed database resources.

Dataset imports accept an existing content-derived dataset, a file under the configured raw-data root, or the checksum-pinned official source. API requests never supply arbitrary remote URLs or model-file paths. Local file payloads include a server-computed source digest. Training can register an existing verified run or invoke the existing pre-test training pipeline. Retuning on the observed official test is still refused by that pipeline.

A one-week forecasting job performs real inference from the registered training boundary using saved pipelines, causal features, baselines and frozen uncertainty. It is labeled with its historical origin, not today's date. A retrospective job registers the existing completed test forecasts only after checking the completed ledger. Inventory jobs require that retrospective forecast scope and call the existing verified scenario pipeline. They remain assumption-driven historical simulations. No future-demand inference, business savings or model improvement is invented.

## Durable job semantics

Submission returns HTTP 202 and a job URL. `(kind,idempotency_key)` is unique. If no key is supplied, canonical payload SHA-256 is the key; an explicit key reused with a different payload conflicts. Replays return the original job, including a failed state. A deliberately new attempt needs a new explicit key after bounded retries.

Workers claim eligible rows using `FOR UPDATE SKIP LOCKED`, commit the claim, then compute outside the transaction. Every claim increments attempts and receives a UUID lease token. A heartbeat renews only a current unexpired lease. Completion locks and checks ownership/expiry, persists all resources, and marks success in the same transaction. A stale worker cannot commit resources or status. Immutable computation files may already exist and are safe to verify/reuse. Expired claims are recovered with bounded retries; exhausted jobs fail. Retryable database/IO failures use backoff; validation, ledger and integrity failures are permanent. Default maximum attempts3 (allowed1–5), lease 60 seconds, polling 1 second.

## API and observability

The service implements the specification's dataset/product/training/model/forecast/scenario endpoints plus `/jobs`, `/ready`, forecast-value/CSV reads and the Phase 6 dashboard/preview routes. Lists are bounded/paginated. Product IDs are scoped by dataset; histories are scoped by training run and contain the pre-test full weekly measures. Completed retrospective actuals are supplied separately in forecast records, without fabricating missing accounting measures.

`/health` is process liveness. `/ready` checks PostgreSQL, the expected migration revision and writable data/artifact roots. `/config` excludes credentials and absolute host paths. Structured JSON request/job logs contain IDs, state and durations, not request bodies, queries, raw customers, credentials or exception strings. Validation errors omit input values; worker errors expose stable codes. OpenAPI is generated at `/openapi.json`, with Swagger at `/docs` and ReDoc at `/redoc`.

This is a trusted local application with authentication out of scope. Bind the development server to 127.0.0.1. CORS allows configured local origins. The API does not start a worker implicitly; run both documented processes. Migrations are explicit and never run during ordinary request handling.

## Dashboard reads and preview boundary

`backend/app/api/dashboard.py` validates bounded identifiers and `InventoryPreviewRequest`; `backend/app/services/dashboard.py` owns read orchestration. `/dashboard/context` selects registered resources, `/dashboard/runs/{id}` exposes frozen model evidence, `/dashboard/forecasts/{id}` projects product history/predictions/first-origin features, and `/dashboard/scenarios/{id}` exposes verified simulated results/configuration. A separate scenario risk export returns simulated product rows.

These reads verify file inventories/lineage against database registration. Forecast observations and simulation facts are compared with their persisted rows. Retrospective reads additionally verify the completed ledger and its existing test point/interval metrics. No projection loads model serializers, fits preprocessing, claims evaluation, computes a new final-test metric, publishes a file or changes PostgreSQL. Safe training-metadata fields exclude internal host paths. Complete projections deliberately perform integrity work on each request rather than claiming the latency of an unchecked in-memory fixture. Bounds limit cohorts to 500 products, records to 100,000 and history to 1,040 weeks; missing, inconsistent and over-limit inputs have explicit safe errors.

`POST /inventory/preview` and `/inventory/preview/export` are synchronous stateless calculations. They reuse the Phase 4 planner and the frozen selected family at its first origin. Error magnitude comes from the pretest calibration block; it is not refit using retrospective outcomes. Quantities/costs/service/lead/review/capacity inputs are strictly validated. Preview recommendations include the flat multiweek approximation and feasibility reasons. A separate nonnegative normal approximation estimates next-week risk/holding/lost demand using on-hand minus backorders; pipeline/new orders are excluded because the preview has no receipt dates. Cost preview adds order cash to those approximate next-week costs while reporting lost margin separately. These outputs retain decision-support labels and do not become historical simulation facts.

Submitting an inventory scenario remains a durable job and uses the full chronological simulator, dated prepaid arrivals, common policy assumptions and conservation/accounting checks. A preview creates neither an inventory configuration nor a scenario or job. This keeps immediate UI updates separate from persisted scenario experiments.

## Compose and artifact portability

`docker-compose.yml` starts PostgreSQL, a root-only runtime initializer, a one-shot Alembic migration, nonroot API/worker processes and Nginx serving a production Vite build. API/worker use the same `/runtime/data` and `/runtime/artifacts` named volumes, read-only image filesystems and temporary `/tmp`. Host publications bind loopback. The existing PostgreSQL volume declaration is retained. The optional `demo` profile runs the five-job HTTP bootstrap after API readiness and worker startup.

Nginx forwards `/api/...` without its prefix. `API_ROOT_PATH=/api` supplies that external path through ASGI middleware, preserving proxy-relative OpenAPI/Swagger/ReDoc while native development defaults to empty. The prefix accepts normalized safe segments, not arbitrary paths/query strings. Nginx access logs are disabled; backend logs retain route templates/status/durations without raw query strings or payloads.

Raw/processed datasets, model artifacts, caches and environment secrets are excluded from image build context. Trusted demonstration inputs enter through a read-only bundle mount, then copy into writable runtime volumes. `scripts/prepare_demo_bundle.py` verifies the source dataset, frozen run, completed ledger/evaluation and every copied inventory. It archives the original ledger bytes and relocates only the copied completion record's `results_dir`; all reservation identities, completed state, timestamps and result-manifest hash remain fixed. Bundle provenance records original/copied digests and changed fields. Installed provenance is retained under `artifacts/demo-bundles/<bundle_id>/`.

Installation refuses symlink trees/root redirection and different existing frozen artifacts/ledgers. It does not reset guards or overwrite an existing completion to make incompatible data appear valid. Wrapper/run IDs can differ after copied-ledger relocation because lineage includes its digest; frozen model/evaluation bytes and decisions remain unchanged. This remains a cooperative trusted-filesystem protocol, not authentication against an actor able to replace models and recompute hashes. An untrusted pickle remains unsafe despite a checksum.

Keep the original host ledger/artifacts and runtime database/file volumes. Back up PostgreSQL and its referenced runtime files together with application writers stopped. A separate Compose project and free ports provide an isolated clean-runtime check without deleting development data. See [delivery procedures](DELIVERY.md) for exact launch, backup and stop commands.

## Verification gates

The Phase 5 gate reran the previous 848 tests and added real PostgreSQL migration/drift/constraint/persistence tests, concurrent/idempotent claims, bounded retry/expiry/stale-owner/transaction-rollback tests, API validation/error/readiness tests and an actual HTTP→job→worker→database→export demonstration. [Phase 5 results](PHASE5_RESULTS.md) preserve its measured evidence.

Phase 6 adds verified dashboard/preview and copied-bundle regressions, frontend rendering/loading/error/input/export tests, browser workflows against real API/worker/PostgreSQL, accessibility/responsiveness checks and isolated clean-image/runtime verification. `scripts/benchmark_dashboard.py` measures actual sequential warm projection/preview requests without jobs or evaluation, retaining every sample plus its environment/scope. Preserve frozen hashes/ledger and report actual commands/counts/limits. Unit fixtures and benchmark timings are not real model or achieved-company-savings evidence; final delivery results are reported only after their checks execute.

## Application schema

Migration `0002_application` adds nine tables to the three Phase 1 metadata tables:

| Table | Role and key |
| --- | --- |
| `jobs` | UUID job, kind/key uniqueness, canonical payload hash, bounded attempts, lease ownership and stable result/error status |
| `training_runs` | Content-derived run ID, dataset, frozen configuration/selection/calibration metrics and training manifest checksum |
| `model_artifacts` | Run/family/hash-derived ID, trusted local path and fitted pipeline metadata |
| `weekly_demand` | Run/product/Monday key, dataset/product foreign keys, complete gross/credit/accounting facts through refitting |
| `forecast_batches` | Versioned source/config/runtime/code-derived ID and explicit one-week or retrospective scope |
| `forecast_values` | Batch/product/week/method key, finite ordered point/bounds, empirical uncertainty label and nullable actual |
| `inventory_configurations` | Canonical configuration digest and validated currency/assumptions |
| `simulation_scenarios` | ID derived from forecast batch and immutable Phase 4 inventory run; exact source/cost lineage |
| `simulation_results` | Scenario/policy/product/week key, nonnegative conserved unit counts and simulated cost details |

The application scenario ID differs from the analytical inventory run ID so two versioned forecast wrappers cannot collide while referencing identical physics. Jobs return both IDs. Model and artifact paths remain private; public responses expose IDs/hashes and business metadata. SQL constraints reject nonfinite/broken accounting values in addition to request validation. Dataset deletion cascades associated lineage; no public deletion endpoint exists. Orphan configuration/job/file retention remains manual local maintenance.

The pinned Phase 3 `_next_week_features` helper is reused by the inference service to preserve feature parity. It is an internal Python interface, so future changes require coordinated regression tests and a new artifact identity. Source files and the consumed official evaluation ledger remain unchanged.
