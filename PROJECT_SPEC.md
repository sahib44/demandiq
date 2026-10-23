You are building DemandIQ, a production-style sales forecasting and inventory optimization application. The complete project specification follows this instruction. Read the entire specification before creating or modifying any files, and treat it as the source of truth for the project.

Begin by inspecting the current repository and development environment. Confirm the available versions of Python, Node.js, Docker, PostgreSQL, and Git. If the directory is empty, create an appropriate repository structure. Do not create a remote repository, push code, or make Git commits unless I explicitly request it.

Before implementation:

1. Save the complete project specification as `PROJECT_SPEC.md`.
2. Create `docs/IMPLEMENTATION_PLAN.md` containing:
   - The proposed architecture
   - Major components and their responsibilities
   - Database design
   - Data and machine-learning pipelines
   - API boundaries
   - Frontend structure
   - Testing strategy
   - Implementation phases
   - Dependencies, assumptions, and technical risks
   - Exact verification criteria for each phase
3. Create a clear README containing setup instructions, required software, environment variables, development commands, testing commands, and the current implementation status.
4. Create `.gitignore` and `.env.example` files. Raw datasets, generated datasets, trained models, database files, secrets, caches, logs, and local environment files must not be committed.

Use the following implementation phases:

### Phase 1: Data foundation

- Repository scaffolding
- Reproducible acquisition of the official dataset
- Data validation and schema enforcement
- Cleaning and normalization
- Correct handling of cancellations, returns, invalid quantities, missing identifiers, dates, prices, and duplicate records
- PostgreSQL schema and migrations
- Automated tests for ingestion and cleaning

### Phase 2: Forecasting foundation

- Product-level weekly demand aggregation
- Continuous product-week time series
- Configurable selection of the top 50 products
- Naive, seasonal-naive, and moving-average baselines
- Leakage-safe feature engineering
- Chronological train, validation, and test splits
- Expanding-window backtesting
- Forecast evaluation metrics

### Phase 3: Machine learning

- Ridge or ElasticNet
- Random Forest or HistGradientBoosting
- XGBoost or LightGBM if justified
- Reproducible model training
- Hyperparameter evaluation using time-aware validation
- Model comparison against baselines
- Prediction intervals or clearly labeled uncertainty estimates
- Saved model artifacts and model metadata
- Model card documenting assumptions, limitations, and intended use

### Phase 4: Inventory optimization

- Reorder points
- Safety stock
- Recommended order quantities
- Lead-time demand
- Configurable service levels, lead times, review periods, holding costs, stockout costs, and order costs
- Chronological inventory simulation
- Comparison of baseline and forecast-driven inventory policies
- Business metrics such as fill rate, service level, lost sales, stockouts, inventory held, and estimated cost
- Clear separation between historical facts, model predictions, assumptions, and simulated outcomes

### Phase 5: Backend application

- FastAPI service
- PostgreSQL persistence
- Background training and forecasting jobs
- Atomic job claiming
- Idempotent operations
- Bounded retries
- Failure recovery
- Structured logging
- Health and readiness endpoints
- API documentation
- Unit and integration tests

### Phase 6: Frontend and delivery

- React and TypeScript dashboard
- Executive overview
- Data-quality page
- Forecast explorer
- Inventory planner
- Scenario comparison
- Model-performance page
- Accessible and responsive interfaces
- CSV exports
- Frontend tests
- Playwright end-to-end testing
- Docker Compose configuration
- Final documentation and reproducible demonstration workflow

Important engineering requirements:

- Start with the top 50 products for the MVP, but make the limit configurable.
- Establish simple forecasting baselines before introducing advanced models.
- Use chronological validation everywhere. Never randomly split time-series observations.
- Prevent data leakage by fitting preprocessing and feature transformations only on data available before each prediction period.
- Make all inventory assumptions configurable and document their default values.
- Never fabricate model performance, business savings, test results, benchmarks, or completed functionality.
- Never describe simulated savings as savings achieved by a real company.
- Use deterministic random seeds where applicable.
- Pin important dependencies and document the reason for major technology choices.
- Keep modules focused and avoid unnecessary abstractions.
- Add typing, validation, useful error messages, and documentation for important interfaces.
- Write tests alongside implementation instead of postponing testing.
- Run the relevant tests at the end of each phase and fix failures before continuing.
- Update the README and implementation plan whenever the architecture or scope changes.
- Do not silently remove requirements. Document any deferred requirement and explain why it was deferred.
- Do not expose secrets or include real customer information.
- Do not use generated mock results as evidence of real model performance.
- Prefer a functional, tested vertical slice over partially implementing every feature.

