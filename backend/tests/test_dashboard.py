"""Dashboard projections on synthetic frozen files, plus isolated PostgreSQL.

No test reads official artifacts or runs an official evaluation. Dummy model
bytes in the fixture are never deserialized. Integration uses disposable *_test
PostgreSQL and clears all DemandIQ tables; run DB suites serially.
"""

import copy
import csv
import io
import json
import math
import os
import shutil
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, insert

from backend.app.core.config import Settings
from backend.app.db.models import (
    Base,
    Dataset,
    ForecastBatch,
    ForecastValue,
    InventoryConfiguration,
    Product,
    SimulationResult,
    SimulationScenario,
    TrainingRun,
)
from backend.app.db.repository import postgres_url
from backend.app.db.session import make_engine
from backend.app.main import create_app
from backend.app.schemas.dashboard import (
    DashboardContext,
    DashboardForecast,
    DashboardRun,
    DashboardScenario,
    InventoryPreview,
    InventoryPreviewRequest,
)
from backend.app.services import dashboard, forecasting
from backend.app.services.errors import ServiceError
from ml.data.acquisition import sha256_file
from ml.evaluation.final_test import claim_final_evaluation, complete_final_evaluation
from ml.evaluation.metrics import evaluate_predictions
from ml.evaluation.uncertainty import calibrate_intervals, interval_metrics
from ml.features.weekly import feature_columns
from ml.inventory.config import ScenarioConfig
from ml.models.config import Phase3Config
from ml.pipelines.artifacts import inventory, write_json
from ml.pipelines.inventory import run_inventory_scenario
from ml.tests.test_inventory_pipeline import build_frozen_fixture

DATASET = "a" * 64
RUN = "b" * 64
NOW = datetime(2024, 1, 1, tzinfo=UTC)


