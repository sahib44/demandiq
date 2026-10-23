"""Bounded REST handlers; services own domain logic, artifacts and transactions."""

from __future__ import annotations

import re
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Header, Path, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response

from backend.app.schemas.requests import (
    DatasetImportRequest,
    Digest,
    ForecastRequest,
    InventoryScenarioRequest,
    TrainingRunRequest,
)
from backend.app.services.errors import ServiceError

router = APIRouter()
ListLimit = Annotated[int, Query(ge=1, le=200)]
RowLimit = Annotated[int, Query(ge=1, le=1000)]
Offset = Annotated[int, Query(ge=0, le=10_000_000)]
StockCode = Annotated[str, Path(min_length=1, max_length=128)]
IdempotencyKey = Annotated[
    str | None,
    Header(
        alias="Idempotency-Key",
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    ),
]
JOB_FIELDS = frozenset(
    {
        "job_id",
        "kind",
        "status",
        "attempts",
        "max_attempts",
        "available_at",
        "created_at",
        "updated_at",
        "started_at",
        "completed_at",
        "result",
        "error_code",
    }
)


def _job(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key in JOB_FIELDS}


def _submit(
    request: Request, kind: str, payload: dict[str, Any], key: str | None
) -> JSONResponse:
    value = request.app.state.service.submit(kind, payload, idempotency_key=key)
    try:
        job_id = str(UUID(str(value["job_id"])))
    except (KeyError, ValueError, TypeError) as exc:
        raise ServiceError(
            500, "invalid_job_response", "The job could not be submitted"
        ) from exc
    return JSONResponse(
        status_code=202,
        content=jsonable_encoder(_job(value)),
        headers={"Location": f"/jobs/{job_id}"},
    )


def _download(content: bytes, filename: str) -> Response:
    safe = (
        re.sub(
            r"[^A-Za-z0-9._-]", "_", str(filename).replace("\\", "/").rsplit("/", 1)[-1]
        )[:128]
        or "export.csv"
    )
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/datasets/import", status_code=202, tags=["datasets"])
def import_dataset(
    body: DatasetImportRequest, request: Request, idempotency_key: IdempotencyKey = None
) -> JSONResponse:
    return _submit(
        request, "dataset_import", body.model_dump(exclude_none=True), idempotency_key
    )


