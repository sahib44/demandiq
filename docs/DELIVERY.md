# Local delivery and verified demonstration

DemandIQ runs as a local PostgreSQL database, one-shot runtime initializer and migration, FastAPI service, separate durable worker, and static React dashboard served by Nginx. Docker Compose builds the Python and frontend images. The browser uses the same-origin `/api` proxy; Nginx strips that prefix and the API advertises `API_ROOT_PATH=/api` for its documentation. API and worker share `/runtime/data` and `/runtime/artifacts` volumes.

The application is trusted local decision support with no authentication. Published database, API and frontend ports bind to `127.0.0.1`. The example credentials are for local development. The containers do not perform automatic purchasing or final-test evaluation.

## Required software

- Docker Engine/Desktop with Docker Compose supporting health and successful-completion dependencies.
- Python 3.12 and the pinned project dependencies when preparing a bundle from host artifacts. Follow [the README](../README.md) for virtual-environment and macOS OpenMP setup. Bundle preparation itself verifies model bytes without loading their serializers.
- Node 24.15 or later within major version 24, plus npm, for host frontend development/testing. Container builds supply their own pinned Node runtime.

The image definitions pin Python `3.12.14-slim-bookworm`, Node `24.19.0-alpine`, Nginx `1.28.2-alpine` and PostgreSQL `16.6-alpine`. `requirements-runtime.lock` pins the Python runtime graph; `frontend/package-lock.json` pins the frontend graph. The runtime image installs Linux OpenMP through `libgomp1`. XGBoost's Linux x86_64 package dependency on NCCL is pinned even though this application uses CPU inference. The platform actually exercised and measured verification results belong in the phase delivery report; available package wheels do not establish execution coverage on every architecture.

## Start an empty application

From the repository root:

```bash
cp .env.example .env
docker compose config --quiet
docker compose up --build
```