@pytest.fixture(scope="module")
def frozen(tmp_path_factory):
    root = tmp_path_factory.mktemp("dashboard-synthetic")
    base = build_frozen_fixture(root / "factory")
    settings = Settings(data_dir=root / "data", artifact_dir=root / "artifacts")
    source = settings.artifact_dir / "phase3" / RUN
    evaluation = settings.artifact_dir / "phase3" / "evaluations" / RUN
    shutil.copytree(base.train, source)
    shutil.copytree(base.evaluation, evaluation)
    config = Phase3Config(**json.loads((source / "config.json").read_text()))
    write_json(source / "config.json", config.to_dict())
    calibration = calibrate_intervals(base.calibration)
    write_json(source / "calibration.json", calibration)
    hashes = {}
    (source / "models").mkdir()
    for family in forecasting.FAMILIES:
        path = source / "models" / f"{family}.joblib"
        path.write_bytes(b"synthetic placeholder; never deserialize")
        hashes[family] = sha256_file(path)
    cohort = json.loads((source / "cohort.json").read_text())
    volumes = pd.DataFrame(
        [
            {
                "fold": "test",
                "stock_code": row["stock_code"],
                "training_units": row["training_units"],
            }
            for row in cohort
        ]
    )
    metrics = evaluate_predictions(base.predictions, training_volumes=volumes)
    metrics["evaluation_scope"] = "test"
    selection = {**metrics, "evaluation_scope": "selection_validation"}
    calibration_metrics = {
        **metrics,
        "evaluation_scope": "calibration_only_not_selection",
    }
    write_json(source / "selection_metrics.json", selection)
    write_json(source / "calibration_metrics.json", calibration_metrics)
    write_json(
        source / "importance.json",
        {
            family: [
                {
                    "feature": "numeric__demand_lag1",
                    "importance": 1.0,
                    "method": "synthetic_fixture_only",
                }
            ]
            for family in forecasting.FAMILIES
        },
    )
    write_json(
        source / "training_metadata.json",
        {
            "training_timestamp_utc": NOW.isoformat(),
            "final_training_rows": 64,
            "final_training_end": config.timeline.validation_end,
            "tracking": "synthetic_fixture_only",
            "private_path": "/do/not/expose/private",
            "model_artifacts": {"ridge": "private/model.joblib"},
        },
    )
    plan = base.plan | {
        "features": list(feature_columns()),
        "model_hashes": hashes,
        "calibration_sha256": sha256_file(source / "calibration.json"),
        "cohort_sha256": sha256_file(source / "cohort.json"),
        "roles": config.roles(),
        "recommended_method": "ridge",
    }
    write_json(source / "plan.json", plan)
    plan_hash = sha256_file(source / "plan.json")
    write_json(
        source / "manifest.json",
        {
            "experiment_id": RUN,
            "dataset_id": DATASET,
            "state": "frozen_pretest",
            "config": config.to_dict(),
            "plan_sha256": plan_hash,
            "artifacts": inventory(source),
        },
    )
    write_json(evaluation / "metrics.json", metrics)
    intervals = interval_metrics(base.predictions)
    intervals["scope"] = "test"
    write_json(evaluation / "interval_metrics.json", intervals)
    write_json(
        evaluation / "evaluation_metadata.json",
        {
            "dataset_id": DATASET,
            "experiment_id": RUN,
            "plan_sha256": plan_hash,
            "evaluation_scope": "test",
            "all_models_frozen_before_test": True,
            "test_refitting": False,
            "selected_before_test": "ridge",
        },
    )
    write_json(
        evaluation / "manifest.json",
        {
            "experiment_id": RUN,
            "dataset_id": DATASET,
            "plan_sha256": plan_hash,
            "evaluation_scope": "test",
            "artifacts": inventory(evaluation),
        },
    )
    claim_final_evaluation(settings.ledger_dir, DATASET, RUN, plan_hash)
    complete_final_evaluation(
        settings.ledger_dir,
        DATASET,
        RUN,
        plan_hash,
        results_dir=evaluation,
        results_manifest_sha256=sha256_file(evaluation / "manifest.json"),
    )
    issued = base.issued.copy()
    issued["actual"] = None
    with patch.object(forecasting, "_one_week", return_value=issued):
        one = forecasting.prepare_forecast(settings, RUN, "one_week")
    retro = forecasting.prepare_forecast(settings, RUN, "retrospective")
    simulated = run_inventory_scenario(
        source,
        config=ScenarioConfig(),
        output_root=settings.artifact_dir / "phase4",
        ledger_root=settings.ledger_dir,
    )
    scenario_id = dashboard._identity(
        {"forecast_id": retro[0], "inventory_run_id": simulated.manifest["run_id"]}
    )
    configuration_id = dashboard._identity(ScenarioConfig().to_dict())
    objects = [
        Dataset(
            dataset_id=DATASET,
            source_sha256="e" * 64,
            cleaning_version="synthetic",
            original_rows=100,
            cleaned_rows=100,
            status="ready",
            config={},
            artifacts={},
            artifact_dir=DATASET,
            manifest={},
            created_at=NOW,
        ),
        TrainingRun(
            run_id=RUN,
            dataset_id=DATASET,
            config=config.to_dict(),
            metrics={"selection": selection, "calibration": calibration_metrics},
            artifact_dir=source.relative_to(settings.artifact_dir).as_posix(),
            manifest_sha256=sha256_file(source / "manifest.json"),
            created_at=NOW,
        ),
        InventoryConfiguration(
            configuration_id=configuration_id,
            config=ScenarioConfig().to_dict(),
            currency="GBP",
            created_at=NOW,
        ),
    ]
    objects.extend(
        Product(
            dataset_id=DATASET,
            stock_code=row["stock_code"],
            description="Synthetic product",
        )
        for row in cohort
    )
    for identifier, directory, metadata, frame in (one, retro):
        objects.append(
            ForecastBatch(
                forecast_id=identifier,
                run_id=RUN,
                scope=metadata["scope"],
                metadata_json=metadata,
                artifact_dir=directory.relative_to(settings.artifact_dir).as_posix(),
                created_at=NOW,
            )
        )
        for row in dashboard._records(frame):
            objects.append(
                ForecastValue(
                    forecast_id=identifier,
                    stock_code=row["stock_code"],
                    week=pd.Timestamp(row["week"]).date(),
                    method=row["model"],
                    point=row["prediction"],
                    lower=row["lower"],
                    upper=row["upper"],
                    actual=row["actual"],
                    nominal_coverage=row["nominal_coverage"],
                    uncertainty_label=row["uncertainty_label"],
                )
            )
    objects.append(
        SimulationScenario(
            scenario_id=scenario_id,
            forecast_id=retro[0],
            configuration_id=configuration_id,
            artifact_dir=simulated.run_dir.relative_to(
                settings.artifact_dir
            ).as_posix(),
            summary=simulated.summary,
            manifest_sha256=sha256_file(simulated.run_dir / "manifest.json"),
            created_at=NOW,
        )
    )
    core = {
        "policy",
        "stock_code",
        "week",
        "actual",
        "fulfilled_units",
        "lost_units",
        "ending_inventory",
    }
    for row in dashboard._records(
        pd.read_parquet(simulated.run_dir / "weekly_results.parquet")
    ):
        objects.append(
            SimulationResult(
                scenario_id=scenario_id,
                **{
                    key: pd.Timestamp(row[key]).date() if key == "week" else row[key]
                    for key in core
                },
                details={key: value for key, value in row.items() if key not in core},
            )
        )
    return SimpleNamespace(
        settings=settings,
        source=source,
        evaluation=evaluation,
        plan=plan,
        one=one,
        retro=retro,
        simulated=simulated,
        scenario_id=scenario_id,
        objects=objects,
        base=base,
    )