@router.get("/datasets", tags=["datasets"])
def datasets(
    request: Request, limit: ListLimit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    return request.app.state.service.list_resources(
        "datasets", limit=limit, offset=offset
    )


@router.get("/datasets/{dataset_id}", tags=["datasets"])
def dataset(dataset_id: Digest, request: Request) -> dict[str, Any]:
    return request.app.state.service.get_resource("datasets", dataset_id)


@router.get("/datasets/{dataset_id}/quality", tags=["datasets"])
def dataset_quality(dataset_id: Digest, request: Request) -> dict[str, Any]:
    return request.app.state.service.quality(dataset_id)


@router.get("/products", tags=["products"])
def products(
    request: Request, dataset_id: Digest, limit: ListLimit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    return request.app.state.service.list_resources(
        "products", limit=limit, offset=offset, filters={"dataset_id": dataset_id}
    )


@router.get("/products/{stock_code}/history", tags=["products"])
def product_history(
    stock_code: StockCode,
    request: Request,
    dataset_id: Digest,
    run_id: Digest | None = None,
    limit: RowLimit = 1000,
    offset: Offset = 0,
) -> dict[str, Any]:
    return request.app.state.service.history(
        stock_code, dataset_id=dataset_id, run_id=run_id, limit=limit, offset=offset
    )


@router.get("/products/{stock_code}", tags=["products"])
def product(
    stock_code: StockCode, request: Request, dataset_id: Digest
) -> dict[str, Any]:
    return request.app.state.service.get_resource(
        "products", stock_code, dataset_id=dataset_id
    )


@router.post("/training-runs", status_code=202, tags=["training"])
def create_training_run(
    body: TrainingRunRequest, request: Request, idempotency_key: IdempotencyKey = None
) -> JSONResponse:
    return _submit(
        request, "training", body.model_dump(exclude_none=True), idempotency_key
    )


@router.get("/training-runs", tags=["training"])
def training_runs(
    request: Request,
    dataset_id: Digest | None = None,
    limit: ListLimit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    return request.app.state.service.list_resources(
        "training-runs",
        limit=limit,
        offset=offset,
        filters={"dataset_id": dataset_id} if dataset_id else None,
    )


@router.get("/training-runs/{run_id}", tags=["training"])
def training_run(run_id: Digest, request: Request) -> dict[str, Any]:
    return request.app.state.service.get_resource("training-runs", run_id)


@router.get("/training-runs/{run_id}/metrics", tags=["training"])
def training_metrics(run_id: Digest, request: Request) -> dict[str, Any]:
    return request.app.state.service.training_metrics(run_id)


@router.get("/models", tags=["models"])
def models(
    request: Request,
    dataset_id: Digest | None = None,
    run_id: Digest | None = None,
    limit: ListLimit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    filters = {
        key: value
        for key, value in {"dataset_id": dataset_id, "run_id": run_id}.items()
        if value is not None
    }
    return request.app.state.service.list_resources(
        "models", limit=limit, offset=offset, filters=filters or None
    )


@router.get("/models/{model_id}", tags=["models"])
def model(model_id: Digest, request: Request) -> dict[str, Any]:
    return request.app.state.service.get_resource("models", model_id)


@router.post("/forecasts", status_code=202, tags=["forecasts"])
def create_forecast(
    body: ForecastRequest, request: Request, idempotency_key: IdempotencyKey = None
) -> JSONResponse:
    return _submit(request, "forecasting", body.model_dump(), idempotency_key)


@router.get("/forecasts", tags=["forecasts"])
def forecasts(
    request: Request,
    dataset_id: Digest | None = None,
    run_id: Digest | None = None,
    limit: ListLimit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    filters = {
        key: value
        for key, value in {"dataset_id": dataset_id, "run_id": run_id}.items()
        if value is not None
    }
    return request.app.state.service.list_resources(
        "forecasts", limit=limit, offset=offset, filters=filters or None
    )


@router.get("/forecasts/{forecast_id}/values", tags=["forecasts"])
def forecast_values(
    forecast_id: Digest,
    request: Request,
    stock_code: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
    method: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    limit: RowLimit = 1000,
    offset: Offset = 0,
) -> dict[str, Any]:
    return request.app.state.service.forecast_rows(
        forecast_id, stock_code=stock_code, method=method, limit=limit, offset=offset
    )


@router.get("/forecasts/{forecast_id}/export", tags=["forecasts"])
def forecast_export(forecast_id: Digest, request: Request) -> Response:
    return _download(*request.app.state.service.export_forecasts(forecast_id))


@router.get("/forecasts/{forecast_id}", tags=["forecasts"])
def forecast(forecast_id: Digest, request: Request) -> dict[str, Any]:
    return request.app.state.service.get_resource("forecasts", forecast_id)


@router.post("/inventory/scenarios", status_code=202, tags=["inventory"])
def create_scenario(
    body: InventoryScenarioRequest,
    request: Request,
    idempotency_key: IdempotencyKey = None,
) -> JSONResponse:
    return _submit(request, "inventory", body.model_dump(), idempotency_key)


@router.get("/inventory/scenarios", tags=["inventory"])
def scenarios(
    request: Request,
    forecast_id: Digest | None = None,
    limit: ListLimit = 50,
    offset: Offset = 0,
) -> list[dict[str, Any]]:
    return request.app.state.service.list_resources(
        "inventory/scenarios",
        limit=limit,
        offset=offset,
        filters={"forecast_id": forecast_id} if forecast_id else None,
    )


@router.get("/inventory/scenarios/{scenario_id}/results", tags=["inventory"])
def scenario_results(
    scenario_id: Digest, request: Request, limit: RowLimit = 1000, offset: Offset = 0
) -> dict[str, Any]:
    return request.app.state.service.scenario_results(
        scenario_id, limit=limit, offset=offset
    )


@router.get("/inventory/scenarios/{scenario_id}/export", tags=["inventory"])
def scenario_export(
    scenario_id: Digest,
    request: Request,
    kind: Annotated[
        str, Query(pattern=r"^(recommendations|summary|weekly_results)$")
    ] = "recommendations",
) -> Response:
    return _download(*request.app.state.service.export_scenario(scenario_id, kind=kind))


@router.get("/inventory/scenarios/{scenario_id}", tags=["inventory"])
def scenario(scenario_id: Digest, request: Request) -> dict[str, Any]:
    return request.app.state.service.get_resource("inventory/scenarios", scenario_id)


@router.get("/jobs", tags=["jobs"])
def jobs(
    request: Request, limit: ListLimit = 50, offset: Offset = 0
) -> list[dict[str, Any]]:
    return [
        _job(value)
        for value in request.app.state.service.list_resources(
            "jobs", limit=limit, offset=offset
        )
    ]


@router.get("/jobs/{job_id}", tags=["jobs"])
def job(job_id: UUID, request: Request) -> dict[str, Any]:
    return _job(request.app.state.service.get_resource("jobs", str(job_id)))