Open [the dashboard](http://127.0.0.1:8080), [proxied API documentation](http://127.0.0.1:8080/api/docs), or [API liveness](http://127.0.0.1:8000/health). The API readiness URL is `/ready`; through Nginx it is `/api/ready`. The initializer creates writable runtime directories, and the migration must finish successfully before API and worker start. The API and worker run as UID/GID `10001`; only the initializer uses root to set ownership of the runtime volumes. The application image filesystem is read-only, with a temporary `/tmp` filesystem.

Without an available demo bundle, the initializer leaves an empty application. Importing data does not invent a trained run, completed evaluation or simulation. If a verified bundle exists at the default mount, initialization copies its files, while database registration still requires the activation workflow or demo profile below.

`docker compose up` does not mount the host repository's original `data/` or `artifacts/` directories. Its named runtime volumes are separate from those host files. The existing PostgreSQL volume key remains `demandiq_postgres`; Compose adds the project-name prefix, as it did before full application delivery.

## Prepare the trusted historical demonstration

The demonstration requires an existing verified processed dataset, frozen Phase 3 run, completed final evaluation and its preserved completed ledger. These large/private artifacts are deliberately absent from Git and Docker build contexts. There is no public model download or generated substitute presented as a real result.

For the existing documented official run:

```bash
.venv/bin/python -m scripts.prepare_demo_bundle prepare
.venv/bin/python -m scripts.prepare_demo_bundle verify
```

The default output is ignored `.cache/demo-bundle/`. To use other existing trusted artifacts, specify all source directories explicitly:

```bash
.venv/bin/python -m scripts.prepare_demo_bundle prepare \
  --dataset-dir data/processed/<dataset-id> \
  --run-dir artifacts/phase3/<run-id> \
  --ledger-dir data/evaluation-ledger \
  --output-dir .cache/my-demo-bundle \
  --runtime-root /runtime
```

Replace the angle-bracket placeholders before running that command. To acquire the official source dataset in a fresh project, follow the reproducible download, ingestion and chronological modeling instructions in [README](../README.md) and [ML methodology](ML_METHODOLOGY.md). Bundle preparation requires their already-completed outputs. It never downloads or trains a substitute, recalculates final metrics, clears a reservation, or completes an interrupted evaluation. An existing consumed official test remains consumed; preserve it rather than resetting the guard to recreate demonstration inputs.

The preparer:

1. Verifies the dataset's source/configuration identity, all file hashes and Parquet row counts.
2. Verifies the frozen training inventory, plan and matching completed ledger/evaluation inventory.
3. Copies complete processed artifacts, frozen training files and completed evaluation files. Raw workbooks are not included.
4. Archives the original ledger bytes under `provenance/original-ledger/<dataset-id>.json`.
5. Changes only the copied ledger's `results_dir` to `/runtime/artifacts/phase3/evaluations/<run-id>`. Experiment, dataset, plan hash, completed status, timestamps and result-manifest hash remain unchanged.
6. Records both ledger hashes, original/relocated paths, changed fields and source-manifest hashes in the bundle's content-derived manifest. Atomic publication and verification make repeated preparation idempotent.

Relocation is a portability operation on an explicitly copied completion record. It does not authorize another test evaluation. The original ledger is checked for byte preservation during preparation. The copied ledger has a different file hash, so later application/inventory wrapper identities may differ while retaining the same frozen prediction and evaluation bytes. No replacement metric or model is generated.

Bundles contain private processed data, including linkable customer pseudonyms, and trusted local joblib models. Keep them local and ignored. Hash verification detects changed bytes; it does not make an untrusted serialized model safe. Use artifacts from a trusted local run only.

## Run the complete demonstration

After preparing the default bundle:

```bash
docker compose --profile demo up --build
```

This is the complete application plus its one-shot bootstrap. Initialization mounts the bundle read-only, verifies it, and copies its files into the runtime volumes. The bootstrap waits for readiness, submits the existing-dataset and frozen-run registration jobs, performs historical one-week inference, loads completed retrospective forecasts, runs/verifies an inventory scenario and exports CSV through HTTP. The separate worker completes all jobs. It does not retrain or invoke final evaluation.

For detached use:

```bash
docker compose --profile demo up --build -d
docker compose --profile demo logs -f demo
docker compose --profile demo ps -a
```

The `runtime-init`, `migrate` and `demo` containers should exit successfully; API, worker, frontend and PostgreSQL remain running. A failed one-shot container is a failed setup, even if another page responds. The bootstrap report and CSVs are stored in the runtime artifact volume at `backend/compose-demo/`.

To mount another prepared bundle, set `DEMANDIQ_DEMO_BUNDLE_DIR` to its absolute host path before starting Compose. Its manifest must still declare runtime root `/runtime`. Installation rejects a different existing frozen artifact or ledger instead of overwriting it. Use a separate Compose project for an independent demonstration.

Job replays reuse their original status/results. After an intentional application update or a fixed failed job, a new explicit key prefix starts new jobs while preserving old records:

```bash
docker compose --profile demo run --rm demo \
  python -m scripts.bootstrap_demo \
  --bundle-dir /opt/demo-bundle \
  --base-url http://api:8000 \
  --output-dir /runtime/artifacts/backend/compose-demo-v2 \
  --idempotency-prefix intentional-demo-v2
```

Do not change keys to bypass a final-test reservation: the bootstrap has no final-evaluation operation. Forecast and scenario resource identities remain derived from verified sources, runtime and implementation rather than from the chosen job key.

## Independent clean-runtime check

Use an unused project name and free host ports. This creates new project-scoped volumes without clearing the existing development database or files:

```bash
export POSTGRES_PORT=55432
export API_PORT=58000
export FRONTEND_PORT=58080
export DEMANDIQ_IMAGE_TAG=phase6
docker compose -p demandiq-cleanroom-check --profile demo up --build -d
docker compose -p demandiq-cleanroom-check --profile demo logs -f demo
docker compose -p demandiq-cleanroom-check --profile demo ps -a
```

The corresponding dashboard is `http://127.0.0.1:58080`; API readiness is `http://127.0.0.1:58000/ready`. Use this same project and environment for subsequent status, log, stop and export commands. Choose another unused project name for a genuinely new runtime; reusing a project verifies persistence rather than first-start initialization. These commands define the verification procedure; measured outcomes are reported separately after execution.

For frontend checks on a host with the documented Node/npm toolchain, from `frontend/`:

```bash
npm ci
npm run lint
npm run format:check
npm test
npm run build
npx playwright install chromium
PLAYWRIGHT_BASE_URL=http://127.0.0.1:58080 npm run test:e2e
```

Playwright runs against the real started application; it does not start PostgreSQL/API/worker itself. Browser binaries and reports are local ignored outputs. Synthetic component tests verify UI behavior and are not evidence of measured forecasting or business performance.

Measure actual dashboard projections without submitting jobs:

```bash
.venv/bin/python -m scripts.benchmark_dashboard \
  --base-url http://127.0.0.1:58000 \
  --samples 30 \
  --output artifacts/phase6/dashboard-benchmark.json
```

This discovers the active dataset/run/forecast/scenario from `/dashboard/context`, selects product `84077` when present (otherwise the first selected product), and makes 30 sequential requests per context/run/product-forecast/scenario endpoint and stateless inventory preview after one excluded warm-up each. It records all individual sample durations, median, nearest-rank P95, minimum, maximum and client environment. Timing includes HTTP transfer and JSON decoding; other activity is not controlled, so it is neither a concurrent load nor capacity benchmark. It uses no import, job, training or evaluation endpoint. Both the report and its containing artifact directory are ignored local outputs.

## Ports, configuration and logs

| Variable | Default / responsibility |
| --- | --- |
| `POSTGRES_PORT` | `5432`, loopback database publication |
| `API_PORT` | `8000`, loopback direct API publication |
| `FRONTEND_PORT` | `8080`, loopback dashboard and `/api` proxy |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Documented development defaults; initialize PostgreSQL only on a new database volume |
| `DEMANDIQ_IMAGE_TAG` | `local`, local backend/frontend image tag |
| `DEMANDIQ_DEMO_BUNDLE_DIR` | `./.cache/demo-bundle`, read-only input mount for initializer/bootstrap |
| `JOB_MAX_ATTEMPTS`, `JOB_LEASE_SECONDS`, `JOB_POLL_SECONDS` | Same validated durable-worker controls as native development |
| `MAX_REQUEST_BYTES` | `1048576`, API request cap; Nginx also limits requests to 1 MiB |

Compose constructs its internal database URL with hostname `postgres`, and sets fixed container data/artifact/ledger paths. Host-development `DATABASE_URL` and relative filesystem settings from `.env` do not replace those internal paths. Passwords interpolated into the internal URL must be URL-safe; use the documented local development values for this demonstration. `API_ROOT_PATH=/api` is set only for the container API; native development defaults to an empty root path.

Inspect status and bounded logs:

```bash
docker compose ps -a
docker compose logs --tail=100 runtime-init migrate api worker
```

Backend logs use structured, redacted events. Nginx access logging is disabled so it does not record raw query strings. Readiness verifies database/migration/storage dependencies; completing a real job separately verifies worker processing. A running API alone does not establish worker availability.

## Stop, preserve and back up

```bash
docker compose stop
# Restart the same project and preserve all its data:
docker compose --profile demo up -d
```

Ctrl-C during foreground `up` also stops services without deleting named volumes. `docker compose down` removes containers/network while retaining ordinary named volumes. **Do not use `down -v`, delete Docker volumes, or delete evaluation ledgers to reset a demonstration.** Source artifacts on the host and copied runtime artifacts are separate retained records.

For a consistent local backup, stop application writers, dump PostgreSQL and archive the runtime files together:

```bash
mkdir -p .cache/backups
docker compose stop api worker
docker compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > .cache/backups/database.dump
docker compose run --rm --no-deps -T runtime-init tar -C /runtime -czf - data artifacts > .cache/backups/runtime.tar.gz
docker compose up -d api worker frontend
```

Keep the trusted original host artifacts, original ledger, prepared bundle and backup pair private. A database dump alone lacks referenced analytical files; a file archive alone lacks application metadata/jobs. Restore into a separate project for inspection before replacing anything. Do not merge incompatible completed ledgers or silently rewrite frozen manifests to make a restore appear compatible.

## Troubleshooting

- **Port already allocated:** use unused publication ports and the same project variables consistently. Do not stop or clear an unrelated database to free a demonstration port.
- **Initializer fails integrity/provenance:** preserve the bundle and runtime volumes; compare the reported manifest/ledger against its trusted source. Prepare a new separate output only after understanding the mismatch.
- **Migration fails:** inspect `migrate` logs and PostgreSQL health. Do not bypass the dependency by manually starting an incompatible API.
- **Jobs remain queued:** inspect worker status/logs. Closing the browser does not cancel a submitted job.
- **A job is permanently failed:** inspect its safe error code and fix its actual input/environment. A deliberate new key starts a new bounded job; replaying the old key returns its old failure.
- **Missing frozen sample:** the import panel can acquire data, but data import alone cannot supply a completed model/evaluation. Follow the documented chronology or supply a verified trusted bundle.
- **Interrupted final-test reservation:** retain ledger and partial results for manual investigation. Neither bundle preparation nor the API authorizes reevaluating that test.

See [the user guide](USER_GUIDE.md), [API documentation](API.md), [data dictionary](DATA_DICTIONARY.md) and [inventory methodology](INVENTORY_METHODOLOGY.md) for interpretation and schema details.