class FakeSession:
    """Evaluate this service's simple SELECT filters over detached ORM rows."""

    def __init__(self, engine):
        self.objects = engine

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def get(self, model, key):
        keys = key if isinstance(key, tuple) else (key,)
        columns = list(model.__table__.primary_key.columns)
        return next(
            (
                row
                for row in self.objects
                if type(row) is model
                and tuple(getattr(row, column.name) for column in columns) == keys
            ),
            None,
        )

    def _query(self, query):
        description = query.column_descriptions[0]
        entity = description["entity"]
        values = [row for row in self.objects if type(row) is entity]
        for name, value in query.compile().params.items():
            field = name.rsplit("_", 1)[0]
            if hasattr(entity, field):
                values = [row for row in values if getattr(row, field) == value]
        key_names = list(entity.__table__.primary_key.columns.keys())
        if entity is ForecastValue:
            key_names = ["week", "stock_code", "method"]
        elif entity is SimulationResult:
            key_names = ["policy", "stock_code", "week"]
        return sorted(
            values, key=lambda row: tuple(getattr(row, field) for field in key_names)
        )

    def scalar(self, query):
        values = self._query(query)
        return values[0] if values else None

    def scalars(self, query):
        return self._query(query)

    def execute(self, query):
        values = self._query(query)
        fields = [item["name"] for item in query.column_descriptions]
        return SimpleNamespace(
            all=lambda: [tuple(getattr(row, name) for name in fields) for row in values]
        )


@pytest.fixture
def service(monkeypatch, frozen):
    monkeypatch.setattr(dashboard, "Session", FakeSession)
    objects = copy.deepcopy(frozen.objects)
    protected = {
        str(path): sha256_file(path)
        for parent in (frozen.source, frozen.evaluation, frozen.settings.ledger_dir)
        for path in parent.rglob("*")
        if path.is_file()
    }
    yield dashboard.DashboardService(frozen.settings, objects)
    assert protected == {name: sha256_file(Path(name)) for name in protected}


@contextmanager
def changed_file(path, data):
    original = path.read_bytes()
    try:
        path.write_bytes(data)
        yield
    finally:
        path.write_bytes(original)


def request(frozen, **changes):
    return InventoryPreviewRequest.model_validate(
        {"forecast_id": frozen.one[0], "stock_code": "SYNTH-A", "on_hand": 3} | changes
    )


def test_empty_dashboard_is_explicit_and_safe(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "Session", FakeSession)
    result = dashboard.DashboardService(
        Settings(data_dir=tmp_path / "data", artifact_dir=tmp_path / "artifacts"), []
    ).context()
    DashboardContext.model_validate(result)
    assert result["dataset"] is None and result["run"] is None
    assert result["products"] == [] and result["overview"] is None