For this initial run, first present a concise summary of the architecture and implementation plan. Then proceed without waiting for confirmation and complete only Phase 1. Do not begin Phase 2 yet.

At the end of the run, provide:

1. A summary of everything implemented
2. A list of files created or modified
3. All commands used to run and test the work
4. The complete test results
5. Any assumptions or limitations
6. Any unresolved problems
7. The exact recommended next prompt for beginning Phase 2

The complete DemandIQ project specification begins below:

# Build DemandIQ: Sales Forecasting and Inventory Optimization Platform

Act as a senior machine learning engineer, data scientist, and full-stack developer. Build a complete, tested, containerized application named **DemandIQ** that forecasts product demand and converts those forecasts into inventory recommendations and measurable business outcomes.

DemandIQ must demonstrate machine learning, time-series feature engineering, business analytics, backend development, frontend development, testing, and reproducibility. The project must be suitable for presentation to software engineering, data science, machine learning, and business analytics recruiters.

Do not fabricate model metrics, performance benchmarks, cost savings, or test results. Every number displayed in the application or documentation must be produced by an actual reproducible run.

## 1. Business problem

Retailers must decide how much inventory to order before future demand is known.

- Under-ordering produces stockouts, lost revenue, and dissatisfied customers.
- Over-ordering produces holding costs and excess inventory.
- Forecast accuracy alone does not guarantee a useful inventory strategy.

DemandIQ must help a company answer:

1. How much demand should we expect for each product next week?
2. Which products have increasing or decreasing demand?
3. Which products face the greatest stockout risk?
4. How much inventory should be reordered?
5. How reliable is each forecast?
6. How does the ML-based policy compare with simple inventory strategies?
7. What are the expected holding costs, stockout costs, lost sales, and total costs?
8. How do business assumptions affect the recommended order quantities?

The system must clearly separate forecast accuracy from business performance.

## 2. Dataset

Use the UCI Online Retail dataset:

https://archive.ics.uci.edu/dataset/352/online+retail

The dataset includes approximately 542,000 transactions from a UK-based online retailer. Expected fields include:

- `InvoiceNo`
- `StockCode`
- `Description`
- `Quantity`
- `InvoiceDate`
- `UnitPrice`
- `CustomerID`
- `Country`

Provide a reproducible script or command that downloads the dataset from the official source. Do not commit an unnecessarily large raw data file if it can be retrieved automatically.

Start with the 50 highest-volume eligible products. Make this limit configurable so the application can later support 100 or more products.

Product selection must be based only on the training period to avoid using future test information.

## 3. Technology stack

Use:

### Machine learning and data

- Python 3.12
- pandas or Polars
- NumPy
- scikit-learn
- XGBoost or LightGBM
- SHAP or native feature importance
- joblib
- MLflow for experiment tracking, if it can be added without making local setup unreliable

### Backend

- FastAPI
- Pydantic
- SQLAlchemy
- PostgreSQL
- Alembic migrations

### Frontend

- React
- TypeScript
- Vite
- A charting library such as Recharts or Plotly
- A clean component library or accessible custom CSS

### Quality and deployment

- pytest
- React Testing Library
- Playwright
- Docker
- Docker Compose
- Ruff or Flake8
- Black
- ESLint
- Prettier

The entire system must run locally through documented commands, preferably:

```bash
docker compose up --build
```

## 4. Data ingestion and validation

Build a reproducible ingestion pipeline that:

1. Downloads or accepts the Online Retail dataset.
2. Validates the required columns and supported types.
3. Parses `InvoiceDate` consistently.
4. Removes exact duplicate transactions.
5. Separates purchases, cancellations, and returns.
6. Handles invoice numbers beginning with `C`.
7. Handles negative quantities appropriately.
8. Rejects or flags impossible values such as nonpositive sale prices.
9. Preserves a data-quality report describing every cleaning decision.
10. Records row counts before and after each cleaning stage.
11. Stores cleaned data in an efficient format such as Parquet.
12. Produces deterministic output when run with the same input and configuration.

Do not silently delete questionable records. Record why records were removed or transformed.

Create a data-quality summary containing:

- Original rows
- Cleaned rows
- Duplicate rows
- Cancellation rows
- Return rows
- Missing descriptions
- Missing customer IDs
- Invalid prices
- Invalid quantities
- Date range
- Unique products
- Unique invoices
- Unique customers
- Countries represented

## 5. Demand aggregation

