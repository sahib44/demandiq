# Public repository preparation and verification

Verified on **2026-10-23**, from the project root, for `sahib44/demandiq`.

## Scope and history

The local repository initially had zero reachable commits, no tracked files and no remote. Git object inspection found local dangling snapshot trees; these are not commits/branch history and are not part of the approved publication tree. No history rewrite or deletion of private artifacts was necessary. Only reviewed source files and documentation images are published. Original datasets, fitted models, generated analytical files, the official completed evaluation ledger, databases, credentials and local caches stay outside the published tree.

The current request explicitly authorizes public GitHub publication and supersedes the earlier experiment-stage instruction not to commit/push. Historical phase reports retain their original measurements; local machine paths and sample passwords were normalized for publication. All 163 protected original ML source/artifact/official-ledger files still match the pre-publication saved SHA-256 inventory.

## Dataset terms and public demo

UCI's official page lists Online Retail as CC BY 4.0. Attribution, license links, transformation notices and independent-project language are in [DATA_LICENSE.md](DATA_LICENSE.md) and the root README. Rather than redistribute the workbook/customer-level records, the repository retains the official checksum-pinned downloader and excludes all raw/processed data and customer pseudonyms.

The public fixture is 175 completely fictional, customer-free rows for three products. The isolated demo genuinely cleans it, trains the three ML families and baselines, evaluates its own separate synthetic dataset/ledger, prepares a local bundle and activates real API/worker/database results. These outputs demonstrate functionality and never substantiate retail model quality or business savings. All generated results remain ignored below `.cache/synthetic-demo/`.

The roughly 2.4% historical result is described as a modeled comparison under illustrative costs, with higher average stock and full closing-asset recovery. The README retains the negative final-test Ridge/baseline comparison and the holding-cost sensitivity that reverses the modeled advantage. This is an independent project, not a deployed business system.

## Security and source-control checks

- Source candidates checked with Gitleaks **8.30.1**, downloaded from the official release and verified against its SHA-256 checksums.
- Source scan: **zero detected leaks**. This complements explicit path/file review; a scanner is not a guarantee against every possible secret.
- `.env.example` contains placeholders. Compose requires an explicitly supplied local password. No real `.env`, credentials, private keys or credential-bearing remote URL is published.
- Only `fixtures/synthetic_retail.csv` is allowlisted through the general CSV exclusion. No original raw rows or pseudonyms occur in that fixture.
- Images are documentation screenshots of aggregate product/forecast/simulation views, with UCI attribution. No customer records are displayed.
- The publication inventory excludes `.git`, `.agents`, `.codex`, `.cache`, `.venv`, `node_modules`, builds, reports, database files, trained models and generated datasets/results.
- No cloud deployment, GitHub Pages deployment, new access token or authentication grant is part of publication.

## Actual rerun results

| Check | Observed result |
| --- | --- |
| Full Python suite, including dedicated PostgreSQL integration database | **1255 passed in 58.25 s**, no failures/skips/warnings |
| Frontend Vitest / React Testing Library | **29 passed in 7.65 s** |
| Existing real-backend Playwright suite | **3 passed in 46.0 s** |
| Desktop/mobile axe and responsive/keyboard checks | Existing browser suite passed all six pages at both sizes |
| TypeScript and Vite production build | Passed |
| Ruff, Black, ESLint, Prettier | Passed |
| Python dependency consistency | No broken requirements |
| Isolated synthetic Compose build/bootstrap | Passed; initializer/migrate/demo exited zero; API/frontend/PostgreSQL healthy; worker ran real jobs |
| Synthetic API/export smoke | Three fictional products; quality/run/forecast/scenario projections passed; 144 forecast CSV rows |
| Synthetic UI notice | Browser verified fictional-data label and no-real-performance/savings notice |
| Original protected ML/artifact/ledger inventory | 163 unchanged files |

The historical official test was **not** reevaluated. The browser workflow registers/verifies completed official artifacts; only the separate fictional fixture is newly trained/evaluated. The synthetic workflow's model family need not match the official Ridge selection, and synthetic numbers are not reported as real metrics.

## Commands used

These use the installed project Python 3.12 environment. For the inspected Mac, the cached OpenMP runtime was supplied with `DYLD_LIBRARY_PATH`. The dedicated test database URL was supplied locally and is not reproduced with its password here.

```bash
git status --short --branch
git rev-list --all --count
git remote -v
git fsck --full --no-reflogs
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" TEST_DATABASE_URL="$TEST_DATABASE_URL" .venv/bin/python -m pytest ml/tests backend/tests
.venv/bin/ruff check .
.venv/bin/black --check .
PIP_CACHE_DIR="$PWD/.cache/pip" .venv/bin/python -m pip check
DYLD_LIBRARY_PATH="$PWD/.cache/libomp" .venv/bin/python -m scripts.demo_synthetic
# Private ignored test env chooses isolated ports and synthetic bundle:
docker compose --env-file .cache/publication.env -p demandiq-publication-check --profile demo config --quiet
docker compose --env-file .cache/publication.env -p demandiq-publication-check --profile demo up --build -d
docker compose --env-file .cache/publication.env -p demandiq-publication-check --profile demo ps -a
.cache/tools/gitleaks/gitleaks dir .cache/publication-source --redact --report-format json --report-path .cache/publication-gitleaks.json
# From frontend/, with Node 24/npm on PATH:
npm test
npm run build
npm run lint
npm run format:check
PLAYWRIGHT_BASE_URL=http://127.0.0.1:58080 PLAYWRIGHT_BROWSERS_PATH="$PWD/../.cache/playwright" npm run test:e2e
```