def test_context_uses_frozen_cohort_and_separates_forecast_from_simulation(
    service, frozen
):
    result = service.context(dataset_id=DATASET, run_id=RUN)
    DashboardContext.model_validate(result)
    assert len(result["products"]) == 2
    assert result["one_week_forecast"]["forecast_id"] == frozen.one[0]
    assert result["retrospective_forecast"]["forecast_id"] == frozen.retro[0]
    assert result["scenario"]["scenario_id"] == frozen.scenario_id
    expected = frozen.one[3].loc[frozen.one[3].model.eq("ridge"), "prediction"].sum()
    assert result["overview"]["forecast_units"] == pytest.approx(expected)
    assert result["overview"]["scenario_policy"]["policy"] == "ml_safety_stock"
    assert "retrospective" in result["scope"]["inventory"]


def test_context_rejects_cross_dataset_run(service):
    with pytest.raises(ServiceError) as error:
        service.context(dataset_id="f" * 64, run_id=RUN)
    assert error.value.status_code == 404


def test_run_preserves_metric_scopes_and_hides_private_training_fields(service):
    result = service.run(RUN)
    DashboardRun.model_validate(result)
    assert result["metrics"]["selection"]["evaluation_scope"] == "selection_validation"
    assert (
        result["metrics"]["calibration"]["evaluation_scope"]
        == "calibration_only_not_selection"
    )
    assert result["metrics"]["test"]["evaluation_scope"] == "test"
    assert result["interval_metrics"]["scope"] == "test"
    assert result["test_status"] == "completed_cached_evaluation"
    assert "private_path" not in result["training_metadata"]
    assert "model_artifacts" not in result["training_metadata"]
    assert "/do/not/expose" not in json.dumps(result)


def test_run_without_registered_retrospective_scope_has_no_test_metrics(service):
    service.engine[:] = [
        row
        for row in service.engine
        if not (isinstance(row, ForecastBatch) and row.scope == "retrospective")
    ]
    result = service.run(RUN)
    assert result["metrics"]["test"] is None
    assert result["interval_metrics"] is None
    assert result["test_status"] == "not_registered"


@pytest.mark.parametrize("scope", ["one", "retro"])
def test_forecast_history_and_features_end_before_origin(service, frozen, scope):
    result = service.forecast(getattr(frozen, scope)[0], stock_code="SYNTH-A")
    DashboardForecast.model_validate(result)
    assert len(result["history"]) == 44
    assert result["history"][-1]["week"] == "2011-10-03"
    assert result["features"]["week"] == "2011-10-10"
    assert result["features"]["values"]["demand_lag1"] == 16
    assert result["features"]["values"]["rolling_mean4"] == 13
    assert "gross_units" not in result["features"]["values"]
    assert len(result["forecasts"]) == (6 if scope == "one" else 48)
    assert all(row["actual"] is None for row in result["forecasts"]) is (scope == "one")
    assert result["planner_defaults"]["on_hand"] == math.ceil(
        2
        * float(
            frozen.base.history.loc[
                frozen.base.history.stock_code.eq("SYNTH-A"), "gross_units"
            ].mean()
        )
    )


def test_forecast_unknown_product_is_not_silently_substituted(service, frozen):
    with pytest.raises(ServiceError) as error:
        service.forecast(frozen.one[0], stock_code="NOT-IN-COHORT")
    assert error.value.status_code == 404


def test_scenario_aggregates_reconcile_to_simulated_policy_totals(service, frozen):
    result = service.scenario(frozen.scenario_id)
    DashboardScenario.model_validate(result)
    assert len(result["weekly"]) == 40
    assert len(result["recommendations"]) == 2
    for policy in result["summary"]["policies"]:
        rows = [row for row in result["weekly"] if row["policy"] == policy["policy"]]
        for field in (
            "lost_units",
            "fulfilled_units",
            "gross_cash_cost",
            "net_inventory_cost",
            "holding_cost",
        ):
            assert sum(row[field] for row in rows) == pytest.approx(policy[field])
    assert (
        result["risk_products"][0]["lost_units"]
        >= result["risk_products"][1]["lost_units"]
    )
    assert all(row["policy"] == "ml_safety_stock" for row in result["risk_products"])