For the first version, predict weekly demand one week ahead.

Aggregate cleaned purchases by:

- Product
- Calendar week

For every selected product, create a continuous weekly series. Insert zero-demand weeks when a product has no purchases so gaps are not mistaken for missing data.

Maintain separate measures for:

- Gross units sold
- Returned units
- Net units
- Revenue
- Number of transactions
- Number of unique customers
- Average selling price

Use gross positive unit demand as the initial forecasting target unless analysis demonstrates that net demand is more appropriate. Document the choice.

## 6. Feature engineering

Every feature must be available before the forecasted week begins.

Create features such as:

- Demand lag 1
- Demand lag 2
- Demand lag 4
- Demand lag 8
- Four-week rolling mean
- Eight-week rolling mean
- Twelve-week rolling mean, when sufficient history exists
- Four-week rolling standard deviation
- Eight-week rolling standard deviation
- Recent demand trend
- Previous-week revenue
- Previous-week average price
- Previous-week transaction count
- Previous-week unique-customer count
- Recent return rate
- Month
- Week of year
- Quarter
- Configurable holiday or seasonal indicators
- Product identifier

All rolling and lagged features must be shifted so the current or future target never enters the feature set.

Create automated tests proving that feature generation does not leak future data.

## 7. Training and validation

Never use a random train-test split for the primary evaluation.

Use chronological evaluation:

- Earlier weeks for training
- A later block for validation
- The final block for testing

Because the dataset covers approximately one year, use expanding-window backtesting where practical. Document the exact dates assigned to every split.

Create at least three backtesting folds if the available history supports them.

Compare these approaches:

### Baselines

1. Last observed demand
2. Four-week moving average
3. Seasonal naive forecast, when sufficient history exists

### ML models

1. Ridge or Elastic Net regression
2. Random forest or histogram-based gradient boosting
3. XGBoost or LightGBM

Use the validation data for model selection and hyperparameter tuning. Touch the test data only for final evaluation.

Use a fixed random seed and store:

- Training configuration
- Feature list
- Dataset version
- Split dates
- Hyperparameters
- Metrics
- Training timestamp
- Git commit hash when available
- Serialized model location

## 8. Forecast evaluation

Calculate:

- MAE
- RMSE
- WAPE
- sMAPE
- Bias, meaning average forecast error
- Error by product
- Error by week
- Error by demand-volume segment

Avoid relying on ordinary MAPE because products may have zero-demand weeks.

Compare every ML model against each baseline. Show whether the selected model actually improves forecasting performance.

Include visualizations for:

- Actual versus predicted demand
- Residual distribution
- Error over time
- Error by product
- Baseline versus model performance
- Underforecasting versus overforecasting
- Feature importance

Clearly label validation and test results.

## 9. Forecast uncertainty

Provide uncertainty estimates for each prediction.

Use a practical method such as:

- Residual quantiles from backtesting
- Conformal prediction
- Quantile regression, if supported reliably

Display:

- Point forecast
- Lower bound
- Upper bound
- Confidence or reliability indicator

Do not describe these bounds as guarantees.

## 10. Inventory optimization

Convert forecasts into actionable reorder recommendations.

Each product must support configurable business inputs:

- Current on-hand inventory
- Units already on order
- Supplier lead time in weeks
- Unit purchase cost
- Unit selling price
- Holding cost per unit per week
- Stockout penalty or lost-margin estimate
- Desired service level
- Minimum order quantity
- Case-pack size
- Maximum inventory capacity, if applicable

Calculate:

```text
Lead-time demand = forecasted demand over the supplier lead time

Inventory position =
on-hand inventory
+ units already ordered
- backordered units

Safety stock =
service-level factor
× forecast-error estimate
× square root of lead time

Reorder point =
lead-time demand + safety stock

Recommended order quantity =
target inventory position - current inventory position
```

Recommendations must:

- Never be negative
- Respect minimum order quantities
- Round to case-pack sizes
- Respect maximum capacity where configured
- Explain the main factors behind the recommendation

If the lead time extends beyond the current one-week forecast horizon, generate the required multiweek forecast or use a documented approximation. Do not silently multiply a one-week prediction without explaining the assumption.

## 11. Inventory simulation

Build a chronological inventory simulator.

For each simulated week:

1. Receive purchase orders whose lead time has elapsed.
2. Add arriving inventory.
3. Observe actual demand.
4. Fulfill as much demand as inventory allows.
5. Record stockouts and lost units.
6. Calculate ending inventory.
7. Place the next order according to the selected policy.
8. Calculate weekly revenue and costs.

