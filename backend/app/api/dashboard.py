"""Thin dashboard projection and synchronous decision-support preview routes."""

from typing import Annotated

from fastapi import APIRouter, Query, Request
from fastapi.responses import Response

from backend.app.api.routes import _download
from backend.app.schemas.dashboard import (
    DashboardContext,
    DashboardForecast,
    DashboardRun,
    DashboardScenario,
    InventoryPreview,
    InventoryPreviewRequest,
)
from backend.app.schemas.requests import Digest
from backend.app.services.dashboard import DashboardService

router = APIRouter(tags=["dashboard"])


def _service(request: Request) -> DashboardService:
    return DashboardService(request.app.state.settings, request.app.state.engine)


@router.get("/dashboard/context", response_model=DashboardContext)
def dashboard_context(
    request: Request, dataset_id: Digest | None = None, run_id: Digest | None = None
):
    return _service(request).context(dataset_id=dataset_id, run_id=run_id)


@router.get("/dashboard/runs/{run_id}", response_model=DashboardRun)
def dashboard_run(run_id: Digest, request: Request):
    return _service(request).run(run_id)


@router.get("/dashboard/forecasts/{forecast_id}", response_model=DashboardForecast)
def dashboard_forecast(
    forecast_id: Digest,
    request: Request,
    stock_code: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
):
    return _service(request).forecast(forecast_id, stock_code=stock_code)


@router.get("/dashboard/scenarios/{scenario_id}", response_model=DashboardScenario)
def dashboard_scenario(scenario_id: Digest, request: Request):
    return _service(request).scenario(scenario_id)


@router.get("/dashboard/scenarios/{scenario_id}/risk/export")
def dashboard_risk_export(scenario_id: Digest, request: Request) -> Response:
    return _download(*_service(request).export_risk(scenario_id))


@router.post("/inventory/preview", response_model=InventoryPreview, tags=["inventory"])
def inventory_preview(body: InventoryPreviewRequest, request: Request):
    return _service(request).preview(body)


@router.post("/inventory/preview/export", tags=["inventory"])
def inventory_preview_export(
    body: InventoryPreviewRequest, request: Request
) -> Response:
    return _download(*_service(request).export_preview(body))