def test_preview_matches_phase4_calibration_and_planner_without_test_residuals(
    service, frozen
):
    result = service.preview(
        request(frozen, parameters={"case_pack_size": 6, "min_order_quantity": 12})
    )
    InventoryPreview.model_validate(result)
    assert result["error_estimate"]["normalized_rmse"] == pytest.approx(math.sqrt(2.5))
    assert result["error_estimate"]["scale"] == 13
    assert result["error_estimate"]["error_std"] == pytest.approx(13 * math.sqrt(2.5))
    assert result["error_estimate"]["test_residuals_used"] is False
    assert result["recommendation"]["recommended_order_quantity"] % 6 == 0
    assert result["recommendation"]["recommended_order_quantity"] >= 12
    assert 0 <= result["risk"]["probability"] <= 1
    assert "not calibrated" in result["risk"]["label"]
    assert result["cost_preview"]["total_cost"] == pytest.approx(
        sum(
            result["cost_preview"][key]
            for key in ("purchase_cost", "order_cost", "holding_cost", "stockout_cost")
        )
    )


def test_preview_capacity_and_arrival_uncertainty_are_explicit(service, frozen):
    result = service.preview(
        request(
            frozen,
            on_hand=3,
            on_order=6,
            backordered_units=1,
            parameters={"max_inventory_capacity": 12, "case_pack_size": 3},
        )
    )
    assert result["recommendation"]["recommended_order_quantity"] <= 3
    assert result["risk"]["available_next_week"] == 2
    assert result["state"]["on_order"] == 6
    assert "arrival dates are unspecified" in result["risk"]["label"]


def test_one_week_and_retrospective_previews_use_same_first_origin_only(
    service, frozen
):
    one = service.preview(request(frozen))
    retro = service.preview(request(frozen, forecast_id=frozen.retro[0]))
    assert one["recommendation"] == retro["recommendation"]
    assert one["error_estimate"] == retro["error_estimate"]
    assert one["risk"] == retro["risk"]


def test_later_origin_predictions_and_actuals_cannot_change_opening_preview(
    service, frozen, monkeypatch
):
    body = request(frozen, forecast_id=frozen.retro[0])
    original = service.preview(body)
    verified = service._forecast

    def altered_later_rows(session, forecast_id):
        batch, run, source, plan, cohort, frame = verified(session, forecast_id)
        frame = frame.copy()
        later = frame.week > frame.week.min()
        frame.loc[later, ["prediction", "actual", "scale"]] = 1_000_000
        return batch, run, source, plan, cohort, frame

    # Perturb only already-verified in-memory later-origin observations. Source
    # artifacts and their completed synthetic evaluation ledger stay unchanged.
    monkeypatch.setattr(service, "_forecast", altered_later_rows)
    changed = service.preview(body)
    for field in ("recommendation", "risk", "cost_preview", "error_estimate"):
        assert changed[field] == original[field]


def test_preview_and_risk_exports_contain_real_computed_fixture_rows(service, frozen):
    csv_bytes, name = service.export_preview(request(frozen))
    rows = list(csv.DictReader(io.StringIO(csv_bytes.decode())))
    assert name == "inventory-preview.csv" and len(rows) == 1
    assert (
        int(rows[0]["recommended_order_quantity"])
        == service.preview(request(frozen))["recommendation"][
            "recommended_order_quantity"
        ]
    )
    csv_bytes, _ = service.export_risk(frozen.scenario_id)
    risk = list(csv.DictReader(io.StringIO(csv_bytes.decode())))
    assert len(risk) == 2
    assert all("retrospective_simulated" in row["scope"] for row in risk)