Track:

- Units sold
- Lost units
- Stockout events
- Ending inventory
- Purchase cost
- Holding cost
- Stockout cost
- Estimated lost margin
- Revenue
- Total cost
- Fill rate
- Service level

Prevent impossible behavior such as negative inventory or orders arriving before their lead time.

## 12. Policy comparison

Compare the ML policy against:

1. Ordering the previous week’s demand
2. Ordering the four-week moving average
3. A fixed reorder-point strategy
4. The selected ML forecast with safety stock

Use the exact same starting inventory and business assumptions for every strategy.

Report:

- Total inventory cost
- Holding cost
- Stockout cost
- Lost sales
- Average inventory
- Stockout frequency
- Fill rate
- Estimated savings relative to each baseline

Only claim savings when the simulation actually produces them. Describe all savings as simulated estimates based on stated assumptions.

## 13. Backend API

Implement documented REST endpoints such as:

### System

- `GET /health`
- `GET /config`

### Datasets

- `POST /datasets/import`
- `GET /datasets`
- `GET /datasets/{dataset_id}`
- `GET /datasets/{dataset_id}/quality`

### Products

- `GET /products`
- `GET /products/{product_id}`
- `GET /products/{product_id}/history`

### Training

- `POST /training-runs`
- `GET /training-runs`
- `GET /training-runs/{run_id}`
- `GET /training-runs/{run_id}/metrics`

### Models and forecasts

- `GET /models`
- `GET /models/{model_id}`
- `POST /forecasts`
- `GET /forecasts`
- `GET /forecasts/{forecast_id}`

### Inventory

- `POST /inventory/scenarios`
- `GET /inventory/scenarios`
- `GET /inventory/scenarios/{scenario_id}`
- `GET /inventory/scenarios/{scenario_id}/results`
- `GET /inventory/scenarios/{scenario_id}/export`

Generate OpenAPI documentation through FastAPI.

Validate all request bodies and return useful error messages. Long-running training tasks must report status rather than causing requests to time out.

## 14. Database design

Create tables or equivalent models for:

- Datasets
- Data-quality reports
- Products
- Weekly demand
- Training runs
- Model artifacts
- Forecasts
- Inventory configurations
- Simulation scenarios
- Simulation results

Use Alembic migrations and database constraints where appropriate.

Large raw or processed analytical files may be stored as Parquet, while PostgreSQL stores metadata, configurations, results, and references to artifacts.

## 15. Frontend requirements

Create a responsive, accessible interface with the following pages:

### Executive Overview

Display:

- Forecasted units
- Products at risk of stockout
- Expected inventory cost
- Expected lost sales
- Fill rate
- Estimated savings versus the selected baseline
- Highest-risk products
- Recent model performance

### Data Quality

Display:

- Import status
- Cleaning summary
- Date coverage
- Missing data
- Removed records
- Returns and cancellations
- Selected products

### Forecast Explorer

Allow the user to:

- Select a product
- View actual and forecasted demand
- View uncertainty intervals
- Compare models and baselines
- Inspect recent features
- Review product-level errors

### Inventory Planner

Allow the user to change:

- Current inventory
- Lead time
- Holding cost
- Stockout cost
- Service level
- Case-pack size
- Minimum order quantity

Immediately show the updated:

- Reorder point
- Recommended quantity
- Safety stock
- Expected stockout risk
- Cost breakdown

### Scenario Comparison

Compare multiple inventory policies and configurations using tables and charts.

### Model Performance

Display:

- Backtesting results
- Test-set metrics
- Baseline comparison
- Error by product
- Feature importance
- Calibration or uncertainty coverage
- Model metadata

### Export

Allow users to download:

- Forecasts
- Inventory recommendations
- Product risk reports
- Scenario results

Use CSV for exports.

## 16. Testing

### Backend and ML tests

Test:

- Schema validation
- Duplicate removal
- Return and cancellation handling
- Weekly aggregation
- Missing-week insertion
- Lag and rolling features
- Absence of target leakage
- Chronological splitting
- Metric calculations
- Baseline forecasts
- Model training smoke test
- Model serialization
- Forecast generation
- Safety-stock calculations
- Case-pack rounding
- Minimum-order handling
- Lead-time behavior
- Inventory arrivals
- Stockout calculations
- Cost calculations
- API validation
- Database persistence

### Frontend tests

Test:

- Page rendering
- API error states
- Loading states
- Product selection
- Scenario inputs
- KPI updates
- Table filtering
- Export controls

### End-to-end test