## Recruiter-facing limitations

The full measured experiment uses one historical retailer, a short timeline and a high-volume 50-product cohort. Sales availability and true unmet demand are unknown. Ridge did not beat the moving-average baseline on final WAPE. Uncertainty is empirical; multihorizon planning uses flat carry-forward and approximate independent-normal error assumptions. Costs, stock and supplier conditions are illustrative; the replenishment controller does not directly optimize economic inputs. Closing stock is assumed fully recoverable. The public synthetic demo is deliberately small and patterned.

The application is local and unauthenticated, with no automated purchasing or external integrations. macOS/Linux ARM64 and Chromium were exercised; AMD64 execution, other browsers and production-scale capacity remain unverified. The full official-data E2E needs trusted locally reproduced artifacts rather than the three-product fixture. The repository provides source, documentation, tests, screenshots and a reproducible synthetic demo; it does not distribute the private development bundle or a deployed service.

## Complete Python and frontend test summaries

### Full Python suite

```text
============================= test session starts ==============================
platform darwin -- Python 3.12.14, pytest-8.3.5, pluggy-1.7.0
rootdir: /path/to/demandiq
configfile: pyproject.toml
plugins: platformdirs-4.13.4, anyio-4.15.1
collected 1255 items

ml/tests/test_acquisition.py .............                               [  1%]
ml/tests/test_baselines.py .............................                 [  3%]
ml/tests/test_cleaning.py .............................................. [  7%]
........................................................................ [ 12%]
                                                                         [ 12%]
ml/tests/test_features.py ..................................             [ 15%]
ml/tests/test_final_test.py ............................................ [ 18%]
..................................                                       [ 21%]
ml/tests/test_ingestion.py ...............                               [ 22%]
ml/tests/test_inventory_config.py ...................................... [ 25%]
..............................................................           [ 30%]
ml/tests/test_inventory_pipeline.py .................................... [ 33%]
..................                                                       [ 35%]
ml/tests/test_inventory_planning.py .................................... [ 38%]
...........                                                              [ 38%]
ml/tests/test_inventory_plots.py ........                                [ 39%]
ml/tests/test_inventory_simulation.py .................................. [ 42%]
.................                                                        [ 43%]
ml/tests/test_metrics.py .................................               [ 46%]
ml/tests/test_model_plots.py .....                                       [ 46%]
ml/tests/test_modeling_pipeline.py ...............                       [ 47%]
ml/tests/test_phase2_pipeline.py ...............                         [ 49%]
ml/tests/test_plots.py ..                                                [ 49%]
ml/tests/test_splits.py .....................                            [ 50%]
ml/tests/test_training.py .............................................. [ 54%]
.......................                                                  [ 56%]
ml/tests/test_uncertainty.py ...................                         [ 57%]
ml/tests/test_weekly.py ................................................ [ 61%]
......................................                                   [ 64%]
backend/tests/test_api.py .............................................. [ 68%]
.......................                                                  [ 70%]
backend/tests/test_application_db.py ................................... [ 72%]
........................................................................ [ 78%]
................................                                         [ 81%]
backend/tests/test_application_services.py ............                  [ 82%]
backend/tests/test_dashboard.py ........................................ [ 85%]
...............                                                          [ 86%]
backend/tests/test_db.py ....................................            [ 89%]
backend/tests/test_demo_bundle.py ......................                 [ 91%]
backend/tests/test_forecasting_service.py ......................         [ 92%]
backend/tests/test_jobs.py ............................................. [ 96%]
.                                                                        [ 96%]
backend/tests/test_operation_integrity.py ..................             [ 98%]
backend/tests/test_synthetic_demo.py .....                               [ 98%]
backend/tests/test_worker.py ...................                         [100%]

============================ 1255 passed in 58.25s =============================
```

### Frontend component tests

```text
> demandiq-frontend@1.0.0 test
> vitest run


 RUN  v5.0.5 /path/to/demandiq/frontend


 Test Files  2 passed (2)
      Tests  29 passed (29)
   Start at  01:51:21
   Duration  7.65s (tests 54%, environment 30%, setup 8%, transform 4%, import 3%)
```

### Real-backend browser tests

```text
> demandiq-frontend@1.0.0 test:e2e
> playwright test


Running 3 tests using 1 worker

  ✓  1 e2e/dashboard.spec.ts:31:1 › real dataset activation → frozen run → forecast → inventory → comparison → CSV (19.0s)
  ✓  2 e2e/dashboard.spec.ts:156:1 › all six pages render real data, pass automated accessibility checks and fit mobile (22.3s)
  ✓  3 e2e/dashboard.spec.ts:237:1 › proxy serves live OpenAPI and the UI handles dependency failure safely (1.8s)

  3 passed (46.0s)
```