@pytest.mark.parametrize(
    "kind",
    [
        "training_hash",
        "forecast_metadata",
        "forecast_value",
        "scenario_summary",
        "scenario_value",
    ],
)
def test_registered_database_tampering_is_rejected(service, frozen, kind):
    if kind == "training_hash":
        next(
            row for row in service.engine if isinstance(row, TrainingRun)
        ).manifest_sha256 = ("0" * 64)
    elif kind == "forecast_metadata":
        next(
            row
            for row in service.engine
            if isinstance(row, ForecastBatch) and row.scope == "one_week"
        ).metadata_json["source"]["plan_sha256"] = ("0" * 64)
    elif kind == "forecast_value":
        next(
            row
            for row in service.engine
            if isinstance(row, ForecastValue) and row.forecast_id == frozen.one[0]
        ).point += 1
    elif kind == "scenario_summary":
        next(
            row for row in service.engine if isinstance(row, SimulationScenario)
        ).summary["currency"] = "XXX"
    else:
        next(
            row for row in service.engine if isinstance(row, SimulationResult)
        ).lost_units += 1
    with pytest.raises(ServiceError) as error:
        if kind.startswith("scenario"):
            service.scenario(frozen.scenario_id)
        else:
            service.forecast(frozen.one[0], stock_code="SYNTH-A")
    assert error.value.status_code == 409
    assert error.value.code == "artifact_integrity"


def test_changed_file_fails_without_exposing_private_exception(service, frozen):
    with changed_file(
        frozen.source / "importance.json", b'{"private":"password=synthetic-secret"}'
    ):
        with pytest.raises(ServiceError) as error:
            service.run(RUN)
    assert error.value.status_code == 409
    assert "synthetic-secret" not in str(error.value)
    assert str(frozen.source) not in str(error.value)


def test_running_or_tampered_ledger_cannot_expose_final_metrics(service, frozen):
    path = frozen.settings.ledger_dir / f"{DATASET}.json"
    with changed_file(path, b'{"status":"running"}'):
        with pytest.raises(ServiceError) as error:
            service.run(RUN)
    assert error.value.status_code == 409


@pytest.mark.parametrize(
    "forecast,sigma,available,probability,lost,ending",
    [
        (10, 0, 3, 1, 7, 0),
        (10, 0, 10, 0, 0, 0),
        (10, 0, 14, 0, 0, 4),
        (0, 0, 0, 0, 0, 0),
    ],
)
def test_normal_preview_zero_error_is_deterministic(
    forecast, sigma, available, probability, lost, ending
):
    result = dashboard.normal_preview(forecast, sigma, available)
    assert result["stockout_probability"] == probability
    assert result["expected_lost_units"] == lost
    assert result["expected_ending_inventory"] == ending


def test_normal_preview_clips_negative_demand_and_conserves_expected_units():
    result = dashboard.normal_preview(0, 2, 0)
    assert result["stockout_probability"] == pytest.approx(0.5)
    assert result["expected_demand"] == pytest.approx(2 / math.sqrt(2 * math.pi))
    assert result["expected_lost_units"] == result["expected_demand"]
    assert result["expected_fulfilled_units"] == 0
    result = dashboard.normal_preview(5, 2, 4)
    assert result["expected_demand"] == pytest.approx(
        result["expected_fulfilled_units"] + result["expected_lost_units"]
    )
    assert result["expected_fulfilled_units"] + result[
        "expected_ending_inventory"
    ] == pytest.approx(4)


@pytest.mark.parametrize(
    "changes",
    [
        {"on_hand": True},
        {"on_hand": -1},
        {"on_order": 1.5},
        {"backordered_units": "2"},
        {"stock_code": " SYNTH-A"},
        {"forecast_id": "A" * 64},
        {"on_hand": 2**53},
        {"on_hand": 2**53 - 1, "on_order": 1},
        {"parameters": {"lead_time_weeks": True}},
        {"parameters": {"lead_time_weeks": 105}},
        {"parameters": {"review_period_weeks": 0}},
        {"parameters": {"service_level": 1}},
        {"parameters": {"service_level": float("nan")}},
        {"parameters": {"holding_cost_per_unit_week": -1}},
        {"parameters": {"unit_purchase_cost": True}},
        {"parameters": {"case_pack_size": 0}},
        {"parameters": {"max_inventory_capacity": 2}},
        {"parameters": {"fixed_reorder_point": 10}},
        {"customer_id": "synthetic-private"},
    ],
)
def test_preview_inputs_are_strict_and_bounded(changes):
    with pytest.raises(ValidationError):
        InventoryPreviewRequest.model_validate(
            {"forecast_id": "a" * 64, "stock_code": "SYNTH-A", "on_hand": 3} | changes
        )