Create at least one Playwright workflow that:

1. Imports or activates a sample dataset.
2. Starts or loads a completed training run.
3. Opens a product forecast.
4. Configures an inventory scenario.
5. Runs the simulation.
6. Compares the ML policy with a baseline.
7. Exports the recommendations.

## 17. Reproducibility and observability

Include:

- Fixed seeds
- Structured logging
- Training and inference timing
- Clear error handling
- Environment-variable configuration
- Health checks
- Model and dataset versioning
- Deterministic tests
- No credentials committed to source control

Record real benchmarks for:

- Data ingestion
- Feature generation
- Model training
- Batch forecasting
- API response time

Do not set resume metrics until the benchmarks have actually been measured.

## 18. Documentation

Create:

- Comprehensive `README.md`
- Architecture overview
- Setup instructions
- Dataset citation
- Data dictionary
- ML methodology
- Inventory formulas
- Assumptions and limitations
- API documentation
- Testing instructions
- Model card
- Example screenshots
- Example business scenario
- Commands for retraining and evaluation

The model card must document:

- Intended use
- Prohibited uses
- Dataset limitations
- Evaluation methodology
- Error patterns
- Forecast horizon
- Uncertainty method
- Business assumptions
- Risks of using historical data
- Why the application is decision support rather than an autonomous purchasing system

## 19. Project structure

Use a clean structure similar to:

```text
demandiq/
  backend/
    app/
      api/
      core/
      db/
      models/
      schemas/
      services/
      main.py
    tests/
    alembic/
    requirements.txt
  frontend/
    src/
      api/
      components/
      pages/
      hooks/
      types/
    tests/
    package.json
  ml/
    data/
    features/
    models/
    evaluation/
    inventory/
    pipelines/
    tests/
  scripts/
    download_data.py
    ingest_data.py
    train.py
    evaluate.py
  artifacts/
  docs/
  docker-compose.yml
  .env.example
  README.md
```

Keep business logic out of API route handlers. Forecasting, inventory, and simulation logic must be independently testable.

## 20. Delivery phases

Implement incrementally.

### Phase 1: Data foundation

- Download dataset
- Validate and clean transactions
- Aggregate weekly demand
- Select products using training data only
- Generate data-quality report
- Add tests

### Phase 2: Forecasting baseline

- Create chronological splits
- Implement naive baselines
- Add evaluation metrics
- Produce initial plots

### Phase 3: ML models

- Implement feature pipeline
- Train multiple models
- Run backtesting
- Select the best model using validation results
- Evaluate once on the test set
- Add uncertainty intervals

### Phase 4: Inventory intelligence

- Implement reorder logic
- Implement safety stock
- Build chronological inventory simulation
- Compare policies
- Add business KPIs

### Phase 5: Application

- Build FastAPI endpoints
- Add PostgreSQL persistence
- Build React dashboard
- Add exports

### Phase 6: Production quality

- Add complete test coverage
- Add Docker
- Add linting and formatting
- Measure performance
- Write documentation and model card
- Complete the Playwright workflow

At the end of each phase:

1. Run the relevant tests.
2. Report what works.
3. Report any remaining limitations.
4. Do not continue with broken tests.
5. Do not claim unmeasured results.

## 21. Acceptance criteria

The project is complete only when:

- The official dataset can be downloaded reproducibly.
- Cleaning decisions are recorded and visible.
- Weekly demand contains no unexplained time gaps.
- Feature generation passes leakage tests.
- At least three baselines and three ML models are evaluated.
- Final test metrics are separated from validation metrics.
- The selected model is compared with simple baselines.
- Forecast uncertainty is displayed.
- Inventory recommendations respect all configured constraints.
- Inventory simulation produces valid chronological results.
- Business policies are compared using identical assumptions.
- The dashboard connects to the real backend.
- Exports contain real forecast and scenario data.
- Backend, frontend, ML, and end-to-end tests pass.
- Docker setup works from a clean environment.
- Documentation explains methodology, assumptions, and limitations.
- No results, savings, benchmarks, or test counts are fabricated.

## 22. Scope controls

Do not add the following to the initial version:

- Deep learning
- Real-time streaming
- Dynamic pricing
- Multiple warehouses
- Supplier optimization
- Authentication
- Cloud deployment
- Automated purchasing
- External ERP integrations

Finish the complete one-week forecasting and single-location inventory workflow before considering these extensions.

The final product should show that machine learning is not valuable merely because it predicts demand. It is valuable because it helps a business make a measurable, explainable, and testable inventory decision.