@pytest.mark.parametrize(
    "root", ["api", "/api/", "/api/../secret", "/api?x=1", "/api\n", "/", None]
)
def test_proxy_root_path_is_bounded(root):
    with pytest.raises(ValueError, match="API root path"):
        Settings(api_root_path=root)


def test_proxy_docs_use_configured_prefix_and_safe_config_hides_host_paths(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("API_ROOT_PATH", "/api")
    settings = Settings.from_env()
    app = create_app(settings)
    with TestClient(app) as client:
        docs = client.get("/docs")
        assert "/api/openapi.json" in docs.text
        spec = client.get("/openapi.json").json()
        assert {"url": "/api"} in spec["servers"]
        assert "/dashboard/context" in spec["paths"]
        response = client.get("/config").json()
        assert str(settings.artifact_dir) not in json.dumps(response)
        assert "api_root_path" not in response


def test_http_projection_and_validation_contracts(service, frozen):
    app = create_app(frozen.settings, engine=service.engine)
    with TestClient(app) as client:
        assert client.get("/dashboard/context").status_code == 200
        assert (
            client.get(f"/dashboard/runs/{RUN}").json()["test_status"]
            == "completed_cached_evaluation"
        )
        response = client.get(
            f"/dashboard/forecasts/{frozen.one[0]}", params={"stock_code": "SYNTH-A"}
        )
        assert response.status_code == 200
        assert response.json()["features"]["scope"] == "causal_first_post_refit_origin"
        body = request(frozen).model_dump()
        assert client.post("/inventory/preview", json=body).status_code == 200
        assert (
            client.post("/inventory/preview/export", json=body)
            .headers["content-type"]
            .startswith("text/csv")
        )
        assert (
            client.get(
                f"/dashboard/scenarios/{frozen.scenario_id}/risk/export"
            ).status_code
            == 200
        )
        invalid = client.post("/inventory/preview", json=body | {"on_hand": True})
        assert invalid.status_code == 422
        assert "input" not in json.dumps(invalid.json())


@pytest.mark.integration
def test_dashboard_reads_and_previews_roundtrip_real_postgresql(monkeypatch, frozen):
    value = os.getenv("TEST_DATABASE_URL")
    if not value:
        pytest.skip(
            "TEST_DATABASE_URL absent: dashboard PostgreSQL integration not run"
        )
    url = postgres_url(value)
    if not url.database.endswith("_test"):
        pytest.fail("Disposable PostgreSQL database name must end in _test")
    monkeypatch.setenv("DATABASE_URL", value)
    command.upgrade(
        Config(str(Path(__file__).resolve().parents[1] / "alembic.ini")), "head"
    )
    engine = make_engine(value)
    objects = copy.deepcopy(frozen.objects)
    by_table = {table.name: [] for table in Base.metadata.sorted_tables}
    for row in objects:
        by_table[row.__tablename__].append(
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
        )

    def clear():
        with engine.begin() as connection:
            for table in reversed(Base.metadata.sorted_tables):
                connection.execute(delete(table))

    clear()
    try:
        with engine.begin() as connection:
            for table in Base.metadata.sorted_tables:
                if by_table[table.name]:
                    connection.execute(insert(table), by_table[table.name])
        service = dashboard.DashboardService(frozen.settings, engine)
        result = service.context(run_id=RUN)
        assert result["scenario"]["scenario_id"] == frozen.scenario_id
        assert service.run(RUN)["metrics"]["test"]["evaluation_scope"] == "test"
        assert (
            len(service.forecast(frozen.retro[0], stock_code="SYNTH-A")["forecasts"])
            == 48
        )
        assert len(service.scenario(frozen.scenario_id)["weekly"]) == 40
        assert (
            service.preview(request(frozen))["recommendation"][
                "recommended_order_quantity"
            ]
            > 0
        )
        with TestClient(create_app(frozen.settings, engine=engine)) as client:
            assert client.get("/dashboard/context").status_code == 200
            assert (
                client.post(
                    "/inventory/preview", json=request(frozen).model_dump()
                ).status_code
                == 200
            )
    finally:
        clear()
        engine.dispose()
